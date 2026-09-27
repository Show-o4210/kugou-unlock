package com.example.kugoudonwload

import com.example.kugoudonwload.core.AudioSniffer
import com.example.kugoudonwload.core.KeyImporter
import com.example.kugoudonwload.core.KgmCipher
import com.example.kugoudonwload.core.ProcessKind
import com.example.kugoudonwload.core.Qmc2Factory
import com.example.kugoudonwload.core.Tea
import com.example.kugoudonwload.core.hexBytes
import com.example.kugoudonwload.storage.RootFileAccess
import com.example.kugoudonwload.storage.selectOutputName
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class CoreMigrationTest {
    @Test
    fun contentDetectionOverridesMisleadingSuffix() {
        val header = AudioSniffer.kgmMagic + ByteArray(4) + byteArrayOf(3, 0, 0, 0)
        assertEquals(ProcessKind.KGM, AudioSniffer.detect(header, "song.kgg.flac.download"))
        assertEquals("song", AudioSniffer.outputBaseName("song.kgg.flac.download"))
    }

    @Test
    fun kgmCipherMatchesPythonGoldenVector() {
        val cipher = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f".hexBytes()
        val expected = "3885ed92795ff84cb303614116a01d47cfdf465c5e5f3bc6784d212f9d700ce9".hexBytes()
        KgmCipher.decryptInPlace(
            cipher,
            cipher.size,
            startPosition = 0,
            coreKey = ByteArray(17) { if (it < 16) it.toByte() else 0 },
            isVpr = false,
        )
        assertArrayEquals(expected, cipher)
    }

    @Test
    fun vprCipherMatchesPythonGoldenVector() {
        val cipher = "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f".hexBytes()
        val expected = "1d5a05340c418d429c83926cae16fe56cffa99b4f82a25b37662a1dcb0c8ba0a".hexBytes()
        KgmCipher.decryptInPlace(
            cipher,
            cipher.size,
            startPosition = 0,
            coreKey = ByteArray(17) { if (it < 16) it.toByte() else 0 },
            isVpr = true,
        )
        assertArrayEquals(expected, cipher)
    }

    @Test
    fun teaMatchesPythonGoldenVector() {
        val result = Tea.cbcDecrypt(ByteArray(24) { it.toByte() }, ByteArray(16) { it.toByte() })
        assertArrayEquals("6508023f12ffe76b9e7d0cd53f3f".hexBytes(), result)
    }

    @Test
    fun textKeyImportKeepsOnlyExplicitHashMappings() {
        val validHash = "0123456789abcdef0123456789abcdef"
        val input = "$validHash\$example-ekey\nnot-a-key\n".encodeToByteArray()
        val result = KeyImporter.parse("kgg.key", input)
        assertEquals("example-ekey", result.keys[validHash])
        assertEquals(1, result.ignoredEntries)
    }

    @Test
    fun mmkvImportReadsOnlyAudioHashEntries() {
        val hash = "fedcba9876543210fedcba9876543210"
        val ekey = "synthetic-ekey"
        val nested = byteArrayOf(ekey.length.toByte()) + ekey.encodeToByteArray()
        val payload = byteArrayOf(0, hash.length.toByte()) + hash.encodeToByteArray() +
            byteArrayOf(nested.size.toByte()) + nested
        val file = byteArrayOf(
            payload.size.toByte(),
            (payload.size ushr 8).toByte(),
            (payload.size ushr 16).toByte(),
            (payload.size ushr 24).toByte(),
        ) + payload
        val result = KeyImporter.parse("mggkey_multi_process", file)
        assertEquals(ekey, result.keys[hash])
    }

    @Test
    fun qmc2MapMatchesPythonSyntheticVector() {
        val ekey = "AAECAwQFBgcUPd9dNWqKxI7Ih6zPHtuHowyhqolDHoY7j3TkkRUuZ3ZIR0pbOjxW" +
            "DJNQQrxBS+n5MVztdXPGhmeZh0j/qsptC19a0PZe6gpvUGXiTtL0nUCEnedduCscE" +
            "EdHYdQWIOozvx+DMeauHF3+jms8rSUWL2PzMbD7RWsiFwW2GQlZW5UER4W9NIBt"
        val cipher = "52ec2b21f5e44020332754e1fd6870aa38aa746ce5f540372330542fed7950bd".hexBytes()
        val expected = "664c6143000102030405060708090a0b0c0d0e0f101112131415161718191a1b".hexBytes()
        val decryptor = requireNotNull(Qmc2Factory.create(ekey))
        decryptor.decrypt(cipher, cipher.size, 0)
        assertArrayEquals(expected, cipher)
    }

    @Test
    fun rootPathIsShellQuotedAsOneLiteralArgument() {
        val path = "/data/user/0/a'b; echo injected"
        assertEquals("'/data/user/0/a'\"'\"'b; echo injected'", RootFileAccess().shellQuote(path))
    }

    @Test
    fun outputNamePolicyCanSkipOrNumberExistingFiles() {
        val existing = setOf("song.flac", "song (2).flac")
        assertEquals(null, selectOutputName("song.flac", existing, skipExisting = true))
        assertEquals("song (3).flac", selectOutputName("song.flac", existing, skipExisting = false))
        assertEquals("new.flac", selectOutputName("new.flac", existing, skipExisting = true))
    }
}
