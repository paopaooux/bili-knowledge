package com.shiyingchengwen.app

data class Inspection(
    val id: String,
    val bvid: String,
    val title: String,
    val uploader: String?,
    val coverUrl: String?,
    val partId: String,
)

data class Stage(
    val name: String,
    val status: String,
    val error: String?,
)

data class JobPart(
    val id: String,
    val title: String,
    val status: String,
    val stages: List<Stage>,
)

data class Job(
    val id: String,
    val bvid: String,
    val title: String,
    val videoUrl: String?,
    val status: String,
    val error: String?,
    val updatedAt: String,
    val parts: List<JobPart>,
)

data class KnowledgeEntry(
    val name: String,
    val path: String,
    val type: String,
    val previewable: Boolean,
    val children: List<KnowledgeEntry>,
)

data class Health(val ok: Boolean, val worker: String)

class ApiFailure(message: String) : RuntimeException(message)

internal enum class JobFilter(val label: String) {
    All("全部"), Active("处理中"), Completed("已完成"), Failed("失败")
}

internal data class RetryTarget(val partId: String, val stage: String)

internal fun retryTarget(job: Job): RetryTarget? = job.parts.firstNotNullOfOrNull { part ->
    part.stages.firstOrNull { it.status == "failed" }?.let { RetryTarget(part.id, it.name) }
}

internal fun filterJobs(jobs: List<Job>, query: String, filter: JobFilter): List<Job> {
    val normalized = query.trim().lowercase()
    return jobs.filter { job ->
        val statusMatches = when (filter) {
            JobFilter.All -> true
            JobFilter.Active -> job.status in setOf("queued", "running")
            JobFilter.Completed -> job.status == "completed"
            JobFilter.Failed -> job.status in setOf("failed", "cancelled")
        }
        val queryMatches = normalized.isEmpty() ||
            job.title.lowercase().contains(normalized) ||
            job.bvid.lowercase().contains(normalized)
        statusMatches && queryMatches
    }
}

internal fun userFacingError(message: String?): String {
    val value = message?.trim().orEmpty()
    return when {
        value.isEmpty() -> "发生未知错误"
        "无效 JSON" in value || "Expecting ',' delimiter" in value ->
            "知识整理结果格式异常，请从失败阶段重试"
        "401 Unauthorized" in value -> "知识稿模型鉴权失败，请检查服务器 API Key"
        "HTTP Error 412" in value ->
            "Bilibili 拒绝了本次解析，请检查链接或改用完整 BV 链接"
        else -> value.substringBefore("\nFor more information").substringBefore("，输出开头为：")
            .take(300)
    }
}
