#!/usr/bin/env python3
"""Fix LocalRuntimeManager.kt imports"""

import subprocess

# Get original from git
result = subprocess.run(
    ['git', 'show', 'HEAD:android/app/src/main/java/com/nastechresearch/jafta/runtime/local/LocalRuntimeManager.kt'],
    capture_output=True, text=True, check=True
)
original = result.stdout

# Find the @Serializable line
idx = original.find('@Serializable\ndata class LocalRuntimeMetadata')
if idx < 0:
    print("ERROR: Could not find class")
    sys.exit(1)

rest = original[idx:]

# Build the header
header = '''// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026
// https://github.com/nastechresearch/Jafta

package com.nastechresearch.jafta.runtime.local

import android.content.Context
import kotlin.jvm.Volatile
import com.nastechresearch.jafta.runtime.LocalAgent
import com.nastechresearch.jafta.runtime.LocalRuntimeStatus
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.InetSocketAddress
import java.net.Socket

'''

header = '''// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026
// https://github.com/nastechresearch/Jafta

package com.nastechresearch.jafta.runtime.local

import android.content.Context
import kotlin.jvm.Volatile
import com.nastechresearch.jafta.runtime.LocalAgent
import com.nastechresearch.jafta.runtime.LocalRuntimeStatus
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.InetSocketAddress
import java.net.Socket

'''

# Find the @Serializable line in the original
# Use git show to get clean original
import subprocess
result = subprocess.run(
    ['git', 'show', 'HEAD:android/app/src/main/java/com/nastechresearch/jafta/runtime/local/LocalRuntimeManager.kt'],
    capture_output=True, text=True, check=True
)
original = result.stdout

idx = original.find('@Serializable\ndata class LocalRuntimeMetadata')
if idx < 0:
    print("ERROR: Could not find class")
    sys.exit(1)

rest = original[idx:]

header = '''// Adapted from nastechresearch/and-code (MIT) — Nsamba/Jafta 2026
// https://github.com/nastechresearch/Jafta

package com.nastechresearch.jafta.runtime.local

import android.content.Context
import kotlin.jvm.Volatile
import com.nastechresearch.jafta.runtime.LocalAgent
import com.nastechresearch.jafta.runtime.LocalRuntimeStatus
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.InetSocketAddress
import java.net.Socket

'''

with open("android/app/src/main/java/com/nastechresearch/jafta/runtime/local/LocalRuntimeManager.kt", "w") as f:
    f.write(header + rest)

print("File updated successfully")