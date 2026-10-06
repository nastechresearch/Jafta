// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026
// https://github.com/nastechresearch/Jafta

package com.nastechresearch.jafta.core.util

fun Throwable.safeMessage(fallback: String = "Unknown error"): String = message?.takeIf { it.isNotBlank() } ?: fallback
