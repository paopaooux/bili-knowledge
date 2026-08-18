package com.shiyingchengwen.app

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerAddressTest {
    @Test
    fun `adds http scheme to IP and port`() {
        assertEquals("http://192.168.1.20:8000", ServerAddress.normalize("192.168.1.20:8000/"))
    }

    @Test
    fun `keeps an HTTPS server domain`() {
        assertEquals("https://knowledge.example.com", ServerAddress.normalize("https://knowledge.example.com"))
    }

    @Test
    fun `rejects a URL with API path`() {
        assertThrows(IllegalArgumentException::class.java) {
            ServerAddress.normalize("https://knowledge.example.com/api")
        }
    }
}
