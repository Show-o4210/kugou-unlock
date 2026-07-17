"""未加密 MMKV 解析，以及 mggkey -> kgg.key 导出。"""
from __future__ import annotations

import fnmatch
import re
import struct
from pathlib import Path

class MMKVReader:
    """Reads unencrypted MMKV binary data files."""

    def __init__(self, data: bytes):
        if len(data) < 4:
            raise ValueError("MMKV file too short")
        self.data = data
        self.pos = 0
        payload_len = struct.unpack_from("<I", data, 0)[0]
        self.pos = 4
        self.end = 4 + payload_len
        if self.end > len(data):
            self.end = len(data)
        if self.available() > 0:
            self.read_int()

    def available(self) -> int:
        return max(0, self.end - self.pos)

    def eof(self) -> bool:
        return self.pos >= self.end

    def read_byte(self) -> int:
        if self.pos >= self.end:
            raise EOFError("MMKV EOF")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_int(self) -> int:
        value = 0
        shift = 0
        while True:
            b = self.read_byte()
            value |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return value
            shift += 7
            if shift > 63:
                raise ValueError("varint too long")

    def read_bytes(self, n: int) -> bytes:
        if n < 0 or self.pos + n > self.end:
            raise EOFError("MMKV read past end")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def read_value(self) -> bytes:
        n = self.read_int()
        return self.read_bytes(n)

    def read_string(self) -> str:
        n = self.read_int()
        if n == 0:
            return ""
        return self.read_bytes(n).decode("utf-8", errors="replace")

    def read_string_value(self) -> str:
        container_len = self.read_int()
        if container_len == 0:
            return ""
        start = self.pos
        end = start + container_len
        if end > self.end:
            raise EOFError("string value container past end")
        value = self.read_string()
        if self.pos < end:
            self.pos = end
        elif self.pos > end:
            raise ValueError("string value overran container")
        return value


def decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise EOFError("varint eof")
        b = data[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def decode_value(val_bytes: bytes, target_type: str = "auto") -> tuple[str, any]:
    if not val_bytes:
        return "empty", ""

    if target_type == "bytes":
        return "bytes", val_bytes
    if target_type == "hex":
        return "hex", val_bytes.hex()

    def is_printable(s: str) -> bool:
        return all(ord(c) >= 32 or c in "\r\n\t" for c in s)

    # 1. Nested string
    if target_type in ("auto", "nested_string"):
        try:
            str_len, pos = decode_varint(val_bytes, 0)
            if pos + str_len == len(val_bytes):
                payload = val_bytes[pos:]
                decoded = payload.decode("utf-8")
                if target_type != "auto" or is_printable(decoded):
                    return "nested_string", decoded
        except Exception:
            if target_type == "nested_string":
                return "hex", val_bytes.hex()

    # 2. Direct UTF-8 string
    if target_type in ("auto", "string"):
        try:
            decoded = val_bytes.decode("utf-8")
            if target_type != "auto" or is_printable(decoded):
                return "string", decoded
        except Exception:
            if target_type == "string":
                return "hex", val_bytes.hex()

    # 3. Boolean
    if target_type in ("auto", "bool") and len(val_bytes) == 1:
        if val_bytes[0] == 0:
            return "bool", False
        elif val_bytes[0] == 1:
            return "bool", True
        if target_type == "bool":
            return "hex", val_bytes.hex()

    # 4. Varint Int
    if target_type in ("auto", "int"):
        try:
            val, pos = decode_varint(val_bytes, 0)
            if pos == len(val_bytes):
                return "int", val
        except Exception:
            if target_type == "int":
                return "hex", val_bytes.hex()

    # 5. Fixed size Ints
    if target_type == "auto":
        if len(val_bytes) == 4:
            return "int32", struct.unpack("<i", val_bytes)[0]
        elif len(val_bytes) == 8:
            return "int64", struct.unpack("<q", val_bytes)[0]

    return "hex", val_bytes.hex()


def is_valid_mmkv(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix in (".crc", ".lock", ".py", ".key", ".kgg", ".txt", ".json", ".flac", ".mp3", ".ogg", ".bat"):
        return False
    try:
        data = path.read_bytes()
        if len(data) < 4:
            return False
        payload_len = struct.unpack_from("<I", data, 0)[0]
        if payload_len == 0 or payload_len > len(data) - 4:
            return False
        r = MMKVReader(data)
        return True
    except Exception:
        return False


def parse_mmkv_raw(path: Path) -> dict[str, bytes] | None:
    try:
        data = path.read_bytes()
        r = MMKVReader(data)
        mapping: dict[str, bytes] = {}
        while not r.eof() and r.available() > 0:
            try:
                key = r.read_string()
                if not key:
                    break
                val_bytes = r.read_value()
                mapping[key] = val_bytes
            except (EOFError, ValueError):
                break
        return mapping
    except Exception:
        return None


def parse_mggkey(path: Path) -> dict[str, str]:
    raw_mapping = parse_mmkv_raw(path)
    if raw_mapping is None:
        return {}
    decoded = {}
    for k, v in raw_mapping.items():
        _, val = decode_value(v, "nested_string")
        decoded[k] = val
    return decoded


def write_kgg_key(mapping: dict[str, str], out: Path) -> None:
    lines = []
    for k, v in sorted(mapping.items()):
        if not k or not v:
            continue
        lines.append(f"{k}${v}")
    out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def filter_mapping(mapping: dict[str, any], term: str, use_regex: bool) -> dict[str, any]:
    filtered = {}
    for k, v in mapping.items():
        matched = False
        if use_regex:
            try:
                if re.search(term, k, re.IGNORECASE):
                    matched = True
            except re.error:
                if term.lower() in k.lower():
                    matched = True
        else:
            if "*" in term or "?" in term:
                if fnmatch.fnmatchcase(k.lower(), term.lower()):
                    matched = True
            else:
                if term.lower() in k.lower():
                    matched = True
        if matched:
            filtered[k] = v
    return filtered

