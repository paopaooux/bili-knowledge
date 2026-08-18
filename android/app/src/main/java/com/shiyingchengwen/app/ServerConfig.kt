package com.shiyingchengwen.app

import android.content.Context
import java.net.URI

object ServerAddress {
    fun normalize(raw: String): String {
        var value = raw.trim().trimEnd('/')
        if (value.isBlank()) throw IllegalArgumentException("请输入后端地址")
        if (!value.contains("://")) value = "http://$value"
        val uri = runCatching { URI(value) }.getOrNull()
            ?: throw IllegalArgumentException("后端地址格式不正确")
        if (uri.scheme !in setOf("http", "https") || uri.host.isNullOrBlank()) {
            throw IllegalArgumentException("请输入有效的 HTTP 或 HTTPS 地址")
        }
        if (uri.path?.let { it.isNotBlank() && it != "/" } == true || uri.query != null) {
            throw IllegalArgumentException("请填写服务器根地址，不要包含路径或参数")
        }
        return value
    }
}

class ServerConfigStore(context: Context) {
    private val preferences = context.getSharedPreferences("server_config", Context.MODE_PRIVATE)

    fun load(): String? = preferences.getString("base_url", null)

    fun save(baseUrl: String) {
        preferences.edit().putString("base_url", baseUrl).apply()
    }

    fun clear() {
        preferences.edit().remove("base_url").apply()
    }
}
