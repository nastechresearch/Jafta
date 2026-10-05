package com.nastechresearch.jafta

import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/**
 * Il salto bloccante sul main thread che fanno i ponti chiamati da Python:
 * posta *block* sul main Looper, aspetta al massimo *timeoutMs* e ne ritorna
 * l'esito, o *fallback* se non arriva in tempo.
 *
 * Stava scritto quattro volte (`FloatingBridge.onMain` e tre metodi di
 * `JaftaBrowserBridge`), ognuna con le sue idee. Qui una volta, con tre regole
 * che prima non valevano ovunque:
 *
 * - **già sul main, lo si esegue sul posto**: un `post` seguito da un `await`
 *   sarebbe un blocco su sé stessi. Python chiama da un thread di lavoro, ma un
 *   deadlock è un guasto troppo silenzioso per affidarlo a un «dovrebbe»;
 * - **qualunque cosa sollevi il blocco si scrive nel log e vale *fallback***,
 *   in tutti e due i casi — `Throwable`, non solo `Exception`: un `Error` sul
 *   main thread abbatte il processo, gateway compreso, quanto un'eccezione;
 * - **a tetto scaduto il blocco non gira più**: il chiamante ha già risposto
 *   *fallback*, e un blocco che partisse dopo farebbe ciò che si è appena detto
 *   non fatto (un fumetto disegnato dopo il «non mostrato», una mascotte
 *   accesa dopo il «non applicato»). Se allo scadere il blocco è già partito,
 *   si aspetta la sua fine e vale il suo esito, che è quello vero. Chi vuole
 *   il contrario — una pulizia che deve arrivare anche in ritardo — lo chiede
 *   con *runLate*.
 *
 * Fuori restano le attese che si sbloccano in una callback
 * (`evaluateJavascript`): lì il blocco finisce prima del risultato.
 */
object MainHop {

    private const val PENDING = 0
    private const val RUNNING = 1
    private const val ABANDONED = 2

    fun <T> call(
        timeoutMs: Long,
        fallback: T,
        tag: String,
        runLate: Boolean = false,
        block: () -> T,
    ): T {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            // Sul posto vale la stessa regola del salto: log e *fallback*.
            return try {
                block()
            } catch (e: Throwable) {
                Log.e(tag, "Main thread call failed", e)
                fallback
            }
        }
        val state = AtomicInteger(PENDING)
        val result = AtomicReference(fallback)
        val done = CountDownLatch(1)
        Handler(Looper.getMainLooper()).post {
            // Abbandonato allo scadere: nessuno aspetta più, e non si fa.
            if (!state.compareAndSet(PENDING, RUNNING) && !runLate) return@post
            try {
                result.set(block())
            } catch (e: Throwable) {
                Log.e(tag, "Main thread call failed", e)
            } finally {
                done.countDown()
            }
        }
        if (done.await(timeoutMs, TimeUnit.MILLISECONDS)) return result.get()
        if (runLate) {
            Log.i(tag, "Main thread call timed out after ${timeoutMs}ms, it will run late")
            return fallback
        }
        if (state.compareAndSet(PENDING, ABANDONED)) {
            Log.i(tag, "Main thread call timed out after ${timeoutMs}ms, dropped")
            return fallback
        }
        // Partito proprio allo scadere: sta girando sul main, e il suo esito è
        // quello che conta.
        done.await()
        return result.get()
    }
}
