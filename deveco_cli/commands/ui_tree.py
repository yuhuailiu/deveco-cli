from __future__ import annotations

import time
from pathlib import Path

from .._config import get_config
from .._runner import ensure_device, resolve_hdc_target, run_cmd
from .._output import progress


def get_app_ui_tree(
    project: Path | str,
    mode: str,
    output_directory: Path | str,
    device: str | None = None,
) -> dict:
    config = get_config(project)
    hdc = str(config.hdc)
    resolved_device, err = resolve_hdc_target(hdc, device)
    if err is not None:
        return {**err, "command": "ui-tree"}
    err = ensure_device(hdc, resolved_device)
    if err is not None:
        return {**err, "command": "ui-tree"}
    hdc_t = [hdc] + (["-t", resolved_device] if resolved_device else [])

    out_dir = Path(output_directory).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())

    if mode == "full":
        remote = f"/data/local/tmp/layout_{ts}.json"
        local = out_dir / f"ui_tree_{ts}.json"

        progress("获取完整 UI 树...")
        dump = run_cmd([*hdc_t, "shell", "uitest", "dumpLayout", "-p", remote])
        if not dump.ok:
            return {"status": "error", "command": "ui-tree", "error_type": "dump_failed",
                    "message": "uitest dumpLayout 失败", "detail": dump.stderr[:2000]}

        recv = run_cmd([*hdc_t, "file", "recv", remote, str(local)])
        if not recv.ok:
            return {"status": "error", "command": "ui-tree", "error_type": "recv_failed",
                    "message": "文件传输失败", "detail": recv.stderr[:2000]}

        return {"status": "ok", "command": "ui-tree", "mode": "full",
                "file": str(local), "message": f"UI 树已保存到 {local}"}

    else:  # simple
        progress("获取窗口节点信息...")
        r = run_cmd([*hdc_t, "shell", "hidumper", "-s", "RenderService", "-a", "screen"])
        if not r.ok:
            return {"status": "error", "command": "ui-tree", "error_type": "hidumper_failed",
                    "message": "hidumper 失败", "detail": r.stderr[:2000]}

        local = out_dir / f"ui_tree_simple_{ts}.txt"
        local.write_text(r.stdout)
        return {"status": "ok", "command": "ui-tree", "mode": "simple",
                "file": str(local), "content": r.stdout,
                "message": f"窗口节点信息已保存到 {local}"}
