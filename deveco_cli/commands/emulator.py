from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Optional

from .._config import _resolve_deveco_path
from .._output import progress
from .._runner import run_cmd


_DEPLOYED_ROOT = Path.home() / ".Huawei" / "Emulator" / "deployed"
_SDK_ROOT = Path.home() / "Library" / "Huawei" / "Sdk"


def _emulator_binary(deveco_path: Optional[Path] = None) -> Path:
    deveco_path = deveco_path or _resolve_deveco_path()
    p = deveco_path / "Contents" / "tools" / "emulator" / "Emulator"
    if not p.exists():
        raise FileNotFoundError(f"Emulator 二进制未找到: {p}")
    return p


def _hdc_binary(deveco_path: Optional[Path] = None) -> Path:
    deveco_path = deveco_path or _resolve_deveco_path()
    return (
        deveco_path / "Contents" / "sdk" / "default" / "openharmony"
        / "toolchains" / "hdc"
    )


def _read_kv(path: Path) -> dict[str, str]:
    """读 key=value 风格的 ini（DevEco 的 .ini 没有 [section]，手工解析）。"""
    kv: dict[str, str] = {}
    if not path.exists():
        return kv
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" in s:
            k, v = s.split("=", 1)
            kv[k.strip()] = v.strip()
    return kv


def _read_instance_info(name: str) -> dict:
    """返回 {instance_path, image_sub_path, sdk_path}。ini 不存在抛 FileNotFoundError。"""
    ini = _DEPLOYED_ROOT / f"{name}.ini"
    if not ini.exists():
        raise FileNotFoundError(f"模拟器实例 ini 不存在: {ini}")
    top = _read_kv(ini)
    instance_path = Path(top.get("path", str(_DEPLOYED_ROOT / name)))
    cfg = _read_kv(instance_path / "config.ini")
    return {
        "instance_path": str(instance_path),
        "image_sub_path": cfg.get("imageSubPath", ""),
        "sdk_path": cfg.get("sdkPath", ""),
    }


def _hdc_targets(hdc: Path) -> list[str]:
    if not hdc.exists():
        return []
    r = run_cmd([hdc, "list", "targets"], timeout=10)
    return [
        t.strip()
        for t in r.stdout.strip().split("\n")
        if t.strip() and t.strip() != "[Empty]"
    ]


def _parse_param_value(text: str) -> str:
    value = text.strip()
    if "=" in value:
        return value.split("=", 1)[1].strip()
    return value


def _is_emulator_target(hdc: Path, target: str) -> bool:
    r = run_cmd(
        [hdc, "-t", target, "shell", "param", "get", "const.product.name"],
        timeout=10,
    )
    if not r.ok:
        return False
    return "emulator" in _parse_param_value(r.stdout).lower()


def _emulator_name_for_target(hdc: Path, target: str) -> str | None:
    r = run_cmd(
        [hdc, "-t", target, "shell", "param", "get", "ohos.qemu.hvd.name"],
        timeout=10,
    )
    if not r.ok:
        return None
    name = _parse_param_value(r.stdout)
    return name or None


def _connected_emulators(hdc: Path) -> list[dict[str, str]]:
    emulators: list[dict[str, str]] = []
    for target in _hdc_targets(hdc):
        if not _is_emulator_target(hdc, target):
            continue
        name = _emulator_name_for_target(hdc, target)
        if not name:
            continue
        emulators.append({"name": name, "target": target})
    return emulators


def _find_connected_emulator(hdc: Path, name: str) -> dict[str, str] | None:
    for emulator in _connected_emulators(hdc):
        if emulator["name"] == name:
            return emulator
    return None


def list_emulators(deveco_path: Optional[Path] = None) -> dict:
    try:
        binary = _emulator_binary(deveco_path)
    except FileNotFoundError as e:
        return {
            "status": "error", "command": "emulator-list",
            "error_type": "deveco_not_found", "message": str(e),
        }
    hdc = _hdc_binary(deveco_path)
    connected_by_name = {item["name"]: item["target"] for item in _connected_emulators(hdc)}
    r = run_cmd([binary, "-list"], timeout=15)
    if r.returncode != 0:
        return {
            "status": "error", "command": "emulator-list",
            "error_type": "list_failed",
            "message": (r.stderr or r.stdout).strip(),
        }
    names = [n.strip() for n in r.stdout.strip().split("\n") if n.strip()]
    instances: list[dict] = []
    for name in names:
        connected_target = connected_by_name.get(name)
        try:
            info = _read_instance_info(name)
            instances.append(
                {
                    "name": name,
                    "is_running": connected_target is not None,
                    "connected_target": connected_target,
                    **info,
                }
            )
        except FileNotFoundError:
            instances.append(
                {
                    "name": name,
                    "is_running": connected_target is not None,
                    "connected_target": connected_target,
                    "instance_path": "",
                    "image_sub_path": "",
                    "sdk_path": "",
                }
            )
    return {
        "status": "ok", "command": "emulator-list", "instances": instances,
    }


def start_emulator(
    name: str,
    wait_hdc_sec: int = 90,
    deveco_path: Optional[Path] = None,
) -> dict:
    try:
        binary = _emulator_binary(deveco_path)
    except FileNotFoundError as e:
        return {
            "status": "error", "command": "emulator-start",
            "error_type": "deveco_not_found", "message": str(e),
        }

    hdc = _hdc_binary(deveco_path)
    existing = set(_hdc_targets(hdc))
    connected = _find_connected_emulator(hdc, name)
    if connected is not None:
        return {
            "status": "ok", "command": "emulator-start",
            "name": name, "already_running": True,
            "connected_devices": [connected["target"]],
            "message": f"模拟器已在运行: {connected['target']}",
        }

    try:
        info = _read_instance_info(name)
    except FileNotFoundError as e:
        return {
            "status": "error", "command": "emulator-start",
            "error_type": "emulator_not_found", "message": str(e),
        }

    # Emulator 的 -path 是 instances 的父目录（deployed），它会在里面找 <name>/ 子目录
    deployed_dir = Path(info["instance_path"]).parent

    progress(f"启动模拟器 {name!r}...")
    try:
        proc = subprocess.Popen(
            [
                str(binary), "-hvd", name,
                "-path", str(deployed_dir),
                "-imageRoot", str(_SDK_ROOT),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        return {
            "status": "error", "command": "emulator-start",
            "error_type": "popen_failed", "message": str(e),
        }

    progress(f"等待 hdc 发现设备（最多 {wait_hdc_sec}s）...")
    deadline = time.monotonic() + wait_hdc_sec
    poll_interval = 3
    last_targets: list[str] = []
    while time.monotonic() < deadline:
        matched = _find_connected_emulator(hdc, name)
        if matched is not None:
            return {
                "status": "ok", "command": "emulator-start",
                "name": name, "pid": proc.pid,
                "connected_devices": [matched["target"]],
                "message": f"模拟器已启动: {matched['target']}",
            }

        rc = proc.poll()
        if rc is not None:
            return {
                "status": "error", "command": "emulator-start",
                "error_type": "emulator_exited",
                "message": f"Emulator 进程提前退出（返回码 {rc}）",
            }
        last_targets = _hdc_targets(hdc)
        time.sleep(poll_interval)

    new_targets = sorted(set(last_targets) - existing)
    return {
        "status": "error", "command": "emulator-start",
        "error_type": "emulator_boot_timeout",
        "message": f"等待 {wait_hdc_sec}s 仍未发现实例 {name!r} 对应的 hdc 设备",
        "pid": proc.pid,
        "observed_new_targets": new_targets,
    }


def stop_emulator(
    name: str, deveco_path: Optional[Path] = None
) -> dict:
    try:
        binary = _emulator_binary(deveco_path)
    except FileNotFoundError as e:
        return {
            "status": "error", "command": "emulator-stop",
            "error_type": "deveco_not_found", "message": str(e),
        }
    r = run_cmd([binary, "-stop", name], timeout=30)
    if r.returncode != 0:
        return {
            "status": "error", "command": "emulator-stop",
            "error_type": "stop_failed",
            "message": (r.stderr or r.stdout).strip(),
        }
    return {"status": "ok", "command": "emulator-stop", "name": name}
