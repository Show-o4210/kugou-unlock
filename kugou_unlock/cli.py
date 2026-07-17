"""命令行入口：自动模式 + 高级 MMKV / 解密接口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .auto import run_auto_mode
from .kgg import decrypt_kgg_file, read_audio_hash_from_kgg
from .keys import load_kgg_key, resolve_key_file
from .mmkv import (
    decode_value,
    filter_mapping,
    is_valid_mmkv,
    parse_mmkv_raw,
    write_kgg_key,
)
from .report import format_csv_tsv, format_json, print_text_format


def _build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="酷狗音乐本地解密工具：MMKV 密钥提取 + .kgg/.kgm/.kgma/.vpr 解密。",
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

  # 5. 无参数：自动模式（扫描 input/，输出到 output/）
  python unlock_tool.py
        """,
    )


def _add_arguments(ap: argparse.ArgumentParser) -> None:
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
        if dec_path.suffix.lower() == ".kgg":
            files_to_decrypt.append(dec_path)
        else:
            print(f"File {dec_path} is not a .kgg file", file=sys.stderr)
            return 1
    elif dec_path.is_dir():
        files_to_decrypt = list(dec_path.glob("*.kgg"))
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

    if args.decrypt is not None:
        return _cmd_decrypt(args)
    return _cmd_mmkv(args)
