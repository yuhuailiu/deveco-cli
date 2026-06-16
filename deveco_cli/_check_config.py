from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._config import DevEcoConfig
from ._json5 import parse_json5


@dataclass
class CheckConfig:
    sdkJsPath: str
    aceLoaderPath: str
    jsComponentType: str = "Declaration"
    apiType: str = "Stage"
    maxOldSpaceSize: int = 8192


def _extract_sdk_level(bp_data: dict) -> str:
    """从 build-profile.json5 的 products[0].compatibleSdkVersion 提取括号内数字。"""
    try:
        ver = bp_data["products"][0]["compatibleSdkVersion"]
        m = re.search(r"\((\d+)\)", str(ver))
        if m:
            return m.group(1)
        return str(ver)
    except (KeyError, IndexError, TypeError):
        return "12"


def _extract_runtime_os(bp_data: dict) -> str:
    try:
        return bp_data["products"][0]["runtimeOS"]
    except (KeyError, IndexError, TypeError):
        return "HarmonyOS"


def _extract_device_types(module_path: Path) -> list[str]:
    """从模块的 src/main/module.json5 读取 deviceTypes。"""
    mj = module_path / "src" / "main" / "module.json5"
    if not mj.exists():
        return ["default"]
    try:
        data = parse_json5(mj.read_text())
        types = data.get("module", {}).get("deviceTypes", ["default"])
        return types if types else ["default"]
    except Exception:
        return ["default"]


def _generate_default_toml(config: DevEcoConfig) -> str:
    sdk_js = str(config.sdk_ets_api)
    ace_loader = str(config.ace_loader)
    return (
        "# deveco-cli.toml — deveco-cli 配置\n"
        "# 以下参数用于 ace-server LSP 初始化，默认值从 SDK 和项目配置自动检测。\n"
        "# 如需覆盖，直接修改对应字段。\n"
        "\n"
        "[check]\n"
        "# SDK ArkTS 声明文件路径\n"
        f'sdkJsPath = "{sdk_js}"\n'
        "# ace-loader 路径\n"
        f'aceLoaderPath = "{ace_loader}"\n'
        "# 组件类型\n"
        'jsComponentType = "Declaration"\n'
        "# 项目模式\n"
        'apiType = "Stage"\n'
        "# Node.js 最大堆内存（MB）\n"
        "maxOldSpaceSize = 8192\n"
    )


def load_check_config(project_path: Path, config: DevEcoConfig) -> tuple[CheckConfig, dict[str, Any]]:
    """
    加载 check 配置。如果 deveco-cli.toml 不存在，自动生成默认值并写入。

    Returns:
        (check_cfg, bp_data) — CheckConfig 和 build-profile.json5 的内容（可能为空 dict）
    """
    toml_path = project_path / "deveco-cli.toml"

    if not toml_path.exists():
        toml_content = _generate_default_toml(config)
        toml_path.write_text(toml_content, encoding="utf-8")
        toml_data: dict[str, Any] = tomllib.loads(toml_content)
    else:
        toml_data = tomllib.loads(toml_path.read_text(encoding="utf-8"))

    check_section = toml_data.get("check", {})

    check_cfg = CheckConfig(
        sdkJsPath=check_section.get("sdkJsPath", str(config.sdk_ets_api)),
        aceLoaderPath=check_section.get("aceLoaderPath", str(config.ace_loader)),
        jsComponentType=check_section.get("jsComponentType", "Declaration"),
        apiType=check_section.get("apiType", "Stage"),
        maxOldSpaceSize=check_section.get("maxOldSpaceSize", 8192),
    )

    bp: dict[str, Any] = {}
    bp_path = project_path / "build-profile.json5"
    if bp_path.exists():
        try:
            bp = parse_json5(bp_path.read_text())
        except Exception:
            bp = {}

    return check_cfg, bp
