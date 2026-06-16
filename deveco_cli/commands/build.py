from __future__ import annotations

from pathlib import Path
from typing import Optional

from .._config import get_config
from .._runner import run_cmd
from .._json5 import parse_json5
from .._output import progress

_INTENT_FLAGS: dict[str, list[str]] = {
    "LogVerification": ["-p", "buildMode=debug", "-p", "debuggable=true", "-p", "debugLine=false"],
    "UIDebug":         ["-p", "buildMode=debug", "-p", "debuggable=true", "-p", "debugLine=true"],
    "PerformanceProfile": ["-p", "buildMode=debug", "-p", "debuggable=true"],
    "Release":         ["-p", "buildMode=release", "-p", "debuggable=false"],
}

_BASE_FLAGS = ["--sync", "--analyze=normal", "--parallel", "--incremental", "--no-daemon"]


def _resolve_task(project_path: Path, module: str | None) -> tuple[str, list[str]]:
    if module is None:
        return "assembleApp", []

    mod_name = module.split("@")[0]
    module_json5 = project_path / mod_name / "src" / "main" / "module.json5"
    mod_type = "entry"
    if module_json5.exists():
        try:
            mod_type = parse_json5(module_json5.read_text()).get("module", {}).get("type", "entry")
        except Exception:
            pass

    task = {"entry": "assembleHap", "feature": "assembleHap",
            "shared": "assembleHsp", "har": "assembleHar"}.get(mod_type, "assembleHap")
    return task, ["-p", f"module={module}"]


def build_project(
    project: Path | str,
    module: str | None = None,
    product: str = "default",
    build_intent: str = "LogVerification",
    log_path: Path | None = None,
) -> dict:
    config = get_config(project)

    # Step 1: ohpm install
    progress("执行 ohpm install...")
    ohpm = run_cmd(
        [config.ohpm, "install", "--all",
         "--registry", "https://ohpm.openharmony.cn/ohpm/",
         "--strict_ssl", "true"],
        cwd=config.project_path,
    )
    if not ohpm.ok:
        return {
            "status": "error", "command": "build",
            "error_type": "ohpm_failed",
            "message": f"ohpm install 失败（退出码 {ohpm.returncode}）",
            "detail": (ohpm.stderr or ohpm.stdout)[:2000],
        }

    # Step 2: hvigorw build
    task, module_flags = _resolve_task(config.project_path, module)
    intent_flags = _INTENT_FLAGS.get(build_intent, _INTENT_FLAGS["LogVerification"])

    hvigor_args = (
        [config.node, config.hvigorw_js, task]
        + _BASE_FLAGS
        + ["-p", f"product={product}"]
        + module_flags
        + intent_flags
    )

    progress(f"执行 hvigorw {task}...")
    build = run_cmd(hvigor_args, cwd=config.project_path,
                    env_extra={"DEVECO_SDK_HOME": str(config.sdk_home)}, timeout=600)

    if log_path:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        Path(log_path).write_text(build.stdout + "\n" + build.stderr)

    if not build.ok:
        return {
            "status": "error", "command": "build",
            "error_type": "build_failed",
            "message": f"hvigorw {task} 失败（退出码 {build.returncode}）",
            "detail": (build.stderr or build.stdout)[:2000],
            "suggestion": "检查 ArkTS 语法错误，或运行 deveco-cli check 进行静态检查",
        }

    hap_files = list(config.project_path.rglob("build/**/*.hap"))
    return {
        "status": "ok", "command": "build",
        "task": task, "intent": build_intent,
        "hap_files": [str(p) for p in hap_files],
        "message": f"构建成功，找到 {len(hap_files)} 个 HAP 文件",
    }
