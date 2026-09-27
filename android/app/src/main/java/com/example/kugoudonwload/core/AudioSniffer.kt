package com.example.kugoudonwload.core

enum class ProcessKind {
    PLAIN,
    KGG,
    KGM,
    UNKNOWN,
}

object AudioSniffer {
    val kgmMagic: ByteArray = "7cd532eb86027f4ba8afa68e0fff9914".hexBytes()
    val vprMagic: ByteArray = "0528bc96e9e45a4391aabdd07af53631".hexBytes()

    private val encryptedSuffix = Regex("(?i)\\.(kgg|kgm|kgma|vpr)(?=\\.|$)")

    fun audioExtension(header: ByteArray): String? = when {
        header.startsWithAscii("fLaC") -> ".flac"
        header.startsWithAscii("ID3") -> ".mp3"
        header.size >= 2 && header[0].u8() == 0xff && (header[1].u8() and 0xe0) == 0xe0 -> ".mp3"
        header.startsWithAscii("OggS") -> ".ogg"
        header.size >= 8 && header.copyOfRange(4, 8).contentEquals("ftyp".encodeToByteArray()) -> ".m4a"
        header.size >= 12 && header.startsWithAscii("RIFF") &&
            header.copyOfRange(8, 12).contentEquals("WAVE".encodeToByteArray()) -> ".wav"
        else -> null
    }

    fun detect(header: ByteArray, displayName: String): ProcessKind {
        if (audioExtension(header) != null) return ProcessKind.PLAIN
        if (header.size >= 16 && header.copyOfRange(0, 16).contentEquals(vprMagic)) {
            return ProcessKind.KGM
        }
        if (header.size >= 16 && header.copyOfRange(0, 16).contentEquals(kgmMagic)) {
            if (header.size >= 24) {
                return when (header.u32Le(20)) {
                    5L -> ProcessKind.KGG
                    3L -> ProcessKind.KGM
                    else -> suffixKind(displayName)
                }
            }
            return ProcessKind.KGM
        }
        return suffixKind(displayName)
    }

    fun outputBaseName(displayName: String): String {
        val matches = encryptedSuffix.findAll(displayName).toList()
        if (matches.isNotEmpty()) {
            return displayName.substring(0, matches.last().range.first).ifBlank { "audio" }
        }
        val dot = displayName.lastIndexOf('.')
        return (if (dot > 0) displayName.substring(0, dot) else displayName).ifBlank { "audio" }
    }

    private fun suffixKind(displayName: String): ProcessKind {
        val match = encryptedSuffix.findAll(displayName).lastOrNull() ?: return ProcessKind.UNKNOWN
        return when (match.groupValues[1].lowercase()) {
            "kgg" -> ProcessKind.KGG
            "kgm", "kgma", "vpr" -> ProcessKind.KGM
            else -> ProcessKind.UNKNOWN
        }
    }
}

internal fun Byte.u8(): Int = toInt() and 0xff

internal fun ByteArray.u32Le(offset: Int): Long {
    require(offset >= 0 && offset + 4 <= size) { "32-bit value exceeds input" }
    return (this[offset].u8().toLong()) or
        (this[offset + 1].u8().toLong() shl 8) or
        (this[offset + 2].u8().toLong() shl 16) or
        (this[offset + 3].u8().toLong() shl 24)
}

internal fun String.hexBytes(): ByteArray {
    require(length % 2 == 0)
    return ByteArray(length / 2) { index ->
        substring(index * 2, index * 2 + 2).toInt(16).toByte()
    }
}

private fun ByteArray.startsWithAscii(value: String): Boolean {
    val prefix = value.encodeToByteArray()
    return size >= prefix.size && copyOfRange(0, prefix.size).contentEquals(prefix)
}
