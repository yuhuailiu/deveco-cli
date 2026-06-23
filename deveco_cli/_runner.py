from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str
    command: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_cmd(
    args: list[str | Path],
    cwd: Path | None = None,
    env_extra: dict[str, str] | None = None,
    timeout: int = 600,
) -> CmdResult:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    str_args = [str(a) for a in args]
    result = subprocess.run(
        str_args,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return CmdResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        command=" ".join(str_args),
    )


# hdc 的设计缺陷：无设备时 `hdc shell ...` 返回 exit 0，错误只出现在 stdout/stderr
# 里（`[Fail]ExecuteCommand need connect-key? please confirm a device by help info`）。
# 所有依赖 hdc shell 的命令在入口处先调这个函数做 gate，若无设备直接返回统一错误 dict。
_NO_DEVICE_MARKERS = (
    "need connect-key",
    "[Empty]",
)

DEFAULT_HVD_ENV = "DEFAULT_HVD"


def _hdc_targets(hdc: Path | str) -> tuple[list[str], dict | None]:
    r = run_cmd([str(hdc), "list", "targets"], timeout=10)
    if not r.ok:
        return [], {
            "status": "error",
            "error_type": "hdc_list_failed",
            "message": (r.stderr or r.stdout).strip(),
        }
    lines = [t.strip() for t in r.stdout.strip().split("\n") if t.strip()]
    return [t for t in lines if t != "[Empty]"], None


def _parse_param_value(text: str) -> str:
    value = text.strip()
    if "=" in value:
        return value.split("=", 1)[1].strip()
    return value


def _emulator_name_for_target(hdc: Path | str, target: str) -> str | None:
    r = run_cmd(
        [str(hdc), "-t", target, "shell", "param", "get", "ohos.qemu.hvd.name"],
        timeout=10,
    )
    if not r.ok:
        return None
    name = _parse_param_value(r.stdout)
    return name or None


def _requested_hvd(device: str | None = None) -> str | None:
    requested = device if device is not None else os.environ.get(DEFAULT_HVD_ENV)
    if requested is None:
        return None
    requested = requested.strip()
    return requested or None


def resolve_hdc_target(hdc: Path | str, device: str | None = None) -> tuple[str | None, dict | None]:
    """Resolve explicit --device or DEFAULT_HVD to an hdc target.

    Returns (None, None) when neither --device nor DEFAULT_HVD is set, so callers
    can preserve their existing automatic device selection behavior.
    """
    requested = _requested_hvd(device)
    if requested is None:
        return None, None

    targets, err = _hdc_targets(hdc)
    if err is not None:
        return None, err
    if not targets:
        return None, {
            "status": "error",
            "error_type": "no_device",
            "message": "未发现已连接的设备，请连接真机或启动模拟器",
        }
    if requested in targets:
        return requested, None

    for target in targets:
        name = _emulator_name_for_target(hdc, target)
        if name == requested:
            return target, None

    return None, {
        "status": "error",
        "error_type": "device_not_found",
        "message": f"指定的设备或模拟器实例 {requested!r} 未连接；当前 hdc targets: {targets}",
        "suggestion": (
            f"请确认 {DEFAULT_HVD_ENV} 指向已运行的模拟器实例名，"
            "或直接传入 hdc target"
        ),
    }


def ensure_device(hdc: Path | str, device: str | None = None) -> dict | None:
    """若无设备返回 {"status":"error", "error_type":"no_device", ...}，否则返回 None。
    调用方应在命令开头: `err = ensure_device(hdc, device); if err: return err`。"""
    targets, err = _hdc_targets(hdc)
    if err is not None:
        return err
    if not targets:
        return {
            "status": "error",
            "error_type": "no_device",
            "message": "未发现已连接的设备，请连接真机或启动模拟器",
        }
    if device and device not in targets:
        return {
            "status": "error",
            "error_type": "device_not_found",
            "message": f"指定的设备 {device!r} 不在 hdc list targets 中：{targets}",
        }
    return None


def is_hdc_no_device_output(text: str) -> bool:
    """检查 stdout/stderr 里是否包含无设备信号（用于 shell 命令事后补检）。"""
    if not text:
        return False
    return any(m in text for m in _NO_DEVICE_MARKERS)
