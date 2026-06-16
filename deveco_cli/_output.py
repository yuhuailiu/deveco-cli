from __future__ import annotations

import json
import sys


def emit(result: dict) -> None:
    """将结果 dict 输出为 JSON 到 stdout。"""
    print(json.dumps(result, ensure_ascii=False, indent=2))


def progress(message: str) -> None:
    """输出进度信息到 stderr，不干扰 JSON stdout。"""
    print(f"[deveco-cli] {message}", file=sys.stderr)
