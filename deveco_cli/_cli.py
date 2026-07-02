from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="deveco-cli",
    help="DevEco Studio 工具链 CLI（deveco-mcp 的 Python 替代）",
    no_args_is_help=True,
)


def _exit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "error":
        raise typer.Exit(1)


def _run(command: str, fn, *args, **kwargs) -> None:
    """调用命令函数并捕获配置层异常，统一转为 JSON 输出。"""
    from ._config import DevEcoNotFoundError, ProjectNotFoundError
    try:
        _exit(fn(*args, **kwargs))
    except typer.Exit:
        raise
    except (DevEcoNotFoundError, ProjectNotFoundError, FileNotFoundError) as e:
        _exit({"status": "error", "command": command,
               "error_type": "config_error", "message": str(e)})
    except Exception as e:
        _exit({"status": "error", "command": command,
               "error_type": "unexpected_error", "message": str(e)})


# ─── build ────────────────────────────────────────────────────────────────────

@app.command()
def build(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
    module: Optional[str] = typer.Option(None, "--module", "-m",
                                         help="模块名（如 entry@default），不传则构建整个 APP"),
    product: str = typer.Option("default", "--product", help="Product 名称"),
    intent: str = typer.Option(
        "LogVerification", "--intent", "-i",
        help="构建意图: LogVerification | UIDebug | PerformanceProfile | Release",
    ),
    log_path: Optional[Path] = typer.Option(None, "--log-path", help="构建日志保存路径"),
):
    """构建 HAP/HSP/HAR（对应 MCP build_project）"""
    from .commands.build import build_project
    _run("build", build_project, project, module, product, intent, log_path)


# ─── sync ─────────────────────────────────────────────────────────────────────

@app.command()
def sync(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
    product: str = typer.Option("default", "--product", help="Product 名称"),
    skip_ohpm: bool = typer.Option(False, "--skip-ohpm", help="跳过 ohpm install"),
    log_path: Optional[Path] = typer.Option(None, "--log-path", help="日志保存路径"),
):
    """项目同步（ohpm install + hvigor --sync）（对应 MCP project_sync）"""
    from .commands.sync import project_sync
    _run("sync", project_sync, project, product, skip_ohpm, log_path)


# ─── check ────────────────────────────────────────────────────────────────────

@app.command()
def check(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
    files: list[Path] = typer.Argument(..., help="待检查的 .ets 文件路径"),
):
    """ArkTS 静态语法检查（对应 MCP check_ets_files）"""
    from .commands.check import check_ets_files
    _run("check", check_ets_files, project, files)


@app.command(name="check-stop")
def check_stop(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
):
    """停止指定工程的 check daemon。"""
    from .commands.check import stop_check_daemon
    _run("check-stop", stop_check_daemon, project)


# ─── start ────────────────────────────────────────────────────────────────────

@app.command()
def start(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
    module: str = typer.Option("entry", "--module", "-m", help="模块名"),
    target: str = typer.Option("default", "--target", "-t", help="构建目标"),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="设备名或 ID"),
    ability: str = typer.Option("EntryAbility", "--ability", "-a", help="Ability 名称"),
):
    """安装并启动应用（对应 MCP start_app）"""
    from .commands.start import start_app
    _run("start", start_app, project, module, target, device, ability)


# ─── ui-tree ──────────────────────────────────────────────────────────────────

@app.command(name="ui-tree")
def ui_tree(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
    mode: str = typer.Option(..., "--mode", help="dump 模式: simple | full"),
    output_dir: Path = typer.Option(..., "--output-dir", "-o", help="输出目录"),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="设备名或 ID"),
):
    """获取 UI 树（对应 MCP get_app_ui_tree）"""
    from .commands.ui_tree import get_app_ui_tree
    _run("ui-tree", get_app_ui_tree, project, mode, output_dir, device)


# ─── ui-action ────────────────────────────────────────────────────────────────

@app.command(name="ui-action")
def ui_action(
    project: Path = typer.Option(..., "--project", "-p", help="HarmonyOS 工程根目录"),
    action_type: str = typer.Option(
        ..., "--type",
        help="操作类型: click | inputText | directionalFling | keyEvent | screenshot",
    ),
    device: Optional[str] = typer.Option(None, "--device", "-d", help="设备名或 ID"),
    x: Optional[int] = typer.Option(None, "--x", help="X 坐标（click/inputText 需要）"),
    y: Optional[int] = typer.Option(None, "--y", help="Y 坐标（click/inputText 需要）"),
    element_id: Optional[str] = typer.Option(None, "--id", help="ArkUI 组件 id/key（click/inputText 可替代坐标）"),
    text: Optional[str] = typer.Option(None, "--text", help="输入文本（inputText 需要）"),
    direction: Optional[int] = typer.Option(None, "--direction",
                                            help="滑动方向: 0=左 1=右 2=上 3=下"),
    velocity: Optional[int] = typer.Option(None, "--velocity", help="滑动速度 px/s"),
    step_length: Optional[int] = typer.Option(None, "--step-length", help="步长 px"),
    key1: Optional[str] = typer.Option(None, "--key1", help="按键 1（keyEvent 需要）"),
    key2: Optional[str] = typer.Option(None, "--key2", help="按键 2（组合键）"),
    key3: Optional[str] = typer.Option(None, "--key3", help="按键 3（组合键）"),
    save_path: Optional[str] = typer.Option(None, "--save-path",
                                            help="设备上的截图路径（screenshot 可选）"),
    local_path: Optional[str] = typer.Option(None, "--local-path",
                                             help="本地保存路径（screenshot 可选）"),
    display_id: Optional[int] = typer.Option(None, "--display-id",
                                             help="显示 ID（多屏截图可选）"),
):
    """UI 操作：点击/输入/滑动/按键/截图（对应 MCP perform_ui_action）"""
    from .commands.ui_action import perform_ui_action
    _run("ui-action", perform_ui_action,
         project, action_type, device,
         x, y, element_id, text, direction, velocity, step_length,
         key1, key2, key3, save_path, local_path, display_id)


# ─── knowledge ────────────────────────────────────────────────────────────────

@app.command()
def knowledge(
    keywords: list[str] = typer.Argument(..., help="搜索关键词（可多个）"),
    max_chars: int = typer.Option(5000, "--max-chars", help="最大返回字符数"),
):
    """搜索 HarmonyOS 开发文档（对应 MCP harmonyos_knowledge_search）"""
    from .commands.knowledge import search_knowledge
    _run("knowledge", search_knowledge, keywords, max_chars)


# ─── hilog ────────────────────────────────────────────────────────────────────

hilog_app = typer.Typer(
    name="hilog",
    help="设备日志管理（list-devices / clear / collect）",
    no_args_is_help=True,
)
app.add_typer(hilog_app)


@hilog_app.command("list-devices")
def hilog_list_devices():
    """列出 hdc 已连接设备。"""
    from .commands.hilog import list_hilog_devices
    _run("hilog-list-devices", list_hilog_devices)


@hilog_app.command("clear")
def hilog_clear(
    device: Optional[str] = typer.Option(None, "--device", "-d", help="设备名或 ID"),
):
    """清空设备 hilog 缓冲区。"""
    from .commands.hilog import clear_hilog
    _run("hilog-clear", clear_hilog, device)


@hilog_app.command("collect")
def hilog_collect(
    device: Optional[str] = typer.Option(None, "--device", "-d", help="设备名或 ID"),
    prefix: str = typer.Option("", "--prefix", help="日志过滤前缀，默认不过滤"),
    lines: int = typer.Option(2000, "--lines", help="最多返回的日志行数，范围 1-5000"),
):
    """采集设备 hilog 日志。"""
    from .commands.hilog import collect_hilog
    _run("hilog-collect", collect_hilog, device, prefix, lines)


# ─── emulator ─────────────────────────────────────────────────────────────────

emulator_app = typer.Typer(
    name="emulator",
    help="鸿蒙模拟器管理（list / start / stop）",
    no_args_is_help=True,
)
app.add_typer(emulator_app)


@emulator_app.command("list")
def emulator_list():
    """列出本机所有已部署的模拟器实例。"""
    from .commands.emulator import list_emulators
    _run("emulator-list", list_emulators)


@emulator_app.command("start")
def emulator_start(
    name: str = typer.Option(..., "--name", "-n", help="模拟器实例名"),
    wait_hdc: int = typer.Option(90, "--wait-hdc", help="等待 hdc 出现设备的最大秒数"),
):
    """启动模拟器（后台进程）并等待 hdc 发现设备。"""
    from .commands.emulator import start_emulator
    _run("emulator-start", start_emulator, name, wait_hdc)


@emulator_app.command("stop")
def emulator_stop(
    name: str = typer.Option(..., "--name", "-n", help="模拟器实例名"),
):
    """停止模拟器。"""
    from .commands.emulator import stop_emulator
    _run("emulator-stop", stop_emulator, name)
