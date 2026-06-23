from __future__ import annotations

from .._config import get_hdc
from .._runner import ensure_device, resolve_hdc_target, run_cmd


DEFAULT_PREFIX = ""
MAX_LINES = 5000


def _target(device: str | None) -> list[str]:
    return ["-t", device] if device else []


def _devices(stdout: str) -> list[str]:
    return [
        item.strip()
        for item in stdout.splitlines()
        if item.strip() and item.strip() != "[Empty]"
    ]


def _pick(input_text: str, prefix: str, lines: int) -> list[str]:
    items = [item.strip() for item in input_text.splitlines() if item.strip()]
    filtered = [item for item in items if prefix in item] if prefix else items
    return filtered[-lines:]


def list_hilog_devices() -> dict:
    hdc = get_hdc()
    r = run_cmd([hdc, "list", "targets"], timeout=10)
    if not r.ok:
        return {
            "status": "error",
            "command": "hilog-list-devices",
            "error_type": "hdc_list_failed",
            "message": (r.stderr or r.stdout).strip(),
        }

    devices = _devices(r.stdout)
    return {
        "status": "ok",
        "command": "hilog-list-devices",
        "devices": devices,
        "device_count": len(devices),
        "message": f"发现 {len(devices)} 个设备" if devices else "未发现已连接的设备",
    }


def clear_hilog(device: str | None = None) -> dict:
    hdc = get_hdc()
    resolved_device, err = resolve_hdc_target(hdc, device)
    if err is not None:
        return {**err, "command": "hilog-clear"}
    err = ensure_device(hdc, resolved_device)
    if err is not None:
        return {**err, "command": "hilog-clear"}

    r = run_cmd([hdc, *_target(resolved_device), "shell", "hilog", "-r"])
    if not r.ok:
        return {
            "status": "error",
            "command": "hilog-clear",
            "error_type": "hilog_clear_failed",
            "message": "清空 hilog 缓冲区失败",
            "detail": (r.stderr or r.stdout)[:2000],
        }

    return {
        "status": "ok",
        "command": "hilog-clear",
        "device": resolved_device or "default",
        "message": "hilog 缓冲区已清空",
    }


def collect_hilog(
    device: str | None = None,
    prefix: str = DEFAULT_PREFIX,
    lines: int = 2000,
) -> dict:
    if lines < 1 or lines > MAX_LINES:
        return {
            "status": "error",
            "command": "hilog-collect",
            "error_type": "invalid_lines",
            "message": f"--lines 必须在 1 到 {MAX_LINES} 之间",
        }

    hdc = get_hdc()
    resolved_device, err = resolve_hdc_target(hdc, device)
    if err is not None:
        return {**err, "command": "hilog-collect"}
    err = ensure_device(hdc, resolved_device)
    if err is not None:
        return {**err, "command": "hilog-collect"}

    r = run_cmd([hdc, *_target(resolved_device), "shell", "hilog", "-x"])
    if not r.ok:
        return {
            "status": "error",
            "command": "hilog-collect",
            "error_type": "hilog_collect_failed",
            "message": "采集 hilog 失败",
            "detail": (r.stderr or r.stdout)[:2000],
        }

    logs = _pick(r.stdout, prefix, lines)
    return {
        "status": "ok",
        "command": "hilog-collect",
        "device": resolved_device or "default",
        "prefix": prefix,
        "requested_lines": lines,
        "count": len(logs),
        "logs": logs,
        "message": f"采集到 {len(logs)} 行匹配日志" if logs else "未找到匹配日志",
    }
