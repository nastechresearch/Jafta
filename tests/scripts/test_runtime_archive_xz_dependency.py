"""La build release deve poter linkare tutto quello che il runtime usa.

`assembleDebug` passa e `assembleRelease` no, perche' solo il secondo gira R8, e
R8 tratta una classe mancante come un **errore** mentre il compilatore Kotlin la
treatsilenziosamente. Il caso reale:

`RuntimeArchive.kt` spacchetta i `.deb` di Termux e legge `data.tar.xz` con
`XZCompressorInputStream`. Quel tipo, dentro `commons-compress`, referenzia
`org.tukaani.xz.XZInputStream`, `SingleXZInputStream` e `MemoryLimitException`,
che stanno nel progetto **separato** `org.tukaani:xz`. Dimenticare quella riga
lascia la compilazione Kotlin intatta e uccide `minifyReleaseWithR8` con
"Missing class org.tukaani.xz.MemoryLimitException".

Non si puo' provare R8 qui: niente Android SDK, niente Gradle, e la regola del
repository e' che il Kotlin non gira in CI. Si prova quindi la **causa**, non
l'effetto, leggendo il sorgente — come fanno gli altri contratti di questa
suite. Sono due fatti che un bump di versione può rompere in silenzio:

1. la dipendenza `org.tukaani:xz` e' dichiarata accanto a `commons-compress`;
2. il runtime usa davvero il percorso xz, quindi la dipendenza non e' spazzatura.

Il secondo e' quello che rende il primo necessario: senza un chiamante xz la
riga mancante sarebbe innocua, e il test (1) da solo passerebbe su un albero
che non estrae niente.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_GRADLE = ROOT / "android" / "app" / "build.gradle.kts"
ANDROID_SRC = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "nastechresearch" / "jafta"

# Le classi che R8 ha nominate nel fallimento, una per una.
XZ_CLASSES = (
    "org.tukaani.xz.XZInputStream",
    "org.tukaani.xz.SingleXZInputStream",
    "org.tukaani.xz.MemoryLimitException",
)


def _gradle() -> str:
    return APP_GRADLE.read_text(encoding="utf-8")


def _runtime_archive() -> str:
    return (ANDROID_SRC / "runtime" / "local" / "RuntimeArchive.kt").read_text(encoding="utf-8")


def test_the_xz_library_is_declared() -> None:
    """`commons-compress` non porta xz con se': e' un progetto Maven a parte.

    E' il motivo per cui la sola dipendenza `commons-compress` non basta: la
    classe che il runtime chiama referenzia tre classi che qui devono arrivare da
    `org.tukaani:xz`, e senza questa riga R8 le cerca nel APK e non le trova.
    """
    assert 'implementation("org.tukaani:xz:' in _gradle(), (
        "org.tukaani:xz non e' dichiarata: XZCompressorInputStream non linka"
    )


def test_the_xz_library_sits_next_to_commons_compress() -> None:
    """Le due righe devono stare nello stesso blocco `dependencies`.

    Sono una coppia: senza `commons-compress` non c'e' `XZCompressorInputStream`,
    e senza `xz` quello non linka. Trovandole in posti separati, un taglio o un
    merge puo' lasciare meta' del paio senza che nessuno se ne accorga.
    """
    gradle = _gradle()
    compress = re.search(r'implementation\("org\.apache\.commons:commons-compress:[^"]+"\)', gradle)
    xz = re.search(r'implementation\("org\.tukaani:xz:[^"]+"\)', gradle)
    assert compress and xz, "una delle due dipendenze manca"
    assert (
        abs(compress.start() - xz.start()) < 400
    ), f"xz e commons-compress distano {abs(compress.start() - xz.start())} caratteri: non sono piu' una coppia"


def test_commons_compress_is_the_version_and_code_runtime_expect() -> None:
    """Il runtime spacchetta i pacchetti Termux, e la linea 1.27 e' quella con
    cui and-code verifica la copia di questo runtime. Tornare a 1.26.2 non
    romperebbe R8, quindi nessun test lo griderebbe: e' per questo che la
    versione viene fissata qui.
    """
    match = re.search(r'implementation\("org\.apache\.commons:commons-compress:([^"]+)"\)', _gradle())
    assert match, "commons-compress non e' dichiarata"
    assert match.group(1) == "1.27.1", (
        f"commons-compress {match.group(1)} non e' la 1.27.1 con cui il runtime e' stato verificato"
    )


def test_the_runtime_really_does_need_xz() -> None:
    """Se nessuno usasse xz, la dipendenza sopra sarebbe inutile e questo test
    fallirebbe — ed e' il controllo che impedisce alla coppia di venire rimossa
    insieme per un motivo sbagliato.

    Il percorso xz e' il contenitore dei pacchetti Termux (`data.tar.xz`), cioe'
    esattamente il payload del runtime che PR #24 ha messo nell'APK.
    """
    archive = _runtime_archive()
    assert "XZCompressorInputStream" in archive, "RuntimeArchive non usa piu' il percorso xz"
    assert "data.tar.xz" in archive, (
        "RuntimeArchive non legge piu' data.tar.xz: la dipendenza xz non serve piu'"
    )


def test_every_xz_class_r8_named_is_the_one_the_dependency_provides() -> None:
    """Le tre classi del messaggio di R8 devono essere le uniche referenziate da
    `XZCompressorInputStream`, e non una fourth parte emersa dopo.

    Il check fissa la lista perche' il messaggio di R8 e' l'unica prova reale
    esista: senza questo elenco, se `commons-compress` aggiungesse un'altra
    dipendenza opzionale, il prossimo build release riporterebbe classi diverse
    da queste e nessuno avrebbe il confronto.
    """
    archive = _runtime_archive()
    assert "import org.apache.commons.compress.compressors.xz.XZCompressorInputStream" in archive
    for missing in XZ_CLASSES:
        short = missing.rsplit(".", 1)[1]
        assert short.endswith("XZInputStream") or short in {
            "SingleXZInputStream",
            "MemoryLimitException",
        }, f"{missing} non e' fra le classi segnalate da R8"
