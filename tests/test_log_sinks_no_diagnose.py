"""Un traceback nel log non porta i valori delle variabili locali.

Il sink di default di loguru ha ``diagnose=True``: ogni ``logger.exception``
stampa il valore di ogni locale di ogni frame, e un'eccezione in una route
autenticata ci metteva il segreto del gateway (o una chiave API passata in
query) sia su logcat sia nel buffer che il modello legge con
``get_recent_logs``. ``run_gateway`` sostituisce il sink di default e il
buffer nasce senza ``diagnose``.
"""

from __future__ import annotations

import hmac

import pytest
from loguru import logger

from jafta import android_entry
from jafta.agent.tools import diagnostics

SECRET = "zz-gateway-secret-4815162342"


@pytest.fixture
def _log_state(monkeypatch):
    """Sink e buffer freschi; alla fine loguru torna com'era."""
    had_default = 0 in logger._core.handlers  # type: ignore[attr-defined]
    monkeypatch.setattr(android_entry, "_STDERR_SINK_ID", None)
    monkeypatch.setattr(diagnostics, "_SINK_ID", None)
    diagnostics._LOG_BUFFER.clear()
    yield
    for sink_id in (android_entry._STDERR_SINK_ID, diagnostics._SINK_ID):
        if sink_id is not None:
            logger.remove(sink_id)
    diagnostics._LOG_BUFFER.clear()
    if had_default:
        # ``configure_log_sinks`` ha tolto il sink di default: i test successivi
        # della sessione lo ritrovano (con un id nuovo, l'unica differenza).
        import sys

        logger.add(sys.stderr)


def _check_token(supplied: str) -> None:
    # Il vecchio confronto di ``http_utils``: con ``diagnose`` il traceback
    # stampa il valore di ``supplied`` e di ``secret`` sotto questa riga.
    secret = SECRET
    hmac.compare_digest(supplied, secret)


def test_logged_traceback_carries_no_local_values(_log_state, capsys) -> None:
    android_entry.configure_log_sinks()
    diagnostics.install_log_buffer()

    try:
        # Costruito a pezzi: la riga sorgente, che il traceback cita, non lo contiene.
        _check_token("s" + chr(0xE9) + "cret")
    except TypeError:
        logger.exception("request failed")
    logger.opt(exception=True).error("second path")  # fuori da un except: nessun traceback

    stderr = capsys.readouterr().err
    buffered = "\n".join(diagnostics._LOG_BUFFER)
    # Il traceback c'è (il sink non è muto) ...
    assert "request failed" in stderr and "TypeError" in stderr
    assert "request failed" in buffered and "TypeError" in buffered
    # ... ma senza i valori delle locali.
    assert SECRET not in stderr
    assert SECRET not in buffered
    assert "sécret" not in stderr
    assert "sécret" not in buffered


def test_configure_log_sinks_is_idempotent(_log_state) -> None:
    android_entry.configure_log_sinks()
    first = android_entry._STDERR_SINK_ID
    android_entry.configure_log_sinks()
    assert android_entry._STDERR_SINK_ID == first
