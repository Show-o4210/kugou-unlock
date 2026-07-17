#!/usr/bin/env python3
"""
酷狗音乐本地解密工具（入口脚本）。

实现代码位于包 `kugou_unlock/`，本文件仅作命令行入口，便于：
  - 双击 run.bat / 直接 python unlock_tool.py
  - 保持历史命令兼容

功能：
  - 解析安卓端 MMKV 密钥库（mggkey），导出 kgg.key
  - 解密酷狗新格式 .kgg（QMC2）
  - 解密酷狗旧格式 .kgm / .kgma / .vpr
"""

from __future__ import annotations

from kugou_unlock.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
