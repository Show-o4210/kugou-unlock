package com.example.kugoudonwload.core

import java.util.Base64

internal interface Qmc2Cipher {
    fun decrypt(buffer: ByteArray, length: Int, offset: Long)
}

internal object Qmc2Factory {
    private const val V2_PREFIX = "UVFNdXNpYyBFbmNWMixLZXk6"
    private val v2Key1 = "386ZJY!@#*$%^&)(".encodeToByteArray()
    private val v2Key2 = "**#!(#$%&^a1cZ,T".encodeToByteArray()

    fun create(ekey: String, legacyMap: Boolean = false): Qmc2Cipher? {
        val key = decryptEkey(ekey) ?: return null
        if (key.isEmpty()) return null
        return if (key.size < 300) Qmc2Map(key, legacyMap) else Qmc2Rc4(key)
    }

    private fun decryptEkey(value: String): ByteArray? {
        return if (value.startsWith(V2_PREFIX)) {
            val encoded = value.substring(V2_PREFIX.length).encodeToByteArray()
            val first = Tea.cbcDecrypt(encoded, v2Key1) ?: return null
            val second = Tea.cbcDecrypt(first, v2Key2) ?: return null
            decryptV1(second.toString(Charsets.US_ASCII))
        } else {
            decryptV1(value)
        }
    }

    private fun decryptV1(value: String): ByteArray? {
        val raw = try {
            Base64.getDecoder().decode(value)
        } catch (_: IllegalArgumentException) {
            return null
        }
        if (raw.size < 8) return null
        val teaKey = byteArrayOf(
            0x69, raw[0], 0x56, raw[1],
            0x46, raw[2], 0x38, raw[3],
            0x2b, raw[4], 0x20, raw[5],
            0x15, raw[6], 0x0b, raw[7],
        )
        val decrypted = Tea.cbcDecrypt(raw.copyOfRange(8, raw.size), teaKey) ?: return null
        return raw.copyOfRange(0, 8) + decrypted
    }
}

private class Qmc2Map(key: ByteArray, sameShift: Boolean) : Qmc2Cipher {
    private val table = ByteArray(128)

    init {
        repeat(table.size) { index ->
            val source = (index * index + 71214) % key.size
            val shift = (source + 4) % 8
            val rightShift = if (sameShift) shift else 8 - shift
            val value = key[source].u8()
            table[index] = ((value shl shift) or (value ushr rightShift)).toByte()
        }
    }

    override fun decrypt(buffer: ByteArray, length: Int, offset: Long) {
        var position = offset
        repeat(length) { index ->
            val normalized = if (position <= 0x7fffL) position else position % 0x7fffL
            buffer[index] = (buffer[index].u8() xor table[(normalized % 128).toInt()].u8()).toByte()
            position++
        }
    }
}

private class Qmc2Rc4(private val key: ByteArray) : Qmc2Cipher {
    private val hash = rc4Hash(key)
    private val stream = Rc4KeySchedule(key).derive(0x1400 + 512)

    override fun decrypt(buffer: ByteArray, length: Int, offset: Long) {
        var inputIndex = 0
        var position = offset
        while (inputIndex < length) {
            if (position < 0x80) {
                val count = minOf(length - inputIndex, (0x80 - position).toInt())
                repeat(count) { relative ->
                    val seed = key[(position % key.size).toInt()].u8()
                    val keyIndex = (segmentKey(hash, position, seed) % key.size).toInt()
                    buffer[inputIndex + relative] =
                        (buffer[inputIndex + relative].u8() xor key[keyIndex].u8()).toByte()
                    position++
                }
                inputIndex += count
            } else {
                val segmentIndex = position / 0x1400
                val segmentOffset = (position % 0x1400).toInt()
                val seed = key[(segmentIndex % key.size).toInt()].u8()
                val skip = (segmentKey(hash, segmentIndex, seed) and 0x1ff).toInt()
                val count = minOf(length - inputIndex, 0x1400 - segmentOffset)
                repeat(count) { relative ->
                    buffer[inputIndex + relative] =
                        (buffer[inputIndex + relative].u8() xor stream[skip + segmentOffset + relative].u8()).toByte()
                }
                position += count
                inputIndex += count
            }
        }
    }

    private fun rc4Hash(bytes: ByteArray): Double {
        var hashValue = 1L
        for (byte in bytes) {
            val value = byte.u8()
            if (value == 0) continue
            val next = (hashValue * value) and 0xffff_ffffL
            if (next <= hashValue) break
            hashValue = next
        }
        return hashValue.toDouble()
    }

    private fun segmentKey(hashValue: Double, segment: Long, seed: Int): Long {
        if (seed == 0) return 0
        return ((hashValue / (seed.toDouble() * (segment + 1).toDouble())) * 100.0).toLong()
    }
}

private class Rc4KeySchedule(key: ByteArray) {
    private val state = ByteArray(key.size) { (it % 256).toByte() }
    private var i = 0
    private var j = 0

    init {
        require(key.isNotEmpty())
        var cursor = 0
        for (index in state.indices) {
            cursor = (cursor + state[index].u8() + key[index].u8()) % state.size
            val swap = state[index]
            state[index] = state[cursor]
            state[cursor] = swap
        }
    }

    fun derive(length: Int): ByteArray = ByteArray(length) { deriveByte() }

    private fun deriveByte(): Byte {
        i = (i + 1) % state.size
        j = (j + state[i].u8()) % state.size
        val swap = state[i]
        state[i] = state[j]
        state[j] = swap
        return state[(state[i].u8() + state[j].u8()) % state.size]
    }
}
