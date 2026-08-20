package com.shiyingchengwen.app

import android.content.Context
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.pdf.PdfDocument
import android.net.Uri
import kotlin.math.max

internal fun writeMarkdownPdf(context: Context, uri: Uri, title: String, markdown: String) {
    val document = PdfDocument()
    val pageWidth = 595
    val pageHeight = 842
    val margin = 44f
    val contentWidth = pageWidth - margin * 2
    val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = android.graphics.Color.rgb(40, 39, 35) }
    var pageNumber = 0
    var page = document.startPage(
        PdfDocument.PageInfo.Builder(pageWidth, pageHeight, ++pageNumber).create()
    )
    var canvas = page.canvas
    var y = margin

    fun newPage() {
        document.finishPage(page)
        page = document.startPage(
            PdfDocument.PageInfo.Builder(pageWidth, pageHeight, ++pageNumber).create()
        )
        canvas = page.canvas
        y = margin
    }

    fun drawLine(text: String, size: Float, bold: Boolean, indent: Float = 0f) {
        paint.textSize = size
        paint.typeface = if (bold) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        val lineHeight = size * 1.55f
        val availableWidth = max(80f, contentWidth - indent)
        val wrapped = wrapPdfText(text, paint, availableWidth)
        for (line in wrapped.ifEmpty { listOf("") }) {
            if (y + lineHeight > pageHeight - margin) newPage()
            if (line.isNotEmpty()) canvas.drawText(line, margin + indent, y + size, paint)
            y += lineHeight
        }
    }

    drawLine(title.removeSuffix(".md"), 22f, true)
    y += 10f
    for (raw in markdown.lines()) {
        val trimmed = raw.trimEnd()
        when {
            trimmed.startsWith("# ") -> {
                y += 8f
                drawLine(trimmed.drop(2), 21f, true)
            }
            trimmed.startsWith("## ") -> {
                y += 7f
                drawLine(trimmed.drop(3), 17f, true)
            }
            trimmed.startsWith("### ") -> {
                y += 5f
                drawLine(trimmed.drop(4), 14f, true)
            }
            trimmed.trimStart().startsWith("- ") ->
                drawLine("• ${trimmed.trimStart().drop(2)}", 11f, false, 12f)
            trimmed.isBlank() -> y += 8f
            else -> drawLine(trimmed, 11f, false)
        }
    }
    document.finishPage(page)
    try {
        context.contentResolver.openOutputStream(uri)?.use(document::writeTo)
            ?: error("无法打开保存位置")
    } finally {
        document.close()
    }
}

internal fun wrapPdfText(text: String, paint: Paint, maxWidth: Float): List<String> {
    if (text.isEmpty()) return emptyList()
    val result = mutableListOf<String>()
    var start = 0
    while (start < text.length) {
        var end = paint.breakText(text, start, text.length, true, maxWidth, null) + start
        if (end <= start) end = start + 1
        result += text.substring(start, end)
        start = end
    }
    return result
}
