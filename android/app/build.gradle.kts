import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    // Da Kotlin 2.0 il compiler di Compose è un plugin a parte
    // (`kotlinCompilerExtensionVersion` è sparito dal plugin kotlin-android):
    // senza questo i file copiati da and-code non compilano nemmeno gli
    // `@Composable`, perché `@Composable` è un'annotation generata dal compiler.
    // La versione deve combaciare **esattamente** con quella di Kotlin: qui 2.0.0,
    // la stessa di `android/build.gradle.kts`.
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.chaquo.python")
}

// ── Release signing credentials ───────────────────────────────────────────────
// Never stored in the repo. Read from the environment (CI) or, failing that,
// from a gitignored `android/keystore.properties` (local release builds):
//
//   storeFile=/absolute/path/to/jafta-release.jks
//   storePassword=...
//   keyAlias=jafta
//   keyPassword=...
//
// If neither source provides a full set, the release build is left UNSIGNED
// rather than failing: `assembleRelease` must keep working for anyone who only
// wants to reproduce and inspect the artifact.
val keystorePropsFile = rootProject.file("keystore.properties")
val keystoreProps = Properties().apply {
    if (keystorePropsFile.exists()) {
        keystorePropsFile.inputStream().use { load(it) }
    }
}

// ── Runtime payload ──────────────────────────────────────────────────────────
// The proot runtime needs two things in the APK: the native launcher (proot
// plus libandroid-shmem and libtalloc, as `.so` files under `jniLibs`), and the
// download manifest that tells the installer where to fetch the Linux rootfs
// and the OpenCode binary from. The launcher has to be **in** the APK because
// it is what `RuntimeBridge` invokes before any download can happen; the
// rootfs is fetched at install time from the URLs in the manifest.
//
// Two Exec tasks, in order: the first downloads the pinned Termux packages and
// mirrors them under `opencode-runtime/<abi>/prefix`, the second copies the
// native libraries out of that tree into the `jniLibs` layout Android expects.
// `inputs`/`outputs` are declared so Gradle can skip the work when nothing
// changed — a payload build is a network round-trip per Termux package.
//
// Upstream (yuga-hashimoto/and-code @ 247ff996) also has a `--local-debs-dir`
// branch that builds the native payload from source instead of downloading
// prebuilt `.deb`s. It is deliberately not wired here: it needs an NDK and a
// Termux cross-toolchain, and the pinned mirror path reproduces the same
// artefacts for anyone building this repo.
// `rootProject.projectDir` e' la directory di `android/`, non quella del
// repository: i path del payload devono risalire di un livello. Usare
// `rootProject.projectDir` produce `/…/Jafta/android/jafta/runtime/proot/…`, che
// non esiste, e Gradle fallisce la configurazione della task con un
// "An input file was expected to be present but it doesn't exist" — un errore
// che nomina i file mancanti senza dire che il root e' sbagliato.
//
// `rootDir.parentFile` e' la stessa directory per un altro verso, ed e' l'idioma
// che questo file usa gia' per risalire al repository (vedi `srcDir("../../")`
// e `rootDir.parentFile` sotto): i due equivalenti, scelti per coerenza.
val runtimeRoot = rootDir.parentFile
val generatedRuntimeAssets = rootProject.layout.buildDirectory.dir("generated/runtime-assets")
val generatedRuntimeJni = rootProject.layout.buildDirectory.dir("generated/runtime-jni")

val prepareRuntimeAssets =
    tasks.register<Exec>("prepareRuntimeAssets") {
        group = "build"
        description = "Download the pinned Termux packages that back the proot runtime"
        inputs.file(runtimeRoot.resolve("jafta/runtime/proot/termux_assets.py"))
        inputs.file(runtimeRoot.resolve("jafta/runtime/proot/termux_assets.lock.json"))
        inputs.file(runtimeRoot.resolve("scripts/prepare_android_runtime_assets.py"))
        outputs.dir(generatedRuntimeAssets)
        commandLine(
            "python3",
            runtimeRoot.resolve("scripts/prepare_android_runtime_assets.py").absolutePath,
            "--output-dir",
            generatedRuntimeAssets.get().asFile.absolutePath,
            "--lock-file",
            runtimeRoot.resolve("jafta/runtime/proot/termux_assets.lock.json").absolutePath,
        )
    }

val prepareRuntimeNativeLibs =
    tasks.register<Exec>("prepareRuntimeNativeLibs") {
        group = "build"
        description = "Copy the proot native launcher out of the payload tree into jniLibs"
        dependsOn(prepareRuntimeAssets)
        inputs.dir(generatedRuntimeAssets)
        inputs.file(runtimeRoot.resolve("jafta/runtime/proot/native_libs.py"))
        outputs.dir(generatedRuntimeJni)
        commandLine(
            "python3",
            runtimeRoot.resolve("jafta/runtime/proot/native_libs.py").absolutePath,
            "--linux-assets-dir",
            generatedRuntimeAssets.get().asFile.absolutePath,
            "--output-dir",
            generatedRuntimeJni.get().asFile.absolutePath,
        )
    }

fun signingCredential(envName: String, propName: String): String? =
    (System.getenv(envName) ?: keystoreProps.getProperty(propName))?.takeIf { it.isNotBlank() }

val releaseStoreFile = signingCredential("JAFTA_KEYSTORE_PATH", "storeFile")
val releaseStorePassword = signingCredential("JAFTA_KEYSTORE_PASSWORD", "storePassword")
val releaseKeyAlias = signingCredential("JAFTA_KEY_ALIAS", "keyAlias")
val releaseKeyPassword = signingCredential("JAFTA_KEY_PASSWORD", "keyPassword")

val hasReleaseSigning = releaseStoreFile != null &&
    releaseStorePassword != null &&
    releaseKeyAlias != null &&
    releaseKeyPassword != null &&
    file(releaseStoreFile!!).exists()

android {
    namespace = "com.nastechresearch.jafta"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.nastechresearch.jafta"
        minSdk = 26
        targetSdk = 34
        // versionCode must increase monotonically on every published build.
        // versionName tracks the Python package version in pyproject.toml —
        // keep the two in sync when releasing.
        //
        // Il 12 e' saltato di proposito: non e' mai stato pubblicato, ma tre APK
        // diversi lo portano gia' (vedi l'avviso sull'albero sporco piu' sotto) e
        // uno di quelli e' installato. Pubblicare a 12 avrebbe significato non
        // poter provare l'aggiornamento proprio sul dispositivo che lo riceve:
        // l'updater pretende un codice STRETTAMENTE maggiore di quello installato.
        versionCode = 23
        versionName = "1.2.0"

        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64", "x86")
        }
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
                // Schemi di firma dichiarati esplicitamente invece di lasciare i
                // default di AGP, che dipendono dal minSdk e cambiano fra versioni.
                // v1 (JAR signing) serve solo sotto API 24: il minSdk è 26, quindi
                // è peso morto nell'APK. v2 copre tutto il parco supportato. v3 è
                // additivo (i dispositivi 28+ lo usano, 26-27 ricadono su v2) e
                // porta il supporto alla rotazione della chiave di firma.
                enableV1Signing = false
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            // null when no credentials were supplied → unsigned APK (see the
            // comment on the credential block above).
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    // Con il plugin Compose dichiarato, il flag dice al plugin di generare il
    // codice dei `@Composable`. `buildFeatures` è il posto giusto: accenderlo in
    // `android {}` prima di `dependencies` cambierebbe l'ordine di applicazione
    // dei plugin e fallirebbe la configurazione.
    buildFeatures {
        compose = true
    }

    packaging {
        resources {
            // jsch e bcprov sono entrambi multi-release jar e spediscono lo
            // stesso metadata OSGi sotto piu cartelle di versione (9, 15, …):
            // due input con lo stesso path fanno FALLIRE
            // mergeReleaseJavaResource. Serve il glob e non il path esatto,
            // altrimenti il build fallisce di nuovo alla cartella successiva.
            // Sono metadata per l'OSGi runtime, che su Android non esiste:
            // escluderli non toglie nulla (le classi dei multi-release jar non
            // passano da qui, le dexa D8).
            excludes += "/META-INF/versions/**/OSGI-INF/**"
        }
        jniLibs {
            // Con il packaging moderno AGP comprime le `.so` dentro l'APK e le
            // estrae al primo accesso. proot non lo sopporta: il processo gira
            // sotto proot, che deve mappare i segmenti dell'eseguibile, e una
            // libreria estratta in `/data` non è mappabile da lì. `extractNativeLibs`
            // deve quindi restare `false`, cioè le `.so` viaggiano grezze.
            useLegacyPackaging = true
        }
    }

    kotlinOptions {
        jvmTarget = "11"
    }

    sourceSets {
        getByName("main") {
            // `builtBy` dichiara i produttori sulla FileCollection e serve a
            // Gradle 8.9, che altrimenti fa FALLIRE `assembleRelease`:
            // `generateReleaseLintVitalReportModel` legge questa cartella senza
            // dipendere da chi la scrive (lintVital gira solo sul release, ed è
            // il motivo per cui `assembleDebug` non mostra il problema).
            // ATTENZIONE: da solo NON basta. AGP legge `assets.srcDirs` come
            // semplici percorsi e la dipendenza dichiarata qui va perduta, così
            // i due Copy non entrano nel grafo e l'APK imbarca in silenzio
            // l'ultimo contenuto rimasto in build/ — o niente affatto su un
            // clone pulito. Il gancio che li fa girare davvero è su `preBuild`,
            // più sotto: non toccare l'uno senza l'altro.
            assets.srcDirs(
                files("$buildDir/generated/assets")
                    .builtBy("copyScriptAssets", "copyPackageSourceAssets")
            )
            // Le librerie native del runtime, prodotte da `prepareRuntimeNativeLibs`.
            // `builtBy` dichiara il produttore sulla FileCollection: senza, il
            // grafo non sa che questo percorso dipende dalla task e la copia gira
            // (o no) per caso. Vale la stessa regola scritta sopra per
            // `assets.srcDirs`: non toccare l'uno senza l'altro.
            jniLibs.srcDir(
                files(generatedRuntimeJni)
                    .builtBy(prepareRuntimeNativeLibs)
            )
        }
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        pip {
            install("-r", "../../requirements-android.lock.txt")
        }
    }
    sourceSets {
        maybeCreate("main").apply {
            srcDir("../../")
            include("jafta/**")
        }
    }
}

// Lo stato del working tree, per l'avviso qui sotto. Stringa vuota = pulito;
// null = non lo sappiamo (fuori da un repo, o `git` non c'è), che è un caso
// diverso e non va raccontato come "pulito".
val workingTreeDirt: String? = try {
    val proc = ProcessBuilder("git", "status", "--porcelain")
        .directory(rootDir.parentFile)
        .redirectErrorStream(true)
        .start()
    val output = proc.inputStream.bufferedReader().readText()
    if (proc.waitFor() == 0) output.trim() else null
} catch (_: Exception) {
    null
}

// Warn about an unsigned release only when a release build was actually
// requested — a configuration-time warning would fire on every debug build too.
gradle.taskGraph.whenReady {
    val buildingRelease = allTasks.any { it.name.contains("Release") }
    if (buildingRelease && !hasReleaseSigning) {
        logger.warn(
            "\n[jafta] WARNING: release signing credentials not found — the APK " +
                "will be UNSIGNED and cannot be installed on a device.\n" +
                "[jafta] Set JAFTA_KEYSTORE_PATH / JAFTA_KEYSTORE_PASSWORD / " +
                "JAFTA_KEY_ALIAS / JAFTA_KEY_PASSWORD, or create " +
                "android/keystore.properties (see app/build.gradle.kts).\n"
        )
    }
    // Chaquopy impacchetta il **working tree**, non HEAD: `srcDir("../../")` qui
    // sopra e `copyPackageSourceAssets` leggono i file da disco. Su un albero
    // sporco l'APK corrisponde quindi a **nessun commit**, mentre chi guarda il
    // telefono attribuisce il comportamento a commit precisi — e `versionName`
    // non può distinguere due build dallo stesso albero modificato.
    //
    // La pratica decisa è buildare da un worktree staccato su uno SHA. Ma era una
    // cosa da ricordarsi, e il 25/08 sono uscite tre release diverse tutte
    // `0.9.0 / versionCode 12` proprio perché nessuno la ricordava. Un avviso la
    // rende meccanica, come già è per la firma.
    //
    // Avviso e non errore, di proposito: buildare da un albero sporco è il modo
    // giusto di **verificare una modifica** prima di committarla, ed è quel che si
    // fa tutto il giorno. Quel che non deve succedere è farlo *senza saperlo*.
    if (buildingRelease && !workingTreeDirt.isNullOrEmpty()) {
        val files = workingTreeDirt.lines().size
        logger.warn(
            "\n[jafta] WARNING: release build from a DIRTY working tree " +
                "($files file(s) modified or untracked).\n" +
                "[jafta] Chaquopy packages the working tree, not HEAD, so this APK " +
                "corresponds to no commit and cannot be reproduced from git.\n" +
                "[jafta] Fine for verifying a change; for anything you install and " +
                "keep, commit first and build from a detached worktree at that SHA.\n"
        )
    }
}

// Copy skill scripts as raw Android assets (Chaquopy compiles .py files
// into .imy, making them unreadable via importlib.resources. By also
// mirroring them as assets, scripts remain extractable at runtime.)
val copyScriptAssets by tasks.registering(Sync::class) {
    from("../../jafta/skills") {
        include("**/scripts/*.py")
    }
    into("$buildDir/generated/assets/skills")
}

// Mirror the whole jafta package as plain .py assets so the agent can
// read its own source on-device (extracted at gateway startup by
// jafta.utils.android_assets.extract_jafta_source).
val copyPackageSourceAssets by tasks.registering(Sync::class) {
    from("../../jafta") {
        include("**/*.py")
        exclude("**/__pycache__/**")
    }
    into("$buildDir/generated/assets/jafta_src/jafta")
}

// I due Copy sopra devono girare prima di QUALUNQUE consumatore della cartella
// generata: `mergeAssets`, ma anche `generate*LintVitalReportModel`. Agganciarli
// per nome uno per uno è fragile (AGP ne aggiunge di nuovi tra le versioni);
// `preBuild` è l'ancora che precede l'intera pipeline della variante, quindi li
// copre tutti, presenti e futuri. Senza questo blocco il build riesce comunque,
// ma silenziosamente con gli asset vecchi: è già capitato.
//
// `prepareRuntimeNativeLibs` si aggancia qui per lo stesso motivo, e per uno in
// più: le `.so` del runtime servono a `mergeJniLibFolders`, che sta più giù
// nella pipeline, e senza questo blocco un clone pulito produce un APK senza
// proot e senza che nessun errore lo dica.
tasks.named("preBuild") {
    dependsOn(copyScriptAssets, copyPackageSourceAssets, prepareRuntimeNativeLibs)
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // Compose — serve agli schermi di onboarding del runtime proot+OpenCode
    // portati da and-code (`feature/onboarding/OnboardingChoiceScreen.kt`,
    // `core/UrlLauncher.kt`). `compose-bom` tiene allineate le librerie fra
    // loro: senza, foundation e material3 possono prendere versioni diverse e
    // il risultato è un APK che non linka. Il BOM 2024.09.03 sta dentro
    // compileSdk 34, che è il tetto di questo progetto.
    //
    // `material-icons-extended` porta le icone filled usate dal selettore
    // (Android, Computer, Terminal): in `material-icons-core` ci sono solo le
    // pochissime icone di default.
    val composeBom = platform("androidx.compose:compose-bom:2024.09.03")
    implementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    // **Non** `activity-compose`, e la ragione va tenuta a mente: nessun file
    // copiato chiama `setContent { }` — il runtime non monta una Activity sua,
    // restituisce solo funzioni `@Composable` che un caller valido può
    // invocare. Aggiungerla tirava su androidx.activity 1.9.3, che cambia la
    // firma di `ComponentActivity.onNewIntent` da `Intent?` a `Intent`, e
    // rompeva l'override già presente in `MainActivity.kt:883` — un file di
    // v1.0.3 che questa PR non deve toccare. Se un giorno serve, va insieme al
    // fix di quell'override, non da solo.

    // Runtime proot + OpenCode. OkHttp parla col server OpenCode; kotlinx
    //.serialization è il codec dei suoi modelli e degli eventi SSE; commons-
    // compress gestisce i formati degli archivi del runtime (tar, ar, xz).
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    // commons-compress **non** porta con sé xz: `XZCompressorInputStream` referenzia
    // `org.tukaani.xz.{XZInputStream,SingleXZInputStream,MemoryLimitException}`, che
    // vivono nel progetto separato `org.tukaani:xz`. Senza questa riga `assembleDebug`
    // passa e `assembleRelease` muore in `minifyReleaseWithR8` con
    // "Missing class org.tukaani.xz.MemoryLimitException" — R8 considera un'assenza
    // un errore, e la build debug non lo fa girare.
    //
    // Le versioni sono quelle di and-code, non le ultime: 1.27.1 e 1.9 sono le coppie
    // con cui quel progetto compila e i suoi test passano, e il runtime portato
    // (`RuntimeArchive`) dipende dalla linea 1.27. Se qui resta 1.26.2 il R8 non
    // segnala nulla di nuovo, ma la coppia non è più quella verificata a monte.
    implementation("org.apache.commons:commons-compress:1.27.1")
    implementation("org.tukaani:xz:1.9")
    // Coroutines: il runtime copiato è scritto con `Flow`/`StateFlow` come stato
    // della sessione, `Mutex` attorno alle operazioni di installazione e
    // `Dispatchers` per i blocchi I/O. Prima arrivava solo per via
    // transitività da WorkManager, il che è fragile da dipenderne:
    // WorkManager può alzare o abbassare la versione e la compilazione si
    // romperebbe per un motivo che non riguarda nessuno dei due. Dichiarata,
    // stessa versione di and-code.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    // Chrome Custom Tabs: apre i link esterni della chat in un browser
    // in-app (con pulsante di chiusura) invece di dirottare la WebView SPA.
    implementation("androidx.browser:browser:1.7.0")

    // Multi-profile WebView (ProfileStore): la sessione di navigazione dei tool
    // browser_* tiene cookie e storage separati dal barattolo globale che usa
    // web_fetch, e li butta alla chiusura. Verificato il 29/08: la 1.14.0 sta
    // dentro compileSdk 34 (a differenza di WorkManager 2.10+), e il Titan 2
    // (WebView 143) espone MULTI_PROFILE a runtime.
    implementation("androidx.webkit:webkit:1.14.0")

    // WorkManager: rete di sicurezza anti-doze indipendente dalle sveglie
    // (GatewayWorker). Gira sul backend JobScheduler, e i gestori batteria dei
    // produttori sono molto piu restii a interferire con un concetto di sistema
    // che con un service nudo. Ferma alla 2.9.x di proposito: dalla 2.10 in su
    // WorkManager richiede compileSdk 35, qui siamo a 34.
    implementation("androidx.work:work-runtime-ktx:2.9.1")

    // SPIKE SSH — client SSH nativo. jsch e puro Java e client-only.
    // BouncyCastle NON e opzionale su Android: X25519 e entrato in Conscrypt
    // solo con Android 14 e qui il minSdk e 26, quindi senza BC lo scambio di
    // chiavi curve25519-sha256 (quello che ogni server moderno negozia) e
    // Ed25519 non sono disponibili. Vedi SshBridge.kt e proguard-rules.pro.
    implementation("com.github.mwiede:jsch:2.28.6")
    implementation("org.bouncycastle:bcprov-jdk18on:1.85")

    // Markdown nelle bolle della finestra flottante (FloatingOverlayController).
    // Le bolle sono TextView e mostravano il sorgente — `1. Scegli **una** cosa`
    // — mentre la WebUI renderizza (marked 15, `gfm: true`, `breaks: true`):
    // la stessa risposta si leggeva in due modi a seconda di dove la guardavi.
    //
    // A mano si fa solo l'enfasi inline; il resto — annidamento delle liste,
    // escape, tabelle — e' un parser, e un parser scritto con le regex sbaglia
    // in silenzio sulle parole di qualcun altro. Markwon e' CommonMark
    // (commonmark-java) reso in Spanned, cioe' esattamente cio' che una
    // TextView sa disegnare.
    //
    // Gli `ext-*` sono il pezzo GFM che CommonMark non ha, ed e' quello che il
    // modello emette davvero. Fuori di proposito: syntax-highlight (Prism4j
    // vuole un annotation processor), ext-latex (JLatexMath, un paio di MB) e
    // le immagini (servirebbe un image loader e una fetch di rete da un
    // overlay). Per quelle tre c'e' il tasto «Continua su app».
    implementation("io.noties.markwon:core:4.6.2")
    implementation("io.noties.markwon:ext-strikethrough:4.6.2")
    implementation("io.noties.markwon:ext-tables:4.6.2")
    implementation("io.noties.markwon:ext-tasklist:4.6.2")
    implementation("io.noties.markwon:linkify:4.6.2")
    implementation("io.noties.markwon:html:4.6.2")
}
