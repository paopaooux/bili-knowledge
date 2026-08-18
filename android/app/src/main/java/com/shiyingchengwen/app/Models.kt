package com.shiyingchengwen.app

data class Inspection(
    val id: String,
    val bvid: String,
    val title: String,
    val uploader: String?,
    val partId: String,
)

data class Stage(
    val name: String,
    val status: String,
    val error: String?,
)

data class JobPart(
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
