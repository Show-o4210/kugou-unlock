"""TEA 加解密（用于 ekey 解密）。"""
from __future__ import annotations

import struct

def tea_single_round(v, sum_val, k1, k2):
    return (((v << 4) + k1) ^ (v + sum_val) ^ ((v >> 5) + k2)) & 0xFFFFFFFF

def tea_ecb_decrypt(v, key):
    y = (v >> 32) & 0xFFFFFFFF
    z = v & 0xFFFFFFFF
    sum_val = (0x9e3779b9 * 16) & 0xFFFFFFFF
    for _ in range(16):
        z = (z - tea_single_round(y, sum_val, key[2], key[3])) & 0xFFFFFFFF
        y = (y - tea_single_round(z, sum_val, key[0], key[1])) & 0xFFFFFFFF
        sum_val = (sum_val - 0x9e3779b9) & 0xFFFFFFFF
    return (y << 32) | z

def be_read_64(b):
    return struct.unpack(">Q", b)[0]

def be_write_64(v):
    return struct.pack(">Q", v)

def decrypt_round(block, iv1, iv2, key):
    iv1_next = be_read_64(block)
    iv2_next = tea_ecb_decrypt(iv1_next ^ iv2, key)
    plain = iv2_next ^ iv1
    return plain, iv1_next, iv2_next

def tea_cbc_decrypt(cipher, key):
    if len(cipher) % 8 != 0 or len(cipher) < 16:
        return None
        
    k = [0] * 4
    if isinstance(key, (bytes, bytearray)):
        k[0] = struct.unpack(">I", key[0:4])[0]
        k[1] = struct.unpack(">I", key[4:8])[0]
        k[2] = struct.unpack(">I", key[8:12])[0]
        k[3] = struct.unpack(">I", key[12:16])[0]
    else:
        k = list(key)
        
    iv1 = 0
    iv2 = 0
    header = bytearray(16)
    
    plain1, iv1, iv2 = decrypt_round(cipher[0:8], iv1, iv2, k)
    plain2, iv1, iv2 = decrypt_round(cipher[8:16], iv1, iv2, k)
    header[0:8] = be_write_64(plain1)
    header[8:16] = be_write_64(plain2)
    
    in_data = cipher[16:]
    hdr_skip = 1 + int(header[0] & 7) + 2
    real_plain = len(cipher) - hdr_skip - 7
    if real_plain < 0:
        return None
        
    res = bytearray(real_plain)
    copy_len = min(real_plain, 16 - hdr_skip)
    res[0:copy_len] = header[hdr_skip : hdr_skip + copy_len]
    p = copy_len
    
    while len(in_data) >= 8:
        if p + 8 > real_plain:
            break
        plain_block, iv1, iv2 = decrypt_round(in_data[0:8], iv1, iv2, k)
        res[p : p + 8] = be_write_64(plain_block)
        in_data = in_data[8:]
        p += 8
        
    if p < real_plain and len(in_data) >= 8:
        plain_block, iv1, iv2 = decrypt_round(in_data[0:8], iv1, iv2, k)
        header_last = be_write_64(plain_block)
        res[p] = header_last[0]
        
    return bytes(res)


