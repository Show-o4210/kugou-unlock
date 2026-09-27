package com.example.kugoudonwload.core

internal object Tea {
    private const val MASK = 0xffff_ffffL
    private const val DELTA = 0x9e37_79b9L

    fun cbcDecrypt(cipher: ByteArray, keyBytes: ByteArray): ByteArray? {
        if (cipher.size < 16 || cipher.size % 8 != 0 || keyBytes.size < 16) return null
        val key = LongArray(4) { index -> readU32Be(keyBytes, index * 4) }
        var iv1 = 0L
        var iv2 = 0L
        val header = ByteArray(16)

        decryptRound(cipher, 0, iv1, iv2, key).also { round ->
            writeU64Be(round.plain, header, 0)
            iv1 = round.iv1
            iv2 = round.iv2
        }
        decryptRound(cipher, 8, iv1, iv2, key).also { round ->
            writeU64Be(round.plain, header, 8)
            iv1 = round.iv1
            iv2 = round.iv2
        }

        val headerSkip = 1 + (header[0].u8() and 7) + 2
        val plainLength = cipher.size - headerSkip - 7
        if (plainLength < 0) return null
        val result = ByteArray(plainLength)
        val initial = minOf(plainLength, 16 - headerSkip)
        header.copyInto(result, 0, headerSkip, headerSkip + initial)

        var source = 16
        var target = initial
        while (source + 8 <= cipher.size && target + 8 <= plainLength) {
            val round = decryptRound(cipher, source, iv1, iv2, key)
            writeU64Be(round.plain, result, target)
            iv1 = round.iv1
            iv2 = round.iv2
            source += 8
            target += 8
        }
        if (target < plainLength && source + 8 <= cipher.size) {
            val round = decryptRound(cipher, source, iv1, iv2, key)
            val tail = ByteArray(8)
            writeU64Be(round.plain, tail, 0)
            tail.copyInto(result, target, 0, minOf(8, plainLength - target))
        }
        return result
    }

    private data class Round(val plain: Long, val iv1: Long, val iv2: Long)

    private fun decryptRound(
        input: ByteArray,
        offset: Int,
        iv1: Long,
        iv2: Long,
        key: LongArray,
    ): Round {
        val nextIv1 = readU64Be(input, offset)
        val nextIv2 = ecbDecrypt(nextIv1 xor iv2, key)
        return Round(nextIv2 xor iv1, nextIv1, nextIv2)
    }

    private fun ecbDecrypt(value: Long, key: LongArray): Long {
        var y = (value ushr 32) and MASK
        var z = value and MASK
        var sum = (DELTA * 16) and MASK
        repeat(16) {
            z = (z - singleRound(y, sum, key[2], key[3])) and MASK
            y = (y - singleRound(z, sum, key[0], key[1])) and MASK
            sum = (sum - DELTA) and MASK
        }
        return (y shl 32) or z
    }

    private fun singleRound(value: Long, sum: Long, k1: Long, k2: Long): Long =
        ((((value shl 4) and MASK) + k1) xor
            ((value + sum) and MASK) xor
            ((value ushr 5) + k2)) and MASK

    private fun readU32Be(bytes: ByteArray, offset: Int): Long =
        (bytes[offset].u8().toLong() shl 24) or
            (bytes[offset + 1].u8().toLong() shl 16) or
            (bytes[offset + 2].u8().toLong() shl 8) or
            bytes[offset + 3].u8().toLong()

    private fun readU64Be(bytes: ByteArray, offset: Int): Long {
        var result = 0L
        repeat(8) { index -> result = (result shl 8) or bytes[offset + index].u8().toLong() }
        return result
    }

    private fun writeU64Be(value: Long, output: ByteArray, offset: Int) {
        repeat(8) { index -> output[offset + index] = (value ushr (56 - index * 8)).toByte() }
    }
}
