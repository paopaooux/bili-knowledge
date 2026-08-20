package com.shiyingchengwen.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TaskUiTest {
    private fun job(status: String, title: String = "测试视频", error: String? = null) = Job(
        id = status,
        bvid = "BV-$status",
        title = title,
        videoUrl = null,
        status = status,
        error = error,
        updatedAt = "2026-01-01T00:00:00Z",
        parts = listOf(
            JobPart(
                id = "part-$status",
                title = "P1",
                status = status,
                stages = listOf(Stage("organize", status, error)),
            )
        ),
    )

    @Test
    fun filtersByStatusAndSearchText() {
        val jobs = listOf(job("running"), job("completed", "完成视频"), job("failed"))

        assertEquals(listOf("running"), filterJobs(jobs, "", JobFilter.Active).map { it.status })
        assertEquals(listOf("completed"), filterJobs(jobs, "完成", JobFilter.All).map { it.status })
        assertEquals(listOf("failed"), filterJobs(jobs, "BV-FAILED", JobFilter.Failed).map { it.status })
    }

    @Test
    fun findsFailedStageForRetry() {
        assertEquals(RetryTarget("part-failed", "organize"), retryTarget(job("failed")))
        assertNull(retryTarget(job("completed")))
    }

    @Test
    fun hidesRawJsonFromModelErrors() {
        val raw = "知识整理返回了无效 JSON：Expecting ',' delimiter，输出开头为：{\"updates\":["

        assertEquals("知识整理结果格式异常，请从失败阶段重试", userFacingError(raw))
    }
}
