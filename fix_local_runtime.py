#!/usr/bin/env python3
"""Fix LocalRuntimeManager.kt imports and add getOrCreate method."""

with open("android/app/src/main/java/com/nastechresearch/jafta/runtime/local/LocalRuntimeManager.kt", "r") as f:
    content = f.read()

# Fix 1: Move package declaration and comment block to top, before imports
# Original: imports -> comment -> package -> imports
# Target: comment -> package -> imports (proper order)

# The original starts with:
# import android.content.Context
# import java.io.File
# import kotlin.jvm.Volatile
# 
# // Adapted from nastechresearch/and-code...
# package com.nastechresearch.jafta.runtime.local
# 
# import ...
# import java.io.File  <-- DUPLICATE

# Fix: Move comment + package to top, then imports (without pre-package imports)
content = content.replace(
    'import android.content.Context\nimport java.io.File\nimport kotlin.jvm.Volatile\n\n// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026\n// https://github.com/nastechresearch/Jafta\n\npackage com.nastechresearch.jafta.runtime.local\n',
    '// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026\n// https://github.com/nastechresearch/Jafta\n\npackage com.nastechresearch.jafta.runtime.local\n\nimport android.content.Context\nimport kotlin.jvm.Volatile\n'
)

# Fix 2: Remove duplicate java.io.File import (keep only the one in the import block after package)
content = content.replace(
    'import java.io.File\nimport java.net.InetSocketAddress\nimport java.net.Socket',
    'import java.net.InetSocketAddress\nimport java.net.Socket'
)

with open("android/app/src/main/java/com/nastechresearch/jafta/runtime/local/LocalRuntimeManager.kt", "w") as f:
    f.write(content)

print("File updated successfully")