"""Riconoscimento endpoint e budget HTTP, condivisi fra i provider (modulo "leaf").

Un endpoint in loopback e uno remoto meritano attese diverse, e la differenza non
dipende dal wire-format: prima del primo token un model server locale sta
macinando il prompt e il silenzio è previsto, mentre su un endpoint remoto lo
stesso silenzio è un blocco. Quella distinzione viveva solo fra gli helper
OpenAI-compat, così il ramo Anthropic si è ritrovato un ``timeout=120`` scritto
a mano, senza override e senza il caso locale — e quel 120 tagliava la richiesta
prima che il budget lungo per il primo token (300s) potesse scadere.

Leaf-level: solo stdlib + loguru. La lettura degli env knob sta in
``config/runtime_env.py``, che è la loro casa.
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

from jafta.config.runtime_env import (
    llm_http_timeout_s,
    resolve_first_output_timeout_s,
    resolve_stream_idle_timeout_s,
)

__all__ = [
    "DEFAULT_REQUEST_TIMEOUT_S",
    "LOCAL_REQUEST_TIMEOUT_S",
    "FIRST_OUTPUT_READ_MARGIN_S",
    "is_local_endpoint",
    "read_timeout_s",
    "request_timeout_s",
]

DEFAULT_REQUEST_TIMEOUT_S = 120.0
# Un model server in loopback macina il prompt prima di emettere il primo
# token, e in quella fase la connessione resta muta: su llama.cpp on-device i
# soli schemi tool sono ~5.800 token, cioè minuti di prompt processing. Il
# limite dei provider remoti taglierebbe ogni richiesta prima della risposta.
LOCAL_REQUEST_TIMEOUT_S = 600.0


def is_local_endpoint(api_base: str | None) -> bool:
    """Return True when the endpoint is a loopback-only model server.

    On Android the app sandbox cannot reach LAN or Docker hosts, so only
    localhost/loopback addresses are considered local.
    """
    if not api_base:
        return False
    raw = api_base.strip().lower()
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    try:
        host = parsed.hostname
    except ValueError:
        return False
    if host == "localhost":
        return True
    if not host:
        return False
    try:
        addr = ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback


def request_timeout_s(*, local: bool = False) -> float:
    """Timeout HTTP per una richiesta al modello, con override da env.

    *local* alza il limite per gli endpoint in loopback. L'override vale per
    entrambi i casi; il nome storico ``JAFTA_OPENAI_COMPAT_TIMEOUT_S`` resta
    valido, ma non è provider-specifico e non lo è mai stato.
    """
    default = LOCAL_REQUEST_TIMEOUT_S if local else DEFAULT_REQUEST_TIMEOUT_S
    return llm_http_timeout_s(default)


# Quanto la read timeout di httpx sta *dopo* il budget del primo token: il
# silenzio lo deve misurare quel budget (che dice «nessun output entro N
# secondi»), non un ``ReadTimeout`` anonimo qualche istante prima.
FIRST_OUTPUT_READ_MARGIN_S = 10.0


def read_timeout_s(*, local: bool = False) -> float:
    """Read timeout di httpx per una richiesta al modello.

    Mai sotto il budget del primo token (``resolve_first_output_timeout_s``):
    prima un endpoint remoto aveva 120 s di read contro 300 di budget, e un
    modello che ragiona in silenzio veniva tagliato da httpx a 120 s — con i
    retry, ~8 minuti per un errore che diceva solo ``ReadTimeout``. Connect,
    write e pool restano a ``request_timeout_s``: una connessione che non si apre
    non ha niente a che fare col modello che pensa.
    """
    # Lo stream aspetta il primo output ``max(primo token, idle)``: è quello il
    # silenzio più lungo che può misurare, e la read deve starci sopra.
    stream_budget = max(resolve_first_output_timeout_s(local=local), resolve_stream_idle_timeout_s())
    return max(request_timeout_s(local=local), stream_budget + FIRST_OUTPUT_READ_MARGIN_S)
