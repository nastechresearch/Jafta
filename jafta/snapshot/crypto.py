"""Formato del container di backup cifrato (file ``.jbk``).

Due versioni, la stessa chiave. Chiave = PBKDF2-HMAC-SHA256(passphrase, salt,
iterations, 32 byte) — tutto stdlib, identico su Android e desktop.

**Versione 1** (monolitica, ormai solo in lettura): header di 37 byte legato
come AAD, così ogni manomissione dell'header invalida il tag:

    magic ``JNBK`` (4) | version=1 (1) | kdf_iterations uint32 BE (4)
    | salt (16) | nonce (12) | ciphertext+tag AES-256-GCM (resto)

Un solo GCM su tutto il payload vuol dire tutto il payload in memoria, e su
Android dentro l'heap Java: ``javax.crypto`` (Conscrypt) accumula l'input fino
a ``doFinal`` anche se glielo si passa a pezzi. Con un workspace di 310 MB e un
heap da 256 MB l'export non può riuscire.

**Versione 2** (a segmenti, quella che si scrive): header di 41 byte

    magic ``JNBK`` (4) | version=2 (1) | kdf_iterations uint32 BE (4)
    | salt (16) | nonce (12) | segment_size uint32 BE (4)

seguito dai segmenti: il payload in chiaro tagliato a ``segment_size`` byte,
ognuno cifrato a parte (ciphertext+tag, quindi ``segment_size + 16`` byte,
l'ultimo più corto o uguale). Per il segmento *i*:

    nonce_i = nonce[:4] | (nonce[4:] XOR i come uint64 BE)
    aad_i   = header | i uint64 BE (8) | final (1: 0x01 sull'ultimo, 0x00 prima)

L'indice nel nonce e nell'AAD impedisce di riordinare i segmenti; il flag
``final`` di troncare il file su un confine di segmento (il lettore decifra
l'ultimo segmento che trova come finale, e un segmento non finale lì non
autentica). Un payload vuoto è un solo segmento finale vuoto. La chiave è
nuova per ogni file (salt casuale), quindi l'unicità dei nonce va garantita
solo dentro il file, e la dà il contatore.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import secrets
import struct
from collections.abc import Awaitable, Callable
from pathlib import Path

from jafta.snapshot.crypto_backends.base import CryptoAuthError, CryptoBackend

MAGIC = b"JNBK"
FORMAT_VERSION = 1
SEGMENTED_FORMAT_VERSION = 2
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32
TAG_LEN = 16
HEADER_LEN = len(MAGIC) + 1 + 4 + SALT_LEN + NONCE_LEN  # 37
SEGMENTED_HEADER_LEN = HEADER_LEN + 4  # 41
# 1 MiB: nell'heap Java ne passano due copie per chiamata (ingresso e uscita),
# un ordine di grandezza sotto qualunque heap Android.
DEFAULT_SEGMENT_SIZE = 1 << 20
# Tetto sul segment_size dichiarato: senza, un header ostile farebbe leggere al
# lettore un segmento da 4 GB in memoria in un colpo solo.
MAX_SEGMENT_SIZE = 64 << 20
DEFAULT_KDF_ITERATIONS = 600_000
# Tetto sulle iterazioni dichiarate nell'header: l'AAD rivela la manomissione
# solo DOPO la KDF, quindi senza tetto un file corrotto/ostile con
# iterations=2^32-1 terrebbe la CPU occupata per ore prima di fallire.
MAX_KDF_ITERATIONS = 10_000_000
BACKUP_FILE_EXTENSION = ".jbk"


def derive_key(passphrase: str, salt: bytes, iterations: int) -> bytes:
    """Deriva la chiave AES dalla passphrase (PBKDF2-HMAC-SHA256, stdlib)."""
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, iterations, dklen=KEY_LEN
    )


def build_header(iterations: int, salt: bytes, nonce: bytes) -> bytes:
    if len(salt) != SALT_LEN or len(nonce) != NONCE_LEN:
        raise ValueError("invalid salt/nonce length")
    return MAGIC + bytes([FORMAT_VERSION]) + struct.pack(">I", iterations) + salt + nonce


def parse_header(data: bytes) -> tuple[int, bytes, bytes]:
    """Valida e spacchetta l'header; ritorna ``(iterations, salt, nonce)``.

    Raises:
        CryptoAuthError: file troppo corto, magic errato o versione ignota.
    """
    if len(data) <= HEADER_LEN:
        raise CryptoAuthError("not a Jafta backup file (truncated)")
    if data[: len(MAGIC)] != MAGIC:
        raise CryptoAuthError("not a Jafta backup file (bad magic)")
    version = data[len(MAGIC)]
    if version != FORMAT_VERSION:
        raise CryptoAuthError(f"unsupported backup format version {version}")
    offset = len(MAGIC) + 1
    (iterations,) = struct.unpack(">I", data[offset : offset + 4])
    if not 1 <= iterations <= MAX_KDF_ITERATIONS:
        raise CryptoAuthError(f"implausible KDF iteration count {iterations} (corrupt header)")
    offset += 4
    salt = data[offset : offset + SALT_LEN]
    offset += SALT_LEN
    nonce = data[offset : offset + NONCE_LEN]
    return iterations, salt, nonce


def get_crypto_backend() -> CryptoBackend:
    """Backend AES-GCM per l'ambiente corrente (javax su Android, dev altrove)."""
    from jafta.runtime.context import get_android_context

    if get_android_context() is not None:
        from jafta.snapshot.crypto_backends.android import AndroidAesGcmBackend

        return AndroidAesGcmBackend()
    from jafta.snapshot.crypto_backends.dev import DevAesGcmBackend

    return DevAesGcmBackend()


async def encrypt_container(
    passphrase: str,
    plaintext: bytes,
    *,
    iterations: int = DEFAULT_KDF_ITERATIONS,
    backend: CryptoBackend | None = None,
    _salt: bytes | None = None,
    _nonce: bytes | None = None,
) -> bytes:
    """Cifra ``plaintext`` in un container ``.jbk`` completo.

    ``_salt``/``_nonce`` esistono SOLO per i test (known-answer test vector);
    in produzione sono sempre generati con ``secrets``.
    """
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    if not 1 <= iterations <= MAX_KDF_ITERATIONS:
        raise ValueError(f"kdf iterations out of range: {iterations}")
    backend = backend or get_crypto_backend()
    salt = _salt if _salt is not None else secrets.token_bytes(SALT_LEN)
    nonce = _nonce if _nonce is not None else secrets.token_bytes(NONCE_LEN)
    header = build_header(iterations, salt, nonce)
    # PBKDF2 con centinaia di migliaia di iterazioni è CPU-bound: off-thread.
    key = await asyncio.to_thread(derive_key, passphrase, salt, iterations)
    ciphertext = await backend.encrypt(key, nonce, plaintext, header)
    return header + ciphertext


async def decrypt_container(
    passphrase: str,
    data: bytes,
    *,
    backend: CryptoBackend | None = None,
) -> bytes:
    """Decifra in memoria un container ``.jbk``, v1 o v2.

    Per un file vero c'è :func:`decrypt_file`, che non lo tiene tutto in RAM.

    Raises:
        CryptoAuthError: formato non riconosciuto, passphrase errata o dato
            corrotto/manomesso (header incluso, essendo legato come AAD).
    """
    backend = backend or get_crypto_backend()
    if _read_version(data) == SEGMENTED_FORMAT_VERSION:
        source = io.BytesIO(data)
        chunks: list[bytes] = []

        async def read(size: int) -> bytes:
            return source.read(size)

        async def write(chunk: bytes) -> None:
            chunks.append(chunk)

        await _decrypt_segments(passphrase, read, write, backend)
        return b"".join(chunks)
    iterations, salt, nonce = parse_header(data)
    header = data[:HEADER_LEN]
    ciphertext = data[HEADER_LEN:]
    key = await asyncio.to_thread(derive_key, passphrase, salt, iterations)
    return await backend.decrypt(key, nonce, ciphertext, header)


# -- versione 2: a segmenti, da file a file ---------------------------------------


def build_segmented_header(
    iterations: int, salt: bytes, nonce: bytes, segment_size: int
) -> bytes:
    if len(salt) != SALT_LEN or len(nonce) != NONCE_LEN:
        raise ValueError("invalid salt/nonce length")
    return (
        MAGIC
        + bytes([SEGMENTED_FORMAT_VERSION])
        + struct.pack(">I", iterations)
        + salt
        + nonce
        + struct.pack(">I", segment_size)
    )


def _segment_nonce(nonce: bytes, index: int) -> bytes:
    counter = int.from_bytes(nonce[4:], "big") ^ index
    return nonce[:4] + counter.to_bytes(8, "big")


def _segment_aad(header: bytes, index: int, final: bool) -> bytes:
    return header + struct.pack(">QB", index, 1 if final else 0)


def _read_version(prefix: bytes) -> int:
    """Magic e versione di un container; *prefix* sono i suoi primi byte."""
    if len(prefix) <= len(MAGIC):
        raise CryptoAuthError("not a Jafta backup file (truncated)")
    if prefix[: len(MAGIC)] != MAGIC:
        raise CryptoAuthError("not a Jafta backup file (bad magic)")
    version = prefix[len(MAGIC)]
    if version not in (FORMAT_VERSION, SEGMENTED_FORMAT_VERSION):
        raise CryptoAuthError(f"unsupported backup format version {version}")
    return version


def _parse_segmented_header(header: bytes) -> tuple[int, bytes, bytes, int]:
    """``(iterations, salt, nonce, segment_size)`` di un header v2 completo."""
    if len(header) < SEGMENTED_HEADER_LEN:
        raise CryptoAuthError("not a Jafta backup file (truncated)")
    offset = len(MAGIC) + 1
    (iterations,) = struct.unpack(">I", header[offset : offset + 4])
    if not 1 <= iterations <= MAX_KDF_ITERATIONS:
        raise CryptoAuthError(f"implausible KDF iteration count {iterations} (corrupt header)")
    offset += 4
    salt = header[offset : offset + SALT_LEN]
    offset += SALT_LEN
    nonce = header[offset : offset + NONCE_LEN]
    offset += NONCE_LEN
    (segment_size,) = struct.unpack(">I", header[offset : offset + 4])
    if not 1 <= segment_size <= MAX_SEGMENT_SIZE:
        raise CryptoAuthError(f"implausible segment size {segment_size} (corrupt header)")
    return iterations, salt, nonce, segment_size


def _fsync_and_close(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


async def encrypt_file(
    passphrase: str,
    source: Path,
    dest: Path,
    *,
    iterations: int = DEFAULT_KDF_ITERATIONS,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
    backend: CryptoBackend | None = None,
    _salt: bytes | None = None,
    _nonce: bytes | None = None,
) -> int:
    """Cifra il file *source* in un container v2 scritto in *dest*.

    In memoria c'è un segmento alla volta, qualunque sia la dimensione del
    file. Ritorna i byte scritti. *dest* viene sovrascritto; se la cifratura
    fallisce a metà resta un file parziale, e toglierlo è del chiamante (che
    scrive comunque su un nome temporaneo).
    """
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    if not 1 <= iterations <= MAX_KDF_ITERATIONS:
        raise ValueError(f"kdf iterations out of range: {iterations}")
    if not 1 <= segment_size <= MAX_SEGMENT_SIZE:
        raise ValueError(f"segment size out of range: {segment_size}")
    backend = backend or get_crypto_backend()
    salt = _salt if _salt is not None else secrets.token_bytes(SALT_LEN)
    nonce = _nonce if _nonce is not None else secrets.token_bytes(NONCE_LEN)
    header = build_segmented_header(iterations, salt, nonce, segment_size)
    key = await asyncio.to_thread(derive_key, passphrase, salt, iterations)

    written = 0
    src = await asyncio.to_thread(open, source, "rb")
    try:
        out = await asyncio.to_thread(open, dest, "wb")
        try:
            await asyncio.to_thread(out.write, header)
            written += len(header)
            chunk = await asyncio.to_thread(src.read, segment_size)
            index = 0
            while True:
                # Si sa se un segmento è l'ultimo solo leggendo il successivo.
                nxt = (
                    await asyncio.to_thread(src.read, segment_size)
                    if len(chunk) == segment_size
                    else b""
                )
                final = not nxt
                sealed = await backend.encrypt(
                    key,
                    _segment_nonce(nonce, index),
                    chunk,
                    _segment_aad(header, index, final),
                )
                await asyncio.to_thread(out.write, sealed)
                written += len(sealed)
                if final:
                    break
                chunk, index = nxt, index + 1
        finally:
            await asyncio.to_thread(_fsync_and_close, out)
    finally:
        src.close()
    return written


async def decrypt_file(
    passphrase: str,
    source: Path,
    dest: Path,
    *,
    backend: CryptoBackend | None = None,
) -> None:
    """Decifra il container *source* (v1 o v2) nel file in chiaro *dest*.

    Un v2 si decifra un segmento alla volta; un v1 è monolitico per
    costruzione e passa tutto in memoria, com'è sempre stato. Se qualcosa non
    autentica *dest* viene tolto: un file in chiaro a metà non deve restare
    dove il chiamante lo aprirebbe.

    Raises:
        CryptoAuthError: formato non riconosciuto, passphrase errata, dato
            corrotto, manomesso, riordinato o troncato.
    """
    backend = backend or get_crypto_backend()
    try:
        await _decrypt_file(passphrase, source, dest, backend)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


async def _decrypt_file(
    passphrase: str, source: Path, dest: Path, backend: CryptoBackend
) -> None:
    src = await asyncio.to_thread(open, source, "rb")
    try:
        prefix = await asyncio.to_thread(src.read, len(MAGIC) + 1)
        if _read_version(prefix) == FORMAT_VERSION:
            rest = await asyncio.to_thread(src.read)
            plaintext = await decrypt_container(passphrase, prefix + rest, backend=backend)
            await asyncio.to_thread(dest.write_bytes, plaintext)
            return
        out = await asyncio.to_thread(open, dest, "wb")
        try:
            pending = [prefix]

            async def read(size: int) -> bytes:
                # Il prefisso già letto per la versione torna per primo.
                if pending:
                    head = pending.pop()
                    return head + await asyncio.to_thread(src.read, size - len(head))
                return await asyncio.to_thread(src.read, size)

            async def write(chunk: bytes) -> None:
                await asyncio.to_thread(out.write, chunk)

            await _decrypt_segments(passphrase, read, write, backend)
        finally:
            await asyncio.to_thread(_fsync_and_close, out)
    finally:
        src.close()


async def _decrypt_segments(
    passphrase: str,
    read: Callable[[int], Awaitable[bytes]],
    write: Callable[[bytes], Awaitable[None]],
    backend: CryptoBackend,
) -> None:
    """Il ciclo del lettore v2, uguale per un file e per dei byte in memoria."""
    header = await read(SEGMENTED_HEADER_LEN)
    iterations, salt, nonce, segment_size = _parse_segmented_header(header)
    key = await asyncio.to_thread(derive_key, passphrase, salt, iterations)
    sealed_size = segment_size + TAG_LEN
    chunk = await read(sealed_size)
    index = 0
    while True:
        if len(chunk) < TAG_LEN:
            raise CryptoAuthError("not a Jafta backup file (truncated)")
        # Come in scrittura: è l'ultimo se dopo non c'è più niente.
        nxt = await read(sealed_size) if len(chunk) == sealed_size else b""
        final = not nxt
        plain = await backend.decrypt(
            key,
            _segment_nonce(nonce, index),
            chunk,
            _segment_aad(header, index, final),
        )
        await write(plain)
        if final:
            return
        chunk, index = nxt, index + 1
