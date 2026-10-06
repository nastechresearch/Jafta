plugins {
    id("com.android.application") version "8.7.0" apply false
    id("org.jetbrains.kotlin.android") version "2.0.0" apply false
    // Stessa versione di `org.jetbrains.kotlin.android` qui sopra: il compiler
    // di Compose non tollera un disallineamento, e un plugin `apply false` senza
    // versione non risolve.
    id("org.jetbrains.kotlin.plugin.compose") version "2.0.0" apply false
    // I modelli OpenCode viaggiano come JSON e il runtime li decodifica con
    // kotlinx.serialization: senza il plugin le `@Serializable` non generano
    // nulla e ogni `Json.decodeFromString` è un riferimento non risolto. Stessa
    // versione di Kotlin.
    id("org.jetbrains.kotlin.plugin.serialization") version "2.0.0" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}
