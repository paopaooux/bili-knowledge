package com.shiyingchengwen.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Rust = Color(0xFFC75B38)
val DeepGreen = Color(0xFF253027)
val Sage = Color(0xFF78866B)
val Paper = Color(0xFFFBFAF6)
val Canvas = Color(0xFFF4F0E8)
val Ink = Color(0xFF282622)
val Line = Color(0xFFD9D2C5)

private val AppColors = lightColorScheme(
    primary = Rust,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFF7E1D8),
    onPrimaryContainer = Color(0xFF6F2817),
    secondary = Sage,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFE7EEE2),
    background = Canvas,
    onBackground = Ink,
    surface = Paper,
    onSurface = Ink,
    outline = Line,
    error = Color(0xFFA33D2B),
)

@Composable
fun ShiyingChengwenTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = AppColors, content = content)
}
