package com.example.kugoudonwload.core

data class KggHeader(
    val payloadOffset: Long,
    val audioHash: String,
)

object KggHeaderParser {
    const val FIXED_HEADER_BYTES = 72
    const val MAX_HEADER_BYTES = 16 * 1024 * 1024L
    const val MAX_HASH_BYTES = 256

    fun parse(fixedHeader: ByteArray, hashBytes: ByteArray): KggHeader {
        require(fixedHeader.size >= FIXED_HEADER_BYTES) { "KGG 文件头不完整" }
        require(fixedHeader.u32Le(20) == 5L) { "仅支持 KGG mode 5" }
        val payloadOffset = fixedHeader.u32Le(16)
        require(payloadOffset in FIXED_HEADER_BYTES.toLong()..MAX_HEADER_BYTES) { "KGG 载荷偏移无效" }
        val declaredHashLength = fixedHeader.u32Le(68)
        require(declaredHashLength == hashBytes.size.toLong()) { "KGG hash 长度不一致" }
        require(hashBytes.size in 1..MAX_HASH_BYTES) { "KGG hash 长度无效" }
        val hash = hashBytes.toString(Charsets.UTF_8)
        require(Regex("^[0-9a-fA-F]{32}$").matches(hash)) { "KGG 音频 hash 无效" }
        return KggHeader(payloadOffset, hash.lowercase())
    }
}
