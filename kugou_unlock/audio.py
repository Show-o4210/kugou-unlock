"""音频容器嗅探 + 加密文件名解析。"""
from __future__ import annotations

from pathlib import Path

# 酷狗加密后缀
CRYPTO_EXTS = frozenset({".kgg", ".kgm", ".kgma", ".vpr"})
KGG_EXTS = frozenset({".kgg"})
KGM_FAMILY_EXTS = frozenset({".kgm", ".kgma", ".vpr"})

# 部分客户端会把真实后缀再拼在加密后缀后面，例如 song.kgg.flac
AUDIO_DISGUISE_EXTS = frozenset({
    ".flac", ".mp3", ".ogg", ".m4a", ".wav", ".aac", ".ape", ".wma", ".opus",
})


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


def cleanup_temp_files(directory: Path | str) -> int:
    """兼容旧导入：转发到 cleanup 模块。"""
    from .cleanup import cleanup_temp_files as _cleanup_temp_files

    return _cleanup_temp_files(directory)


