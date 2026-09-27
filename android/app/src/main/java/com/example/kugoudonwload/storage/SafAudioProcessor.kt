package com.example.kugoudonwload.storage

import android.content.ContentResolver
import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import com.example.kugoudonwload.core.AudioSniffer
import com.example.kugoudonwload.core.KeyImportResult
import com.example.kugoudonwload.core.KeyImporter
import com.example.kugoudonwload.core.KggHeaderParser
import com.example.kugoudonwload.core.KgmCipher
import com.example.kugoudonwload.core.ProcessKind
import com.example.kugoudonwload.core.Qmc2Factory
import java.io.ByteArrayOutputStream
import java.io.EOFException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID
import java.util.concurrent.CancellationException
import java.util.concurrent.atomic.AtomicBoolean

data class SelectedAudio(
    val uri: Uri?,
    val rootPath: String?,
    val displayName: String,
    val kind: ProcessKind,
    val sizeBytes: Long?,
)

data class ProcessResult(
    val inputName: String,
    val outputName: String?,
    val error: String?,
    val skipped: Boolean = false,
) {
    val succeeded: Boolean get() = error == null && !skipped
}

private data class OutputWriteResult(val name: String, val skipped: Boolean)

class SafAudioProcessor(context: Context) {
    private val resolver: ContentResolver = context.contentResolver
    private val rootFiles = RootFileAccess()
    private val outputNameLock = Any()
    private val reservedOutputNames = mutableMapOf<String, MutableSet<String>>()

    fun inspect(uri: Uri): SelectedAudio {
        val (name, size) = metadata(uri)
        val header = open(uri).use { it.readUpTo(24) }
        return SelectedAudio(uri, null, name, AudioSniffer.detect(header, name), size)
    }

    fun importKeys(uri: Uri, displayName: String): KeyImportResult {
        return open(uri).use { input -> importKeys(input, displayName) }
    }

    fun inspectRoot(path: String): SelectedAudio {
        val name = path.substringAfterLast('/').ifBlank { "audio" }
        val header = rootFiles.open(path).use { it.readUpTo(24) }
        return SelectedAudio(null, path, name, AudioSniffer.detect(header, name), rootFiles.fileSize(path))
    }

    fun importRootKeys(path: String): KeyImportResult =
        rootFiles.open(path).use { input -> importKeys(input, path.substringAfterLast('/')) }

    fun inspectTree(tree: Uri, maxFiles: Int = 5_000): List<SelectedAudio> {
        val queue = ArrayDeque<String>()
        queue += DocumentsContract.getTreeDocumentId(tree)
        val result = mutableListOf<SelectedAudio>()
        while (queue.isNotEmpty() && result.size < maxFiles) {
            val parentId = queue.removeFirst()
            val children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parentId)
            resolver.query(
                children,
                arrayOf(
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                ),
                null,
                null,
                null,
            )?.use { cursor ->
                while (cursor.moveToNext() && result.size < maxFiles) {
                    val documentId = cursor.getString(0)
                    val mime = cursor.getString(1)
                    if (mime == DocumentsContract.Document.MIME_TYPE_DIR) {
                        queue += documentId
                    } else {
                        val uri = DocumentsContract.buildDocumentUriUsingTree(tree, documentId)
                        try {
                            result += inspect(uri)
                        } catch (_: Exception) {
                            // A provider may expose an entry that cannot be opened; skip it.
                        }
                    }
                }
            }
        }
        return result
    }

    private fun importKeys(input: InputStream, displayName: String): KeyImportResult {
        val bytes = input.use {
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(64 * 1024)
            var total = 0
            while (true) {
                val count = it.read(buffer)
                if (count < 0) break
                total += count
                require(total <= KeyImporter.MAX_INPUT_BYTES) { "密钥文件超过 32 MiB 限制" }
                output.write(buffer, 0, count)
            }
            output.toByteArray()
        }
        return KeyImporter.parse(displayName, bytes)
    }

    fun process(
        selected: SelectedAudio,
        outputTree: Uri,
        keys: Map<String, String>,
        cancelled: AtomicBoolean,
        skipExisting: Boolean = false,
        onBytesProcessed: (Long) -> Unit = {},
    ): ProcessResult = try {
        checkNotCancelled(cancelled)
        val output = when (selected.kind) {
            ProcessKind.PLAIN -> copyPlain(selected, outputTree, cancelled, skipExisting, onBytesProcessed)
            ProcessKind.KGM -> decryptKgm(selected, outputTree, cancelled, skipExisting, onBytesProcessed)
            ProcessKind.KGG -> decryptKgg(selected, outputTree, keys, cancelled, skipExisting, onBytesProcessed)
            ProcessKind.UNKNOWN -> error("无法可靠识别文件格式")
        }
        ProcessResult(selected.displayName, output.name, null, output.skipped)
    } catch (cancelledError: CancellationException) {
        ProcessResult(selected.displayName, null, "已取消")
    } catch (error: Exception) {
        ProcessResult(selected.displayName, null, error.message ?: error.javaClass.simpleName)
    }

    private fun copyPlain(
        selected: SelectedAudio,
        outputTree: Uri,
        cancelled: AtomicBoolean,
        skipExisting: Boolean,
        onBytesProcessed: (Long) -> Unit,
    ): OutputWriteResult {
        val probe = open(selected).use { it.readUpTo(16) }
        val extension = AudioSniffer.audioExtension(probe) ?: error("明文音频头无效")
        val target = AudioSniffer.outputBaseName(selected.displayName) + extension
        return writeAtomic(outputTree, target, mimeFor(extension), skipExisting) { output ->
            open(selected).use { input -> copy(input, output, cancelled, onBytesProcessed) }
        }
    }

    private fun decryptKgm(
        selected: SelectedAudio,
        outputTree: Uri,
        cancelled: AtomicBoolean,
        skipExisting: Boolean,
        onBytesProcessed: (Long) -> Unit,
    ): OutputWriteResult {
        val input = open(selected)
        input.use {
            val fixedHeader = it.readExactly(60)
            val header = KgmCipher.parseHeader(fixedHeader)
            require(header.payloadOffset <= KggHeaderParser.MAX_HEADER_BYTES) { "KGM 载荷偏移过大" }
            it.skipExactly(header.payloadOffset - 60)
            val buffer = ByteArray(64 * 1024)
            var count = it.read(buffer)
            require(count > 0) { "KGM 没有音频载荷" }
            KgmCipher.decryptInPlace(buffer, count, 0, header.coreKey, header.isVpr)
            val extension = AudioSniffer.audioExtension(buffer.copyOf(minOf(count, 16)))
                ?: error("解密结果不是受支持的音频格式")
            val target = AudioSniffer.outputBaseName(selected.displayName) + extension
            return writeAtomic(outputTree, target, mimeFor(extension), skipExisting) { output ->
                onBytesProcessed(header.payloadOffset)
                var position = 0L
                while (count > 0) {
                    checkNotCancelled(cancelled)
                    output.write(buffer, 0, count)
                    onBytesProcessed(count.toLong())
                    position += count
                    count = it.read(buffer)
                    if (count > 0) KgmCipher.decryptInPlace(buffer, count, position, header.coreKey, header.isVpr)
                }
            }
        }
    }

    private fun decryptKgg(
        selected: SelectedAudio,
        outputTree: Uri,
        keys: Map<String, String>,
        cancelled: AtomicBoolean,
        skipExisting: Boolean,
        onBytesProcessed: (Long) -> Unit,
    ): OutputWriteResult {
        val metadataInput = open(selected)
        val header = metadataInput.use {
            val fixed = it.readExactly(KggHeaderParser.FIXED_HEADER_BYTES)
            val hashLength = fixed.u32LeForStorage(68)
            require(hashLength in 1..KggHeaderParser.MAX_HASH_BYTES.toLong()) { "KGG hash 长度无效" }
            KggHeaderParser.parse(fixed, it.readExactly(hashLength.toInt()))
        }
        val ekey = keys[header.audioHash] ?: error("没有找到该歌曲的 KGG 密钥")

        val input = open(selected)
        input.use {
            it.skipExactly(header.payloadOffset)
            val buffer = ByteArray(64 * 1024)
            var count = it.read(buffer)
            require(count > 0) { "KGG 没有音频载荷" }
            val encryptedProbe = buffer.copyOf(minOf(count, 16))
            var cipher = Qmc2Factory.create(ekey) ?: error("KGG 密钥格式无效")
            val normalProbe = encryptedProbe.copyOf()
            cipher.decrypt(normalProbe, normalProbe.size, 0)
            var extension = AudioSniffer.audioExtension(normalProbe)
            if (extension == null) {
                val legacy = Qmc2Factory.create(ekey, legacyMap = true) ?: error("KGG 密钥格式无效")
                val legacyProbe = encryptedProbe.copyOf()
                legacy.decrypt(legacyProbe, legacyProbe.size, 0)
                extension = AudioSniffer.audioExtension(legacyProbe)
                if (extension != null) cipher = legacy
            }
            requireNotNull(extension) { "KGG 密钥不匹配或音频格式不受支持" }

            cipher.decrypt(buffer, count, 0)
            val target = AudioSniffer.outputBaseName(selected.displayName) + extension
            return writeAtomic(outputTree, target, mimeFor(extension), skipExisting) { output ->
                onBytesProcessed(header.payloadOffset)
                var position = 0L
                while (count > 0) {
                    checkNotCancelled(cancelled)
                    output.write(buffer, 0, count)
                    onBytesProcessed(count.toLong())
                    position += count
                    count = it.read(buffer)
                    if (count > 0) cipher.decrypt(buffer, count, position)
                }
            }
        }
    }

    private fun writeAtomic(
        tree: Uri,
        requestedName: String,
        mime: String,
        skipExisting: Boolean,
        writer: (OutputStream) -> Unit,
    ): OutputWriteResult {
        val parent = DocumentsContract.buildDocumentUriUsingTree(
            tree,
            DocumentsContract.getTreeDocumentId(tree),
        )
        val finalName = reserveOutputName(tree, parent, requestedName, skipExisting)
            ?: return OutputWriteResult(requestedName, skipped = true)
        try {
            val tempName = ".local-decode-${UUID.randomUUID()}.tmp"
            val temp = DocumentsContract.createDocument(resolver, parent, "application/octet-stream", tempName)
                ?: error("输出目录不允许创建文件")
            try {
                resolver.openOutputStream(temp, "w")?.use(writer) ?: error("无法打开临时输出")
                try {
                    val renamed = DocumentsContract.renameDocument(resolver, temp, finalName)
                    if (renamed != null) return OutputWriteResult(finalName, skipped = false)
                } catch (_: Exception) {
                    // Some providers do not implement rename; verified local copy is the fallback.
                }
                val finalUri = DocumentsContract.createDocument(resolver, parent, mime, finalName)
                    ?: error("无法创建最终输出")
                try {
                    open(temp).use { input ->
                        resolver.openOutputStream(finalUri, "w")?.use { output -> input.copyTo(output) }
                            ?: error("无法写入最终输出")
                    }
                } catch (error: Exception) {
                    DocumentsContract.deleteDocument(resolver, finalUri)
                    throw error
                }
                DocumentsContract.deleteDocument(resolver, temp)
                return OutputWriteResult(finalName, skipped = false)
            } catch (error: Exception) {
                try {
                    DocumentsContract.deleteDocument(resolver, temp)
                } catch (_: Exception) {
                    // Best effort cleanup; source URI is never changed.
                }
                throw error
            }
        } finally {
            releaseOutputName(tree, finalName)
        }
    }

    private fun reserveOutputName(
        tree: Uri,
        parent: Uri,
        requested: String,
        skipExisting: Boolean,
    ): String? = synchronized(outputNameLock) {
        val treeKey = tree.toString()
        val existing = mutableSetOf<String>()
        try {
            val children = DocumentsContract.buildChildDocumentsUriUsingTree(
                tree,
                DocumentsContract.getDocumentId(parent),
            )
            resolver.query(
                children,
                arrayOf(DocumentsContract.Document.COLUMN_DISPLAY_NAME),
                null,
                null,
                null,
            )?.use { cursor ->
                while (cursor.moveToNext()) existing += cursor.getString(0)
            }
        } catch (_: Exception) {
            // Some providers cannot enumerate children; in-memory reservations still avoid worker races.
        }
        val reserved = reservedOutputNames.getOrPut(treeKey) { mutableSetOf() }
        existing += reserved
        val finalName = selectOutputName(requested, existing, skipExisting) ?: return@synchronized null
        reserved += finalName
        finalName
    }

    private fun releaseOutputName(tree: Uri, name: String) = synchronized(outputNameLock) {
        val reserved = reservedOutputNames[tree.toString()] ?: return@synchronized
        reserved -= name
        if (reserved.isEmpty()) reservedOutputNames.remove(tree.toString())
    }

    private fun metadata(uri: Uri): Pair<String, Long?> {
        try {
            resolver.query(
                uri,
                arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE),
                null,
                null,
                null,
            )?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val name = cursor.getString(0) ?: "audio"
                    val size = if (cursor.isNull(1)) null else cursor.getLong(1).takeIf { it >= 0 }
                    return name to size
                }
            }
        } catch (_: Exception) {
            // Some third-party providers omit SIZE; processing can fall back to an estimated weight.
        }
        return (uri.lastPathSegment ?: "audio") to null
    }

    private fun open(uri: Uri): InputStream =
        resolver.openInputStream(uri) ?: error("无法读取所选文件")

    private fun open(selected: SelectedAudio): InputStream = when {
        selected.uri != null -> open(selected.uri)
        selected.rootPath != null -> rootFiles.open(selected.rootPath)
        else -> error("音频来源无效")
    }

    private fun copy(
        input: InputStream,
        output: OutputStream,
        cancelled: AtomicBoolean,
        onBytesProcessed: (Long) -> Unit,
    ) {
        val buffer = ByteArray(64 * 1024)
        while (true) {
            checkNotCancelled(cancelled)
            val count = input.read(buffer)
            if (count < 0) return
            output.write(buffer, 0, count)
            onBytesProcessed(count.toLong())
        }
    }

    private fun checkNotCancelled(cancelled: AtomicBoolean) {
        if (cancelled.get()) throw CancellationException("cancelled")
    }

    private fun mimeFor(extension: String): String = when (extension) {
        ".flac" -> "audio/flac"
        ".mp3" -> "audio/mpeg"
        ".ogg" -> "audio/ogg"
        ".m4a" -> "audio/mp4"
        ".wav" -> "audio/wav"
        else -> "application/octet-stream"
    }
}

internal fun selectOutputName(requested: String, existing: Set<String>, skipExisting: Boolean): String? {
    if (requested !in existing) return requested
    if (skipExisting) return null
    val dot = requested.lastIndexOf('.')
    val base = if (dot > 0) requested.substring(0, dot) else requested
    val extension = if (dot > 0) requested.substring(dot) else ""
    var number = 2
    while ("$base ($number)$extension" in existing) number++
    return "$base ($number)$extension"
}

private fun InputStream.readUpTo(length: Int): ByteArray {
    val result = ByteArray(length)
    var offset = 0
    while (offset < length) {
        val count = read(result, offset, length - offset)
        if (count < 0) break
        offset += count
    }
    return result.copyOf(offset)
}

private fun InputStream.readExactly(length: Int): ByteArray {
    val result = readUpTo(length)
    if (result.size != length) throw EOFException("文件内容被截断")
    return result
}

private fun InputStream.skipExactly(length: Long) {
    require(length >= 0) { "文件偏移无效" }
    var remaining = length
    val discard = ByteArray(8 * 1024)
    while (remaining > 0) {
        val skipped = skip(remaining)
        if (skipped > 0) {
            remaining -= skipped
        } else {
            val count = read(discard, 0, minOf(discard.size.toLong(), remaining).toInt())
            if (count < 0) throw EOFException("文件内容被截断")
            remaining -= count
        }
    }
}

private fun ByteArray.u32LeForStorage(offset: Int): Long {
    require(offset >= 0 && offset + 4 <= size)
    return (this[offset].toInt() and 0xff).toLong() or
        ((this[offset + 1].toInt() and 0xff).toLong() shl 8) or
        ((this[offset + 2].toInt() and 0xff).toLong() shl 16) or
        ((this[offset + 3].toInt() and 0xff).toLong() shl 24)
}
