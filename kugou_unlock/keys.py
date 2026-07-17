"""kgg.key 读写辅助。"""
from __future__ import annotations

from pathlib import Path

from .mmkv import write_kgg_key


def load_kgg_key(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if "$" in line:
            h, k = line.split("$", 1)
            mapping[h] = k
    return mapping


def resolve_key_file(path: Path) -> Path:
    """查找 kgg.key：原路径 -> tools/ -> tootls/（历史拼写）。"""
    p = Path(path)
    if p.exists():
        return p
    for d in ("tools", "tootls"):
        cand = Path(d) / p.name
        if cand.exists():
            return cand
    return p
