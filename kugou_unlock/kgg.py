"""酷狗 .kgg 解密。"""
from __future__ import annotations

import struct
from pathlib import Path

from .audio import sniff_audio_ext
from .qmc2 import create_qmc2

def read_audio_hash_from_kgg(src_path):
    with open(src_path, "rb") as f:
        f.seek(68)
        b4 = f.read(4)
        if len(b4) < 4:
            return None
        hash_len = struct.unpack("<I", b4)[0]
        audio_hash = f.read(hash_len)
        return audio_hash.decode("utf-8", errors="replace")


def decrypt_kgg_file(src_path, dest_dir, ekey_str):
    src_path = Path(src_path)
    dest_dir = Path(dest_dir)
    
    with open(src_path, "rb") as f:
        f.seek(16)
        hdr = f.read(8)
        if len(hdr) < 8:
            raise ValueError(f"KGG file {src_path.name} too short")
        header_len = struct.unpack("<I", hdr[0:4])[0]
        mode = struct.unpack("<I", hdr[4:8])[0]
        if mode != 5:
            raise ValueError(f"Unsupported KGG mode {mode} in file {src_path.name}")
            
        dec = create_qmc2(ekey_str)
        if not dec:
            raise ValueError(f"Failed to create QMC2 decryptor from ekey of {src_path.name}")
            
        temp_dest = dest_dir / f"temp_{src_path.stem}.bin"
        f.seek(header_len)
        offset = 0
        
        with open(temp_dest, "wb") as out:
            while True:
                block = bytearray(f.read(64 * 1024))
                if not block:
                    break
                dec.decrypt(block, offset)
                out.write(block)
                offset += len(block)
                
        with open(temp_dest, "rb") as test_f:
            header_bytes = test_f.read(12)
            ext = sniff_audio_ext(header_bytes)
        if not ext:
            temp_dest.unlink(missing_ok=True)
            raise ValueError(f"Decrypted data from {src_path.name} is not a recognized audio format")

        final_dest = dest_dir / f"{src_path.stem}{ext}"
        if final_dest.exists():
            final_dest.unlink()
        temp_dest.rename(final_dest)
        print(f"    [+] Decrypted: {src_path.name} -> output/{final_dest.name} ({final_dest.stat().st_size} bytes)")


