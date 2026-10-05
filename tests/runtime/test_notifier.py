"""Test per jafta/runtime/notifier.py (alert di sistema Android).

Il bridge Chaquopy non esiste nei test desktop: si verifica la derivazione
pura dei campi (``alert_fields``), il no-op senza contesto Android e il
percorso completo con un bridge finto.
"""

from __future__ import annotations

import asyncio
from typing import Any

from jafta.runtime import notifier
from jafta.webui.metadata import WEBUI_MESSAGE_SOURCE_METADATA_KEY


class _FakeBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.result = True

    def postAlert(self, title: str, body: str, tag: str) -> bool:  # noqa: N802
        self.calls.append((title, body, tag))
        return self.result


def _meta(kind: str, label: str | None = None) -> dict[str, Any]:
    source: dict[str, str] = {"kind": kind}
    if label is not None:
        source["label"] = label
    return {WEBUI_MESSAGE_SOURCE_METADATA_KEY: source}


class TestAlertFields:
    def test_cron_with_label(self):
        title, body, tag = notifier.alert_fields("ricordati il pane", _meta("cron", "spesa"))
        assert title == "Jafta ⏰ spesa"
        assert tag == "cron:spesa"
        assert body == "ricordati il pane"

    def test_cron_without_label(self):
        title, _, tag = notifier.alert_fields("ping", _meta("cron"))
        assert title == "Jafta ⏰ promemoria"
        assert tag == "cron"

    def test_cron_blank_label_falls_back(self):
        title, _, tag = notifier.alert_fields("ping", _meta("cron", "   "))
        assert title == "Jafta ⏰ promemoria"
        assert tag == "cron"

    def test_heartbeat(self):
        title, _, tag = notifier.alert_fields("evento X accaduto", _meta("heartbeat"))
        assert title == "Jafta · monitoraggio"
        assert tag == "heartbeat"

    def test_update(self):
        # Tag dedicato: l'annuncio in chat e l'alert esplicito di un update
        # critico coalizzano invece di suonare due volte.
        title, _, tag = notifier.alert_fields("nuova versione 0.7.0", _meta("update"))
        assert title == "Jafta · aggiornamento"
        assert tag == "update"

    def test_plain_message_defaults(self):
        for metadata in (None, {}, {"latency_ms": 3}):
            title, _, tag = notifier.alert_fields("ciao", metadata)
            assert title == "Jafta"
            assert tag == "message"

    def test_malformed_source_is_ignored(self):
        title, _, tag = notifier.alert_fields(
            "ciao", {WEBUI_MESSAGE_SOURCE_METADATA_KEY: "cron"}
        )
        assert title == "Jafta"
        assert tag == "message"

    def test_body_collapses_whitespace_and_truncates(self):
        _, body, _ = notifier.alert_fields("riga1\n\n  riga2\t fine", None)
        assert body == "riga1 riga2 fine"
        _, long_body, _ = notifier.alert_fields("x" * 500, None)
        assert len(long_body) == notifier._BODY_MAX_CHARS
        assert long_body.endswith("…")

    def test_empty_body_placeholder(self):
        _, body, _ = notifier.alert_fields("   \n  ", None)
        assert body == "Nuovo messaggio"


class TestPostAlert:
    async def test_noop_without_android_context(self, monkeypatch):
        monkeypatch.setattr(notifier, "get_android_context", lambda: None)
        assert await notifier.post_alert("ciao", None) is False

    async def test_posts_via_bridge(self, monkeypatch):
        bridge = _FakeBridge()
        monkeypatch.setattr(notifier, "get_android_context", lambda: object())

        async def fake_get_bridge(context: Any) -> Any:
            return bridge

        monkeypatch.setattr(notifier, "_get_bridge", fake_get_bridge)
        ok = await notifier.post_alert("ricordati il pane", _meta("cron", "spesa"))
        assert ok is True
        assert bridge.calls == [("Jafta ⏰ spesa", "ricordati il pane", "cron:spesa")]

    async def test_thread_overrides_the_tag_and_leaves_the_title(self, monkeypatch):
        """Il canale della tendina passa un thread unico.

        Il tag dice *dove* va la notifica — e le risposte dell'agente devono
        coalizzare su una voce sola invece di impilarsi una per messaggio — ma
        il titolo continua a dire *di cosa parla*, quindi resta quello che
        ``alert_fields`` deriva dai metadata.
        """
        bridge = _FakeBridge()
        monkeypatch.setattr(notifier, "get_android_context", lambda: object())

        async def fake_get_bridge(context: Any) -> Any:
            return bridge

        monkeypatch.setattr(notifier, "_get_bridge", fake_get_bridge)
        await notifier.post_alert("ecco", _meta("cron", "spesa"), thread="chat")
        assert bridge.calls == [("Jafta ⏰ spesa", "ecco", "chat")]

    async def test_without_thread_nothing_changes(self, monkeypatch):
        """Gli avvisi proattivi tengono i loro tag distinti."""
        bridge = _FakeBridge()
        monkeypatch.setattr(notifier, "get_android_context", lambda: object())

        async def fake_get_bridge(context: Any) -> Any:
            return bridge

        monkeypatch.setattr(notifier, "_get_bridge", fake_get_bridge)
        await notifier.post_alert("ecco", _meta("heartbeat"), thread=None)
        assert bridge.calls[0][2] == "heartbeat"

    async def test_bridge_error_is_swallowed(self, monkeypatch):
        monkeypatch.setattr(notifier, "get_android_context", lambda: object())

        async def broken_get_bridge(context: Any) -> Any:
            raise RuntimeError("no chaquopy here")

        monkeypatch.setattr(notifier, "_get_bridge", broken_get_bridge)
        assert await notifier.post_alert("ciao", None) is False


class TestNotifyDelivery:
    async def test_noop_without_android_context(self, monkeypatch):
        monkeypatch.setattr(notifier, "get_android_context", lambda: None)
        notifier.notify_delivery("ciao", None)
        assert not notifier._TASKS

    async def test_schedules_fire_and_forget_task(self, monkeypatch):
        bridge = _FakeBridge()
        monkeypatch.setattr(notifier, "get_android_context", lambda: object())

        async def fake_get_bridge(context: Any) -> Any:
            return bridge

        monkeypatch.setattr(notifier, "_get_bridge", fake_get_bridge)
        notifier.notify_delivery("evento X", _meta("heartbeat"))
        assert notifier._TASKS
        await asyncio.gather(*notifier._TASKS)
        assert bridge.calls == [("Jafta · monitoraggio", "evento X", "heartbeat")]
        assert not notifier._TASKS
