from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .._check_config import (
    CheckConfig,
    load_check_config,
)
from .._config import DevEcoConfig, get_config
from .._output import progress


DAEMON_DIR_NAME = ".deveco-cli"
DAEMON_SOCKET_NAME = "check-daemon.sock"
DAEMON_PID_NAME = "check-daemon.pid"
DAEMON_STATE_NAME = "check-daemon.json"
DAEMON_LOG_NAME = "check-daemon.log"
CHECK_IDLE_TIMEOUT_SECONDS = 30 * 60
CHECK_REQUEST_TIMEOUT_SECONDS = 420
CHECK_STOP_TIMEOUT_SECONDS = 20
CHECK_DIAGNOSTIC_TIMEOUT_SECONDS = 20
EXPECTED_DIAGNOSTIC_VERSIONS = {1000, 2000, 3000, 3001}


@dataclass(frozen=True)
class CheckDaemonPaths:
    root: Path
    socket_path: Path
    pid_path: Path
    state_path: Path
    log_path: Path


def get_check_daemon_paths(project_path: Path | str) -> CheckDaemonPaths:
    root = Path(project_path).resolve() / DAEMON_DIR_NAME
    return CheckDaemonPaths(
        root=root,
        socket_path=root / DAEMON_SOCKET_NAME,
        pid_path=root / DAEMON_PID_NAME,
        state_path=root / DAEMON_STATE_NAME,
        log_path=root / DAEMON_LOG_NAME,
    )


def _try_read_lsp_msg(stdout, deadline: float) -> dict | None:
    """非阻塞 LSP 消息读取。deadline 为 time.monotonic() 绝对时间。"""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    ready, _, _ = select.select([stdout], [], [], min(remaining, 1.0))
    if not ready:
        return None

    headers: dict[str, str] = {}
    while True:
        raw = stdout.readline()
        if not raw:
            return None
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            break
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()

    length = int(headers.get("content-length", 0))
    if length == 0:
        return None
    msg = json.loads(stdout.read(length).decode("utf-8"))
    if isinstance(msg, str):
        try:
            msg = json.loads(msg)
        except json.JSONDecodeError:
            return None
    if not isinstance(msg, dict):
        return None
    return msg


def _send_lsp_msg(stdin, msg: dict) -> None:
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    stdin.write(header + body)
    stdin.flush()


def _lsp_text_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _normalize_diagnostic(diagnostic) -> dict:
    if isinstance(diagnostic, dict):
        return diagnostic
    if isinstance(diagnostic, str):
        try:
            parsed = json.loads(diagnostic)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"message": diagnostic}
    return {"message": str(diagnostic)}


class AceLspSession:
    """Long-lived ArkTS LSP proxy session used by the check daemon."""

    def __init__(
        self,
        config: DevEcoConfig,
        check_cfg: CheckConfig,
        stderr: int | IO[bytes] | None = None,
    ):
        self.config = config
        self.check_cfg = check_cfg
        self.stderr = stderr
        self.proc: subprocess.Popen | None = None
        self.req_id = 0
        self.open_versions: dict[str, int] = {}
        self._index_tmpdir: tempfile.TemporaryDirectory | None = None

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        if self.is_alive():
            return

        proxy = Path(__file__).resolve().parents[1] / "vendor" / "arkts-lang-server-0.2.4.cjs"
        if not proxy.exists():
            raise FileNotFoundError(f"ArkTS LSP proxy 未找到: {proxy}")
        sdk_path = self.config.sdk_home
        extension_path = self.config.deveco_path / "Contents" / "plugins" / "openharmony"
        if not sdk_path.exists():
            raise FileNotFoundError(f"DevEco SDK 未找到: {sdk_path}")
        if not (extension_path / "ace-server" / "out" / "index.js").exists():
            raise FileNotFoundError(f"DevEco openharmony 插件未找到: {extension_path}")

        daemon_root = self.config.project_path / DAEMON_DIR_NAME
        log_dir = daemon_root / "lsp-log"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._index_tmpdir = tempfile.TemporaryDirectory(prefix="deveco-cli-lsp-index-")
        stderr_target = self.stderr if self.stderr is not None else subprocess.DEVNULL
        self.proc = subprocess.Popen(
            [
                str(self.config.node),
                str(proxy),
                str(self.config.project_path),
                str(sdk_path),
                str(extension_path),
                "--log",
                str(log_dir),
                "--lsp-index",
                self._index_tmpdir.name,
                "--node_max_old_space_size",
                str(self.check_cfg.maxOldSpaceSize),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_target,
            cwd=str(self.config.project_path),
            env={
                **os.environ.copy(),
                "DEVECO_PATH": str(self.config.deveco_path),
                "DEVECO_SDK_HOME": str(sdk_path),
            },
        )

        deadline = time.monotonic() + 300.0
        while time.monotonic() < deadline:
            msg = _try_read_lsp_msg(self.proc.stdout, deadline)
            if msg is None:
                if time.monotonic() >= deadline:
                    break
                continue
            if msg.get("method") == "arkts/initialized":
                return
            if msg.get("method") == "arkts/indexingProgress":
                deadline = time.monotonic() + 300.0
            elif msg.get("method") == "arkts/initializationFailed":
                self.close(kill=True)
                reason = msg.get("params", {}).get("message", "unknown")
                raise RuntimeError(f"ArkTS LSP 初始化失败: {reason}")

        self.close(kill=True)
        raise TimeoutError("ArkTS LSP 初始化超时或失败")

    def check_files(self, file_paths: list[Path]) -> dict:
        self.start()
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("ace-server 未启动")

        diagnostics: dict[str, list] = {}
        for fp in file_paths:
            diagnostics[fp.as_uri()] = self._check_file(fp)

        return _format_check_result(file_paths, diagnostics)

    def _check_file(self, fp: Path) -> list:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("ace-server 未启动")

        uri = fp.as_uri()
        text = fp.read_text()
        text_length = _lsp_text_length(text)
        self.req_id += 1
        _send_lsp_msg(self.proc.stdin, {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": str(fp),
                    "languageId": f"deveco.apptool.{fp.suffix.lstrip('.') or 'plaintext'}",
                    "version": text_length,
                    "text": text,
                },
                "editorFiles": [str(fp)],
                "isFromEditor": False,
            },
        })
        self.open_versions[uri] = text_length
        try:
            return self._collect_diagnostics(uri)
        finally:
            self._close_file(uri)

    def _collect_diagnostics(self, expected_uri: str) -> list:
        if self.proc is None or self.proc.stdout is None:
            return []

        diagnostics: list = []
        seen_diagnostics: set[str] = set()
        received_versions: set[int] = set()
        deadline = time.monotonic() + CHECK_DIAGNOSTIC_TIMEOUT_SECONDS
        quiet_deadline: float | None = None
        while time.monotonic() < deadline:
            current_deadline = min(deadline, quiet_deadline) if quiet_deadline else deadline
            msg = _try_read_lsp_msg(self.proc.stdout, current_deadline)
            if msg is None:
                now = time.monotonic()
                if quiet_deadline is not None and now >= quiet_deadline:
                    break
                if now >= deadline:
                    break
                continue
            if msg.get("method") == "textDocument/publishDiagnostics":
                params = msg.get("params", {})
                if params.get("uri") != expected_uri:
                    continue
                version = params.get("version")
                if isinstance(version, int):
                    received_versions.add(version)
                for diagnostic in params.get("diagnostics", []) or []:
                    normalized = _normalize_diagnostic(diagnostic)
                    key = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
                    if key not in seen_diagnostics:
                        seen_diagnostics.add(key)
                        diagnostics.append(normalized)
                quiet_deadline = time.monotonic() + 1.0
                if EXPECTED_DIAGNOSTIC_VERSIONS.issubset(received_versions):
                    break
        return diagnostics

    def _close_file(self, uri: str) -> None:
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            _send_lsp_msg(self.proc.stdin, {
                "jsonrpc": "2.0",
                "method": "textDocument/didClose",
                "params": {"textDocument": {"uri": uri}, "isManual": False},
            })
        except Exception:
            pass
        self.open_versions.pop(uri, None)

    def shutdown(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            self.close(kill=False)
            return

        try:
            _send_lsp_msg(self.proc.stdin, {"jsonrpc": "2.0", "method": "exit", "params": {}})
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            self.proc.wait(timeout=2)
        except Exception:
            self.close(kill=True)
        finally:
            self.close(kill=False)

    def close(self, kill: bool = False) -> None:
        proc = self.proc
        self.proc = None
        self.open_versions.clear()
        if proc is None:
            return
        if proc.poll() is None:
            if kill:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            else:
                try:
                    proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
        if self._index_tmpdir is not None:
            try:
                self._index_tmpdir.cleanup()
            except Exception:
                pass
            self._index_tmpdir = None


def _format_check_result(file_paths: list[Path], diagnostics: dict[str, list]) -> dict:
    results: dict[str, list] = {}
    for uri, diags in diagnostics.items():
        path_str = uri.removeprefix("file://")
        results[path_str] = [
            {
                "range": d.get("range", {}),
                "severity": d.get("severity", 1),
                "code": d.get("code", ""),
                "message": d.get("message", ""),
            }
            for d in diags
        ]

    total = sum(len(v) for v in results.values())
    return {
        "status": "ok",
        "command": "check",
        "files_checked": len(file_paths),
        "total_issues": total,
        "diagnostics": results,
        "message": f"检查完成，{total} 个问题",
    }


def check_ets_files_once(project: Path | str, files: list[str | Path]) -> dict:
    """Single-shot check path kept for fallback/debugging."""
    config = get_config(project)
    file_paths = [Path(f).resolve() for f in files]
    missing = [f for f in file_paths if not f.exists()]
    if missing:
        return {
            "status": "error",
            "command": "check",
            "error_type": "file_not_found",
            "message": f"文件不存在: {', '.join(str(f) for f in missing)}",
        }

    try:
        check_cfg, _ = load_check_config(config.project_path, config)
        session = AceLspSession(config, check_cfg)
        try:
            return session.check_files(file_paths)
        finally:
            session.shutdown()
    except FileNotFoundError as e:
        return {
            "status": "error",
            "command": "check",
            "error_type": "ace_server_not_found",
            "message": str(e),
            "suggestion": "使用 deveco-cli build 获取构建时的编译错误",
        }
    except TimeoutError as e:
        return {
            "status": "error",
            "command": "check",
            "error_type": "lsp_init_timeout",
            "message": str(e),
            "suggestion": "使用 deveco-cli build 获取构建时的编译错误",
        }
    except Exception as e:
        return {
            "status": "error",
            "command": "check",
            "error_type": "lsp_error",
            "message": f"LSP 通信错误: {e}",
            "suggestion": "使用 deveco-cli build 获取构建时的编译错误",
        }


def check_ets_files(project: Path | str, files: list[str | Path]) -> dict:
    config = get_config(project)
    file_paths = [Path(f).resolve() for f in files]

    missing = [f for f in file_paths if not f.exists()]
    if missing:
        return {
            "status": "error",
            "command": "check",
            "error_type": "file_not_found",
            "message": f"文件不存在: {', '.join(str(f) for f in missing)}",
        }

    paths = get_check_daemon_paths(config.project_path)
    try:
        _ensure_check_daemon(config.project_path, paths)
        return _send_daemon_request(
            paths,
            {"command": "check", "files": [str(f) for f in file_paths]},
            timeout=CHECK_REQUEST_TIMEOUT_SECONDS,
        )
    except TimeoutError as e:
        return {
            "status": "error",
            "command": "check",
            "error_type": "daemon_start_timeout",
            "message": str(e),
            "suggestion": f"查看 daemon 日志: {paths.log_path}",
        }
    except (OSError, RuntimeError) as e:
        return {
            "status": "error",
            "command": "check",
            "error_type": "daemon_error",
            "message": str(e),
            "suggestion": f"可运行 deveco-cli check-stop -p {config.project_path} 后重试；日志: {paths.log_path}",
        }


def stop_check_daemon(project: Path | str) -> dict:
    config = get_config(project)
    paths = get_check_daemon_paths(config.project_path)
    if not paths.socket_path.exists():
        _cleanup_stale_daemon_files(paths)
        return {
            "status": "ok",
            "command": "check-stop",
            "stopped": False,
            "message": "check daemon 未运行",
        }

    try:
        return _send_daemon_request(paths, {"command": "stop"}, timeout=CHECK_STOP_TIMEOUT_SECONDS)
    except (OSError, RuntimeError) as e:
        _cleanup_stale_daemon_files(paths)
        return {
            "status": "error",
            "command": "check-stop",
            "error_type": "daemon_unreachable",
            "message": f"无法连接 check daemon，已清理失效 socket: {e}",
        }


def _ensure_check_daemon(project_path: Path, paths: CheckDaemonPaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)

    if _can_connect(paths.socket_path):
        return

    _cleanup_stale_daemon_files(paths)
    progress("启动 check daemon...")
    _spawn_check_daemon(project_path, paths)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if _can_connect(paths.socket_path):
            return
        time.sleep(0.2)
    raise TimeoutError(f"check daemon 启动超时: {paths.socket_path}")


def _spawn_check_daemon(project_path: Path, paths: CheckDaemonPaths) -> None:
    env = os.environ.copy()
    source_root = Path(__file__).resolve().parents[2]
    old_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(source_root)
        if not old_pythonpath
        else str(source_root) + os.pathsep + old_pythonpath
    )

    log = paths.log_path.open("ab")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "deveco_cli.commands.check_daemon", str(project_path)],
            cwd=str(project_path),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log.close()


def _send_daemon_request(paths: CheckDaemonPaths, request: dict, timeout: int) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(paths.socket_path))
        payload = json.dumps(request).encode("utf-8") + b"\n"
        sock.sendall(payload)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)

    raw = b"".join(chunks).strip()
    if not raw:
        raise RuntimeError("check daemon 未返回结果")
    return json.loads(raw.decode("utf-8"))


def _can_connect(socket_path: Path) -> bool:
    if not socket_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            sock.connect(str(socket_path))
        return True
    except OSError:
        return False


def _cleanup_stale_daemon_files(paths: CheckDaemonPaths) -> None:
    pid = _read_pid(paths.pid_path)
    try:
        paths.socket_path.unlink()
    except FileNotFoundError:
        pass
    if pid is None or not _pid_alive(pid):
        try:
            paths.pid_path.unlink()
        except FileNotFoundError:
            pass


def _read_pid(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
