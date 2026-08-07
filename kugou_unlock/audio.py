"""音频容器嗅探 + 加密文件名解析。"""
from __future__ import annotations

import shutil
from pathlib import Path

# 酷狗加密后缀
CRYPTO_EXTS = frozenset({".kgg", ".kgm", ".kgma", ".vpr"})
KGG_EXTS = frozenset({".kgg"})
KGM_FAMILY_EXTS = frozenset({".kgm", ".kgma", ".vpr"})

# KGM / VPR 文件头魔数（与 kgm.py 一致；此处用于内容嗅探）
KGM_MAGIC = bytes.fromhex("7cd532eb86027f4ba8afa68e0fff9914")
VPR_MAGIC = bytes.fromhex("0528bc96e9e45a4391aabdd07af53631")

# 部分客户端会把真实后缀再拼在加密后缀后面，例如 song.kgg.flac
AUDIO_DISGUISE_EXTS = frozenset({
    ".flac", ".mp3", ".ogg", ".m4a", ".wav", ".aac", ".ape", ".wma", ".opus",
})

# 明文音频后缀（无加密标记，直接可播放）
PLAIN_AUDIO_EXTS = AUDIO_DISGUISE_EXTS


def sniff_audio_ext(header_bytes: bytes) -> str | None:
    """根据文件头判断真实音频容器扩展名。无法识别时返回 None。"""
    if not header_bytes:
        return None
    if header_bytes.startswith(b"fLaC"):
        return ".flac"
    if header_bytes.startswith(b"ID3"):
        return ".mp3"
    if len(header_bytes) >= 2 and header_bytes[0] == 0xFF and (header_bytes[1] & 0xE0) == 0xE0:
        return ".mp3"
    if header_bytes.startswith(b"OggS"):
        return ".ogg"
    if len(header_bytes) >= 8 and header_bytes[4:8] == b"ftyp":
        return ".m4a"
    if header_bytes.startswith(b"RIFF") and len(header_bytes) >= 12 and header_bytes[8:12] == b"WAVE":
        return ".wav"
    return None


def sniff_crypto_kind(header_bytes: bytes) -> str | None:
    """根据文件头判断加密类型：'kgg' | 'kgm' | None。

    酷狗 .kgg 与 .kgm 可能共用同一 16 字节魔数：
      - offset 20 的 u32 == 3 → KGM encryption version 3
      - offset 20 的 u32 == 5 → KGG mode 5（QMC2）
      - VPR 魔数 → 始终按 kgm 族处理
    """
    if not header_bytes or len(header_bytes) < 16:
        return None
    head16 = header_bytes[:16]
    if head16 == VPR_MAGIC:
        return "kgm"
    if head16 == KGM_MAGIC:
        if len(header_bytes) < 24:
            # 魔数像 KGM，但版本字段不足时先标 kgm，后续由解密器校验
            return "kgm"
        version_or_mode = int.from_bytes(header_bytes[20:24], "little")
        if version_or_mode == 5:
            return "kgg"
        if version_or_mode == 3:
            return "kgm"
        # 未知版本：交给文件名回退
        return None
    return None


def detect_process_kind(path: Path | str) -> str | None:
    """综合文件头 + 文件名，返回任务类型：'kgg' | 'kgm' | 'plain' | None。

    优先文件头（区分 KGG mode5 与 KGM v3；二者可能共用魔数）。
    """
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            header = f.read(24)
    except OSError:
        return None

    # 1) 明文音频头
    if sniff_audio_ext(header):
        return "plain"

    # 2) 按魔数 + version/mode 区分 kgg / kgm
    crypto = sniff_crypto_kind(header)
    if crypto in ("kgg", "kgm"):
        return crypto

    # 3) 回退到文件名
    name_ext = crypto_ext_of(p)
    if name_ext in KGG_EXTS:
        return "kgg"
    if name_ext in KGM_FAMILY_EXTS:
        return "kgm"
    if is_plain_audio_file(p):
        return "plain"
    return None


def _lower_suffixes(path: Path) -> list[str]:
    return [s.lower() for s in Path(path).suffixes]


def crypto_ext_of(path: Path | str) -> str | None:
    """返回识别到的加密后缀（小写），如 '.kgg' / '.kgm'；无法识别则 None。

    支持：
      - song.kgg / song.kgm / song.kgma / song.vpr
      - song.kgg.flac / song.kgm.mp3 等「加密后缀 + 伪装音频后缀」
    """
    suffixes = _lower_suffixes(Path(path))
    if not suffixes:
        return None
    if suffixes[-1] in CRYPTO_EXTS:
        return suffixes[-1]
    if (
        len(suffixes) >= 2
        and suffixes[-2] in CRYPTO_EXTS
        and suffixes[-1] in AUDIO_DISGUISE_EXTS
    ):
        return suffixes[-2]
    return None


def is_kgg_file(path: Path | str) -> bool:
    return crypto_ext_of(path) in KGG_EXTS


def is_kgm_family_file(path: Path | str) -> bool:
    return crypto_ext_of(path) in KGM_FAMILY_EXTS


def encrypted_base_stem(path: Path | str) -> str:
    """去掉加密后缀及可选的伪装音频后缀，得到输出用的基名。

    例：
      song.kgg           -> song
      song.kgg.flac      -> song
      a.b.kgma           -> a.b
      a.b.kgm.mp3        -> a.b
    """
    p = Path(path)
    suffixes = _lower_suffixes(p)
    n_strip = 0
    if not suffixes:
        return p.name
    if suffixes[-1] in CRYPTO_EXTS:
        n_strip = 1
    elif (
        len(suffixes) >= 2
        and suffixes[-2] in CRYPTO_EXTS
        and suffixes[-1] in AUDIO_DISGUISE_EXTS
    ):
        n_strip = 2
    else:
        return p.stem

    name = p.name
    for _ in range(n_strip):
        dot = name.rfind(".")
        if dot <= 0:
            break
        name = name[:dot]
    return name or p.stem


def is_plain_audio_file(path: Path | str) -> bool:
    """是否为无加密标记的标准音频文件名（如 .flac / .mp3）。

    不含 .kgg.flac 这类「加密 + 伪装后缀」——那些由 crypto_ext_of 识别。
    """
    p = Path(path)
    if crypto_ext_of(p) is not None:
        return False
    suffixes = _lower_suffixes(p)
    return bool(suffixes) and suffixes[-1] in PLAIN_AUDIO_EXTS


def collect_encrypted_files(directory: Path | str) -> tuple[list[Path], list[Path]]:
    """扫描目录，返回 (kgg_files, kgm_family_files)。"""
    directory = Path(directory)
    kgg_files: list[Path] = []
    kgm_files: list[Path] = []
    if not directory.is_dir():
        return kgg_files, kgm_files
    for p in sorted(directory.iterdir()):
        if not p.is_file():
            continue
        kind = crypto_ext_of(p)
        if kind in KGG_EXTS:
            kgg_files.append(p)
        elif kind in KGM_FAMILY_EXTS:
            kgm_files.append(p)
    return kgg_files, kgm_files


def collect_processable_files(
    directory: Path | str,
) -> tuple[list[Path], list[Path], list[Path]]:
    """扫描目录，返回 (kgg_files, kgm_family_files, plain_audio_files)。

    按文件头优先识别类型：
      - 明文 fLaC/ID3 等 → plain（透传）
      - KGM/VPR 魔数 → kgm（即使文件名是 .kgg.flac）
      - 其余再按文件名 .kgg / .kgm 等
    """
    directory = Path(directory)
    kgg_files: list[Path] = []
    kgm_files: list[Path] = []
    plain_files: list[Path] = []
    if not directory.is_dir():
        return kgg_files, kgm_files, plain_files
    for p in sorted(directory.iterdir()):
        if not p.is_file():
            continue
        kind = detect_process_kind(p)
        if kind == "kgg":
            kgg_files.append(p)
        elif kind == "kgm":
            kgm_files.append(p)
        elif kind == "plain":
            plain_files.append(p)
    return kgg_files, kgm_files, plain_files


def pass_through_plain_audio(src_path: Path | str, output_dir: Path | str) -> str:
    """将未加密音频校验后拷贝到 output/，返回输出文件名。

    用文件头识别真实容器，纠正错误后缀；拒绝无法识别的文件。
    """
    src_path = Path(src_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(src_path, "rb") as f:
        header = f.read(16)
    ext = sniff_audio_ext(header)
    if not ext:
        raise ValueError(
            f"Unrecognized plain audio header in {src_path.name} "
            f"(header={header[:8].hex() if header else 'empty'})"
        )

    # 基名：去掉最后一个后缀（Path.stem），再挂上文件头识别出的真实扩展名
    base = src_path.stem or src_path.name
    out_name = f"{base}{ext}"
    out_path = output_dir / out_name
    if out_path.resolve() == src_path.resolve():
        # 源已在输出目录且同名：无需拷贝
        return out_name
    if out_path.exists():
        out_path.unlink()
    shutil.copy2(src_path, out_path)
    return out_name


def cleanup_temp_files(directory: Path | str) -> int:
    """兼容旧导入：转发到 cleanup 模块。"""
    from .cleanup import cleanup_temp_files as _cleanup_temp_files

    return _cleanup_temp_files(directory)


