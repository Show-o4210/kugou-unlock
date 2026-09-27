package com.example.kugoudonwload.core

data class KgmHeader(
    val payloadOffset: Long,
    val coreKey: ByteArray,
    val isVpr: Boolean,
)

object KgmCipher {
    private val table1 = "000000000000000000000000000000000001210161012101e101210161012101d223020242420202c2c2020242420202d3d3020363436303e3c3e3036343630394b494650404040484848484040404049595959504052505e585a585e5052505d6b696b6d6270606c6c68686c6c60606d7d79797d7d70607e7c7e787e7c7e70718381878183818e9080808080808080819191919191919190809290969092909da3a1a3a5a3a1a3ada2b0a0a4a4a0a0adbdb1b1b5b5b1b1bdbdb0a0b6b4b6b0b9cbc9c7c1c3c1c7c9cbc9c6d0c0c0c9d9d9d1d1d1d1d9d9d9d9d0c0d2d0ddebe9ebede3e1e3edebe9ebede2f0e0edfdf9f9fdfdf1f1fdfdf9f9fdfdf0e0f00200060002000e000200060002000f1".hexBytes()
    private val table2 = "000000000000000000000000000000000001230167012301ef01230167012301df21020246460202cece020246460202dede020365476503edcfed03654765039dbf9d63040404048c8c8c8c040404049c9c9c9c04052705eb8daf8deb052705dbbd9fbddb250606caca8e8ecaca0606dada9e9edada0607e9cbe98fe9cbe907193b197f193b19e70808080808080808181818181818181808092b096f092b09d7391b395f391b39d7290a0a4e4e0a0ad6d61a1a5e5e1a1ad6d60a0b6d4f6d0b95b7957b1d3f1d7b95b7956b0c0c0c0c949494941c1c1c1c949494940c0d2f0dd3b597b5d33d1f3dd3b597b5d32d0e0ed2d29696d2d21e1ed2d29696d2d20e0f00220066002200ee00220066002200fe".hexBytes()
    private val tableV2 = "b8d53db2e9af788c8333715176a0cd372f3e358da9be98b7e78c22ce5a61df686989fea5b6dea977fcc8bdbde56d3e5a36ef694ebee1e9661cf3d902b6f2129b44d06fb93589b6466d73820669c1edd785c230dfa262be792d62623d0d7ebe48892302a0e4d57551320253fd163a213b160fc3b2bbb3e2ba3a3d13ecf6014584a5700f93490c64cd31d5cc4c07019e001a2390bf881e3baba63ec47347107e3b5ebce30084ff09d4e0890f5b58704ffb65d85c531bd3c8c6bfef98b0504f0feae583588c282c8467cdd09e47db2750caf46363e8977f1b4b0cc2c1214ccc58f59452a3f3d3e068f40023f35e0a7b93ddab12b213e884d7a79f0f324c551d043652dc03f3f94e42e93d61ef7cb6b39350".hexBytes()
    private val vprKey = "25dfe8a6751e750e2f80f32db8b6e31100".hexBytes()

    fun parseHeader(header: ByteArray): KgmHeader {
        require(header.size >= 60) { "KGM 文件头不完整" }
        val magic = header.copyOfRange(0, 16)
        val isVpr = when {
            magic.contentEquals(AudioSniffer.vprMagic) -> true
            magic.contentEquals(AudioSniffer.kgmMagic) -> false
            else -> throw IllegalArgumentException("不是受支持的 KGM/VPR 文件")
        }
        val payloadOffset = header.u32Le(16)
        require(payloadOffset >= 60) { "KGM 载荷偏移无效" }
        require(header.u32Le(20) == 3L) { "仅支持 KGM/KGMA/VPR version 3" }
        return KgmHeader(
            payloadOffset = payloadOffset,
            coreKey = header.copyOfRange(28, 44) + byteArrayOf(0),
            isVpr = isVpr,
        )
    }

    fun decryptInPlace(
        buffer: ByteArray,
        length: Int,
        startPosition: Long,
        coreKey: ByteArray,
        isVpr: Boolean,
    ) {
        require(length in 0..buffer.size)
        require(coreKey.size == 17)
        repeat(length) { index ->
            val position = startPosition + index
            var byte = buffer[index].u8()
            byte = byte xor ((byte and 0x0f) shl 4)

            var cursor = position ushr 4
            var value = 0
            while (cursor >= 17) {
                value = value xor table1[(cursor % 272).toInt()].u8()
                cursor = cursor ushr 4
                value = value xor table2[(cursor % 272).toInt()].u8()
                cursor = cursor ushr 4
            }
            var mask = value xor tableV2[(position % 272).toInt()].u8()
            mask = mask xor coreKey[(position % 17).toInt()].u8()
            var plain = byte xor (mask xor ((mask and 0x0f) shl 4))
            if (isVpr) plain = plain xor vprKey[(position % 17).toInt()].u8()
            buffer[index] = plain.toByte()
        }
    }
}
