"""Due KDoc che vendevano come barriera ciò che non lo è.

Il codice resta com'è — tutti e due i
controlli sono giusti — ma il commento diceva di più, e un commento di
sicurezza che promette troppo è peggio di nessuno: chi lo legge smette di
cercare.

- ``NativeCommandListener`` esige ``isMainFrame`` «perché nessuna
  cornice — nemmeno della stessa origine — ha motivo di parlare col nativo».
  Una cornice della stessa origine non ne ha bisogno: raggiunge
  ``parent.JaftaNativePort`` e lo chiama da lì, col frame principale come
  mittente. La barriera è l'origine; il frame principale è difesa in profondità.
- ``ReplyReceiver`` «lo raggiunge solo il nostro PendingIntent, che
  porta la nostra identità». Quello della risposta è mutabile: un'app con
  l'accesso alle notifiche lo manda con un testo suo.

Qui si leggono **i commenti**, apposta: è il loro contenuto a essere il difetto.
"""

from __future__ import annotations

import re
from pathlib import Path

from support.kotlin_source import function_body, read_code, read_comments

MANIFEST = Path(__file__).resolve().parents[2] / "android/app/src/main/AndroidManifest.xml"


def test_the_main_frame_check_is_called_defence_in_depth() -> None:
    comments = read_comments("MainActivity")
    assert "difesa in profondità" in comments
    assert "parent.JaftaNativePort" in comments
    assert "nemmeno una della stessa origine" not in comments, (
        "il KDoc torna a dire che isMainFrame ferma una cornice della stessa origine"
    )
    # E il codice il controllo lo fa ancora: difesa in profondità, non tolta.
    code = read_code("MainActivity")
    body = function_body(code, "onPostMessage")
    assert "!isMainFrame || !isGatewayOrigin(sourceOrigin)" in body


def test_the_reply_receiver_says_its_pending_intent_is_mutable() -> None:
    comments = read_comments("ReplyReceiver")
    assert "mutabile" in comments and "accesso alle notifiche" in comments
    assert "l'unica cosa che lo raggiunge" not in comments
    notifier = read_comments("NotifierBridge")
    assert "chiunque tenga" in notifier


def test_the_manifest_comment_does_not_call_the_reply_receiver_closed() -> None:
    xml = MANIFEST.read_text(encoding="utf-8")
    block = re.search(r"<!-- Risposta rapida dalla tendina\..*?-->", xml, re.S)
    assert block, "commento del ReplyReceiver non trovato nel manifest"
    assert "l'unica cosa che lo raggiunge" not in block.group(0)
    assert "mutabile" in block.group(0)
