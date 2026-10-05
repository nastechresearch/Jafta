"""Container ``.jbk`` v2, a segmenti: roundtrip, manomissioni, troncamenti.

Il v2 esiste perché il v1 teneva tutto il payload in un solo GCM, e su Android
nell'heap Java: con un workspace di 310 MB l'export non entrava in 256 MB.
Questi test usano segmenti di pochi byte per vedere i confini senza file grossi.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from jafta.snapshot.crypto import (
    MAGIC,
    MAX_SEGMENT_SIZE,
    SEGMENTED_FORMAT_VERSION,
    SEGMENTED_HEADER_LEN,
    TAG_LEN,
    decrypt_container,
    decrypt_file,
    encrypt_container,
    encrypt_file,
)
from jafta.snapshot.crypto_backends.base import CryptoAuthError

pytest.importorskip("cryptography")

from jafta.snapshot.crypto_backends.dev import DevAesGcmBackend  # noqa: E402

_BACKEND = DevAesGcmBackend()
_ITER = 1000
_PASS = "passphrase àè"
_SEG = 16


async def _encrypt(tmp_path: Path, payload: bytes, *, segment_size: int = _SEG) -> Path:
    source = tmp_path / "plain.zip"
    source.write_bytes(payload)
    dest = tmp_path / "out.jbk"
    written = await encrypt_file(
        _PASS, source, dest, iterations=_ITER, segment_size=segment_size, backend=_BACKEND
    )
    assert written == dest.stat().st_size
    return dest


async def _decrypt(tmp_path: Path, container: Path, passphrase: str = _PASS) -> bytes:
    dest = tmp_path / "back.zip"
    await decrypt_file(passphrase, container, dest, backend=_BACKEND)
    return dest.read_bytes()


def _segments(blob: bytes, segment_size: int = _SEG) -> list[bytes]:
    body = blob[SEGMENTED_HEADER_LEN:]
    step = segment_size + TAG_LEN
    return [body[i : i + step] for i in range(0, len(body), step)]


# I confini che contano: vuoto, meno di un segmento, esattamente uno, un
# multiplo esatto (l'ultimo segmento pieno è il finale, senza un vuoto dopo),
# e un resto.
@pytest.mark.parametrize("size", [0, 1, _SEG - 1, _SEG, _SEG + 1, 3 * _SEG, 3 * _SEG + 5])
async def test_roundtrip_across_segment_boundaries(tmp_path: Path, size: int) -> None:
    payload = bytes(i % 251 for i in range(size))
    container = await _encrypt(tmp_path, payload)

    blob = container.read_bytes()
    assert blob[: len(MAGIC)] == MAGIC
    assert blob[len(MAGIC)] == SEGMENTED_FORMAT_VERSION
    expected_segments = max(1, -(-size // _SEG))
    assert len(_segments(blob)) == expected_segments
    assert await _decrypt(tmp_path, container) == payload
    # Il lettore in memoria dà lo stesso risultato di quello su file.
    assert await decrypt_container(_PASS, blob, backend=_BACKEND) == payload


async def test_every_cipher_call_sees_one_segment_at_most(tmp_path: Path) -> None:
    """È il punto del formato: nessuna chiamata al backend riceve tutto il file."""
    seen: list[int] = []

    class Recording(DevAesGcmBackend):
        async def encrypt(self, key, nonce, plaintext, aad):
            seen.append(len(plaintext))
            return await super().encrypt(key, nonce, plaintext, aad)

        async def decrypt(self, key, nonce, ciphertext, aad):
            seen.append(len(ciphertext))
            return await super().decrypt(key, nonce, ciphertext, aad)

    source = tmp_path / "plain.zip"
    source.write_bytes(b"x" * (10 * _SEG + 3))
    dest = tmp_path / "out.jbk"
    await encrypt_file(
        _PASS, source, dest, iterations=_ITER, segment_size=_SEG, backend=Recording()
    )
    await decrypt_file(_PASS, dest, tmp_path / "back.zip", backend=Recording())

    assert len(seen) == 22
    assert max(seen) <= _SEG + TAG_LEN


async def test_wrong_passphrase_rejected_and_nothing_left(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"segreto" * 10)
    with pytest.raises(CryptoAuthError):
        await _decrypt(tmp_path, container, passphrase="sbagliata")
    assert not (tmp_path / "back.zip").exists()


async def test_tampered_segment_rejected(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"a" * (3 * _SEG))
    blob = bytearray(container.read_bytes())
    blob[SEGMENTED_HEADER_LEN + _SEG + TAG_LEN + 2] ^= 0x01  # dentro il secondo segmento
    container.write_bytes(bytes(blob))
    with pytest.raises(CryptoAuthError):
        await _decrypt(tmp_path, container)
    assert not (tmp_path / "back.zip").exists()


async def test_tampered_header_rejected(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"dati")
    blob = bytearray(container.read_bytes())
    blob[SEGMENTED_HEADER_LEN - 5] ^= 0x01  # ultimo byte del nonce
    container.write_bytes(bytes(blob))
    with pytest.raises(CryptoAuthError):
        await _decrypt(tmp_path, container)


async def test_swapped_segments_rejected(tmp_path: Path) -> None:
    payload = b"A" * _SEG + b"B" * _SEG + b"C" * 3
    container = await _encrypt(tmp_path, payload)
    blob = container.read_bytes()
    first, second, last = _segments(blob)
    container.write_bytes(blob[:SEGMENTED_HEADER_LEN] + second + first + last)
    with pytest.raises(CryptoAuthError):
        await _decrypt(tmp_path, container)


async def test_truncation_on_a_segment_boundary_rejected(tmp_path: Path) -> None:
    """Senza il flag ``final`` nell'AAD, tagliare via l'ultimo segmento passerebbe."""
    container = await _encrypt(tmp_path, b"z" * (3 * _SEG))
    blob = container.read_bytes()
    container.write_bytes(blob[: SEGMENTED_HEADER_LEN + 2 * (_SEG + TAG_LEN)])
    with pytest.raises(CryptoAuthError):
        await _decrypt(tmp_path, container)
    assert not (tmp_path / "back.zip").exists()


async def test_truncation_inside_a_segment_rejected(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"z" * (3 * _SEG))
    blob = container.read_bytes()
    for cut in (SEGMENTED_HEADER_LEN, SEGMENTED_HEADER_LEN + 5, len(blob) - 1):
        container.write_bytes(blob[:cut])
        with pytest.raises(CryptoAuthError):
            await _decrypt(tmp_path, container)


async def test_appended_garbage_rejected(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"z" * (2 * _SEG))
    container.write_bytes(container.read_bytes() + b"\x00" * (_SEG + TAG_LEN))
    with pytest.raises(CryptoAuthError):
        await _decrypt(tmp_path, container)


def _patch_u32(blob: bytes, offset: int, value: int) -> bytes:
    return blob[:offset] + struct.pack(">I", value) + blob[offset + 4 :]


async def test_hostile_segment_size_rejected_before_reading(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"dati")
    offset = SEGMENTED_HEADER_LEN - 4
    for bad in (0, MAX_SEGMENT_SIZE + 1, 0xFFFFFFFF):
        container.write_bytes(_patch_u32(container.read_bytes(), offset, bad))
        with pytest.raises(CryptoAuthError, match="segment size"):
            await _decrypt(tmp_path, container)


async def test_kdf_iteration_bomb_rejected_in_v2(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"dati")
    container.write_bytes(_patch_u32(container.read_bytes(), len(MAGIC) + 1, 0xFFFFFFFF))
    with pytest.raises(CryptoAuthError, match="implausible"):
        await _decrypt(tmp_path, container)


async def test_a_v1_file_still_imports(tmp_path: Path) -> None:
    """I backup esportati prima del v2 restano leggibili."""
    legacy = await encrypt_container(_PASS, b"backup vecchio", iterations=_ITER, backend=_BACKEND)
    container = tmp_path / "old.jbk"
    container.write_bytes(legacy)
    assert await _decrypt(tmp_path, container) == b"backup vecchio"


async def test_unknown_version_rejected(tmp_path: Path) -> None:
    container = await _encrypt(tmp_path, b"dati")
    blob = bytearray(container.read_bytes())
    blob[len(MAGIC)] = 3
    container.write_bytes(bytes(blob))
    with pytest.raises(CryptoAuthError, match="version"):
        await _decrypt(tmp_path, container)


async def test_encrypt_rejects_bad_arguments(tmp_path: Path) -> None:
    source = tmp_path / "p"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        await encrypt_file("", source, tmp_path / "o", backend=_BACKEND)
    with pytest.raises(ValueError):
        await encrypt_file(_PASS, source, tmp_path / "o", segment_size=0, backend=_BACKEND)


# Riferimento cross-implementazione, come i KAT del v1: stessi input, stessi byte
# anche col backend javax del telefono.
KAT_SALT = bytes(range(16))
KAT_NONCE = bytes(range(12))
KAT_PLAINTEXT = b"contenuto segreto del backup, in due segmenti"
KAT_SEGMENT_SIZE = 32


async def test_v2_known_answer(tmp_path: Path) -> None:
    source = tmp_path / "plain"
    source.write_bytes(KAT_PLAINTEXT)
    dest = tmp_path / "kat.jbk"
    await encrypt_file(
        "passphrase-di-prova",
        source,
        dest,
        iterations=_ITER,
        segment_size=KAT_SEGMENT_SIZE,
        backend=_BACKEND,
        _salt=KAT_SALT,
        _nonce=KAT_NONCE,
    )
    assert dest.read_bytes().hex() == KAT_CONTAINER_V2_HEX


# Ricavato dalla spec nel docstring di ``crypto.py`` con ``AESGCM`` grezzo, non
# da ``encrypt_file``: header a mano, nonce_i e aad_i a mano, due segmenti.
KAT_CONTAINER_V2_HEX = (
    "4a4e424b02000003e8000102030405060708090a0b0c0d0e0f000102030405060708090a0b00000020"
    "d7f2633b425e70fd8d7107b892f69736c5b62d0b792c4cd7fe2e828232c02fc3a36ce236e7d71c284d8e42a5"
    "cb6925a40e1692fda1d30136ec5bcdf5ea2d78a1abb0f102ec7e773bb2a52ded5b"
)
