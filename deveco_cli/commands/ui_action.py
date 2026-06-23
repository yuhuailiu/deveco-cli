from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import re
import tempfile
import time
from pathlib import Path
from typing import Optional

from .._config import get_config
from .._runner import ensure_device, resolve_hdc_target, run_cmd
from .._output import progress


@contextmanager
def _dump_layout_lock():
    lock_path = Path(tempfile.gettempdir()) / "deveco_cli_dump_layout.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def perform_ui_action(
    project: Path | str,
    action_type: str,
    device: Optional[str] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
    element_id: Optional[str] = None,
    text: Optional[str] = None,
    direction: Optional[int] = None,
    velocity: Optional[int] = None,
    step_length: Optional[int] = None,
    key1: Optional[str] = None,
    key2: Optional[str] = None,
    key3: Optional[str] = None,
    save_path: Optional[str] = None,
    local_path: Optional[str] = None,
    display_id: Optional[int] = None,
) -> dict:
    config = get_config(project)
    hdc = str(config.hdc)
    resolved_device, err = resolve_hdc_target(hdc, device)
    if err is not None:
        return {**err, "command": "ui-action"}
    err = ensure_device(hdc, resolved_device)
    if err is not None:
        return {**err, "command": "ui-action"}
    hdc_t = [hdc] + (["-t", resolved_device] if resolved_device else [])

    def _err(msg: str, detail: str = "") -> dict:
        r = {"status": "error", "command": "ui-action",
             "error_type": "action_failed", "message": msg}
        if detail:
            r["detail"] = detail[:2000]
        return r

    def _resolve_point_by_id(wanted_id: str) -> tuple[int, int] | dict:
        last_detail = ""
        data: dict | None = None
        for attempt in range(1, 4):
            ts = int(time.time() * 1000)
            remote = f"/data/local/tmp/ui_action_layout_{ts}_{attempt}.json"
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                local = Path(tmp.name)
            try:
                # `uitest dumpLayout` can produce an empty/partial file when multiple
                # CLI processes dump concurrently. Serialize the dump/recv pair and
                # retry empty parses so id-based actions remain reliable.
                with _dump_layout_lock():
                    dump = run_cmd([*hdc_t, "shell", "uitest", "dumpLayout", "-p", remote])
                    if not dump.ok:
                        return _err("dumpLayout 失败，无法按 id 定位组件", dump.stderr or dump.stdout)
                    recv = run_cmd([*hdc_t, "file", "recv", remote, str(local)])
                    if not recv.ok:
                        return _err("拉取 dumpLayout 结果失败", recv.stderr or recv.stdout)

                if not local.exists() or local.stat().st_size == 0:
                    last_detail = f"dumpLayout 本地文件为空: {local}"
                    time.sleep(0.15 * attempt)
                    continue

                try:
                    data = json.loads(local.read_text(encoding="utf-8"))
                    break
                except Exception as e:
                    last_detail = str(e)
                    time.sleep(0.15 * attempt)
            finally:
                try:
                    local.unlink()
                except OSError:
                    pass

        if data is None:
            return _err("解析 dumpLayout JSON 失败", last_detail)

        matches: list[dict] = []

        def walk(node: dict) -> None:
            attrs = node.get("attributes", {})
            if attrs.get("id") == wanted_id or attrs.get("key") == wanted_id:
                matches.append(attrs)
            for child in node.get("children", []):
                walk(child)

        walk(data)
        if not matches:
            return {
                "status": "error", "command": "ui-action",
                "error_type": "element_not_found",
                "message": f"未在当前 UI 树中找到 id/key: {wanted_id}",
            }
        attrs = matches[0]
        bounds = attrs.get("bounds", "")
        match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if not match:
            return {
                "status": "error", "command": "ui-action",
                "error_type": "invalid_bounds",
                "message": f"组件 {wanted_id} 缺少有效 bounds: {bounds}",
            }
        x1, y1, x2, y2 = [int(v) for v in match.groups()]
        return (x1 + x2) // 2, (y1 + y2) // 2

    if action_type == "click":
        resolved_id = element_id
        if element_id is not None and (x is None or y is None):
            point = _resolve_point_by_id(element_id)
            if isinstance(point, dict):
                return point
            x, y = point
        if x is None or y is None:
            return {"status": "error", "command": "ui-action",
                    "error_type": "missing_params", "message": "click 需要 --x/--y 或 --id"}
        r = run_cmd([*hdc_t, "shell", "uitest", "uiInput", "click", str(x), str(y)])
        if not r.ok:
            return _err("click 操作失败", r.stderr)
        result = {"status": "ok", "command": "ui-action", "action": "click", "x": x, "y": y}
        if resolved_id is not None:
            result["id"] = resolved_id
        return result

    elif action_type == "inputText":
        resolved_id = element_id
        if element_id is not None and (x is None or y is None):
            point = _resolve_point_by_id(element_id)
            if isinstance(point, dict):
                return point
            x, y = point
        if x is None or y is None or text is None:
            return {"status": "error", "command": "ui-action",
                    "error_type": "missing_params", "message": "inputText 需要 --text，并提供 --x/--y 或 --id"}
        run_cmd([*hdc_t, "shell", "uitest", "uiInput", "click", str(x), str(y)])
        time.sleep(0.3)
        run_cmd([*hdc_t, "shell", "uitest", "uiInput", "keyEvent", "2072", "2017"])
        time.sleep(0.1)
        run_cmd([*hdc_t, "shell", "uitest", "uiInput", "keyEvent", "2071"])
        time.sleep(0.1)
        r = run_cmd([*hdc_t, "shell", "uitest", "uiInput", "inputText", str(x), str(y), text])
        if not r.ok:
            return _err("inputText 操作失败", r.stderr)
        result = {"status": "ok", "command": "ui-action", "action": "inputText", "text": text, "x": x, "y": y}
        if resolved_id is not None:
            result["id"] = resolved_id
        return result

    elif action_type == "directionalFling":
        d = str(direction if direction is not None else 0)
        v = str(velocity if velocity is not None else 600)
        s = str(step_length if step_length is not None else 200)
        r = run_cmd([*hdc_t, "shell", "uitest", "uiInput", "dircFling", d, v, s])
        if not r.ok:
            return _err("directionalFling 操作失败", r.stderr)
        return {"status": "ok", "command": "ui-action", "action": "directionalFling",
                "direction": d, "velocity": v, "step_length": s}

    elif action_type == "keyEvent":
        keys = [k for k in [key1, key2, key3] if k is not None]
        if not keys:
            return {"status": "error", "command": "ui-action",
                    "error_type": "missing_params", "message": "keyEvent 需要 --key1"}
        r = run_cmd([*hdc_t, "shell", "uitest", "uiInput", "keyEvent", *keys])
        if not r.ok:
            return _err("keyEvent 操作失败", r.stderr)
        return {"status": "ok", "command": "ui-action", "action": "keyEvent", "keys": keys}

    elif action_type == "screenshot":
        ts = int(time.time() * 1000)
        remote = save_path or f"/data/local/tmp/screenshot_{ts}.png"
        local = Path(local_path) if local_path else config.project_path / "screenshot" / f"{ts}.png"
        local.parent.mkdir(parents=True, exist_ok=True)

        cmd = [*hdc_t, "shell", "uitest", "screenCap", "-p", remote]
        if display_id is not None:
            cmd += ["-d", str(display_id)]

        progress("截图中...")
        r = run_cmd(cmd)
        if not r.ok:
            return _err("截图失败", r.stderr)

        recv = run_cmd([*hdc_t, "file", "recv", remote, str(local)])
        if not recv.ok:
            return _err("截图传输失败", recv.stderr)
        if not local.exists() or local.stat().st_size == 0:
            return _err("截图传输失败", f"本地文件未生成或为空: {local}")

        return {"status": "ok", "command": "ui-action", "action": "screenshot",
                "file": str(local), "message": f"截图已保存到 {local}"}

    else:
        return {"status": "error", "command": "ui-action",
                "error_type": "unknown_action",
                "message": f"未知操作类型: {action_type}。"
                           "支持: click, inputText, directionalFling, keyEvent, screenshot"}
