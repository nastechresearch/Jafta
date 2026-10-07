package com.nastechresearch.jafta

import android.content.Context
import android.util.Log
import com.nastechresearch.jafta.runtime.local.LocalRuntimeManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.StateFlow

/**
 * Bridge per il runtime OpenCode locale (proot), esposto a Python via Chaquopy
 * (`jclass("com.nastechresearch.jafta.RuntimeBridge")`), mai istanziato da Kotlin —
 * stesso pattern di `PowerBridge` / `LocationBridge`.
 *
 * Qui vive solo la meccanica nativa (avvio/stop/state del servizio foreground).
 * La decisione "quando installare/avviare/fermare" vive in Python, che è
 * l'unico a sapere cosa l'utente ha chiesto.
 *
 * Nessun metodo lancia mai verso Python: si logga e si torna un default sicuro.
 * Un'eccezione che attraversa il confine Chaquopy abortirebbe l'operazione
 * proprio nel punto in cui stavamo cercando di proteggerla.
 */
class RuntimeBridge(context: Context) {

    companion object {
        private const val TAG = "RuntimeBridge"
    }

    private val manager = LocalRuntimeManager.getOrCreate(context)

    /** Stato osservabile: Disconnected / Connecting / Connected(version) / Failed(msg) / Unavailable(reason) */
    val state: StateFlow<com.nastechresearch.jafta.runtime.LocalRuntimeStatus> = manager.status

    /** Avvia l'installazione completa (scarica rootfs + OpenCode, estrae, configura). Non blocca. */
    fun install(): Boolean = runCatching {
        CoroutineScope(Dispatchers.IO).launch { manager.installAndStart() }
        true
    }.getOrElse { e ->
        Log.e(TAG, "install failed", e)
        false
    }

    /** Avvia il runtime già installato. Non blocca. */
    fun start(): Boolean = runCatching {
        CoroutineScope(Dispatchers.IO).launch { manager.ensureRunning() }
        true
    }.getOrElse { e ->
        Log.e(TAG, "start failed", e)
        false
    }

    /** Ferma il runtime (kill del processo proot + servizio). Non blocca. */
    fun stop(): Boolean = runCatching {
        manager.stop()
        true
    }.getOrElse { e ->
        Log.e(TAG, "stop failed", e)
        false
    }

    /** Cancella tutto: rootfs, binari, log, cache. Non blocca. */
    fun delete(): Boolean = runCatching {
        manager.deleteRuntime()
        true
    }.getOrElse { e ->
        Log.e(TAG, "delete failed", e)
        false
    }

    /** Diagnostica leggibile: disco, memoria, PID, uptime, log tail. */
    fun diagnostics(): String = runCatching {
        manager.diagnostics()
    }.getOrElse { e ->
        Log.e(TAG, "diagnostics failed", e)
        """{"error": "diagnostics unavailable"}"""
    }

    /** True se l'ABI del device è supportata (arm64-v8a o x86_64). */
    fun supportsAbi(): Boolean = runCatching {
        manager.supportsAbi()
    }.getOrElse { e ->
        Log.e(TAG, "supportsAbi failed", e)
        false
    }

    /** Porta HTTP su cui il server OpenCode ascolta (se running). -1 se non running. */
    fun installedPort(): Int = runCatching {
        manager.installedPort()
    }.getOrElse { e ->
        Log.e(TAG, "installedPort failed", e)
        -1
    }

    /** True se il runtime è installato e healthy. */
    fun isHealthy(): Boolean = runCatching {
        manager.isHealthy()
    }.getOrElse { e ->
        Log.e(TAG, "isHealthy failed", e)
        false
    }
}