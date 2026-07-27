"""无参数自动模式：扫描 input/，写出 output/（多线程 + 断点续跑）。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .cleanup import cleanup_workspace
from .keys import load_kgg_key
from .mmkv import decode_value, is_valid_mmkv, parse_mmkv_raw, write_kgg_key
from .pipeline import default_worker_count, run_pipeline

LogFn = Callable[[str], None]

# 引导文案
KEY_GUIDE = (
    "【说明】\n"
    "请在此文件夹中放入从安卓酷狗客户端导出的 MMKV 密钥数据库文件。\n"
    "\n"
    "适用客户端：\n"
    "  - 酷狗音乐        包名 com.kugou.android\n"
    "  - 酷狗音乐概念版  包名 com.kugou.android.lite\n"
    "\n"
    "手机内原始目录（需 root / 备份导出）：\n"
    "  /data/data/com.kugou.android/files/mmkv/\n"
    "  /data/data/com.kugou.android.lite/files/mmkv/\n"
    "\n"
    "常用文件名：\n"
    "  - mggkey_multi_process\n"
    "  - mggkey_multi_process.crc（可选，校验文件，可不放）\n"
    "\n"
    "※ 仅解密 .kgg（酷狗新加密）时需要此密钥库。\n"
    "※ .kgm / .kgma / .vpr 不需要密钥库。\n"
    "※ 放入后运行工具，程序会自动解析并写入 tools/kgg.key。\n"
)

MUSIC_GUIDE = (
    "【说明】\n"
    "请在此文件夹中放入需要解密的酷狗加密音频文件。\n"
    "更适合安卓「酷狗音乐」「酷狗音乐概念版」本地下载的歌曲。\n"
    "\n"
    "支持格式：\n"
    "  - .kgg / .kgg.flac / .kgg.mp3  等（酷狗新加密，需要 mggkey）\n"
    "  - .kgm / .kgma / .vpr         以及再带伪装后缀的文件名\n"
    "\n"
    "说明：部分客户端文件名类似 song.kgg.flac，工具会自动去掉多余后缀。\n"
    "解密成功后，源加密文件会从本目录删除；成品在 output/。\n"
    "进度写入 tools/progress.json，中断后再次运行会跳过已成功项。\n"
)


def ensure_workspace(
    input_dir: Path,
    output_dir: Path,
    tools_dir: Path,
) -> tuple[Path, Path]:
    """创建目录并写入引导说明，返回 (key_db_dir, music_files_dir)。"""
    key_db_dir = input_dir / "key_database"
    music_files_dir = input_dir / "music_files"

    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    tools_dir.mkdir(exist_ok=True)
    key_db_dir.mkdir(exist_ok=True)
    music_files_dir.mkdir(exist_ok=True)

    (key_db_dir / "PLACE_ANDROID_MGGKEY_HERE.txt").write_text(KEY_GUIDE, encoding="utf-8")
    (music_files_dir / "PLACE_ENCRYPTED_MUSIC_HERE.txt").write_text(MUSIC_GUIDE, encoding="utf-8")
    return key_db_dir, music_files_dir


def extract_keys_from_mmkv(
    key_db_dir: Path,
    tools_dir: Path,
    log: LogFn | None = None,
) -> Path | None:
    """从 mggkey 提取并写出 tools/kgg.key，返回路径（若无有效库则 None）。"""
    _log = log or print
    mmkv_files = [p for p in key_db_dir.glob("*") if is_valid_mmkv(p)]
    if not mmkv_files:
        return None
    _log(f"[*] Found {len(mmkv_files)} MMKV key database(s). Extracting keys...")
    flat_map: dict[str, str] = {}
    for f in mmkv_files:
        raw_map = parse_mmkv_raw(f)
        if raw_map:
            for k, v in raw_map.items():
                _v_type, v_val = decode_value(v, "nested_string")
                flat_map[k] = str(v_val)
    out_key_path = tools_dir / "kgg.key"
    write_kgg_key(flat_map, out_key_path)
    _log(f"[+] Extracted keys to {out_key_path} ({out_key_path.stat().st_size} bytes)")
    return out_key_path


def load_key_mapping(tools_dir: Path, log: LogFn | None = None) -> dict[str, str]:
    _log = log or print
    key_file_path = tools_dir / "kgg.key"
    if not key_file_path.exists():
        return {}
    try:
        return load_kgg_key(key_file_path)
    except Exception as e:
        _log(f"[!] Error reading key file {key_file_path}: {e}")
        return {}


def run_auto_mode(
    input_dir: Path | str = "input",
    output_dir: Path | str = "output",
    tools_dir: Path | str = "tools",
    *,
    workers: int | None = None,
    progress_path: Path | str | None = None,
    remove_source: bool = True,
    log: LogFn | None = None,
) -> int:
    _log = log or print
    _log("====================================================")
    _log("  KuGou Music Unlock Tool - Auto Mode")
    _log("====================================================")

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    tools_dir = Path(tools_dir)

    key_db_dir, music_files_dir = ensure_workspace(input_dir, output_dir, tools_dir)

    if progress_path is None:
        progress_path = tools_dir / "progress.json"
    else:
        progress_path = Path(progress_path)

    # 1. 密钥
    extract_keys_from_mmkv(key_db_dir, tools_dir, log=_log)
    mapping = load_key_mapping(tools_dir, log=_log)

    # 2. 多线程流水线 + 断点
    workers = workers if workers and workers > 0 else default_worker_count()
    total, success, failed, skipped = run_pipeline(
        music_files_dir,
        output_dir,
        mapping,
        workers=workers,
        progress_path=progress_path,
        remove_source=remove_source,
        clean_temps=True,
        log=_log,
    )

    if total == 0:
        _log("    Please place your files (.kgg, .kgg.flac, .kgm, .kgma, .vpr, ...) and run again.")
        _log("====================================================")
        return 0

    _log("====================================================")
    _log(f"[+] All done! total={total} success={success} skipped={skipped} failed={failed}")
    _log("    Check the 'output/' folder for your decrypted audio.")
    _log(f"    Progress file: {progress_path}")
    if remove_source and success:
        _log("    Successfully decrypted sources were removed from input/music_files/.")
    _log("====================================================")
    return 0 if failed == 0 else 1


def run_cleanup_only(
    output_dir: Path | str = "output",
    tools_dir: Path | str = "tools",
    *,
    reset_progress: bool = False,
    log: LogFn | None = None,
) -> int:
    """仅清理工作区（临时文件；可选重置进度）。"""
    _log = log or print
    output_dir = Path(output_dir)
    tools_dir = Path(tools_dir)
    progress_path = tools_dir / "progress.json"
    report = cleanup_workspace(
        output_dir=output_dir,
        progress_path=progress_path,
        reset_progress=reset_progress,
    )
    _log(f"[*] Workspace cleanup: {report.summary()}")
    for err in report.errors:
        _log(f"    [!] {err}")
    return 0 if not report.errors else 1
