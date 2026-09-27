package com.example.kugoudonwload.storage

import android.annotation.SuppressLint
import java.io.ByteArrayOutputStream
import java.io.FilterInputStream
import java.io.InputStream
import java.util.concurrent.TimeUnit

data class RootDetection(
    val rootAvailable: Boolean,
    val musicDirectories: List<String>,
    val keyFiles: List<String>,
)

class RootFileAccess {
    companion object {
        val DEFAULT_MUSIC_DIRECTORIES = listOf(
            "/storage/emulated/0/kgmusic",
        )

        // These intentionally target another app's user-approved, root-only files.
        @SuppressLint("SdCardPath")
        val DEFAULT_KEY_FILES = listOf(
            "/data/user/0/com.kugou.android/files/mmkv/mggkey_multi_process",
            "/data/user/0/com.kugou.android.lite/files/mmkv/mggkey_multi_process",
            "/data/data/com.kugou.android/files/mmkv/mggkey_multi_process",
            "/data/data/com.kugou.android.lite/files/mmkv/mggkey_multi_process",
        )

        private const val MAX_LIST_BYTES = 4 * 1024 * 1024
        private const val MAX_FILES = 5_000
    }

    fun detectDefaults(): RootDetection {
        val root = runSmall("id -u").lineSequence().any { it.trim() == "0" }
        if (!root) return RootDetection(false, emptyList(), emptyList())
        return RootDetection(
            rootAvailable = true,
            musicDirectories = DEFAULT_MUSIC_DIRECTORIES.filter { exists(it, directory = true) },
            keyFiles = DEFAULT_KEY_FILES.filter { exists(it, directory = false) }.distinct(),
        )
    }

    fun listFiles(directory: String): List<String> {
        validatePath(directory)
        val command = "find ${shellQuote(directory)} -type f -print0 2>/dev/null"
        val process = ProcessBuilder("su", "-c", command).start()
        val bytes = process.inputStream.use { it.readBounded(MAX_LIST_BYTES) }
        if (!process.waitFor(30, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            error("root 目录扫描超时")
        }
        require(process.exitValue() == 0) { "无法读取 root 歌曲目录" }
        return bytes.splitZeroTerminated().asSequence()
            .filter { it.isNotBlank() }
            .take(MAX_FILES)
            .toList()
    }

    fun open(path: String): InputStream {
        validatePath(path)
        val process = ProcessBuilder(
            "su",
            "-c",
            "cat ${shellQuote(path)} 2>/dev/null",
        ).start()
        return ProcessBackedInputStream(process)
    }

    fun fileSize(path: String): Long? {
        validatePath(path)
        return runSmall("stat -c %s ${shellQuote(path)} 2>/dev/null").trim().toLongOrNull()
            ?.takeIf { it >= 0 }
    }

    private fun exists(path: String, directory: Boolean): Boolean {
        validatePath(path)
        val test = if (directory) "-d" else "-f"
        return runSmall("if [ $test ${shellQuote(path)} ]; then printf 1; fi").trim() == "1"
    }

    private fun runSmall(command: String): String {
        val process = try {
            ProcessBuilder("su", "-c", command).start()
        } catch (_: Exception) {
            return ""
        }
        if (!process.waitFor(30, TimeUnit.SECONDS)) {
            process.destroyForcibly()
            return ""
        }
        return process.inputStream.bufferedReader().use { it.readText().take(8 * 1024) }
    }

    private fun validatePath(path: String) {
        require(path.isNotBlank() && path.length <= 4_096 && '\u0000' !in path) { "root 路径无效" }
    }

    internal fun shellQuote(value: String): String = "'" + value.replace("'", "'\"'\"'") + "'"

    private class ProcessBackedInputStream(
        private val process: Process,
    ) : FilterInputStream(process.inputStream) {
        override fun close() {
            try {
                super.close()
            } finally {
                if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly()
            }
        }
    }
}

private fun InputStream.readBounded(maxBytes: Int): ByteArray {
    val output = ByteArrayOutputStream()
    val buffer = ByteArray(64 * 1024)
    var total = 0
    while (true) {
        val count = read(buffer)
        if (count < 0) break
        total += count
        require(total <= maxBytes) { "root 目录返回内容过大" }
        output.write(buffer, 0, count)
    }
    return output.toByteArray()
}

private fun ByteArray.splitZeroTerminated(): List<String> {
    val result = mutableListOf<String>()
    var start = 0
    indices.forEach { index ->
        if (this[index] == 0.toByte()) {
            result += copyOfRange(start, index).toString(Charsets.UTF_8)
            start = index + 1
        }
    }
    if (start < size) result += copyOfRange(start, size).toString(Charsets.UTF_8)
    return result
}
