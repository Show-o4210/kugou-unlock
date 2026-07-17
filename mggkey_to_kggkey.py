#!/usr/bin/env python3
"""兼容旧命令名的入口，实际逻辑见 unlock_tool.py / kugou_unlock.cli。"""
from kugou_unlock.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
