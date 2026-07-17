"""无参数自动模式：扫描 input/，写出 output/。"""

from __future__ import annotations

from pathlib import Path

from .kgg import decrypt_kgg_file, read_audio_hash_from_kgg
from .kgm import decrypt_kgm_family_file
from .keys import load_kgg_key
from .mmkv import decode_value, is_valid_mmkv, parse_mmkv_raw, write_kgg_key

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
    "  - .kgg   酷狗新加密（需要 input/key_database 中的 mggkey）\n"
    "  - .kgm   酷狗旧加密\n"
    "  - .kgma  酷狗旧加密（音频变体）\n"
    "  - .vpr   酷狗 VPR 加密\n"
    "\n"
    "解密完成后，标准音频文件会输出到 output/ 文件夹。\n"
)


def run_auto_mode(
    input_dir: Path | str = "input",
    output_dir: Path | str = "output",
    tools_dir: Path | str = "tools",
) -> int:
    print("====================================================")
    print("  KuGou Music Unlock Tool - Auto Mode")
    print("====================================================")

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    tools_dir = Path(tools_dir)

    key_db_dir = input_dir / "key_database"
    music_files_dir = input_dir / "music_files"

    input_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    tools_dir.mkdir(exist_ok=True)
    key_db_dir.mkdir(exist_ok=True)
    music_files_dir.mkdir(exist_ok=True)

    (key_db_dir / "PLACE_ANDROID_MGGKEY_HERE.txt").write_text(KEY_GUIDE, encoding="utf-8")
    (music_files_dir / "PLACE_ENCRYPTED_MUSIC_HERE.txt").write_text(MUSIC_GUIDE, encoding="utf-8")

    # 1. 提取 mggkey -> tools/kgg.key
    mmkv_files = [p for p in key_db_dir.glob("*") if is_valid_mmkv(p)]
    if mmkv_files:
        print(f"[*] Found {len(mmkv_files)} MMKV key database(s). Extracting keys...")
        flat_map: dict[str, str] = {}
        for f in mmkv_files:
            raw_map = parse_mmkv_raw(f)
            if raw_map:
                for k, v in raw_map.items():
                    _v_type, v_val = decode_value(v, "nested_string")
                    flat_map[k] = str(v_val)
        out_key_path = tools_dir / "kgg.key"
        write_kgg_key(flat_map, out_key_path)
        print(f"[+] Extracted keys to {out_key_path} ({out_key_path.stat().st_size} bytes)")

    # 2. 加载密钥表
    key_file_path = tools_dir / "kgg.key"
    mapping: dict[str, str] = {}
    if key_file_path.exists():
        try:
            mapping = load_kgg_key(key_file_path)
        except Exception as e:
            print(f"[!] Error reading key file {key_file_path}: {e}")

    # 3. 收集待解密文件
    kgg_files = list(music_files_dir.glob("*.kgg"))
    kgm_files: list[Path] = []
    for ext in ("*.kgm", "*.kgma", "*.vpr"):
        kgm_files.extend(music_files_dir.glob(ext))

    total_files = len(kgg_files) + len(kgm_files)
    if total_files == 0:
        print("[*] No encrypted files found in the 'input/music_files/' folder.")
        print("    Please place your files (.kgg, .kgm, .kgma, .vpr) in 'input/music_files/' and run again.")
        print("====================================================")
        return 0

    print(f"[*] Found {total_files} encrypted file(s) in 'input/music_files/'. Starting conversion...")
    success_count = 0

    # 4. .kgg
    if kgg_files:
        if not mapping:
            print("[!] Warning: No key database tools/kgg.key found. .kgg files may fail to decrypt.")
        for p in kgg_files:
            print(f"[*] Processing {p.name}...")
            try:
                audio_hash = read_audio_hash_from_kgg(p)
                if not audio_hash:
                    print(f"    [!] Failed to read audio hash from {p.name}")
                    continue
                ekey_str = mapping.get(audio_hash)
                if not ekey_str:
                    print(f"    [!] EKey not found for hash {audio_hash} in tools/kgg.key")
                    continue
                decrypt_kgg_file(p, output_dir, ekey_str)
                success_count += 1
            except Exception as e:
                print(f"    [!] Error decrypting {p.name}: {e}")

    # 5. .kgm / .kgma / .vpr
    for p in kgm_files:
        print(f"[*] Processing {p.name}...")
        try:
            out_name = decrypt_kgm_family_file(p, output_dir)
            out_path = output_dir / out_name
            print(f"    [+] Decrypted: {p.name} -> output/{out_name} ({out_path.stat().st_size} bytes)")
            success_count += 1
        except Exception as e:
            print(f"    [!] Error decrypting {p.name}: {e}")

    print("====================================================")
    print(f"[+] All done! Successfully processed {success_count}/{total_files} file(s).")
    print("    Check the 'output/' folder for your decrypted audio.")
    print("====================================================")
    return 0
