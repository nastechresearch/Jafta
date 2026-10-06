"""Il lock del payload e i due script che lo consumano.

Tre fatti che devono restare veri insieme, e che non sono visibili da nessuna
parteDa sola: sono l'unico posto in cui una versione di Termux viene scritta.

1. **Nessun SONAME scritto a mano.** Il SONAME di ``libtalloc`` segue la
   versione del pacchetto (``libtalloc.so.2.4.3`` a 2.4.3, un altro nome a
   2.5.0). Il lock è passato da 2.4.3 a 2.5.0 proprio mentre il progetto si
   fermava a guardarlo: un ``libtalloc.so.2.4.3`` letterale nel codice, o un
   ``libtalloc.so.2`` nel pattern, si rompe al prossimo bump senza che nessun
   test se ne accorga. Per questo ``RUNTIME_LIBRARIES`` porta ``libtalloc.so.*``
   e qui si verifica che nessun file del payload ne nomi uno esatto.

2. **I due script devono leggere lo stesso lock e produrre la stessa radice.**
   ``prepare_android_runtime_assets.py`` scrive sotto ``opencode-runtime/<abi>/prefix``
   e ``native_libs.py`` legge esattamente lì: se uno dei due cambia spelling,
   l'altro copia da una directory che non esiste e l'errore è un
   ``FileNotFoundError`` che parla di ``proot``, non della radice sbagliata.

3. **Ogni pacchetto pinnato è verificato.** Lo SHA-256 è l'unica cosa che lega
   il lock a un file concreto: un pacchetto senza hash verrebbe scaricato e
   usato senza controllo.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from jafta.runtime.proot import termux_assets
from jafta.runtime.proot.native_libs import ANDROID_ABIS, RUNTIME_LIBRARIES

ROOT = Path(__file__).resolve().parents[3]
PROOT_DIR = ROOT / "jafta" / "runtime" / "proot"
LOCK_FILE = PROOT_DIR / "termux_assets.lock.json"
DRIVER = ROOT / "scripts" / "prepare_android_runtime_assets.py"

# I due file che trasformano il lock in librerie native.
PAYLOAD_SOURCES = (PROOT_DIR / "native_libs.py", DRIVER)

# Un SONAME con la versione dentro: `libtalloc.so.2.4.3`. Servono **due**
# componenti numerici, perché `libtalloc.so.2` è un nome proprio e legittimo:
# è l'ago di `patch_needed`, e lì non cerca niente, sostituisce.
_PINNED_SONAME = re.compile(r"libtalloc\.so\.\d+\.\d+")


def _lock() -> dict:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. nessun SONAME scritto a mano
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", PAYLOAD_SOURCES, ids=lambda p: p.name)
def test_no_payload_source_pins_a_talloc_soname(source: Path) -> None:
    """Nessuna costante di stringa nomina un SONAME di talloc con la versione.

    Si legge l'AST invece del testo: un commento che **spiega** il motivo
    (``e.g. libtalloc.so.2.4.3``) è esattamente quello che questo file vuole, e
    segnalarlo come un difetto renderebbe il test un rumido che il prossimo
    passaggio di formattazione zittifica.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    offenders = [
        f"{source.name}:{node.lineno}: {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _PINNED_SONAME.search(node.value)
    ]
    assert not offenders, "SONAME di talloc con la versione dentro: " + "; ".join(offenders)


def test_the_comment_that_explains_the_glob_survives() -> None:
    """Il contraltare del test sopra: la tabella deve *dire* perché è un glob.

    Senza questo, cancellare il commento insieme al glob lascerebbe la tabella
    muta e il test successivo continuerebbe a passare — cioè la protezione
    diventerebbe un avviso con la spiegazione già andata via.
    """
    table = (PROOT_DIR / "native_libs.py").read_text(encoding="utf-8")
    assert "SONAME" in table, "la tabella di RUNTIME_LIBRARIES deve dire perché usa un glob"


def test_the_talloc_entry_is_a_glob_and_is_required() -> None:
    """La voce esiste, è un glob, ed è obbligatoria: senza di lei ``copy_abi``
    passerebbe oltre una copia senza talloc, e proot non parte."""
    assert "libtalloc.so.*" in RUNTIME_LIBRARIES
    assert RUNTIME_LIBRARIES["libtalloc.so.*"] == ("libtalloc.so", True)


def test_the_lock_actually_pins_talloc() -> None:
    """Il glob non serve a nulla se il lock non porta talloc: il caso reale
    (2.4.3 → 2.5.0) è il motivo per cui il glob esiste, quindi il pacchetto
    dev'esserci con un hash."""
    versions = {
        package["name"]
        for abi in _lock()["architectures"].values()
        for package in abi["packages"]
    }
    assert "libtalloc" in versions


# ---------------------------------------------------------------------------
# 2. i due script concordano su lock e radice
# ---------------------------------------------------------------------------


def test_both_abis_pin_the_same_package_set() -> None:
    """``copy_abi`` gira su ogni ABI della mappa: un ABI con un pacchetto in
    meno fallisce in build, e su un device solo non lo si scopre."""
    pinned = {
        abi: frozenset(package["name"] for package in entry["packages"])
        for abi, entry in _lock()["architectures"].items()
    }
    assert set(pinned) == set(ANDROID_ABIS), f"ABI nel lock diversi dalla mappa: {sorted(pinned)}"

    distinct = set(pinned.values())
    assert len(distinct) == 1, f"gli ABI non pinnano lo stesso insieme di pacchetti: {pinned}"


def test_the_driver_and_the_copier_agree_on_the_asset_root() -> None:
    """``asset_prefix_dir`` è la fonte unica della radice; il driver la usa per
    scrivere e ``native_libs`` la ripete letterale per leggere. Se le due
    divergono, la copia legge una directory che nessuno ha scritto."""
    expected = termux_assets.asset_prefix_dir("/assets", "arm64-v8a")

    copier = (PROOT_DIR / "native_libs.py").read_text(encoding="utf-8")
    assert 'ANDROID_LINUX_ASSET_ROOT' not in copier or termux_assets.ANDROID_LINUX_ASSET_ROOT in copier
    assert '"opencode-runtime"' in copier, "il nome della radice è ripetuto a mano in native_libs.py"

    driver = DRIVER.read_text(encoding="utf-8")
    assert "asset_prefix_dir" in driver, "il driver deve usare l'helper, non un path scritto a mano"

    assert expected.as_posix().endswith("opencode-runtime/arm64-v8a/prefix")


def test_the_driver_reads_the_lock_jafta_actually_ships() -> None:
    """``DEFAULT_LOCK_FILE`` nel driver è il posto dove una sbavatura di path
    passa inosservata: punta a ``runtime_tools/`` upstream e a
    ``jafta/runtime/proot/`` qui, e un mix dei due fa fallire il build."""
    driver = DRIVER.read_text(encoding="utf-8")
    assert 'DEFAULT_LOCK_FILE = REPO_ROOT / "jafta" / "runtime" / "proot"' in driver
    assert "runtime_tools" not in driver, "il driver non deve puntare a runtime_tools/"


def test_the_driver_imports_the_termux_assets_that_lives_here() -> None:
    """Lo stesso: l'import deve essere ``jafta.runtime.proot.termux_assets``,
    altrimenti il driver va in cerca di un pacchetto che questo fork non ha."""
    driver = DRIVER.read_text(encoding="utf-8")
    assert "from jafta.runtime.proot.termux_assets import (" in driver
    assert "runtime_tools" not in driver


# ---------------------------------------------------------------------------
# 3. ogni pacchetto pinnato è verificato
# ---------------------------------------------------------------------------


def test_every_pinned_package_carries_a_verified_digest() -> None:
    """Lo SHA-256 è l'unico legame fra il lock e il file scaricato: senza, il
    pacchetto entra nell'APK senza nessun controllo."""
    missing = [
        f"{abi}/{package['name']}"
        for abi, entry in _lock()["architectures"].items()
        for package in entry["packages"]
        if not re.fullmatch(r"[0-9a-f]{64}", package.get("sha256", ""))
    ]
    assert not missing, f"pacchetti senza sha256 valido: {missing}"


def test_the_lock_root_package_is_still_proot() -> None:
    """``ROOT_PACKAGES`` nel codice e ``root_packages`` nel lock sono due modi
    di dire la stessa cosa: proot è il pacchetto radice da cui si risolve tutto
    il resto della chiusura."""
    assert termux_assets.ROOT_PACKAGES == _lock()["root_packages"] == ["proot"]
