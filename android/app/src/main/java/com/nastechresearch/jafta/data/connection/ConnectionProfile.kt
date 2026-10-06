// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026
// https://github.com/nastechresearch/Jafta


package com.nastechresearch.jafta.data.connection

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.util.UUID

@Serializable
data class ConnectionProfile(
    @SerialName("id") val id: String = UUID.randomUUID().toString(),
    @SerialName("name") val name: String,
    @SerialName("baseUrl") val baseUrl: String,
    @SerialName("username") val username: String = "opencode",
    @SerialName("password") val password: String? = null,
    /** Bearer credential used by Nastech-Agent's API server. */
    @SerialName("apiKey") val apiKey: String? = null,
    @SerialName("dashboardUrl") val dashboardUrl: String? = null,
    /** Connection protocol owned by the remote runtime. Defaults to OpenCode for old profiles. */
    @SerialName("runtime") val runtime: String = "opencode",
    @SerialName("allowInsecureLan") val allowInsecureLan: Boolean = false,
    @SerialName("pinSha256") val pinSha256: String? = null,
) {
    override fun toString(): String =
        "ConnectionProfile(id=$id, name=$name, baseUrl=$baseUrl, username=$username, password=<redacted>, apiKey=<redacted>, runtime=$runtime, allowInsecureLan=$allowInsecureLan, pinSha256=<redacted>)"
}

object ConnectionProfileCodec {
    private val json =
        Json {
            ignoreUnknownKeys = true
            isLenient = true
            encodeDefaults = true
        }

    fun encode(profiles: List<ConnectionProfile>): String = json.encodeToString(profiles)

    fun decode(jsonString: String): List<ConnectionProfile> {
        if (jsonString.isBlank()) return emptyList()
        return json.decodeFromString<List<ConnectionProfile>>(jsonString)
    }
}
