package com.shiyingchengwen.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.AddCircle
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CenterAlignedTopAppBar
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.shiyingchengwen.app.ui.theme.DeepGreen
import com.shiyingchengwen.app.ui.theme.Line
import com.shiyingchengwen.app.ui.theme.Rust
import com.shiyingchengwen.app.ui.theme.ShiyingChengwenTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ShiyingChengwenTheme { AppRoot() } }
    }
}

private enum class AppTab(val label: String, val icon: ImageVector) {
    Submit("提交任务", Icons.Default.AddCircle),
    Tasks("任务", Icons.Default.History),
    Knowledge("知识库", Icons.Default.VideoLibrary),
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AppRoot() {
    val context = LocalContext.current
    val store = remember { ServerConfigStore(context) }
    var baseUrl by remember { mutableStateOf(store.load()) }
    var tab by rememberSaveable { mutableStateOf(AppTab.Submit) }
    var editingServer by remember { mutableStateOf(false) }

    if (baseUrl == null) {
        ConnectionScreen(initialValue = "", onConnected = {
            store.save(it)
            baseUrl = it
        })
        return
    }

    val api = remember(baseUrl) { ApiClient(baseUrl!!) }
    Scaffold(
        topBar = {
            CenterAlignedTopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        AppLogo(30)
                        Spacer(Modifier.width(9.dp))
                        Text("拾影成文", fontWeight = FontWeight.Bold)
                    }
                },
                actions = {
                    IconButton(onClick = { editingServer = true }) {
                        Icon(Icons.Default.Settings, contentDescription = "连接设置")
                    }
                },
            )
        },
        bottomBar = {
            NavigationBar {
                AppTab.entries.forEach { item ->
                    NavigationBarItem(
                        selected = tab == item,
                        onClick = { tab = item },
                        icon = { Icon(item.icon, contentDescription = null) },
                        label = { Text(item.label) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (tab) {
                AppTab.Submit -> SubmitScreen(api) { tab = AppTab.Tasks }
                AppTab.Tasks -> TasksScreen(api)
                AppTab.Knowledge -> KnowledgeScreen(api)
            }
        }
    }

    if (editingServer) {
        ServerDialog(
            current = baseUrl!!,
            onDismiss = { editingServer = false },
            onSaved = {
                store.save(it)
                baseUrl = it
                editingServer = false
            },
        )
    }
}

@Composable
private fun AppLogo(size: Int) {
    Box(
        Modifier.size(size.dp).clip(RoundedCornerShape((size / 5).dp)).background(Rust),
        contentAlignment = Alignment.Center,
    ) {
        Icon(Icons.Default.VideoLibrary, contentDescription = null, tint = Color(0xFFFFF8ED), modifier = Modifier.size((size * 0.68).dp))
    }
}

@Composable
private fun ConnectionScreen(initialValue: String, onConnected: (String) -> Unit) {
    var address by rememberSaveable { mutableStateOf(initialValue) }
    var error by remember { mutableStateOf<String?>(null) }
    var connecting by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Surface(Modifier.fillMaxSize(), color = DeepGreen) {
        Column(
            Modifier.fillMaxSize().padding(28.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.Center,
        ) {
            AppLogo(64)
            Spacer(Modifier.height(22.dp))
            Text("拾影成文", color = Color.White, fontSize = 31.sp, fontWeight = FontWeight.Bold)
            Text("连接你的知识后端", color = Color(0xFFBDC4B8), fontSize = 15.sp)
            Spacer(Modifier.height(36.dp))
            OutlinedTextField(
                value = address,
                onValueChange = { address = it; error = null },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("后端地址") },
                placeholder = { Text("192.168.1.20:8000") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = {}),
                isError = error != null,
                supportingText = { Text(error ?: "支持 IP:端口 或 https://your-domain.com") },
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                    cursorColor = Rust,
                    focusedBorderColor = Rust,
                    unfocusedBorderColor = Color(0xFFBDC4B8),
                    focusedLabelColor = Rust,
                    unfocusedLabelColor = Color(0xFFBDC4B8),
                    focusedPlaceholderColor = Color(0xFF9CA69A),
                    unfocusedPlaceholderColor = Color(0xFF9CA69A),
                    focusedSupportingTextColor = Color(0xFFBDC4B8),
                    unfocusedSupportingTextColor = Color(0xFFBDC4B8),
                    errorSupportingTextColor = Color(0xFFFFB4AB),
                ),
            )
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    scope.launch {
                        connecting = true
                        error = null
                        try {
                            val normalized = ServerAddress.normalize(address)
                            val health = ApiClient(normalized).health()
                            if (!health.ok) throw ApiFailure("后端健康检查未通过")
                            onConnected(normalized)
                        } catch (failure: Exception) {
                            error = failure.message ?: "连接失败"
                        } finally { connecting = false }
                    }
                },
                enabled = !connecting,
                modifier = Modifier.fillMaxWidth().height(50.dp),
            ) {
                if (connecting) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                else Text("连接并进入")
            }
        }
    }
}

@Composable
private fun ServerDialog(current: String, onDismiss: () -> Unit, onSaved: (String) -> Unit) {
    var address by rememberSaveable { mutableStateOf(current) }
    var error by remember { mutableStateOf<String?>(null) }
    var connecting by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("连接设置") },
        text = {
            Column {
                Text("修改后端 IP、端口或服务器域名。")
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = address,
                    onValueChange = { address = it; error = null },
                    label = { Text("后端地址") },
                    singleLine = true,
                    isError = error != null,
                    supportingText = { error?.let { Text(it) } },
                )
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
        confirmButton = {
            TextButton(
                enabled = !connecting,
                onClick = {
                    scope.launch {
                        connecting = true
                        try {
                            val normalized = ServerAddress.normalize(address)
                            val health = ApiClient(normalized).health()
                            if (!health.ok) throw ApiFailure("后端健康检查未通过")
                            onSaved(normalized)
                        } catch (failure: Exception) {
                            error = failure.message ?: "连接失败"
                        } finally { connecting = false }
                    }
                },
            ) { Text(if (connecting) "连接中…" else "测试并保存") }
        },
    )
}

@Composable
private fun SubmitScreen(api: ApiClient, onSubmitted: () -> Unit) {
    var videoUrl by rememberSaveable { mutableStateOf("") }
    var inspection by remember { mutableStateOf<Inspection?>(null) }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Column(Modifier.fillMaxSize().padding(20.dp).verticalScroll(rememberScrollState())) {
        SectionTitle("提交任务", "支持 Bilibili BV 链接和 b23.tv 手机分享短链")
        OutlinedTextField(
            value = videoUrl,
            onValueChange = { videoUrl = it; inspection = null; message = null },
            modifier = Modifier.fillMaxWidth(),
            label = { Text("Bilibili URL") },
            placeholder = { Text("https://b23.tv/… 或 BV 视频链接") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done),
            singleLine = true,
        )
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = {
                scope.launch {
                    busy = true; message = null
                    try { inspection = api.inspect(videoUrl.trim()) }
                    catch (failure: Exception) { message = userFacingError(failure.message) }
                    finally { busy = false }
                }
            },
            enabled = videoUrl.isNotBlank() && !busy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (busy) "正在解析…" else "解析视频") }

        message?.let { ErrorText(it) }
        inspection?.let { result ->
            Spacer(Modifier.height(22.dp))
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                Column(Modifier.padding(18.dp)) {
                    result.coverUrl?.let { coverUrl ->
                        AsyncImage(
                            model = ImageRequest.Builder(LocalContext.current)
                                .data(coverUrl)
                                .crossfade(true)
                                .addHeader("Referer", "https://www.bilibili.com/")
                                .build(),
                            contentDescription = "视频封面",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.fillMaxWidth().height(180.dp)
                                .clip(RoundedCornerShape(6.dp)),
                        )
                        Spacer(Modifier.height(14.dp))
                    }
                    Text(result.bvid, color = Rust, fontSize = 12.sp)
                    Text(result.title, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                    result.uploader?.let { Text(it, color = MaterialTheme.colorScheme.secondary) }
                    Spacer(Modifier.height(16.dp))
                    Button(
                        onClick = {
                            scope.launch {
                                busy = true; message = null
                                try {
                                    api.createJob(result)
                                    videoUrl = ""; inspection = null
                                    onSubmitted()
                                } catch (failure: Exception) { message = userFacingError(failure.message) }
                                finally { busy = false }
                            }
                        },
                        enabled = !busy,
                        modifier = Modifier.fillMaxWidth(),
                    ) { Text(if (busy) "正在提交…" else "生成知识文档") }
                }
            }
        }
    }
}

@Composable
private fun TasksScreen(api: ApiClient) {
    var jobs by remember { mutableStateOf<List<Job>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    val expanded = remember { mutableStateMapOf<String, Boolean>() }
    val retrying = remember { mutableStateMapOf<String, Boolean>() }
    var query by rememberSaveable { mutableStateOf("") }
    var filter by rememberSaveable { mutableStateOf(JobFilter.All) }
    var refreshKey by remember { mutableIntStateOf(0) }
    val scope = rememberCoroutineScope()
    val visibleJobs = filterJobs(jobs, query, filter)

    LaunchedEffect(api, refreshKey) {
        while (true) {
            try { jobs = api.jobs(); error = null }
            catch (failure: Exception) { error = failure.message }
            finally { loading = false }
            delay(if (jobs.any { it.status == "queued" || it.status == "running" }) 3_000 else 15_000)
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(20.dp, 16.dp, 12.dp, 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.weight(1f)) { SectionTitle("任务", "按最后更新时间降序") }
            IconButton(onClick = { refreshKey += 1 }) { Icon(Icons.Default.Refresh, "刷新") }
        }
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
            label = { Text("搜索任务") },
            placeholder = { Text("视频标题或 BV 号") },
            singleLine = true,
        )
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            JobFilter.entries.forEach { item ->
                FilterChip(
                    selected = filter == item,
                    onClick = { filter = item },
                    label = { Text(item.label) },
                )
            }
        }
        if (loading) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        else if (jobs.isEmpty()) EmptyState("还没有任务", "提交第一个视频后，进度会显示在这里。")
        else if (visibleJobs.isEmpty()) EmptyState("没有匹配任务", "换个关键词或状态试试。")
        else LazyColumn(
            contentPadding = PaddingValues(16.dp, 6.dp, 16.dp, 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            error?.let { item { ErrorText(it) } }
            items(visibleJobs, key = { it.id }) { job ->
                JobCard(
                    job = job,
                    expanded = expanded[job.id] == true,
                    retrying = retrying[job.id] == true,
                    onToggle = { expanded[job.id] = expanded[job.id] != true },
                    onRetry = {
                        retryTarget(job)?.let { target ->
                            scope.launch {
                                retrying[job.id] = true
                                try {
                                    val updated = api.retry(job.id, target.partId, target.stage)
                                    jobs = jobs.map { if (it.id == updated.id) updated else it }
                                    error = null
                                } catch (failure: Exception) {
                                    error = userFacingError(failure.message)
                                } finally {
                                    retrying.remove(job.id)
                                }
                            }
                        }
                    },
                )
            }
        }
    }
}

@Composable
private fun JobCard(
    job: Job,
    expanded: Boolean,
    retrying: Boolean,
    onToggle: () -> Unit,
    onRetry: () -> Unit,
) {
    val context = LocalContext.current
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onToggle),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Text(job.bvid, color = Rust, fontSize = 11.sp)
                    Text(job.title, fontWeight = FontWeight.Bold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text("最后更新：${formatTime(job.updatedAt)}", fontSize = 11.sp, color = MaterialTheme.colorScheme.secondary)
                }
                StatusChip(job.status)
            }
            if (expanded) {
                job.videoUrl?.let { url ->
                    TextButton(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }) {
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.size(16.dp))
                        Spacer(Modifier.width(5.dp))
                        Text("打开原视频")
                    }
                }
                job.error?.let { ErrorText(userFacingError(it)) }
                retryTarget(job)?.let { target ->
                    OutlinedButton(
                        onClick = onRetry,
                        enabled = !retrying,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        if (retrying) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                        }
                        Text(if (retrying) "正在重新排队…" else "从${stageLabel(target.stage)}阶段重试")
                    }
                }
                job.parts.forEach { part ->
                    HorizontalDivider(Modifier.padding(vertical = 10.dp), color = Line)
                    Text(part.title, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(8.dp))
                    part.stages.forEach { stage -> StageRow(stage, stage.error != job.error) }
                }
            }
        }
    }
}

@Composable
private fun StageRow(stage: Stage, showError: Boolean = true) {
    val label = stageLabel(stage.name)
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        val color = when (stage.status) {
            "completed", "skipped" -> MaterialTheme.colorScheme.secondary
            "failed" -> MaterialTheme.colorScheme.error
            "running" -> Color(0xFFD49A32)
            else -> MaterialTheme.colorScheme.outline
        }
        Box(Modifier.size(9.dp).clip(CircleShape).background(color))
        Spacer(Modifier.width(9.dp))
        Text(label, Modifier.weight(1f), fontSize = 13.sp)
        Text(statusLabel(stage.status), color = color, fontSize = 12.sp)
    }
    if (showError) stage.error?.let {
        Text(userFacingError(it), color = MaterialTheme.colorScheme.error, fontSize = 11.sp, modifier = Modifier.padding(start = 18.dp))
    }
}

private fun stageLabel(stage: String) = mapOf(
        "parse" to "解析", "acquire" to "获取素材", "transcribe" to "转写",
        "generate" to "生成知识稿", "organize" to "归档知识", "publish" to "发布",
    )[stage] ?: stage

@Composable
private fun KnowledgeScreen(api: ApiClient) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var files by remember { mutableStateOf<List<KnowledgeEntry>>(emptyList()) }
    var selected by remember { mutableStateOf<KnowledgeEntry?>(null) }
    var content by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshKey by remember { mutableIntStateOf(0) }
    val expandedDirectories = remember { mutableStateMapOf<String, Boolean>() }
    var refactoring by remember { mutableStateOf(false) }
    var showRefactorConfirm by remember { mutableStateOf(false) }
    val pdfLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/pdf")
    ) { uri ->
        val entry = selected
        val markdown = content
        if (uri != null && entry != null && markdown != null) {
            scope.launch {
                try {
                    withContext(Dispatchers.IO) {
                        writeMarkdownPdf(context, uri, entry.name, markdown)
                    }
                    Toast.makeText(context, "PDF 已保存", Toast.LENGTH_SHORT).show()
                } catch (failure: Exception) {
                    Toast.makeText(
                        context,
                        "PDF 保存失败：${failure.message ?: "未知错误"}",
                        Toast.LENGTH_LONG,
                    ).show()
                }
            }
        }
    }

    LaunchedEffect(api, refreshKey) {
        loading = true
        try {
            files = api.knowledgeFiles(); error = null
            expandedDirectories.clear()
            files.filter { it.type == "directory" }.forEach { expandedDirectories[it.path] = true }
        }
        catch (failure: Exception) { error = failure.message }
        finally { loading = false }
    }
    LaunchedEffect(api, selected?.path) {
        val entry = selected ?: return@LaunchedEffect
        content = null; error = null
        try { content = api.knowledgeFile(entry.path) }
        catch (failure: Exception) { error = failure.message }
    }

    if (showRefactorConfirm && selected != null) {
        AlertDialog(
            onDismissRequest = { if (!refactoring) showRefactorConfirm = false },
            title = { Text("确认整理合并") },
            text = { Text("AI 会把相似内容合并成更完整的讨论，并重新组织知识层级，让主题更易读。") },
            confirmButton = {
                TextButton(enabled = !refactoring, onClick = {
                    val entry = selected ?: return@TextButton
                    showRefactorConfirm = false
                    refactoring = true
                    scope.launch {
                        try { content = api.refactorKnowledgeFile(entry.path); Toast.makeText(context, "已整理合并", Toast.LENGTH_SHORT).show(); refreshKey += 1 }
                        catch (failure: Exception) { error = failure.message }
                        finally { refactoring = false }
                    }
                }) { Text("确定") }
            },
            dismissButton = { TextButton(enabled = !refactoring, onClick = { showRefactorConfirm = false }) { Text("取消") } },
        )
    }

    if (selected != null) {
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { selected = null; content = null }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回知识库") }
                Column(Modifier.weight(1f)) {
                    Text(selected!!.name, fontWeight = FontWeight.Bold)
                    Text(selected!!.path, fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                IconButton(
                    enabled = content != null,
                    onClick = {
                        val filename = selected!!.name.removeSuffix(".md") + ".pdf"
                        pdfLauncher.launch(filename)
                    },
                ) { Icon(Icons.Default.Download, "导出 PDF") }
                if (selected!!.name.endsWith(".md", ignoreCase = true)) {
                    TextButton(enabled = !refactoring, onClick = { showRefactorConfirm = true }) {
                        Text(if (refactoring) "整理中…" else "整理合并")
                    }
                }
            }
            HorizontalDivider(color = Line)
            error?.let { ErrorText(it) }
            if (content == null && error == null) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            else content?.let { MarkdownPreview(it) }
        }
        return
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().padding(20.dp, 16.dp, 12.dp, 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.weight(1f)) { SectionTitle("知识库", "仅浏览已归档的 Markdown") }
            IconButton(onClick = { refreshKey += 1 }) { Icon(Icons.Default.Refresh, "刷新") }
        }
        error?.let { ErrorText(it) }
        if (loading) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        else if (!hasReadableKnowledge(files)) EmptyState("知识库还是空的", "任务归档后，主题文件会显示在这里。")
        else LazyColumn(contentPadding = PaddingValues(12.dp, 4.dp, 12.dp, 24.dp)) {
            items(visibleKnowledge(files, expandedDirectories), key = { it.first.path }) { (entry, depth) ->
                KnowledgeRow(entry, depth, expandedDirectories[entry.path] == true) {
                    if (entry.type == "directory") expandedDirectories[entry.path] = expandedDirectories[entry.path] != true
                    else if (entry.previewable) selected = entry
                }
            }
        }
    }
}

@Composable
private fun KnowledgeRow(entry: KnowledgeEntry, depth: Int, expanded: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(enabled = entry.type == "directory" || entry.previewable, onClick = onClick)
            .padding(start = (depth * 18).dp, top = 10.dp, end = 8.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (entry.type == "directory") Icon(if (expanded) Icons.Default.ExpandMore else Icons.Default.ChevronRight, "展开/收起")
        else Spacer(Modifier.width(24.dp))
        Icon(
            if (entry.type == "directory") Icons.Default.Folder else Icons.AutoMirrored.Filled.InsertDriveFile,
            contentDescription = null,
            tint = if (entry.type == "directory") MaterialTheme.colorScheme.secondary else Rust,
        )
        Spacer(Modifier.width(10.dp))
        Text(entry.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

private data class MarkdownListItem(val id: String, val text: String, val children: MutableList<MarkdownListItem>)
private sealed interface MarkdownBlock { data class Line(val text: String) : MarkdownBlock; data class Item(val item: MarkdownListItem) : MarkdownBlock }

private fun parseMarkdownBlocks(markdown: String): List<MarkdownBlock> {
    val blocks = mutableListOf<MarkdownBlock>(); val stack = mutableListOf<Pair<Int, MarkdownListItem>>(); var sequence = 0
    markdown.lines().forEach { raw ->
        val trimmed = raw.trimEnd(); val match = Regex("^(\\s*)[-*+]\\s+(.*)$").find(trimmed)
        if (match == null) { stack.clear(); blocks += MarkdownBlock.Line(trimmed); return@forEach }
        val indent = match.groupValues[1].length; val node = MarkdownListItem("item-${sequence++}", match.groupValues[2], mutableListOf())
        while (stack.isNotEmpty() && indent <= stack.last().first) stack.removeAt(stack.lastIndex)
        if (stack.isEmpty()) blocks += MarkdownBlock.Item(node)
        if (stack.isNotEmpty()) stack.last().second.children += node
        stack += indent to node
    }; return blocks
}

@Composable
private fun MarkdownList(item: MarkdownListItem, depth: Int = 0) {
    var expanded by remember(item.id) { mutableStateOf(false) }
    Column(Modifier.padding(start = (depth * 16).dp)) {
        Row(Modifier.fillMaxWidth().clickable(enabled = item.children.isNotEmpty()) { expanded = !expanded }.padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
            if (item.children.isNotEmpty()) Icon(if (expanded) Icons.Default.ExpandMore else Icons.Default.ChevronRight, if (expanded) "收起" else "展开", Modifier.size(20.dp), tint = Rust)
            else Spacer(Modifier.width(20.dp))
            MarkdownInlineText("• ${item.text}")
        }
        if (expanded) item.children.forEach { MarkdownList(it, depth + 1) }
    }
}

@Composable
private fun MarkdownInlineText(text: String, modifier: Modifier = Modifier) {
    val pattern = remember(text) { Regex("(\\*\\*|__)(.+?)\\1") }
    val value = remember(text) {
        buildAnnotatedString {
            var cursor = 0
            pattern.findAll(text).forEach { match ->
                append(text.substring(cursor, match.range.first).replace(Regex("`([^`]*)`"), "$1"))
                withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(match.groupValues[2]) }
                cursor = match.range.last + 1
            }
            append(text.substring(cursor).replace(Regex("`([^`]*)`"), "$1"))
        }
    }
    Text(value, modifier = modifier, lineHeight = 22.sp)
}

@Composable
private fun MarkdownPreview(markdown: String) {
    val blocks = remember(markdown) { parseMarkdownBlocks(markdown) }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    var trackHeightPx by remember { mutableIntStateOf(0) }
    val thumbHeightPx = 52.dp
    val progress by remember(blocks.size) {
        derivedStateOf {
            val visibleCount = listState.layoutInfo.visibleItemsInfo.size.coerceAtLeast(1)
            val maxFirstIndex = (blocks.size - visibleCount).coerceAtLeast(1)
            listState.firstVisibleItemIndex.toFloat() / maxFirstIndex.toFloat()
        }
    }

    fun jumpTo(position: Offset, trackHeight: Int, thumbHeight: Float) {
        if (blocks.size <= 1 || trackHeight <= 0) return
        val usableHeight = (trackHeight - thumbHeight).coerceAtLeast(1f)
        val fraction = ((position.y - thumbHeight / 2f) / usableHeight).coerceIn(0f, 1f)
        val visibleCount = listState.layoutInfo.visibleItemsInfo.size.coerceAtLeast(1)
        val maxFirstIndex = (blocks.size - visibleCount).coerceAtLeast(0)
        scope.launch { listState.scrollToItem((fraction * maxFirstIndex).roundToInt()) }
    }

    Box(Modifier.fillMaxHeight()) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize().padding(end = 18.dp),
            contentPadding = PaddingValues(20.dp, 12.dp, 8.dp, 32.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(blocks) { block ->
                when (block) {
                    is MarkdownBlock.Item -> MarkdownList(block.item)
                    is MarkdownBlock.Line -> { val line = block.text; when {
                    line.startsWith("# ") -> Text(line.drop(2), fontSize = 25.sp, fontWeight = FontWeight.Bold)
                    line.startsWith("## ") -> Text(line.drop(3), fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 12.dp))
                    line.startsWith("### ") -> Text(line.drop(4), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
                    line.trimStart().startsWith("- ") -> MarkdownInlineText("• ${line.trimStart().drop(2)}", Modifier.padding(start = ((line.length - line.trimStart().length) * 4).dp))
                    line.isBlank() -> Spacer(Modifier.height(5.dp))
                    else -> MarkdownInlineText(line)
                    } }
                }
            }
        }
        if (blocks.size > 1) {
            val thumbPx = with(androidx.compose.ui.platform.LocalDensity.current) {
                thumbHeightPx.toPx()
            }
            Box(
                Modifier.align(Alignment.CenterEnd).fillMaxHeight().width(28.dp)
                    .padding(vertical = 8.dp)
                    .onSizeChanged { trackHeightPx = it.height }
                    .pointerInput(blocks.size, trackHeightPx) {
                        detectTapGestures { jumpTo(it, trackHeightPx, thumbPx) }
                    }
                    .pointerInput(blocks.size, trackHeightPx) {
                        detectDragGestures(
                            onDragStart = { jumpTo(it, trackHeightPx, thumbPx) },
                            onDrag = { change, _ -> jumpTo(change.position, trackHeightPx, thumbPx) },
                        )
                    },
            ) {
                Box(
                    Modifier.align(Alignment.TopCenter).fillMaxHeight().width(3.dp)
                        .background(Line.copy(alpha = 0.55f), CircleShape)
                )
                val maxOffset = (trackHeightPx - thumbPx).coerceAtLeast(0f)
                Box(
                    Modifier.align(Alignment.TopCenter)
                        .offset { IntOffset(0, (maxOffset * progress.coerceIn(0f, 1f)).roundToInt()) }
                        .width(9.dp).height(thumbHeightPx)
                        .background(Rust.copy(alpha = 0.78f), CircleShape)
                )
            }
        }
    }
}

@Composable
private fun SectionTitle(title: String, subtitle: String) {
    Column {
        Text(title, fontSize = 25.sp, fontWeight = FontWeight.Bold)
        Text(subtitle, color = MaterialTheme.colorScheme.secondary, fontSize = 13.sp)
    }
}

@Composable
private fun ErrorText(message: String) {
    Text(
        message,
        color = MaterialTheme.colorScheme.error,
        modifier = Modifier.fillMaxWidth().padding(vertical = 10.dp).background(Color(0xFFF9E8E3), RoundedCornerShape(4.dp)).padding(10.dp),
        fontSize = 13.sp,
    )
}

@Composable
private fun EmptyState(title: String, detail: String) {
    Column(Modifier.fillMaxSize().padding(30.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Icon(Icons.Default.Description, null, Modifier.size(42.dp), tint = MaterialTheme.colorScheme.outline)
        Spacer(Modifier.height(12.dp))
        Text(title, fontWeight = FontWeight.Bold)
        Text(detail, color = MaterialTheme.colorScheme.secondary, fontSize = 13.sp)
    }
}

@Composable
private fun StatusChip(status: String) {
    val color = when (status) {
        "completed" -> MaterialTheme.colorScheme.secondary
        "failed", "cancelled" -> MaterialTheme.colorScheme.error
        "running", "queued" -> Color(0xFF8A651E)
        else -> MaterialTheme.colorScheme.outline
    }
    Text(
        statusLabel(status),
        color = color,
        fontSize = 11.sp,
        modifier = Modifier.background(color.copy(alpha = 0.12f), CircleShape).padding(horizontal = 9.dp, vertical = 5.dp),
    )
}

private fun statusLabel(status: String) = mapOf(
    "pending" to "等待", "queued" to "排队", "running" to "处理中",
    "completed" to "完成", "failed" to "失败", "cancelled" to "已取消", "skipped" to "已复用",
)[status] ?: status

private fun visibleKnowledge(entries: List<KnowledgeEntry>, expanded: Map<String, Boolean>, depth: Int = 0): List<Pair<KnowledgeEntry, Int>> =
    entries.flatMap { entry ->
        listOf(entry to depth) + if (entry.type == "directory" && expanded[entry.path] == true)
            visibleKnowledge(entry.children, expanded, depth + 1) else emptyList()
    }

internal fun hasReadableKnowledge(entries: List<KnowledgeEntry>): Boolean =
    entries.any { entry ->
        (entry.type == "file" && entry.previewable) || hasReadableKnowledge(entry.children)
    }

private fun formatTime(value: String): String = runCatching {
    OffsetDateTime.parse(value).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
}.getOrDefault(value)
