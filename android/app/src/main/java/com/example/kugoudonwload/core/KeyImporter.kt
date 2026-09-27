package com.example.kugoudonwload.core

import java.nio.charset.StandardCharsets

data class KeyImportResult(
    val keys: Map<String, String>,
    val ignoredEntries: Int,
)

object KeyImporter {
    const val MAX_INPUT_BYTES = 32 * 1024 * 1024
    private const val MAX_ENTRY_BYTES = 1024 * 1024
    private const val MAX_ENTRIES = 200_000
    private val hashPattern = Regex("^[0-9a-fA-F]{32}$")

    fun parse(displayName: String, data: ByteArray): KeyImportResult {
        require(data.size <= MAX_INPUT_BYTES) { "密钥文件超过 32 MiB 限制" }
        return if (displayName.endsWith(".key", ignoreCase = true)) {
            parseTextKey(data)
        } else {
            parseMmkv(data)
        }
    }

    private fun parseTextKey(data: ByteArray): KeyImportResult {
        val result = linkedMapOf<String, String>()
        var ignored = 0
        data.toString(StandardCharsets.UTF_8).lineSequence().forEach { line ->
            val separator = line.indexOf('$')
            if (separator <= 0) {
                if (line.isNotBlank()) ignored++
                return@forEach
            }
            val hash = line.substring(0, separator)
            val ekey = line.substring(separator + 1)
            if (hashPattern.matches(hash) && ekey.isNotBlank()) result[hash.lowercase()] = ekey else ignored++
        }
        require(result.isNotEmpty()) { "文件中没有有效的 KGG 密钥" }
        return KeyImportResult(result, ignored)
    }

    private fun parseMmkv(data: ByteArray): KeyImportResult {
        require(data.size >= 4) { "MMKV 文件过短" }
        val payloadLength = data.u32Le(0)
        require(payloadLength in 1..(data.size - 4).toLong()) { "MMKV 载荷长度无效" }
        val reader = Cursor(data, 4, 4 + payloadLength.toInt())
        reader.readVarint() // MMKV sequence number
        val result = linkedMapOf<String, String>()
        var ignored = 0
        var entries = 0
        while (reader.available > 0) {
            require(++entries <= MAX_ENTRIES) { "MMKV 条目数量超过限制" }
            val key = reader.readString()
            if (key.isEmpty()) break
            val value = reader.readLengthDelimited()
            if (!hashPattern.matches(key)) {
                ignored++
                continue
            }
            val ekey = nestedString(value)
            if (ekey.isNullOrBlank()) ignored++ else result[key.lowercase()] = ekey
        }
        require(result.isNotEmpty()) { "MMKV 中没有找到有效的 KGG 密钥" }
        return KeyImportResult(result, ignored)
    }

    private fun nestedString(value: ByteArray): String? {
        if (value.isEmpty()) return null
        return try {
            val reader = Cursor(value, 0, value.size)
            val length = reader.readVarint().toInt()
            if (length != reader.available || length > MAX_ENTRY_BYTES) null
            else reader.readBytes(length).toString(StandardCharsets.UTF_8)
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    private class Cursor(
        private val bytes: ByteArray,
        private var position: Int,
        private val end: Int,
    ) {
        val available: Int get() = end - position

        fun readVarint(): Long {
            var value = 0L
            var shift = 0
            while (true) {
                require(position < end && shift <= 63) { "MMKV varint 无效" }
                val byte = bytes[position++].u8()
                value = value or ((byte and 0x7f).toLong() shl shift)
                if (byte and 0x80 == 0) return value
                shift += 7
            }
        }

        fun readString(): String {
            val length = readLength()
            return readBytes(length).toString(StandardCharsets.UTF_8)
        }

        fun readLengthDelimited(): ByteArray = readBytes(readLength())

        fun readBytes(length: Int): ByteArray {
            require(length >= 0 && length <= available) { "MMKV 条目越界" }
            val result = bytes.copyOfRange(position, position + length)
            position += length
            return result
        }

        private fun readLength(): Int {
            val length = readVarint()
            require(length <= MAX_ENTRY_BYTES && length <= Int.MAX_VALUE) { "MMKV 条目过大" }
            return length.toInt()
        }
    }
}
