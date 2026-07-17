"""QMC2 ekey 解密与音流密码（Map / Hardened RC4）。"""
from __future__ import annotations

import base64

from .tea import tea_cbc_decrypt

EKEY_V2_PREFIX = "UVFNdXNpYyBFbmNWMixLZXk6"
EKEY_V2_KEY1 = bytes([0x33, 0x38, 0x36, 0x5A, 0x4A, 0x59, 0x21, 0x40, 0x23, 0x2A, 0x24, 0x25, 0x5E, 0x26, 0x29, 0x28])
EKEY_V2_KEY2 = bytes([0x2A, 0x2A, 0x23, 0x21, 0x28, 0x23, 0x24, 0x25, 0x26, 0x5E, 0x61, 0x31, 0x63, 0x5A, 0x2C, 0x54])

def decrypt_ekey_v1(ekey_str):
    try:
        raw = base64.b64decode(ekey_str)
    except Exception:
        return None
    if len(raw) < 8:
        return None
        
    tea_key = [
        (0x69005600 | (raw[0] << 16) | raw[1]) & 0xFFFFFFFF,
        (0x46003800 | (raw[2] << 16) | raw[3]) & 0xFFFFFFFF,
        (0x2b002000 | (raw[4] << 16) | raw[5]) & 0xFFFFFFFF,
        (0x15000b00 | (raw[6] << 16) | raw[7]) & 0xFFFFFFFF,
    ]
    
    dec = tea_cbc_decrypt(raw[8:], tea_key)
    if not dec:
        return None
        
    return raw[:8] + dec

def decrypt_ekey(ekey_str):
    if ekey_str.startswith(EKEY_V2_PREFIX):
        ekey = ekey_str[len(EKEY_V2_PREFIX):]
        b = tea_cbc_decrypt(ekey.encode("ascii"), EKEY_V2_KEY1)
        if not b:
            return None
        b = tea_cbc_decrypt(b, EKEY_V2_KEY2)
        if not b:
            return None
        return decrypt_ekey_v1(b.decode("ascii", errors="ignore"))
    else:
        return decrypt_ekey_v1(ekey_str)


# --- QMC2 Decryption Ciphers ---

class QMC2Map:
    def __init__(self, key):
        self.key = bytearray(128)
        n = len(key)
        for i in range(128):
            j = (i * i + 71214) % n
            shift = (j + 4) % 8
            val = ((key[j] << shift) | (key[j] >> (8 - shift))) & 0xFF
            self.key[i] = val

    def decrypt(self, buf, offset):
        for i in range(len(buf)):
            idx = offset if offset <= 0x7FFF else (offset % 0x7FFF)
            buf[i] ^= self.key[idx % 128]
            offset += 1

def rc4_hash(key):
    h = 1
    for b in key:
        if b == 0:
            continue
        next_h = (h * b) & 0xFFFFFFFF
        if next_h <= h:
            break
        h = next_h
    return float(h)

class RC4KeySched:
    def __init__(self):
        self.s = bytearray()
        self.i = 0
        self.j = 0

    def init(self, key):
        n = len(key)
        self.s = bytearray(i % 256 for i in range(n))
        j = 0
        for i in range(n):
            j = (j + self.s[i] + key[i]) % n
            self.s[i], self.s[j] = self.s[j], self.s[i]
        self.i = 0
        self.j = 0

    def derive(self, out_len):
        n = len(self.s)
        i = self.i
        j = self.j
        s = self.s
        out = bytearray(out_len)
        for k in range(out_len):
            i = (i + 1) % n
            j = (j + s[i]) % n
            s[i], s[j] = s[j], s[i]
            out[k] = s[(s[i] + s[j]) % n]
        self.i = i
        self.j = j
        return out

class QMC2RC4:
    def __init__(self, key):
        self.key = bytes(key)
        self.hash = rc4_hash(key)
        rc = RC4KeySched()
        rc.init(key)
        self.key_stream = rc.derive(0x1400 + 512)

    def decrypt(self, buf, offset):
        idx = 0
        buf_len = len(buf)
        while idx < buf_len:
            if offset < 0x80:
                n = self.decrypt_first(buf, idx, offset)
                offset += n
                idx += n
            else:
                n = self.decrypt_other(buf, idx, offset)
                offset += n
                idx += n

    def decrypt_first(self, buf, start_idx, offset):
        n = len(self.key)
        process = min(len(buf) - start_idx, 0x80 - int(offset))
        for i in range(process):
            seed = self.key[offset % n]
            segment_key = get_segment_key(self.hash, offset, seed)
            idx = int(segment_key) % n
            buf[start_idx + i] ^= self.key[idx]
            offset += 1
        return process

    def decrypt_other(self, buf, start_idx, offset):
        n = len(self.key)
        seg_idx = offset // 0x1400
        seg_off = offset % 0x1400
        seed = self.key[seg_idx % n]
        skip = get_segment_key(self.hash, seg_idx, seed) & 0x1FF
        process = min(len(buf) - start_idx, 0x1400 - int(seg_off))
        stream = self.key_stream[skip + seg_off : skip + seg_off + process]
        for i in range(process):
            buf[start_idx + i] ^= stream[i]
        return process

def get_segment_key(hash_val, segment_id, seed):
    if seed == 0:
        return 0
    return int((hash_val / (float(seed) * float(segment_id + 1))) * 100.0)

def create_qmc2(ekey_str):
    key = decrypt_ekey(ekey_str)
    if not key:
        return None
    if len(key) < 300:
        return QMC2Map(key)
    return QMC2RC4(key)


