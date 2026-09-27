package com.example.kugoudonwload

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.Switch
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.core.content.edit
import com.example.kugoudonwload.core.ProcessKind
import com.example.kugoudonwload.storage.ProcessResult
import com.example.kugoudonwload.storage.RootFileAccess
import com.example.kugoudonwload.storage.SafAudioProcessor
import com.example.kugoudonwload.storage.SelectedAudio
import com.example.kugoudonwload.ui.theme.KugoudonwloadTheme
import java.util.concurrent.Executors
import java.util.concurrent.ExecutorCompletionService
import java.util.concurrent.Future
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLongArray
import kotlin.math.roundToInt

private sealed interface PendingKeySource {
    val label: String

    data class ContentUri(val uri: Uri, override val label: String) : PendingKeySource
    data class RootPath(val path: String) : PendingKeySource {
        override val label: String = path
    }
}

private enum class AppTab(val label: String) {
    SONGS("歌曲"),
    KEYS("密钥"),
    OUTPUT("输出"),
    PROCESS("处理"),
}

class MainActivity : ComponentActivity() {
    private val controlWorker = Executors.newSingleThreadExecutor()
    private val processingWorkers = Executors.newFixedThreadPool(PROCESSING_THREADS)
    private val cancelled = AtomicBoolean(false)
    private val rootFiles = RootFileAccess()
    private lateinit var processor: SafAudioProcessor
    private var runningTask: Future<*>? = null

    private var selectedAudios by mutableStateOf<List<SelectedAudio>>(emptyList())
    private var outputTree by mutableStateOf<Uri?>(null)
    private var outputLabel by mutableStateOf("尚未选择")
    private var pendingKey by mutableStateOf<PendingKeySource?>(null)
    private var showKeyConfirmation by mutableStateOf(false)
    private var keyMapping: Map<String, String> = emptyMap()
    private var keyStatus by mutableStateOf("未导入（KGM/KGMA/VPR 不需要）")
    private var busy by mutableStateOf(false)
    private var progress by mutableFloatStateOf(0f)
    private var progressText by mutableStateOf("尚未开始")
    private var processing by mutableStateOf(false)
    private var status by mutableStateOf("请选择本地歌曲和输出目录")
    private var results by mutableStateOf<List<ProcessResult>>(emptyList())
    private var rootBusy by mutableStateOf(false)
    private var rootStatus by mutableStateOf("正在等待 root 环境检测")
    private var rootMusicPath by mutableStateOf(RootFileAccess.DEFAULT_MUSIC_DIRECTORIES.first())
    private var rootKeyPath by mutableStateOf(RootFileAccess.DEFAULT_KEY_FILES.first())
    private var showUsageAgreement by mutableStateOf(false)
    private var showSettings by mutableStateOf(false)
    private var skipExisting by mutableStateOf(true)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        processor = SafAudioProcessor(this)
        val agreementAccepted = getSharedPreferences(PREFERENCES_NAME, MODE_PRIVATE)
            .getBoolean(AGREEMENT_KEY, false)
        skipExisting = getSharedPreferences(PREFERENCES_NAME, MODE_PRIVATE)
            .getBoolean(SKIP_EXISTING_KEY, true)
        showUsageAgreement = !agreementAccepted
        if (!agreementAccepted) rootStatus = "完成首次使用确认后再检测 Root 环境"

        val audioPicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                val uris = linkedSetOf<Uri>()
                result.data?.clipData?.let { clipData ->
                    repeat(clipData.itemCount) { index ->
                        uris += clipData.getItemAt(index).uri
                    }
                }
                result.data?.data?.let(uris::add)
                inspectSelectedAudios(uris.toList())
            }
        }
        val audioFolderPicker = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            if (uri != null) inspectAudioTree(uri)
        }
        val outputPicker = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            outputTree = uri
            outputLabel = uri?.lastPathSegment ?: "尚未选择"
        }
        val keyPicker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val uri = result.data?.data
            if (result.resultCode == Activity.RESULT_OK && uri != null) {
                pendingKey = PendingKeySource.ContentUri(uri, queryDisplayName(uri))
                showKeyConfirmation = true
            }
        }

        enableEdgeToEdge()
        setContent {
            KugoudonwloadTheme {
                Scaffold(
                    modifier = Modifier.fillMaxSize(),
                    containerColor = androidx.compose.ui.graphics.Color.Transparent,
                ) { innerPadding ->
                    MainScreen(
                        modifier = Modifier.padding(innerPadding),
                        onChooseAudioFiles = {
                            val request = Intent(Intent.ACTION_GET_CONTENT).apply {
                                type = "*/*"
                                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                                addCategory(Intent.CATEGORY_OPENABLE)
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            audioPicker.launch(
                                Intent.createChooser(request, "选择用于打开歌曲的文件管理器"),
                            )
                        },
                        onChooseAudioFolder = { audioFolderPicker.launch(null) },
                        onChooseOutput = { outputPicker.launch(null) },
                        onChooseKey = {
                            val request = Intent(Intent.ACTION_GET_CONTENT).apply {
                                type = "*/*"
                                addCategory(Intent.CATEGORY_OPENABLE)
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            keyPicker.launch(
                                Intent.createChooser(request, "选择用于打开密钥的文件管理器"),
                            )
                        },
                        onDetectRoot = ::detectRootSources,
                        onScanRootMusic = ::scanRootMusic,
                        onUseRootKey = {
                            pendingKey = PendingKeySource.RootPath(rootKeyPath.trim())
                            showKeyConfirmation = true
                        },
                        onStart = ::startProcessing,
                        onCancel = {
                            cancelled.set(true)
                            status = "正在取消并清理未完成输出…"
                        },
                        onAcceptAgreement = ::acceptUsageAgreement,
                        onDeclineAgreement = ::finish,
                    )
                }
            }
        }
        if (agreementAccepted) detectRootSources()
    }

    @Composable
    private fun MainScreen(
        modifier: Modifier,
        onChooseAudioFiles: () -> Unit,
        onChooseAudioFolder: () -> Unit,
        onChooseOutput: () -> Unit,
        onChooseKey: () -> Unit,
        onDetectRoot: () -> Unit,
        onScanRootMusic: () -> Unit,
        onUseRootKey: () -> Unit,
        onStart: () -> Unit,
        onCancel: () -> Unit,
        onAcceptAgreement: () -> Unit,
        onDeclineAgreement: () -> Unit,
    ) {
        var selectedTab by rememberSaveable { mutableIntStateOf(0) }
        var songPathExpanded by rememberSaveable { mutableStateOf(false) }
        var keyPathExpanded by rememberSaveable { mutableStateOf(false) }

        if (showSettings) {
            AlertDialog(
                onDismissRequest = { showSettings = false },
                title = { Text("处理设置") },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text("跳过同名文件", style = MaterialTheme.typography.titleSmall)
                                Text(
                                    if (skipExisting) "输出目录已有同名文件时不再处理" else "同名时自动编号并生成新副本",
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                            Switch(checked = skipExisting, onCheckedChange = ::updateSkipExisting)
                        }
                        Text(
                            "批量处理使用 $PROCESSING_THREADS 个并行任务。",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                },
                confirmButton = {
                    TextButton(onClick = { showSettings = false }) { Text("完成") }
                },
            )
        }

        if (showUsageAgreement) {
            UsageAgreementDialog(onAcceptAgreement, onDeclineAgreement)
        }

        if (showKeyConfirmation) {
            val candidate = pendingKey
            AlertDialog(
                onDismissRequest = { showKeyConfirmation = false },
                title = { Text("确认解析密钥") },
                text = {
                    Text(
                        "将只读取你刚刚选择的本地文件：\n${candidate?.label.orEmpty()}\n\n" +
                            "该密钥必须由你本人拥有或已获得合法授权。本应用不提供、下载或共享公共密钥。" +
                            "解析结果仅保留在本次应用进程中，不上传、不写入日志，也不会读取其他路径。",
                    )
                },
                confirmButton = {
                    TextButton(onClick = {
                        showKeyConfirmation = false
                        candidate?.let(::importKeys)
                    }) { Text("授权并解析") }
                },
                dismissButton = {
                    TextButton(onClick = {
                        showKeyConfirmation = false
                        pendingKey = null
                    }) { Text("取消") }
                },
            )
        }

        Box(modifier = modifier.fillMaxSize()) {
            Image(
                painter = painterResource(R.drawable.music_background),
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                alpha = 0.24f,
            )
            Box(
                modifier = Modifier.fillMaxSize().background(
                    MaterialTheme.colorScheme.surface.copy(alpha = 0.76f),
                ),
            )
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text("本地音乐解码", style = MaterialTheme.typography.headlineSmall)
                        Text(
                            "完全离线 · Root 只读 · 仅生成本地副本",
                            color = MaterialTheme.colorScheme.primary,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                    IconButton(onClick = { showSettings = true }, enabled = !processing) {
                        Text("⚙", style = MaterialTheme.typography.headlineSmall)
                    }
                }
                PrimaryTabRow(selectedTabIndex = selectedTab) {
                    AppTab.entries.forEachIndexed { index, tab ->
                        Tab(
                            selected = selectedTab == index,
                            onClick = { selectedTab = index },
                            text = { Text(tab.label) },
                        )
                    }
                }
                if (processing) {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
                        Text(progressText, style = MaterialTheme.typography.bodySmall)
                    }
                } else if (rootBusy || busy) {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                }
                TabBody(selectedTab) {
                    when (AppTab.entries[selectedTab]) {
                        AppTab.SONGS -> {
                            SectionCard("选择本地歌曲") {
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                                ) {
                                    Button(
                                        onClick = onChooseAudioFiles,
                                        enabled = !busy && !rootBusy,
                                        modifier = Modifier.weight(1f),
                                    ) { Text("选择文件") }
                                    OutlinedButton(
                                        onClick = onChooseAudioFolder,
                                        enabled = !busy && !rootBusy,
                                        modifier = Modifier.weight(1f),
                                    ) { Text("选择文件夹") }
                                }
                                Text(if (selectedAudios.isEmpty()) "尚未选择歌曲" else "已识别 ${selectedAudios.size} 个文件")
                                selectedAudios.take(12).forEach { item ->
                                    Text("${kindLabel(item.kind)}  ${item.displayName}")
                                }
                                if (selectedAudios.size > 12) {
                                    Text("另有 ${selectedAudios.size - 12} 个文件未在此展开", style = MaterialTheme.typography.bodySmall)
                                }
                            }
                            ExpandableSection(
                                title = "Root 歌曲路径",
                                summary = rootStatus.lineSequence().firstOrNull().orEmpty(),
                                expanded = songPathExpanded,
                                onExpandedChange = { songPathExpanded = it },
                            ) {
                                Text(rootStatus)
                                OutlinedButton(onClick = onDetectRoot, enabled = !rootBusy && !busy) {
                                    Text("重新检测默认路径")
                                }
                                OutlinedTextField(
                                    value = rootMusicPath,
                                    onValueChange = { rootMusicPath = it },
                                    label = { Text("歌曲目录") },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                Button(
                                    onClick = onScanRootMusic,
                                    enabled = !rootBusy && !busy && rootMusicPath.isNotBlank(),
                                ) { Text("扫描此歌曲目录") }
                                Text(
                                    "同意使用声明后会自动加载检测到的默认目录；这里仍可修改路径并重新扫描。",
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                        }

                        AppTab.KEYS -> {
                            SectionCard("KGG 密钥（可选）") {
                                OutlinedButton(onClick = onChooseKey, enabled = !busy && !rootBusy) {
                                    Text("从文件管理器选择密钥")
                                }
                                Text(keyStatus)
                                Text(
                                    "密钥必须由你本人拥有或取得合法授权。本应用不提供、下载、" +
                                        "共享或维护任何公共密钥库。默认路径在使用声明同意后自动读取；" +
                                        "手动选择的来源仍会再次确认。",
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                            ExpandableSection(
                                title = "Root 密钥路径",
                                summary = "默认折叠，展开后可编辑",
                                expanded = keyPathExpanded,
                                onExpandedChange = { keyPathExpanded = it },
                            ) {
                                OutlinedTextField(
                                    value = rootKeyPath,
                                    onValueChange = { rootKeyPath = it },
                                    label = { Text("mggkey / kgg.key 路径") },
                                    singleLine = true,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                                OutlinedButton(
                                    onClick = onUseRootKey,
                                    enabled = !rootBusy && !busy && rootKeyPath.isNotBlank(),
                                ) { Text("确认此密钥来源") }
                                Text(
                                    "检测到的默认密钥会自动读取；手动修改此路径时仍会再次确认。密钥仅保留在当前进程。",
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                        }

                        AppTab.OUTPUT -> {
                            SectionCard("选择输出目录") {
                                Button(onClick = onChooseOutput, enabled = !busy && !rootBusy) {
                                    Text("选择保存目录")
                                }
                                Text(outputLabel)
                                Text(
                                    if (skipExisting) {
                                        "只生成新的本地副本；遇到同名文件时跳过，可在顶部 ⚙ 中关闭。"
                                    } else {
                                        "只生成新的本地副本；遇到同名文件时自动编号，不覆盖源文件。"
                                    },
                                    style = MaterialTheme.typography.bodySmall,
                                )
                            }
                        }

                        AppTab.PROCESS -> {
                            SectionCard("准备情况") {
                                Text("歌曲：${selectedAudios.size} 个")
                                Text("密钥：$keyStatus")
                                Text("输出：$outputLabel")
                            }
                            SectionCard("开始处理") {
                                if (processing) {
                                    OutlinedButton(onClick = onCancel) { Text("取消") }
                                } else {
                                    Button(
                                        onClick = onStart,
                                        enabled = !busy && !rootBusy && selectedAudios.isNotEmpty() && outputTree != null,
                                    ) { Text("确认并生成本地副本") }
                                    if (progress > 0f) Text(progressText)
                                }
                                Text(status)
                            }
                            if (results.isNotEmpty()) {
                                SectionCard("处理结果") {
                                    results.forEach { result ->
                                        Text(
                                            if (result.skipped) {
                                                "跳过：${result.inputName}（已存在 ${result.outputName}）"
                                            } else if (result.succeeded) {
                                                "成功：${result.inputName} → ${result.outputName}"
                                            } else {
                                                "失败：${result.inputName}（${result.error}）"
                                            },
                                            color = if (result.succeeded) {
                                                MaterialTheme.colorScheme.primary
                                            } else if (result.skipped) {
                                                MaterialTheme.colorScheme.tertiary
                                            } else {
                                                MaterialTheme.colorScheme.error
                                            },
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    @Composable
    private fun UsageAgreementDialog(onAccept: () -> Unit, onDecline: () -> Unit) {
        var rightsConfirmed by rememberSaveable { mutableStateOf(false) }
        var keyConfirmed by rememberSaveable { mutableStateOf(false) }
        AlertDialog(
            onDismissRequest = {},
            title = { Text("本地使用与密钥来源声明") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(
                        "同意后，本工具会自动读取文档列出的默认 Root 歌曲目录和本人密钥；" +
                            "也可由你手动选择路径。应用不联网获取歌曲或密钥，" +
                            "也不会提供任何公共密钥。请在继续前确认：",
                    )
                    ConfirmationRow(
                        checked = rightsConfirmed,
                        onCheckedChange = { rightsConfirmed = it },
                        text = "我只处理本人拥有或已获得合法授权的本地音乐文件。",
                    )
                    ConfirmationRow(
                        checked = keyConfirmed,
                        onCheckedChange = { keyConfirmed = it },
                        text = "使用的密钥来自我本人控制的设备或合法授权来源，并非由本应用提供。",
                    )
                    Text(
                        "请勿用于绕过订阅、付费、账号权限或处理他人的文件与密钥。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            confirmButton = {
                TextButton(
                    onClick = onAccept,
                    enabled = rightsConfirmed && keyConfirmed,
                ) { Text("同意并继续") }
            },
            dismissButton = {
                TextButton(onClick = onDecline) { Text("不同意并退出") }
            },
        )
    }

    @Composable
    private fun ConfirmationRow(
        checked: Boolean,
        onCheckedChange: (Boolean) -> Unit,
        text: String,
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Checkbox(checked = checked, onCheckedChange = onCheckedChange)
            Text(text, modifier = Modifier.padding(top = 12.dp))
        }
    }

    @Composable
    private fun TabBody(selectedTab: Int, content: @Composable () -> Unit) {
        val scrollState = remember(selectedTab) { androidx.compose.foundation.ScrollState(0) }
        Column(
            modifier = Modifier.fillMaxSize().verticalScroll(scrollState).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            content()
        }
    }

    @Composable
    private fun ExpandableSection(
        title: String,
        summary: String,
        expanded: Boolean,
        onExpandedChange: (Boolean) -> Unit,
        content: @Composable () -> Unit,
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text(title, style = MaterialTheme.typography.titleMedium)
                        if (!expanded) Text(summary, style = MaterialTheme.typography.bodySmall)
                    }
                    TextButton(onClick = { onExpandedChange(!expanded) }) {
                        Text(if (expanded) "收起" else "展开")
                    }
                }
                if (expanded) content()
            }
        }
    }

    @Composable
    private fun SectionCard(title: String, content: @Composable () -> Unit) {
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(title, style = MaterialTheme.typography.titleMedium)
                content()
            }
        }
    }

    private fun acceptUsageAgreement() {
        getSharedPreferences(PREFERENCES_NAME, MODE_PRIVATE).edit {
            putBoolean(AGREEMENT_KEY, true)
        }
        showUsageAgreement = false
        detectRootSources()
    }

    private fun updateSkipExisting(value: Boolean) {
        skipExisting = value
        getSharedPreferences(PREFERENCES_NAME, MODE_PRIVATE).edit {
            putBoolean(SKIP_EXISTING_KEY, value)
        }
    }

    private fun importKeys(source: PendingKeySource) {
        busy = true
        status = "正在本地解析密钥…"
        runningTask = controlWorker.submit {
            try {
                val imported = when (source) {
                    is PendingKeySource.ContentUri -> processor.importKeys(source.uri, source.label)
                    is PendingKeySource.RootPath -> processor.importRootKeys(source.path)
                }
                runOnUiThread {
                    keyMapping = imported.keys
                    keyStatus = "本次已导入 ${imported.keys.size} 条密钥"
                    status = "密钥解析完成"
                }
            } catch (error: Exception) {
                runOnUiThread {
                    keyMapping = emptyMap()
                    keyStatus = "解析失败：${error.message ?: error.javaClass.simpleName}"
                    status = "密钥未导入"
                }
            } finally {
                runOnUiThread { busy = false }
            }
        }
    }

    private fun detectRootSources() {
        if (rootBusy || busy) return
        rootBusy = true
        rootStatus = "正在请求 Root 并自动加载默认路径…"
        runningTask = controlWorker.submit {
            try {
                val detected = rootFiles.detectDefaults()
                if (!detected.rootAvailable) {
                    runOnUiThread { rootStatus = "未取得 Root；仍可使用文件/文件夹选择器" }
                    return@submit
                }

                val musicDirectory = detected.musicDirectories.firstOrNull()
                val keyFile = detected.keyFiles.firstOrNull()
                runOnUiThread {
                    musicDirectory?.let { rootMusicPath = it }
                    keyFile?.let { rootKeyPath = it }
                    rootStatus = "Root 可用，正在自动读取默认歌曲目录和密钥…"
                }

                var importedKeyCount: Int? = null
                var keyError: String? = null
                if (keyFile != null) {
                    try {
                        val imported = processor.importRootKeys(keyFile)
                        importedKeyCount = imported.keys.size
                        runOnUiThread {
                            keyMapping = imported.keys
                            keyStatus = "已自动导入 ${imported.keys.size} 条密钥"
                        }
                    } catch (error: Exception) {
                        keyError = error.message ?: error.javaClass.simpleName
                        runOnUiThread {
                            keyMapping = emptyMap()
                            keyStatus = "默认密钥读取失败：$keyError"
                        }
                    }
                }

                val inspected = if (musicDirectory != null) {
                    inspectRootPaths(rootFiles.listFiles(musicDirectory))
                } else {
                    emptyList()
                }
                runOnUiThread {
                    if (musicDirectory != null) {
                        selectedAudios = inspected
                        results = emptyList()
                        status = "默认目录中识别到 ${inspected.size} 个可处理文件"
                    }
                    val musicSummary = musicDirectory ?: "未找到"
                    val keySummary = when {
                        keyFile == null -> "未找到"
                        keyError != null -> "读取失败"
                        else -> "$keyFile（${importedKeyCount ?: 0} 条）"
                    }
                    rootStatus = "Root 可用\n歌曲目录：$musicSummary\n密钥文件：$keySummary"
                }
            } catch (error: Exception) {
                runOnUiThread { rootStatus = "Root 检测失败：${error.message ?: error.javaClass.simpleName}" }
            } finally {
                runOnUiThread { rootBusy = false }
            }
        }
    }

    private fun scanRootMusic() {
        val directory = rootMusicPath.trim()
        if (directory.isEmpty() || rootBusy || busy) return
        rootBusy = true
        status = "正在只读扫描 root 歌曲目录…"
        runningTask = controlWorker.submit {
            try {
                val inspected = inspectRootPaths(rootFiles.listFiles(directory))
                runOnUiThread {
                    selectedAudios = inspected
                    results = emptyList()
                    status = "Root 目录中识别到 ${inspected.size} 个可处理文件"
                }
            } catch (error: Exception) {
                runOnUiThread { status = "Root 目录扫描失败：${error.message ?: error.javaClass.simpleName}" }
            } finally {
                runOnUiThread { rootBusy = false }
            }
        }
    }

    private fun inspectRootPaths(paths: List<String>): List<SelectedAudio> {
        val futures = paths.map { path ->
            processingWorkers.submit<SelectedAudio?> {
                try {
                    processor.inspectRoot(path).takeIf { it.kind != ProcessKind.UNKNOWN }
                } catch (_: Exception) {
                    null
                }
            }
        }
        return futures.mapNotNull { future ->
            try {
                future.get()
            } catch (_: Exception) {
                null
            }
        }
    }

    private fun inspectAudioTree(tree: Uri) {
        if (busy || rootBusy) return
        busy = true
        status = "正在扫描所选文件夹…"
        runningTask = controlWorker.submit {
            try {
                val inspected = processor.inspectTree(tree).filter { it.kind != ProcessKind.UNKNOWN }
                runOnUiThread {
                    selectedAudios = inspected
                    results = emptyList()
                    status = "文件夹中识别到 ${inspected.size} 个可处理文件"
                }
            } catch (error: Exception) {
                runOnUiThread { status = "文件夹扫描失败：${error.message ?: error.javaClass.simpleName}" }
            } finally {
                runOnUiThread { busy = false }
            }
        }
    }

    private fun inspectSelectedAudios(uris: List<Uri>) {
        if (uris.isEmpty()) return
        busy = true
        status = "正在读取文件头…"
        runningTask = controlWorker.submit {
            val inspected = uris.mapNotNull { uri ->
                try {
                    processor.inspect(uri)
                } catch (_: Exception) {
                    null
                }
            }
            runOnUiThread {
                selectedAudios = inspected
                busy = false
                status = "已选择 ${inspected.size} 个可读取文件"
                results = emptyList()
            }
        }
    }

    private fun startProcessing() {
        val tree = outputTree ?: return
        val inputs = selectedAudios
        val keys = keyMapping.toMap()
        val skipExistingSnapshot = skipExisting
        if (inputs.isEmpty()) return
        cancelled.set(false)
        busy = true
        processing = true
        progress = 0f
        progressText = "0% · 0/${inputs.size}"
        results = emptyList()
        status = "正在启动 $PROCESSING_THREADS 个并行任务…"
        runningTask = controlWorker.submit {
            val weights = inputs.map { (it.sizeBytes ?: UNKNOWN_FILE_WEIGHT).coerceAtLeast(1L) }
            val totalWeight = weights.sum().coerceAtLeast(1L)
            val processedBytes = AtomicLongArray(inputs.size)
            val completedCount = AtomicInteger(0)
            val completedResults = arrayOfNulls<ProcessResult>(inputs.size)
            val progressLock = Any()
            var lastProgressAt = 0L

            fun publishProgress(force: Boolean = false) {
                val snapshot = synchronized(progressLock) {
                    val now = System.nanoTime()
                    if (!force && now - lastProgressAt < PROGRESS_UPDATE_NANOS) return@synchronized null
                    lastProgressAt = now
                    val processed = (0 until inputs.size).sumOf { processedBytes.get(it) }
                    Triple(
                        (processed.toDouble() / totalWeight.toDouble()).coerceIn(0.0, 1.0).toFloat(),
                        completedCount.get(),
                        inputs.size,
                    )
                } ?: return
                runOnUiThread {
                    progress = snapshot.first
                    progressText = "${(snapshot.first * 100).roundToInt()}% · ${snapshot.second}/${snapshot.third}"
                    results = completedResults.filterNotNull()
                    status = "正在并行处理 ${snapshot.second}/${snapshot.third}"
                }
            }

            fun addProgress(index: Int, delta: Long) {
                if (delta <= 0) return
                val limit = weights[index]
                while (true) {
                    val current = processedBytes.get(index)
                    val next = (current + delta).coerceAtMost(limit)
                    if (processedBytes.compareAndSet(index, current, next)) break
                }
                publishProgress()
            }

            try {
                val completion = ExecutorCompletionService<Pair<Int, ProcessResult>>(processingWorkers)
                inputs.forEachIndexed { index, selected ->
                    completion.submit {
                        val result = processor.process(
                            selected = selected,
                            outputTree = tree,
                            keys = keys,
                            cancelled = cancelled,
                            skipExisting = skipExistingSnapshot,
                            onBytesProcessed = { delta -> addProgress(index, delta) },
                        )
                        index to result
                    }
                }

                repeat(inputs.size) {
                    val (index, result) = completion.take().get()
                    completedResults[index] = result
                    processedBytes.set(index, weights[index])
                    completedCount.incrementAndGet()
                    publishProgress(force = true)
                }
            } finally {
                runOnUiThread {
                    processing = false
                    busy = false
                    progress = 1f
                    val completed = completedResults.filterNotNull()
                    val successes = completed.count { it.succeeded }
                    val skipped = completed.count { it.skipped }
                    val failures = completed.count { !it.succeeded && !it.skipped }
                    progressText = if (cancelled.get()) {
                        "已取消 · 已返回 ${completed.size}/${inputs.size}"
                    } else {
                        "100% · ${completed.size}/${inputs.size}"
                    }
                    status = if (cancelled.get()) {
                        "已取消：成功 $successes，跳过 $skipped，失败 $failures"
                    } else {
                        "处理完成：成功 $successes，跳过 $skipped，失败 $failures"
                    }
                }
            }
        }
    }

    private fun queryDisplayName(uri: Uri): String {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) return cursor.getString(0) ?: "密钥文件"
        }
        return uri.lastPathSegment ?: "密钥文件"
    }

    private fun kindLabel(kind: ProcessKind): String = when (kind) {
        ProcessKind.PLAIN -> "[明文复制]"
        ProcessKind.KGG -> "[KGG]"
        ProcessKind.KGM -> "[KGM 系列]"
        ProcessKind.UNKNOWN -> "[无法识别]"
    }

    override fun onDestroy() {
        cancelled.set(true)
        runningTask?.cancel(true)
        keyMapping = emptyMap()
        controlWorker.shutdownNow()
        processingWorkers.shutdownNow()
        super.onDestroy()
    }

    private companion object {
        const val PREFERENCES_NAME = "local_use_consent"
        const val AGREEMENT_KEY = "authorized_local_use_v2"
        const val SKIP_EXISTING_KEY = "skip_existing_output"
        const val UNKNOWN_FILE_WEIGHT = 32L * 1024L * 1024L
        const val PROGRESS_UPDATE_NANOS = 100_000_000L
        val PROCESSING_THREADS = Runtime.getRuntime().availableProcessors().coerceIn(2, 4)
    }
}
