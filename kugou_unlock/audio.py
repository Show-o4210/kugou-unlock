"""音频容器嗅探。"""
from __future__ import annotations

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


