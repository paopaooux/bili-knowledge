package com.shiyingchengwen.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ApiClient(private val baseUrl: String) {
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .build()

    suspend fun health(): Health = objectRequest("/api/health") {
        Health(it.optBoolean("ok"), it.optString("worker"))
    }

    suspend fun inspect(videoUrl: String): Inspection = objectRequest(
        "/api/videos/inspect",
        method = "POST",
        body = JSONObject().put("url", videoUrl).toString(),
    ) { value ->
        val parts = value.getJSONArray("parts")
        if (parts.length() == 0) throw ApiFailure("视频没有可处理的分 P")
        Inspection(
            id = value.getString("id"),
            bvid = value.getString("bvid"),
            title = value.getString("title"),
            uploader = value.optNullableString("uploader"),
            coverUrl = value.optNullableString("cover_url"),
            partId = parts.getJSONObject(0).getString("id"),
        )
    }

    suspend fun createJob(inspection: Inspection): Job = objectRequest(
        "/api/jobs",
        method = "POST",
        body = JSONObject()
            .put("video_id", inspection.id)
            .put("part_ids", JSONArray().put(inspection.partId))
            .toString(),
        parser = ::parseJob,
    )

    suspend fun jobs(): List<Job> = arrayRequest("/api/jobs?compact=true") { array ->
        List(array.length()) { parseJob(array.getJSONObject(it)) }
    }

    suspend fun retry(jobId: String, partId: String, stage: String): Job = objectRequest(
        "/api/jobs/$jobId/retry",
        method = "POST",
        body = JSONObject().put("part_id", partId).put("stage", stage).toString(),
        parser = ::parseJob,
    )

    suspend fun knowledgeFiles(): List<KnowledgeEntry> = arrayRequest("/api/knowledge/files") {
        array -> List(array.length()) { parseKnowledgeEntry(array.getJSONObject(it)) }
    }

    suspend fun knowledgeFile(path: String): String {
        val url = (baseUrl + "/api/knowledge/file").toHttpUrl().newBuilder()
            .addQueryParameter("path", path)
            .build()
        return execute(Request.Builder().url(url).get().build())
    }

    suspend fun refactorKnowledgeFile(path: String): String {
        val url = (baseUrl + "/api/knowledge/file/refactor").toHttpUrl().newBuilder()
            .addQueryParameter("path", path)
            .build()
        return execute(Request.Builder().url(url).post("{}".toRequestBody(jsonType)).build())
    }

    private suspend fun <T> objectRequest(
        path: String,
        method: String = "GET",
        body: String? = null,
        parser: (JSONObject) -> T,
    ): T = JSONObject(request(path, method, body)).let(parser)

    private suspend fun <T> arrayRequest(path: String, parser: (JSONArray) -> T): T =
        JSONArray(request(path)).let(parser)

    private suspend fun request(path: String, method: String = "GET", body: String? = null): String {
        val builder = Request.Builder().url(baseUrl + path)
        if (method == "POST") builder.post((body ?: "{}").toRequestBody(jsonType)) else builder.get()
        return execute(builder.build())
    }

    private suspend fun execute(request: Request): String = withContext(Dispatchers.IO) {
        try {
            client.newCall(request).execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detail = runCatching { JSONObject(text).optString("detail") }.getOrNull()
                    throw ApiFailure(detail?.takeIf { it.isNotBlank() } ?: "请求失败 (${response.code})")
                }
                text
            }
        } catch (error: ApiFailure) {
            throw error
        } catch (error: Exception) {
            throw ApiFailure("无法连接后端：${error.message ?: "网络异常"}")
        }
    }

    private fun parseJob(value: JSONObject): Job {
        val parts = value.optJSONArray("parts") ?: JSONArray()
        return Job(
            id = value.getString("id"),
            bvid = value.getString("bvid"),
            title = value.getString("video_title"),
            videoUrl = value.optNullableString("video_url"),
            status = value.getString("status"),
            error = value.optNullableString("error"),
            updatedAt = value.optString("updated_at", value.optString("created_at")),
            parts = List(parts.length()) { index ->
                val part = parts.getJSONObject(index)
                val stages = part.optJSONArray("stages") ?: JSONArray()
                JobPart(
                    id = part.getString("id"),
                    title = part.getString("title"),
                    status = part.getString("status"),
                    stages = List(stages.length()) { stageIndex ->
                        val stage = stages.getJSONObject(stageIndex)
                        Stage(
                            name = stage.getString("stage"),
                            status = stage.getString("status"),
                            error = stage.optNullableString("error"),
                        )
                    },
                )
            },
        )
    }

    private fun parseKnowledgeEntry(value: JSONObject): KnowledgeEntry {
        val children = value.optJSONArray("children") ?: JSONArray()
        return KnowledgeEntry(
            name = value.getString("name"),
            path = value.getString("path"),
            type = value.getString("type"),
            previewable = value.optBoolean("previewable"),
            children = List(children.length()) { parseKnowledgeEntry(children.getJSONObject(it)) },
        )
    }
}

private fun JSONObject.optNullableString(key: String): String? =
    if (isNull(key)) null else optString(key).takeIf { it.isNotBlank() }
