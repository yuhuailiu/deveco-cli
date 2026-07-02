from __future__ import annotations

import json
import os
import socketserver
import sys
import time
from pathlib import Path

from .._check_config import load_check_config
from .._config import get_config
from .check import (
    CHECK_IDLE_TIMEOUT_SECONDS,
    AceLspSession,
    CheckDaemonPaths,
    get_check_daemon_paths,
)


class CheckDaemonState:
    def __init__(self, project_path: Path, paths: CheckDaemonPaths):
        self.project_path = project_path
        self.paths = paths
        self.started_at = time.time()
        self.last_activity = time.time()
        self.stopping = False
        self.session: AceLspSession | None = None
        self.ace_stderr = None
        self.write_state("starting")

    def write_state(self, status: str, **extra) -> None:
        data = {
            "pid": os.getpid(),
            "status": status,
            "project": str(self.project_path),
            "socket": str(self.paths.socket_path),
            "idle_timeout_seconds": CHECK_IDLE_TIMEOUT_SECONDS,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
        }
        data.update(extra)
        self.paths.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def handle_check(self, files: list[str]) -> dict:
        self.last_activity = time.time()
        try:
            file_paths = [Path(f).resolve() for f in files]
            missing = [f for f in file_paths if not f.exists()]
            if missing:
                return {
                    "status": "error",
                    "command": "check",
                    "error_type": "file_not_found",
                    "message": f"文件不存在: {', '.join(str(f) for f in missing)}",
                }

            self.write_state("checking", files=[str(f) for f in file_paths])
            self._ensure_session()
            assert self.session is not None
            return self.session.check_files(file_paths)
        except FileNotFoundError as e:
            self.shutdown_session(kill=True)
            return {
                "status": "error",
                "command": "check",
                "error_type": "ace_server_not_found",
                "message": str(e),
                "suggestion": "使用 deveco-cli build 获取构建时的编译错误",
            }
        except TimeoutError as e:
            self.shutdown_session(kill=True)
            return {
                "status": "error",
                "command": "check",
                "error_type": "lsp_init_timeout",
                "message": str(e),
                "suggestion": "使用 deveco-cli build 获取构建时的编译错误",
            }
        except Exception as e:
            self.shutdown_session(kill=True)
            return {
                "status": "error",
                "command": "check",
                "error_type": "lsp_error",
                "message": f"LSP 通信错误: {e}",
                "suggestion": "使用 deveco-cli build 获取构建时的编译错误",
            }
        finally:
            self.last_activity = time.time()
            self.write_state("idle")

    def handle_stop(self) -> dict:
        self.last_activity = time.time()
        self.write_state("stopping")
        self.shutdown_session()
        self.stopping = True
        self.write_state("stopped")
        return {
            "status": "ok",
            "command": "check-stop",
            "stopped": True,
            "message": "check daemon 已停止",
        }

    def idle_expired(self) -> bool:
        return (time.time() - self.last_activity) >= CHECK_IDLE_TIMEOUT_SECONDS

    def shutdown_session(self, kill: bool = False) -> None:
        if self.session is not None:
            if kill:
                self.session.close(kill=True)
            else:
                self.session.shutdown()
            self.session = None
        if self.ace_stderr is not None:
            try:
                self.ace_stderr.close()
            except Exception:
                pass
            self.ace_stderr = None

    def _ensure_session(self) -> None:
        if self.session is not None and self.session.is_alive():
            return

        self.shutdown_session(kill=True)
        self.write_state("initializing")
        config = get_config(self.project_path)
        check_cfg, _ = load_check_config(config.project_path, config)
        self.ace_stderr = self.paths.log_path.open("ab")
        self.session = AceLspSession(config, check_cfg, stderr=self.ace_stderr)
        self.session.start()
        self.write_state("idle")


class CheckDaemonServer(socketserver.UnixStreamServer):
    def __init__(self, server_address: str, state: CheckDaemonState):
        self.state = state
        super().__init__(server_address, CheckDaemonHandler)
        self.timeout = 1.0


class CheckDaemonHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline()
        if not raw:
            return
        try:
            request = json.loads(raw.decode("utf-8"))
            command = request.get("command")
            if command == "check":
                response = self.server.state.handle_check(request.get("files", []))
            elif command == "stop":
                response = self.server.state.handle_stop()
            else:
                response = {
                    "status": "error",
                    "command": command or "unknown",
                    "error_type": "unknown_daemon_command",
                    "message": f"未知 daemon 命令: {command!r}",
                }
        except Exception as e:
            response = {
                "status": "error",
                "command": "check",
                "error_type": "daemon_error",
                "message": str(e),
            }

        self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
        self.wfile.flush()


def run_daemon(project: Path | str) -> None:
    project_path = Path(project).resolve()
    paths = get_check_daemon_paths(project_path)
    paths.root.mkdir(parents=True, exist_ok=True)

    try:
        paths.socket_path.unlink()
    except FileNotFoundError:
        pass
    paths.pid_path.write_text(str(os.getpid()), encoding="utf-8")

    state = CheckDaemonState(project_path, paths)
    server = CheckDaemonServer(str(paths.socket_path), state)
    try:
        state.write_state("idle")
        while not state.stopping:
            server.handle_request()
            if state.stopping:
                break
            if state.idle_expired():
                state.write_state("idle_timeout")
                state.shutdown_session()
                break
    finally:
        server.server_close()
        state.shutdown_session()
        for path in (paths.socket_path, paths.pid_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: python -m deveco_cli.commands.check_daemon <project>", file=sys.stderr)
        return 2
    run_daemon(argv[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
