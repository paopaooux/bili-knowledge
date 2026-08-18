package com.shiyingchengwen.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class KnowledgeTreeTest {
    @Test
    fun `empty profile root has no readable knowledge`() {
        val root = KnowledgeEntry(
            name = "开放知识库",
            path = "@knowledge-base",
            type = "directory",
            previewable = false,
            children = emptyList(),
        )

        assertFalse(hasReadableKnowledge(listOf(root)))
    }

    @Test
    fun `nested previewable markdown is readable knowledge`() {
        val topic = KnowledgeEntry(
            name = "学习方法.md",
            path = "topics/个人成长/学习方法.md",
            type = "file",
            previewable = true,
            children = emptyList(),
        )
        val root = KnowledgeEntry(
            name = "开放知识库",
            path = "@knowledge-base",
            type = "directory",
            previewable = false,
            children = listOf(
                KnowledgeEntry(
                    name = "个人成长",
                    path = "topics/个人成长",
                    type = "directory",
                    previewable = false,
                    children = listOf(topic),
                )
            ),
        )

        assertTrue(hasReadableKnowledge(listOf(root)))
    }
}
