package com.shiyingchengwen.app

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.shiyingchengwen.app.ui.theme.DeepGreen
import com.shiyingchengwen.app.ui.theme.Line
import com.shiyingchengwen.app.ui.theme.Rust
import com.shiyingchengwen.app.ui.theme.ShiyingChengwenTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

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
                    catch (failure: Exception) { message = failure.message }
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
                                } catch (failure: Exception) { message = failure.message }
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
    var refreshKey by remember { mutableIntStateOf(0) }

    LaunchedEffect(api, refreshKey) {
        while (true) {
            try { jobs = api.jobs(); error = null }
            catch (failure: Exception) { error = failure.message }
            finally { loading = false }
            delay(3_000)
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
        if (loading) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        else if (jobs.isEmpty()) EmptyState("还没有任务", "提交第一个视频后，进度会显示在这里。")
        else LazyColumn(
            contentPadding = PaddingValues(16.dp, 6.dp, 16.dp, 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            error?.let { item { ErrorText(it) } }
            items(jobs, key = { it.id }) { job ->
                JobCard(job, expanded[job.id] == true) { expanded[job.id] = expanded[job.id] != true }
            }
        }
    }
}

@Composable
private fun JobCard(job: Job, expanded: Boolean, onToggle: () -> Unit) {
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
                job.error?.let { ErrorText(it) }
                job.parts.forEach { part ->
                    HorizontalDivider(Modifier.padding(vertical = 10.dp), color = Line)
                    Text(part.title, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(8.dp))
                    part.stages.forEach { stage -> StageRow(stage) }
                }
            }
        }
    }
}

@Composable
private fun StageRow(stage: Stage) {
    val label = mapOf(
        "parse" to "解析", "acquire" to "获取素材", "transcribe" to "转写",
        "generate" to "生成知识稿", "organize" to "归档知识", "publish" to "发布",
    )[stage.name] ?: stage.name
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
    stage.error?.let { Text(it, color = MaterialTheme.colorScheme.error, fontSize = 11.sp, modifier = Modifier.padding(start = 18.dp)) }
}

@Composable
private fun KnowledgeScreen(api: ApiClient) {
    var files by remember { mutableStateOf<List<KnowledgeEntry>>(emptyList()) }
    var selected by remember { mutableStateOf<KnowledgeEntry?>(null) }
    var content by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshKey by remember { mutableIntStateOf(0) }

    LaunchedEffect(api, refreshKey) {
        loading = true
        try { files = api.knowledgeFiles(); error = null }
        catch (failure: Exception) { error = failure.message }
        finally { loading = false }
    }
    LaunchedEffect(api, selected?.path) {
        val entry = selected ?: return@LaunchedEffect
        content = null; error = null
        try { content = api.knowledgeFile(entry.path) }
        catch (failure: Exception) { error = failure.message }
    }

    if (selected != null) {
        Column(Modifier.fillMaxSize()) {
            Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { selected = null; content = null }) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回知识库") }
                Column(Modifier.weight(1f)) {
                    Text(selected!!.name, fontWeight = FontWeight.Bold)
                    Text(selected!!.path, fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
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
            items(flattenKnowledge(files), key = { it.first.path }) { (entry, depth) ->
                KnowledgeRow(entry, depth) { if (entry.type == "file" && entry.previewable) selected = entry }
            }
        }
    }
}

@Composable
private fun KnowledgeRow(entry: KnowledgeEntry, depth: Int, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(enabled = entry.type == "file" && entry.previewable, onClick = onClick)
            .padding(start = (depth * 18).dp, top = 10.dp, end = 8.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            if (entry.type == "directory") Icons.Default.Folder else Icons.AutoMirrored.Filled.InsertDriveFile,
            contentDescription = null,
            tint = if (entry.type == "directory") MaterialTheme.colorScheme.secondary else Rust,
        )
        Spacer(Modifier.width(10.dp))
        Text(entry.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
private fun MarkdownPreview(markdown: String) {
    val lines = remember(markdown) { markdown.lines() }
    LazyColumn(
        modifier = Modifier.fillMaxHeight(),
        contentPadding = PaddingValues(20.dp, 12.dp, 20.dp, 32.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items(lines) { raw ->
            val line = raw.trimEnd()
            when {
                line.startsWith("# ") -> Text(line.drop(2), fontSize = 25.sp, fontWeight = FontWeight.Bold)
                line.startsWith("## ") -> Text(line.drop(3), fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 12.dp))
                line.startsWith("### ") -> Text(line.drop(4), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 8.dp))
                line.trimStart().startsWith("- ") -> Text("• ${line.trimStart().drop(2)}", lineHeight = 22.sp, modifier = Modifier.padding(start = ((line.length - line.trimStart().length) * 4).dp))
                line.isBlank() -> Spacer(Modifier.height(5.dp))
                else -> Text(line, lineHeight = 22.sp)
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

private fun flattenKnowledge(entries: List<KnowledgeEntry>, depth: Int = 0): List<Pair<KnowledgeEntry, Int>> =
    entries.flatMap { entry -> listOf(entry to depth) + flattenKnowledge(entry.children, depth + 1) }

internal fun hasReadableKnowledge(entries: List<KnowledgeEntry>): Boolean =
    entries.any { entry ->
        (entry.type == "file" && entry.previewable) || hasReadableKnowledge(entry.children)
    }

private fun formatTime(value: String): String = runCatching {
    OffsetDateTime.parse(value).atZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
}.getOrDefault(value)
