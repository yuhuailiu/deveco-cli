from __future__ import annotations

import time
from pathlib import Path

from .._config import get_config
from .._json5 import parse_json5
from .._runner import run_cmd
from .._output import progress


def _get_bundle_name(project_path: Path) -> str:
    app_json5 = project_path / "AppScope" / "app.json5"
    if not app_json5.exists():
        raise FileNotFoundError(f"未找到 app.json5: {app_json5}")
    bundle = parse_json5(app_json5.read_text()).get("app", {}).get("bundleName", "")
    if not bundle:
        raise ValueError("app.json5 中未找到 bundleName")
    return bundle


def _find_hap(project_path: Path, module: str, target: str) -> Path | None:
    # 精确路径
    p = project_path / module / "build" / "outputs" / target / f"{module}-{target}-signed.hap"
    if p.exists():
        return p
    # glob 兜底，取最新
    haps = sorted(project_path.rglob("build/**/*.hap"),
                  key=lambda f: f.stat().st_mtime, reverse=True)
    return haps[0] if haps else None


def start_app(
    project: Path | str,
    module: str = "entry",
    target: str = "default",
    device: str | None = None,
    ability: str = "EntryAbility",
) -> dict:
    config = get_config(project)
    hdc = str(config.hdc)

    try:
        bundle = _get_bundle_name(config.project_path)
    except Exception as e:
        return {"status": "error", "command": "start", "error_type": "config_error", "message": str(e)}

    # 解析设备
    hdc_t = [hdc]
    if device:
        hdc_t = [hdc, "-t", device]
    else:
        r = run_cmd([hdc, "list", "targets"])
        targets = [t.strip() for t in r.stdout.strip().split("\n")
                   if t.strip() and t.strip() != "[Empty]"]
        if not targets:
            return {"status": "error", "command": "start", "error_type": "no_device",
                    "message": "未发现已连接的设备，请连接真机或启动模拟器"}
        if len(targets) > 1:
            hdc_t = [hdc, "-t", targets[0]]
            progress(f"多个设备，使用: {targets[0]}")

    # 停止已有进程
    check = run_cmd([*hdc_t, "shell", "aa", "dump", "-a"])
    if bundle in check.stdout:
        progress(f"停止已运行的 {bundle}...")
        run_cmd([*hdc_t, "shell", "aa", "force-stop", bundle])
        time.sleep(0.5)

    # 查找 HAP
    hap = _find_hap(config.project_path, module, target)
    if hap is None:
        return {"status": "error", "command": "start", "error_type": "hap_not_found",
                "message": f"未找到 HAP 文件，请先运行 deveco-cli build --project {project}"}

    # 安装
    progress(f"安装 {hap.name}...")
    install = run_cmd([*hdc_t, "install", "-r", str(hap)])
    if not install.ok:
        return {"status": "error", "command": "start", "error_type": "install_failed",
                "message": f"HAP 安装失败（退出码 {install.returncode}）",
                "detail": install.stderr[:2000]}

    # 启动
    progress(f"启动 {bundle}/{ability}...")
    start = run_cmd([*hdc_t, "shell", "aa", "start", "-a", ability, "-b", bundle])
    if not start.ok:
        return {"status": "error", "command": "start", "error_type": "start_failed",
                "message": f"应用启动失败（退出码 {start.returncode}）",
                "detail": start.stderr[:2000]}

    return {
        "status": "ok", "command": "start",
        "bundle_name": bundle, "ability": ability, "hap": str(hap),
        "message": f"应用已启动: {bundle}",
    }
