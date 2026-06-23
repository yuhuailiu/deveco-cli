# deveco-cli

DevEco Studio 工具链的 Python CLI 封装。提供 9 条命令，覆盖鸿蒙应用开发从构建、UI 操控到日志采集和模拟器管理的完整流程。**所有输出均为 JSON（stdout），进度信息输出到 stderr**，天然适合脚本自动化与 AI Agent 驱动场景。

> 仅支持 macOS，DevEco Studio 须已安装于本机。安装路径与鸿蒙工程路径均不得含空格。

---

## Quick Start

```bash
# 1. 安装
uv pip install -e .   # 或 pip install -e .

# 2. 验证
deveco-cli --help

# 3. 第一条命令：构建工程
deveco-cli build --project /path/to/my-harmony-app
```

---

## 命令总览

| 命令 | 功能 | 典型用法 |
|---|---|---|
| `build` | 构建 HAP / HSP / HAR | `deveco-cli build -p <工程路径>` |
| `sync` | 同步工程依赖（ohpm + hvigorw） | `deveco-cli sync -p <工程路径>` |
| `check` | ArkTS 静态语法检查（LSP 级别） | `deveco-cli check -p <工程路径> Index.ets` |
| `start` | 安装并启动应用到设备 | `deveco-cli start -p <工程路径>` |
| `ui-tree` | 获取当前界面 UI 组件树 | `deveco-cli ui-tree -p <工程路径> --mode simple -o ./out` |
| `ui-action` | UI 操作：点击 / 输入 / 滑动 / 按键 / 截图 | `deveco-cli ui-action -p <工程路径> --type click --x 360 --y 640` |
| `knowledge` | 搜索 HarmonyOS 开发文档 | `deveco-cli knowledge ArkTS Text 组件` |
| `hilog` | 设备日志采集与清理 | `deveco-cli hilog collect` |
| `emulator` | 模拟器管理（list / start / stop） | `deveco-cli emulator start --name "Pura 80 Ultra"` |

---

## 命令详解

### `build` — 构建 HAP / HSP / HAR

自动推断构建任务（`assembleApp` / `assembleHap` / `assembleHsp` / `assembleHar`），依次执行 `ohpm install` 和 `hvigorw`。

**Synopsis**
```
deveco-cli build -p <工程路径> [-m <模块>] [--product <产品>] [-i <意图>] [--log-path <日志>]
```

**参数**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--project` | `-p` | 是 | — | 鸿蒙工程根目录 |
| `--module` | `-m` | 否 | — | 模块名（如 `entry@default`），不传则构建整个 APP |
| `--product` | | 否 | `default` | Product 名称 |
| `--intent` | `-i` | 否 | `LogVerification` | 构建意图，见下表 |
| `--log-path` | | 否 | — | 构建日志保存路径 |

| `--intent` 值 | buildMode | debuggable | debugLine |
|---|---|---|---|
| `LogVerification`（默认）| debug | true | false |
| `UIDebug` | debug | true | true |
| `PerformanceProfile` | debug | true | — |
| `Release` | release | false | — |

**Example**
```bash
# 构建整个 APP
deveco-cli build -p ~/projects/MyApp

# 仅构建 entry 模块，Release 模式
deveco-cli build -p ~/projects/MyApp -m entry@default -i Release
```

```json
{
  "status": "ok",
  "command": "build",
  "task": "assembleHap",
  "intent": "LogVerification",
  "hap_files": ["/path/to/entry-default-signed.hap"],
  "message": "构建成功，找到 1 个 HAP 文件"
}
```

---

### `sync` — 同步工程依赖

执行 `ohpm install`（可跳过）和 `hvigorw --sync`，用于初始化依赖或更新 Gradle 配置。

**Synopsis**
```
deveco-cli sync -p <工程路径> [--product <产品>] [--skip-ohpm] [--log-path <日志>]
```

**参数**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--project` | `-p` | 是 | — | 鸿蒙工程根目录 |
| `--product` | | 否 | `default` | Product 名称 |
| `--skip-ohpm` | | 否 | false | 跳过 ohpm install 步骤 |
| `--log-path` | | 否 | — | 日志保存路径 |

**Example**
```bash
deveco-cli sync -p ~/projects/MyApp

# 已运行过 ohpm，仅重新 sync hvigorw
deveco-cli sync -p ~/projects/MyApp --skip-ohpm
```

```json
{
  "status": "ok",
  "command": "sync",
  "message": "项目同步成功"
}
```

---

### `check` — ArkTS 静态语法检查

启动 DevEco Studio 内置的 `ace-server` LSP 服务，对指定 `.ets` 文件进行静态分析，返回与 IDE 一致的诊断结果。首次运行会在工程根目录自动生成 `deveco-cli.toml` 配置文件。

**Synopsis**
```
deveco-cli check -p <工程路径> <file.ets> [<file2.ets> ...]
```

**参数**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--project` | `-p` | 是 | — | 鸿蒙工程根目录 |
| `<files>` | | 是 | — | 一个或多个 `.ets` 文件路径（位置参数） |

**Example**
```bash
deveco-cli check -p ~/projects/MyApp src/main/ets/pages/Index.ets

# 同时检查多个文件
deveco-cli check -p ~/projects/MyApp src/main/ets/pages/Index.ets src/main/ets/components/Button.ets
```

```json
{
  "status": "ok",
  "command": "check",
  "files_checked": 1,
  "total_issues": 2,
  "diagnostics": {
    "/abs/path/to/Index.ets": [
      {
        "range": {"start": {"line": 10, "character": 4}, "end": {"line": 10, "character": 12}},
        "severity": 1,
        "code": "ts(2322)",
        "message": "Type 'string' is not assignable to type 'number'."
      }
    ]
  },
  "message": "检查完成，2 个问题"
}
```

`severity`：`1` Error · `2` Warning · `3` Information · `4` Hint

---

### `start` — 安装并启动应用

将 HAP 安装到已连接的设备或模拟器，强制停止同名进程后启动指定 Ability。未指定 `--device` 时自动发现已连接设备。

**Synopsis**
```
deveco-cli start -p <工程路径> [-m <模块>] [-t <构建目标>] [-d <设备>] [-a <Ability>]
```

**参数**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--project` | `-p` | 是 | — | 鸿蒙工程根目录 |
| `--module` | `-m` | 否 | `entry` | 模块名 |
| `--target` | `-t` | 否 | `default` | 构建目标 |
| `--device` | `-d` | 否 | 自动发现 | 设备名或 ID（来自 `hdc list targets`） |
| `--ability` | `-a` | 否 | `EntryAbility` | Ability 名称 |

**Example**
```bash
deveco-cli start -p ~/projects/MyApp

# 指定设备和 Ability
deveco-cli start -p ~/projects/MyApp -d emulator-5554 -a MainAbility
```

```json
{
  "status": "ok",
  "command": "start",
  "bundle_name": "com.example.myapp",
  "ability": "EntryAbility",
  "hap": "/path/to/entry-default-signed.hap",
  "message": "应用已启动"
}
```

---

### `ui-tree` — 获取 UI 组件树

Dump 当前界面的 UI 组件树并保存到本地目录。`full` 模式通过 `uitest dumpLayout` 输出完整 JSON；`simple` 模式通过 `hidumper` 输出关键节点文本。

**Synopsis**
```
deveco-cli ui-tree -p <工程路径> --mode simple|full -o <输出目录> [-d <设备>]
```

**参数**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--project` | `-p` | 是 | — | 鸿蒙工程根目录 |
| `--mode` | | 是 | — | `simple`（关键节点文本）或 `full`（完整 JSON） |
| `--output-dir` | `-o` | 是 | — | 输出目录（文件名自动带时间戳） |
| `--device` | `-d` | 否 | 自动发现 | 设备名或 ID |

**Example**
```bash
deveco-cli ui-tree -p ~/projects/MyApp --mode simple -o ./ui-snapshots

deveco-cli ui-tree -p ~/projects/MyApp --mode full -o ./ui-snapshots -d 127.0.0.1:5555
```

```json
{
  "status": "ok",
  "command": "ui-tree",
  "mode": "simple",
  "file": "/abs/path/to/ui-snapshots/ui_tree_simple_1718000000.txt",
  "content": "...",
  "message": "UI 树已保存"
}
```

---

### `ui-action` — UI 操作

在已连接设备上执行 UI 操作，通过 `hdc shell uitest uiInput` 驱动。支持 5 种操作类型，各类型所需参数不同。

**Synopsis**
```
deveco-cli ui-action -p <工程路径> --type <类型> [类型专属参数...] [-d <设备>]
```

**通用参数**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--project` | `-p` | 是 | — | 鸿蒙工程根目录 |
| `--type` | | 是 | — | 操作类型，见下表 |
| `--device` | `-d` | 否 | 自动发现 | 设备名或 ID |
| `--id` | | 否 | — | ArkUI 组件 id/key；`click` / `inputText` 可用它替代坐标 |

**各类型专属参数**

| `--type` | 专属参数 | 说明 |
|---|---|---|
| `click` | `--x` + `--y`，或 `--id` | 点击坐标或指定 id/key 组件中心点 |
| `inputText` | `--text`（必填），并提供 `--x` + `--y` 或 `--id` | 先清空再输入（click → 全选 → 删除 → 输入） |
| `directionalFling` | `--direction`（0左/1右/2上/3下，默认0）`--velocity`（默认600）`--step-length`（默认200）| 方向滑动 |
| `keyEvent` | `--key1`（必填）`--key2`（可选）`--key3`（可选）| 按键或组合键 |
| `screenshot` | `--save-path`（设备路径，可选）`--local-path`（本地路径，可选）`--display-id`（多屏，可选）| 截图并拉取到本地 |

**Example**
```bash
# 点击
deveco-cli ui-action -p ~/projects/MyApp --type click --x 360 --y 640

# 按 ArkUI id 点击
deveco-cli ui-action -p ~/projects/MyApp --type click --id home-add-button

# 在输入框输入文字
deveco-cli ui-action -p ~/projects/MyApp --type inputText --x 200 --y 300 --text "Hello World"

# 按 ArkUI id 在输入框输入文字
deveco-cli ui-action -p ~/projects/MyApp --type inputText --id food-form-name-input --text "Hello World"

# 向上滑动
deveco-cli ui-action -p ~/projects/MyApp --type directionalFling --direction 2 --velocity 800

# 按下返回键
deveco-cli ui-action -p ~/projects/MyApp --type keyEvent --key1 Back

# 截图保存到本地
deveco-cli ui-action -p ~/projects/MyApp --type screenshot --local-path ./screenshot.png
```

```json
{
  "status": "ok",
  "command": "ui-action",
  "action": "click",
  "message": "操作成功"
}
```

---

### `knowledge` — 搜索 HarmonyOS 开发文档

根据关键词搜索鸿蒙开发知识库，返回相关文档片段，用于辅助代码生成。

**Synopsis**
```
deveco-cli knowledge <关键词> [<关键词2> ...] [--max-chars <字符数>]
```

**参数**

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `<keywords>` | 是 | — | 一个或多个关键词（位置参数） |
| `--max-chars` | 否 | `5000` | 最大返回字符数 |

**Example**
```bash
deveco-cli knowledge ArkTS Text 组件

deveco-cli knowledge 页面路由 router --max-chars 3000
```

```json
{
  "status": "ok",
  "command": "knowledge",
  "keywords": ["ArkTS", "Text", "组件"],
  "data": { ... }
}
```

---

### `hilog` — 设备日志采集与清理

通过 `hdc shell hilog` 采集、清理设备日志，并可列出当前 hdc 已连接设备。该命令不需要传入工程路径。

**Synopsis**
```
deveco-cli hilog list-devices
deveco-cli hilog clear [-d <设备>]
deveco-cli hilog collect [-d <设备>] [--prefix <前缀>] [--lines <行数>]
```

**参数（clear / collect）**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--device` | `-d` | 否 | 自动发现 | 设备名或 ID（来自 `hdc list targets`） |
| `--prefix` | | 否 | 空字符串 | 日志过滤前缀，默认不过滤 |
| `--lines` | | 否 | `2000` | 最多返回的日志行数，范围 `1-5000` |

**Example**
```bash
deveco-cli hilog list-devices

deveco-cli hilog clear

deveco-cli hilog collect

deveco-cli hilog collect -d 127.0.0.1:5555 --lines 500

deveco-cli hilog collect --prefix "[ARKPILOT_DEBUG]"
```

```json
{
  "status": "ok",
  "command": "hilog-collect",
  "device": "default",
  "prefix": "",
  "requested_lines": 2000,
  "count": 2,
  "logs": ["..."],
  "message": "采集到 2 行匹配日志"
}
```

---

### `emulator` — 模拟器管理

提供 `list / start / stop` 三个子命令，封装 `/Applications/DevEco-Studio.app/Contents/tools/emulator/Emulator`。`start` 会后台拉起 Emulator 进程，然后通过设备侧参数 `ohos.qemu.hvd.name` 反查实例名，直到找到与 `--name` 对应的 `hdc target`。

**Synopsis**
```
deveco-cli emulator list
deveco-cli emulator start --name "<实例名>" [--wait-hdc <秒数>]
deveco-cli emulator stop  --name "<实例名>"
```

**参数（start）**

| 参数 | 短写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--name` | `-n` | 是 | — | 模拟器实例名（`deveco-cli emulator list` 可查） |
| `--wait-hdc` | | 否 | `90` | 等待 hdc 发现设备的最大秒数，超时返回 `emulator_boot_timeout` |

**Example**
```bash
deveco-cli emulator list

deveco-cli emulator start --name "Pura 80 Ultra" --wait-hdc 180

deveco-cli emulator stop --name "Pura 80 Ultra"
```

```json
{
  "status": "ok",
  "command": "emulator-start",
  "name": "Pura 80 Ultra",
  "pid": 67615,
  "connected_devices": ["127.0.0.1:5555"],
  "message": "模拟器已启动: 127.0.0.1:5555"
}
```

若目标实例已经在运行，`start` 会返回 `already_running: true`，并给出该实例对应的 `connected_devices`。其他真机或模拟器在线不会阻止启动指定实例。

**`error_type` 扩展**：`deveco_not_found` / `emulator_not_found` / `emulator_exited` / `emulator_boot_timeout` / `popen_failed` / `list_failed` / `stop_failed`。

---

## 输出协议

所有命令均遵循同一套 JSON 协议：

- **stdout**：唯一的机器可读输出，始终为合法 JSON
- **stderr**：进度信息（格式 `[deveco-cli] ...`），供人类阅读，**不要解析**
- **退出码**：`0` 成功，`1` 失败

**成功响应通用字段**

```json
{ "status": "ok", "command": "<命令名>", ... }
```

**失败响应通用字段**

```json
{
  "status": "error",
  "command": "<命令名>",
  "error_type": "<分类>",
  "message": "<描述>",
  "detail": "<可选：原始日志，截断至 2000 字符>",
  "suggestion": "<可选：修复建议>"
}
```

常见 `error_type`：

| 值 | 含义 |
|---|---|
| `config_error` | DevEco 未找到或工程路径不存在 |
| `ohpm_failed` | ohpm install 失败 |
| `build_failed` | hvigorw 构建失败 |
| `sync_failed` | hvigorw sync 失败 |
| `lsp_init_timeout` | ace-server 启动超时 |
| `no_device` | 未找到已连接设备 |
| `hap_not_found` | 未找到 HAP 构建产物 |
| `install_failed` | hdc install 失败 |
| `action_failed` | UI 操作执行失败 |
| `connection_error` | 知识库 API 不可达 |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEVECO_PATH` | `/Applications/DevEco-Studio.app` | DevEco Studio 安装路径 |
| `DEFAULT_HVD` | — | 默认设备/模拟器实例名。影响 `start`、`ui-tree`、`ui-action`、`hilog clear`、`hilog collect`；会解析为对应的 `hdc target` |
| `ADK_KNOWLEDGE_API` | 内置地址 | `knowledge` 命令使用的搜索 API endpoint |

`DEFAULT_HVD` 仅匹配已连接设备或已运行模拟器实例；不会隐式启动模拟器。命令行显式传入的 `--device` 优先于该环境变量。

---

## AI Agent 集成指南

deveco-cli 的设计目标之一是作为 Agent 的工具调用层：

**解析输出的推荐模式**

```python
import subprocess, json

result = subprocess.run(
    ["deveco-cli", "build", "--project", project_path],
    capture_output=True, text=True
)
# stdout 是 JSON，stderr 是进度日志（不解析）
data = json.loads(result.stdout)
if data["status"] == "error":
    # 利用 error_type 决策下一步
    handle_error(data["error_type"], data.get("suggestion"))
```

**典型 Agent 工作流**

```
check（静态检查）
  → 有 Error？修复代码后重试
  → 通过 → build（构建）
              → 失败？根据 detail 排查
              → 成功 → start（安装启动）
                          → ui-tree（获取界面结构）
                            → ui-action（执行操作）
                              → ui-tree（验证结果）
                                → 循环...
```

**注意事项**

- `check` 首次运行较慢（ace-server 需要索引工程，最长等待约 5 分钟），后续快
- `build` 超时 600 秒，`sync` 超时 300 秒，请勿过早中断
- 多设备环境下建议始终传 `--device`，避免自动选择到非预期设备

---

## License

MIT
