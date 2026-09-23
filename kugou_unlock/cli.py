"""命令行入口：自动模式 + 高级 MMKV / 解密接口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audio import collect_encrypted_files, detect_process_kind
from .auto import run_auto_mode, run_cleanup_only
from .enrich import run_enrichment
from .kgg import decrypt_kgg_file, read_audio_hash_from_kgg
from .keys import load_kgg_key, resolve_key_file
from .mmkv import (
    decode_value,
    filter_mapping,
    is_valid_mmkv,
    parse_mmkv_raw,
    write_kgg_key,
)
from .pipeline import default_worker_count
from .report import format_csv_tsv, format_json, print_text_format


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="酷狗音乐本地工具：密钥提取、音频解密、手动导出数据的歌词/封面补全。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. 从 mggkey 导出 kgg.key
  python unlock_tool.py -i input/key_database/mggkey_multi_process -o tools/kgg.key

  # 2. 解密当前目录下的 .kgg
  python unlock_tool.py -d . -k tools/kgg.key

  # 3. 解密指定 .kgg
  python unlock_tool.py -d "input/music_files/song.kgg" -k tools/kgg.key

  # 4. 以 JSON 查看 MMKV 内容
  python unlock_tool.py -i input/key_database/mggkey_multi_process -f json -t auto

  # 5. 无参数 / --auto：自动模式（多线程 + 断点续跑）
  python unlock_tool.py
  python unlock_tool.py --auto -j 8

  # 6. 仅清理工作区临时文件
  python unlock_tool.py --cleanup
  python unlock_tool.py --cleanup --reset-progress

  # 7. 用手动导出的 Android 数据补全歌词与封面
  python unlock_tool.py --enrich --metadata-db input/metadata/kugou_music_phone_v7.db --lyrics-dir input/metadata/lyrics
        """,
    )


def _add_arguments(ap: argparse.ArgumentParser) -> None:
    ap.add_argument(
        "--auto",
        action="store_true",
        help="run auto mode (scan input/, write output/, multi-thread + checkpoint)",
    )
    ap.add_argument(
        "-j",
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=f"worker threads for auto mode (default: {default_worker_count()})",
    )
    ap.add_argument(
        "--progress",
        default=None,
        metavar="PATH",
        help="progress JSON path for resume (default: tools/progress.json)",
    )
    ap.add_argument(
        "--keep-source",
        action="store_true",
        help="do not delete encrypted sources after successful decrypt",
    )
    ap.add_argument(
        "--cleanup",
        action="store_true",
        help="only clean workspace temp files (and optionally reset progress)",
    )
    ap.add_argument(
        "--reset-progress",
        action="store_true",
        help="with --cleanup: also delete tools/progress.json",
    )
    ap.add_argument(
        "--enrich",
        action="store_true",
        help="add LRC, cover art, and tags from manually exported Android data",
    )
    ap.add_argument(
        "--audio-dir",
        default="output",
        metavar="DIR",
        help="audio directory for --enrich (default: output)",
    )
    ap.add_argument(
        "--metadata-db",
        default=None,
        metavar="PATH",
        help="manually exported KuGou SQLite database for --enrich",
    )
    ap.add_argument(
        "--lyrics-dir",
        default=None,
        metavar="DIR",
        help="manually exported KRC cache directory for --enrich",
    )
    ap.add_argument(
        "--cover-cache",
        default="tools/cover_cache",
        metavar="DIR",
        help="download cache for --enrich covers (default: tools/cover_cache)",
    )
    ap.add_argument(
        "--external-only",
        action="store_true",
        help="with --enrich: create same-name LRC/cover files without editing audio tags",
    )
    ap.add_argument(
        "-i",
        "--input",
        default="input/key_database/mggkey_multi_process",
        help="path to input MMKV file or directory of MMKV files (for MMKV mode)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="output file path (defaults to tools/kgg.key for format 'kgg', otherwise stdout)",
    )
    ap.add_argument(
        "-f",
        "--format",
        default="kgg",
        choices=["kgg", "json", "text", "csv", "tsv"],
        help="output format for MMKV mode (default: kgg)",
    )
    ap.add_argument(
        "-t",
        "--type",
        default="auto",
        choices=["auto", "string", "nested_string", "int", "bool", "bytes", "hex"],
        help="force decode MMKV values using a specific type (default: auto)",
    )
    ap.add_argument(
        "-s",
        "--search",
        help="search/filter MMKV keys by substring or glob pattern (case-insensitive)",
    )
    ap.add_argument(
        "-r",
        "--regex",
        action="store_true",
        help="interpret the search term as a regular expression",
    )
    ap.add_argument(
        "--show-types",
        action="store_true",
        help="include type information in the output format (JSON, CSV, TSV, text)",
    )
    ap.add_argument(
        "--no-truncate",
        action="store_true",
        help="do not truncate values in human-readable 'text' format",
    )
    ap.add_argument(
        "--hash",
        dest="audio_hash",
        default=None,
        help="print ekey for a specific hash (legacy option for backward compatibility)",
    )
    ap.add_argument(
        "-d",
        "--decrypt",
        nargs="?",
        const=".",
        default=None,
        help="decrypt KGG files (accepts a file path, directory path, or defaults to current directory)",
    )
    ap.add_argument(
        "-k",
        "--key-file",
        default="kgg.key",
        help="path to kgg.key file containing keys for decryption (default: kgg.key)",
    )


def _cmd_decrypt(args: argparse.Namespace) -> int:
    dec_path = Path(args.decrypt)
    if not dec_path.exists():
        local_fallback = Path(dec_path.name)
        if local_fallback.exists():
            dec_path = local_fallback
        else:
            print(f"Decryption path not found: {dec_path}", file=sys.stderr)
            return 1

    key_file_path = resolve_key_file(Path(args.key_file))
    if not key_file_path.exists():
        print(f"Key file not found: {key_file_path}", file=sys.stderr)
        return 1

    try:
        mapping = load_kgg_key(key_file_path)
    except Exception as e:
        print(f"Error reading key file {key_file_path}: {e}", file=sys.stderr)
        return 1

    files_to_decrypt: list[Path] = []
    if dec_path.is_file():
        if detect_process_kind(dec_path) == "kgg":
            files_to_decrypt.append(dec_path)
        else:
            print(
                f"File {dec_path} is not recognized as KGG by header or filename",
                file=sys.stderr,
            )
            return 1
    elif dec_path.is_dir():
        kgg_files, _kgm = collect_encrypted_files(dec_path)
        files_to_decrypt = kgg_files
        if not files_to_decrypt:
            print(f"No .kgg files found in directory {dec_path}", file=sys.stderr)
            return 1

    success_count = 0
    for p in files_to_decrypt:
        try:
            audio_hash = read_audio_hash_from_kgg(p)
            if not audio_hash:
                print(f"Error: Failed to read audio hash from {p.name}", file=sys.stderr)
                continue
            ekey_str = mapping.get(audio_hash)
            if not ekey_str:
                print(f"Error: EKey not found for hash {audio_hash} in {p.name}", file=sys.stderr)
                continue
            decrypt_kgg_file(p, p.parent, ekey_str)
            success_count += 1
        except Exception as e:
            print(f"Error decrypting {p.name}: {e}", file=sys.stderr)

    print(
        f"Decryption complete: successfully decrypted "
        f"{success_count}/{len(files_to_decrypt)} file(s)"
    )
    return 0 if success_count == len(files_to_decrypt) else 1


def _cmd_enrich(args: argparse.Namespace) -> int:
    if not args.metadata_db or not args.lyrics_dir:
        print(
            "--enrich requires --metadata-db and --lyrics-dir; "
            "export both from Android manually first",
            file=sys.stderr,
        )
        return 2
    try:
        total, ok, failures = run_enrichment(
            args.audio_dir,
            args.lyrics_dir,
            args.metadata_db,
            args.cover_cache,
            external_only=args.external_only,
        )
    except Exception as exc:
        print(f"Enrichment failed: {exc}", file=sys.stderr)
        return 1
    print(f"[=] enriched={ok} total={total} failed={len(failures)}")
    for failure in failures:
        print(f"[!] {failure}", file=sys.stderr)
    return 0 if not failures else 1


def _cmd_mmkv(args: argparse.Namespace) -> int:
    inp = Path(args.input)
    if not inp.exists():
        local_fallback = Path(inp.name)
        if local_fallback.exists():
            inp = local_fallback
        else:
            print(f"input not found: {inp}", file=sys.stderr)
            return 1

    files_to_process: list[Path] = []
    is_dir_scan = False
    if inp.is_file():
        files_to_process.append(inp)
    elif inp.is_dir():
        is_dir_scan = True
        for p in inp.rglob("*"):
            if is_valid_mmkv(p):
                files_to_process.append(p)
        if not files_to_process:
            print(f"no valid MMKV files found in directory: {inp}", file=sys.stderr)
            return 1

    mapping: dict = {}
    for f in files_to_process:
        raw_map = parse_mmkv_raw(f)
        if raw_map is None:
            continue

        decoded_map = {}
        for k, v in raw_map.items():
            v_type, v_val = decode_value(v, args.type)
            decoded_map[k] = (v_type, v_val)

        if args.search:
            decoded_map = filter_mapping(decoded_map, args.search, args.regex)

        if is_dir_scan:
            rel_path = f.relative_to(inp).as_posix()
            mapping[rel_path] = decoded_map
        else:
            mapping = decoded_map

    if args.audio_hash:
        found_val = None
        if is_dir_scan:
            for file_map in mapping.values():
                if args.audio_hash in file_map:
                    found_val = file_map[args.audio_hash][1]
                    break
        else:
            if args.audio_hash in mapping:
                found_val = mapping[args.audio_hash][1]

        if found_val is None:
            print(f"hash not found: {args.audio_hash}", file=sys.stderr)
            return 2
        print(found_val)
        return 0

    if args.format == "kgg":
        flat_map: dict[str, str] = {}
        if is_dir_scan:
            for file_map in mapping.values():
                for k, (_v_type, v_val) in file_map.items():
                    flat_map[k] = str(v_val)
        else:
            flat_map = {k: str(v_val) for k, (_v_type, v_val) in mapping.items()}

        out_path = Path(args.output or "tools/kgg.key")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        write_kgg_key(flat_map, out_path)
        print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
        return 0

    if args.format == "json":
        out_content = format_json(mapping, args.show_types, is_dir_scan)
    elif args.format in ("csv", "tsv"):
        sep = "," if args.format == "csv" else "\t"
        out_content = format_csv_tsv(mapping, sep, args.show_types, is_dir_scan)
    elif args.format == "text":
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                print_text_format(
                    mapping, args.show_types, is_dir_scan, args.no_truncate, file=f
                )
            print(f"wrote text output to {out_path}")
        else:
            print_text_format(mapping, args.show_types, is_dir_scan, args.no_truncate)
        return 0
    else:
        out_content = ""

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_content, encoding="utf-8")
        print(f"wrote formatted output to {out_path}")
    else:
        print(out_content)

    return 0


def main() -> int:
    # 无参数：自动模式
    if len(sys.argv) == 1:
        return run_auto_mode()

    ap = _build_parser()
    _add_arguments(ap)
    args = ap.parse_args()

    if args.cleanup:
        return run_cleanup_only(reset_progress=args.reset_progress)

    if args.enrich:
        return _cmd_enrich(args)

    if args.auto or args.workers is not None or args.progress is not None or args.keep_source:
        return run_auto_mode(
            workers=args.workers,
            progress_path=args.progress,
            remove_source=not args.keep_source,
        )

    if args.decrypt is not None:
        return _cmd_decrypt(args)
    return _cmd_mmkv(args)
