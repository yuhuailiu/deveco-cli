from __future__ import annotations

import json
import os
import select
import subprocess
import time
from pathlib import Path

from .._check_config import (
    CheckConfig,
    _extract_device_types,
    _extract_runtime_os,
    _extract_sdk_level,
    load_check_config,
)
from .._config import get_config
from .._json5 import parse_json5
from .._output import progress


def _try_read_lsp_msg(stdout, deadline: float) -> dict | None:
    """非阻塞 LSP 消息读取。deadline 为 time.monotonic() 绝对时间。

    使用 select.select() 轮询（最多 1s 一次），deadline 到期返回 None。
    """
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
    return json.loads(stdout.read(length).decode("utf-8"))


def _send_lsp_msg(stdin, msg: dict) -> None:
    """向 LSP stdin 写一条消息。"""
    body = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    stdin.write(header + body)
    stdin.flush()


def _get_modules(project_path: Path, config, check_cfg: CheckConfig) -> list[dict]:
    """从 build-profile.json5 构建完整的 ace-server module 列表。"""
    bp_path = project_path / "build-profile.json5"
    if not bp_path.exists():
        return []
    try:
        bp_data = parse_json5(bp_path.read_text())
    except Exception:
        return []

    sdk_level = _extract_sdk_level(bp_data)
    runtime_os = _extract_runtime_os(bp_data)

    modules = []
    for m in bp_data.get("modules", []):
        name = m.get("name", "")
        src_path_str = m.get("srcPath", "")
        if src_path_str.startswith("."):
            module_path = (project_path / src_path_str).resolve()
        elif src_path_str:
            module_path = Path(src_path_str).resolve()
        else:
            module_path = project_path / name

        device_types = _extract_device_types(module_path)

        modules.append({
            "moduleName": name,
            "modulePath": str(module_path),
            "sdkJsPath": check_cfg.sdkJsPath,
            "aceLoaderPath": check_cfg.aceLoaderPath,
            "jsComponentType": check_cfg.jsComponentType,
            "deviceType": device_types,
            "compatibleSdkLevel": sdk_level,
            "apiType": check_cfg.apiType,
            "runtimeOs": runtime_os,
        })

    return modules


def check_ets_files(project: Path | str, files: list[str | Path]) -> dict:
    config = get_config(project)
    file_paths = [Path(f).resolve() for f in files]

    missing = [f for f in file_paths if not f.exists()]
    if missing:
        return {"status": "error", "command": "check",
                "error_type": "file_not_found",
                "message": f"文件不存在: {', '.join(str(f) for f in missing)}"}

    try:
        ace = config.ace_server
    except FileNotFoundError as e:
        return {"status": "error", "command": "check",
                "error_type": "ace_server_not_found", "message": str(e),
                "suggestion": "使用 deveco-cli build 获取构建时的编译错误"}

    # 加载 check 配置（如不存在则自动生成 deveco-cli.toml）
    check_cfg, _ = load_check_config(config.project_path, config)

    progress("启动 ace-server LSP...")

    proc = subprocess.Popen(
        [str(config.node), f"--max-old-space-size={check_cfg.maxOldSpaceSize}", str(ace), "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(config.project_path),
    )

    diagnostics: dict[str, list] = {}
    req_id = 0

    try:
        # initialize
        req_id += 1
        _send_lsp_msg(proc.stdin, {
            "jsonrpc": "2.0", "id": req_id, "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "capabilities": {},
                "rootUri": config.project_path.as_uri(),
                "initializationOptions": {
                    "rootUri": config.project_path.as_uri(),
                    "lspServerWorkspacePath": str(config.project_path),
                    "modules": _get_modules(config.project_path, config, check_cfg),
                },
            },
        })

        # Step 1: 等待 initialize response（15s）
        deadline = time.monotonic() + 15.0
        initialized = False
        while time.monotonic() < deadline:
            msg = _try_read_lsp_msg(proc.stdout, deadline)
            if msg is None:
                if time.monotonic() >= deadline:
                    break
                continue
            if msg.get("id") == req_id and "result" in msg:
                initialized = True
                break

        if not initialized:
            return {"status": "error", "command": "check",
                    "error_type": "lsp_init_timeout",
                    "message": "ace-server 初始化超时或失败",
                    "suggestion": "使用 deveco-cli build 获取构建时的编译错误"}

        # initialized notification
        _send_lsp_msg(proc.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}})

        # Step 2: 等待 aceProject/onModuleInitFinish（idle 60s + 绝对 300s）
        progress("等待模块索引完成...")
        abs_deadline = time.monotonic() + 300.0
        idle_deadline = time.monotonic() + 60.0
        module_init_done = False
        while time.monotonic() < abs_deadline and time.monotonic() < idle_deadline:
            current_deadline = min(idle_deadline, abs_deadline)
            msg = _try_read_lsp_msg(proc.stdout, current_deadline)
            if msg is None:
                if time.monotonic() >= current_deadline:
                    break
                continue
            if msg.get("method") == "aceProject/onIndexingProgressUpdate":
                idle_deadline = time.monotonic() + 60.0  # 收到进度通知则重置 idle
            elif msg.get("method") == "aceProject/onModuleInitFinish":
                module_init_done = True
                break

        # 索引未完成时继续尝试（不报错，让 diagnostics 阶段能拿到部分结果）

        # 打开文件
        for fp in file_paths:
            _send_lsp_msg(proc.stdin, {
                "jsonrpc": "2.0", "method": "textDocument/didOpen",
                "params": {"textDocument": {
                    "uri": fp.as_uri(),
                    "languageId": "arkts",
                    "version": 1,
                    "text": fp.read_text(),
                }},
            })

        # 收集 diagnostics（非阻塞）
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            msg = _try_read_lsp_msg(proc.stdout, deadline)
            if msg is None:
                if time.monotonic() >= deadline:
                    break
                continue
            if msg.get("method") == "textDocument/publishDiagnostics":
                uri = msg["params"]["uri"]
                diagnostics[uri] = msg["params"]["diagnostics"]
            if len(diagnostics) >= len(file_paths):
                break

        # shutdown
        req_id += 1
        _send_lsp_msg(proc.stdin, {"jsonrpc": "2.0", "id": req_id, "method": "shutdown", "params": {}})
        _send_lsp_msg(proc.stdin, {"jsonrpc": "2.0", "method": "exit", "params": {}})

    except Exception as e:
        return {"status": "error", "command": "check",
                "error_type": "lsp_error", "message": f"LSP 通信错误: {e}",
                "suggestion": "使用 deveco-cli build 获取构建时的编译错误"}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    # 整理结果
    results: dict[str, list] = {}
    for uri, diags in diagnostics.items():
        path_str = uri.removeprefix("file://")
        results[path_str] = [
            {"range": d.get("range", {}), "severity": d.get("severity", 1),
             "code": d.get("code", ""), "message": d.get("message", "")}
            for d in diags
        ]

    total = sum(len(v) for v in results.values())
    return {
        "status": "ok", "command": "check",
        "files_checked": len(file_paths),
        "total_issues": total,
        "diagnostics": results,
        "message": f"检查完成，{total} 个问题",
    }
