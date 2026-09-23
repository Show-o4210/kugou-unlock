"""兼容入口；新用法请运行 unlock_tool.py --enrich。"""

from __future__ import annotations

import argparse
from pathlib import Path

from kugou_unlock.enrich import run_enrichment


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich audio from manually exported KuGou Android data."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lyrics", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cover-cache", type=Path, required=True)
    parser.add_argument("--external-only", action="store_true")
    args = parser.parse_args()
    try:
        total, ok, failures = run_enrichment(
            args.output,
            args.lyrics,
            args.database,
            args.cover_cache,
            external_only=args.external_only,
        )
    except Exception as exc:
        print(f"[!] {exc}")
        return 1
    print(f"[=] enriched={ok} total={total} failed={len(failures)}")
    for failure in failures:
        print(f"[!] {failure}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
