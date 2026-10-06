"""Test per ``jafta/runtime/proot/native_libs.py`` (librerie native nel pacchetto).

Questo file è la copia di ``scripts/prepare_android_runtime_native_libs.py`` di
and-code, e il corpo è identico a upstream: i test qui non verificano una
riscrittura, verificano che **il comportamento di cui il runtime dipende** sia
rimasto quello, e in particolare che le due correzioni che upstream ha portato
dopo la prima versione non si perdano in una prossima sincronizzazione.

Le due:

- ``libtalloc.so.*`` è risolto con un glob e non con un SONAME scritto a mano.
  Il SONAME di talloc segue la versione del pacchetto (``libtalloc.so.2.4.3`` a
  2.4.3, altro nome a 2.5.0), quindi un nome fissato si rompe a ogni bump di
  Termux. Il lock è passato proprio da 2.4.3 a 2.5.0: è il caso reale, non
  un'ipotesi.
- Un symlink di versione pendente viene scartato. ``is_file()`` segue i
  symlink, quindi un link che punta a nulla non è un file e non raggiunge
  ``copy2``; fra i candidati vanno preferiti i file veri.

Il resto sono le invarianti che il chiamante (``Gradle``) dà per scontate: un
binario richiesto che manca è un errore che nomina il pattern, una libreria
opzionale che manca non lo è, e la directory di uscita viene ripulita prima
così che un build precedente non lasci dentro librerie fantasma.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jafta.runtime.proot.native_libs import (
    ANDROID_ABIS,
    NATIVE_EXECUTABLES,
    RUNTIME_LIBRARIES,
    copy_abi,
    native_executable_name,
    patch_needed,
    prepare_native_libs,
    select_runtime_library,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_prefix(root: Path, abi: str) -> Path:
    """Crea ``<root>/opencode-runtime/<abi>/prefix`` e la restituisce."""
    prefix = root / "opencode-runtime" / abi / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib").mkdir(parents=True)
    (prefix / "libexec" / "proot").mkdir(parents=True)
    return prefix


def _write_executables(prefix: Path, payload: bytes = b"ELF-ish") -> None:
    """Scrive i tre eseguibili nativi che ``NATIVE_EXECUTABLES`` richiede."""
    for source_relative in NATIVE_EXECUTABLES:
        target = prefix / source_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def _write_library(prefix: Path, name: str, payload: bytes = b"lib") -> Path:
    """Scrive una libreria nella ``prefix/lib`` e la restituisce."""
    target = prefix / "lib" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return target


def _is_executable(path: Path) -> bool:
    """Vero se il file ha il bit di esecuzione per il proprietario."""
    return bool(path.stat().st_mode & stat.S_IXUSR)


# ---------------------------------------------------------------------------
# select_runtime_library — il glob invece del SONAME scritto a mano
# ---------------------------------------------------------------------------


def test_talloc_is_found_by_glob_so_a_version_bump_does_not_break_it(tmp_path: Path) -> None:
    """Il caso reale: il lock porta libtalloc da 2.4.3 a 2.5.0, e il SONAME
    cambia con la versione. Un SONAME fissato a 2.4.3 non troverebbe nulla."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    (lib_dir / "libtalloc.so.2.4.3").write_bytes(b"lib")
    (lib_dir / "libtalloc.so.2.5.0").write_bytes(b"lib")

    chosen = select_runtime_library(lib_dir, "libtalloc.so.*")

    assert chosen is not None, "il glob deve trovare talloc fra le versioni presenti"
    assert chosen.name == "libtalloc.so.2.5.0", "con più versioni ne va scelta la più alta"


def test_a_dangling_version_symlink_is_dropped(tmp_path: Path) -> None:
    """``is_file()`` segue i symlink, quindi un link a un file assente non è un
    file: deve essere scartato prima di ``copy2``, che altrimenti solleva."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    good = lib_dir / "libtalloc.so.2.5.0"
    good.write_bytes(b"lib")
    (lib_dir / "libtalloc.so.9.9.9").symlink_to(lib_dir / "does-not-exist")

    chosen = select_runtime_library(lib_dir, "libtalloc.so.*")

    assert chosen == good, "il symlink pendente non deve essere scelto"


def test_a_real_file_wins_over_a_version_symlink(tmp_path: Path) -> None:
    """Se sono entrambi utilizzabili, il file vero ha la precedenza sul link."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    real = lib_dir / "libtalloc.so.2.5.0"
    real.write_bytes(b"lib")
    (lib_dir / "libtalloc.so.2.5.1").symlink_to(real)

    chosen = select_runtime_library(lib_dir, "libtalloc.so.*")

    assert chosen == real, "fra candidati utilizzabili, il file vero vince"


def test_no_match_is_none_rather_than_an_error(tmp_path: Path) -> None:
    """Nessun candidato non è un'eccezione: la decisione (obbligatoria o no) la
    prende il chiamante in ``copy_abi``, che conosce il flag ``required``."""
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()

    assert select_runtime_library(lib_dir, "libtalloc.so.*") is None


# ---------------------------------------------------------------------------
# copy_abi — un binario mancante è un errore che nomina il pacchetto
# ---------------------------------------------------------------------------


def test_a_missing_required_executable_fails_naming_the_path(tmp_path: Path) -> None:
    """Senza ``bin/proot`` non c'è un runtime: l'errore deve dire qualcosa
    esatto, perché in CI arriva dentro il nome del task Gradle."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix)
    (prefix / "bin" / "proot").unlink()

    with pytest.raises(FileNotFoundError, match=r"bin/proot"):
        copy_abi(tmp_path, tmp_path / "out", "arm64-v8a")


def test_a_missing_required_library_fails_naming_the_pattern(tmp_path: Path) -> None:
    """``libtalloc`` è obbligatoria: l'errore nomina il pattern (``libtalloc.so.*``),
    non un nome che l'haver già risolto — altrimenti non si sa cosa cercare."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix)
    _write_library(prefix, "libandroid-shmem.so")

    with pytest.raises(FileNotFoundError, match=r"libtalloc\.so\.\*"):
        copy_abi(tmp_path, tmp_path / "out", "arm64-v8a")


def test_the_optional_c_library_is_skipped_when_absent(tmp_path: Path) -> None:
    """``libc++_shared.so`` porta ``required=False``: la sua assenza non ferma
    la copia, e il fatto che resti fuori dall'output è il risultato."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix)
    _write_library(prefix, "libandroid-shmem.so")
    _write_library(prefix, "libtalloc.so.2.5.0")

    out = tmp_path / "out"
    copy_abi(tmp_path, out, "arm64-v8a")

    assert not (out / "arm64-v8a" / "libc++_shared.so").exists()


def test_everything_copied_lands_executable(tmp_path: Path) -> None:
    """Le librerie finiscono in ``jniLibs`` e vengono caricate da ``dlopen``: un
    file senza bit di esecuzione non viene mappato, quindi il ``chmod`` conta."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix)
    _write_library(prefix, "libandroid-shmem.so")
    _write_library(prefix, "libtalloc.so.2.5.0")

    out = tmp_path / "out"
    copy_abi(tmp_path, out, "arm64-v8a")

    copied = sorted(p for p in (out / "arm64-v8a").iterdir())
    assert copied, "la copia non ha prodotto nulla"
    for path in copied:
        assert _is_executable(path), f"{path.name} non è eseguibile"


def test_the_talloc_soname_is_patched_down_to_the_shipped_name(tmp_path: Path) -> None:
    """``proot`` porta dentro il nome ``libtalloc.so.2``; in ``jniLibs`` la
    libreria si chiama ``libtalloc.so``, e senza la patch il ``dlopen``
    non la risolve."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix, payload=b"xxlibtalloc.so.2\x00yy")
    _write_library(prefix, "libandroid-shmem.so")
    _write_library(prefix, "libtalloc.so.2.5.0")

    out = tmp_path / "out"
    copy_abi(tmp_path, out, "arm64-v8a")

    payload = (out / "arm64-v8a" / "libopencode_android_proot.so").read_bytes()
    assert b"libtalloc.so\x00" in payload
    assert b"libtalloc.so.2\x00" not in payload


# ---------------------------------------------------------------------------
# patch_needed — la sostituzione non può crescere
# ---------------------------------------------------------------------------


def test_patch_needed_refuses_a_longer_replacement(tmp_path: Path) -> None:
    """Il binario contiene nomi a lunghezza fissa: rimpiazzare ``libtalloc.so.2``
    (15 caratteri) con qualcosa di più lungo sposterebbe tutto quello che segue,
    quindi si rifiuta invece di produrre un file corrotto in silenzio."""
    target = tmp_path / "proot.so"
    target.write_bytes(b"libtalloc.so.2\x00")

    with pytest.raises(ValueError, match="longer"):
        patch_needed(target, "libtalloc.so.2", "libtalloc.so.2.5.0")


def test_patch_needed_is_a_no_op_when_the_needle_is_absent(tmp_path: Path) -> None:
    """Un binario senza quel nome non va riscritto: il file resta com'era."""
    target = tmp_path / "proot.so"
    target.write_bytes(b"qualcos\'altro\x00")
    before = target.read_bytes()

    patch_needed(target, "libtalloc.so.2", "libtalloc.so")

    assert target.read_bytes() == before


def test_patch_needed_pads_so_the_length_does_not_move(tmp_path: Path) -> None:
    """Il nome nuovo è più corto: il resto del binario deve restare dove era,
    quindi il b'\0' finale riempie la differenza invece di accorciare il file."""
    target = tmp_path / "proot.so"
    old = b"libtalloc.so.2\x00"  # 15 byte
    new = b"libtalloc.so\x00" + b"\x00" * 2  # 12 + 1 (il terminatore) + 2 = 15 byte
    target.write_bytes(b"AA" + old + b"BB")
    assert len(target.read_bytes()) == 19

    patch_needed(target, "libtalloc.so.2", "libtalloc.so")

    assert target.read_bytes() == b"AA" + new + b"BB"
    assert len(target.read_bytes()) == 19, "la lunghezza del file non deve cambiare"


def test_patch_needed_ignores_a_path_that_is_not_a_file(tmp_path: Path) -> None:
    """La patch è applicata a un nome noto, ma il file può non esserci: non è
    un errore, è solo niente da patchare."""
    patch_needed(tmp_path / "assente.so", "libtalloc.so.2", "libtalloc.so")


# ---------------------------------------------------------------------------
# native_executable_name — noti, e un nome sanificato per il resto
# ---------------------------------------------------------------------------


def test_known_executables_keep_their_shipped_name() -> None:
    """I tre binari hanno nomi fissi: sono già nella mappa."""
    assert native_executable_name("bin/proot") == "libopencode_android_proot.so"
    assert native_executable_name("libexec/proot/loader") == (
        "libopencode_android_proot_loader.so"
    )


def test_an_unknown_executable_gets_a_sanitised_name() -> None:
    """Un percorso fuori dalla mappa non viene rifiutato: ogni carattere che non
    è alfanumerico diventa ``_``, e un nome vuoto cade su ``command`` — altrimenti
    ``jniLibs`` riceverebbe un file senza nome."""
    assert native_executable_name("bin/proot-distro") == "libopencode_exec_bin_proot_distro.so"
    assert native_executable_name("   ") == "libopencode_exec_command.so"


def test_backslashes_are_normalised_before_sanitising() -> None:
    """Un percorso Windows non deve produrre un nome con backslash dentro."""
    assert "\\" not in native_executable_name("bin\\proot")


# ---------------------------------------------------------------------------
# prepare_native_libs — l'output è ricostruito, non accumulato
# ---------------------------------------------------------------------------


def _write_prefix_for_every_abi(root: Path) -> None:
    """Popola un ``prefix`` completo per ciascun ABI della mappa.

    ``prepare_native_libs`` scorre ``ANDROID_ABIS`` e non perdona un prefix
    mancante: una fixture ne prepara uno solo e si ferma sul secondo ABI, con
    un errore che parla del ``proot`` e non della fixture.
    """
    for abi in ANDROID_ABIS:
        prefix = _make_prefix(root, abi)
        _write_executables(prefix)
        _write_library(prefix, "libandroid-shmem.so")
        _write_library(prefix, "libtalloc.so.2.5.0")


def test_a_stale_output_directory_is_cleared_first(tmp_path: Path) -> None:
    """Un build precedente può aver lasciato dentro un file che questa versione
    non produce più: senza la pulizia quello finisce nell'APK."""
    out = tmp_path / "out"
    stale = out / "arm64-v8a" / "libfantasma.so"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"vecchio")

    _write_prefix_for_every_abi(tmp_path)

    prepare_native_libs(tmp_path, out)

    assert not stale.exists(), "il file fantasma è sopravvissuto alla pulizia"


def test_both_architectures_are_prepared(tmp_path: Path) -> None:
    """Il runtime viene impacchettato per entrambi gli ABI della mappa: senza
    ``x86_64`` l'emulatore non parte, e quello è il device dei test."""
    _write_prefix_for_every_abi(tmp_path)

    out = tmp_path / "out"
    prepare_native_libs(tmp_path, out)

    for abi in ANDROID_ABIS:
        assert (out / abi / "libopencode_android_proot.so").exists(), f"{abi} senza proot"


def test_the_talloc_pattern_in_the_table_is_a_glob() -> None:
    """La voce di talloc deve restare un glob: è la garanzia, e una voce
    ``libtalloc.so`` (senza stella) la renderebbe dipendente dalla versione."""
    assert "libtalloc.so.*" in RUNTIME_LIBRARIES
    assert RUNTIME_LIBRARIES["libtalloc.so.*"][1] is True, "talloc è obbligatoria"


def test_the_output_layout_is_one_directory_per_abi(tmp_path: Path) -> None:
    """Il consumatore (``jniLibs.srcDir``) si aspetta ``<abi>/`` al primo
    livello, non un ``lib/<abi>/`` o un percorso con il nome dell'app."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix)
    _write_library(prefix, "libandroid-shmem.so")
    _write_library(prefix, "libtalloc.so.2.5.0")

    out = tmp_path / "out"
    copy_abi(tmp_path, out, "arm64-v8a")

    assert sorted(p.name for p in out.iterdir()) == ["arm64-v8a"]


def test_copied_libraries_are_real_files_not_symlinks(tmp_path: Path) -> None:
    """In ``jniLibs`` un symlink punta a una destinazione che l'APK non
    contiene: la copia deve materializzare il contenuto."""
    prefix = _make_prefix(tmp_path, "arm64-v8a")
    _write_executables(prefix)
    real = _write_library(prefix, "libtalloc.so.2.5.0")
    (prefix / "lib" / "libtalloc.so").symlink_to(real)
    _write_library(prefix, "libandroid-shmem.so")

    out = tmp_path / "out"
    copy_abi(tmp_path, out, "arm64-v8a")

    shipped = out / "arm64-v8a" / "libtalloc.so"
    assert not shipped.is_symlink()
    assert shipped.read_bytes() == b"lib"


def test_the_script_is_executable_and_has_a_shebang() -> None:
    """Gradle lo esegue come ``python3 <path>``, ma il bit di esecuzione serve
    a chi lo invoca direttamente, e lo shebang è la riga che il build log
    usa per dire da dove è partito."""
    source = Path(__file__).resolve().parents[3] / "jafta/runtime/proot/native_libs.py"
    text = source.read_text(encoding="utf-8")

    assert text.startswith("#!/usr/bin/env python3")
    assert os.access(source, os.X_OK), f"{source} non è eseguibile"
