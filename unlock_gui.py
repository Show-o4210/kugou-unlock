#!/usr/bin/env python3
"""酷狗本地解密工具 · PySide6 图形界面入口。"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from kugou_unlock.gui_app import run_gui
    except ImportError as e:
        print(
            "无法启动 GUI。请先安装依赖：\n"
            "  pip install -r requirements.txt\n"
            f"详细错误: {e}",
            file=sys.stderr,
        )
        return 1
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
