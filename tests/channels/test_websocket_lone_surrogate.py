"""Un surrogato isolato nel messaggio non cancella la riga utente dal transcript.

``json.loads`` produce un surrogato isolato da un frame tagliato a metà di
un'emoji (``"\\ud83d"``), e in UTF-8 non esiste: la riga utente si scriveva nel
transcript *prima* della pulizia (che avviene più avanti, nel loop), la sua
codifica falliva, e il messaggio spariva dalla cronologia della WebUI mentre
l'agente gli rispondeva.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jafta.channels.websocket import WebSocketChannel, WebSocketConfig
from jafta.webui.gateway_services import build_gateway_services
from jafta.webui.transcript import read_transcript_lines


@pytest.fixture(autouse=True)
def isolate_webui_workspace_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jafta.config.paths.get_data_dir", lambda: tmp_path)


def _make_channel() -> WebSocketChannel:
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    cfg = {"enabled": True, "allowFrom": ["*"], "websocketRequiresToken": False}
    gateway = build_gateway_services(
        config=WebSocketConfig.model_validate(cfg), bus=bus, session_manager=None,
        workspace_path=Path.cwd(), default_restrict_to_workspace=False,
        runtime_model_name=None,
    )
    channel = WebSocketChannel(cfg, bus, gateway=gateway)
    channel._handle_message = AsyncMock()  # type: ignore[method-assign]
    return channel


async def test_a_lone_surrogate_keeps_the_user_row_in_the_transcript() -> None:
    channel = _make_channel()
    envelope = {"type": "message", "chat_id": "default", "content": "ciao \ud83d a te"}

    await channel._dispatch_envelope(AsyncMock(), "client-1", envelope)

    rows = read_transcript_lines("websocket:default")
    users = [row for row in rows if row.get("event") == "user"]
    assert [row.get("text") for row in users] == ["ciao � a te"]
    assert channel._handle_message.call_args.kwargs["content"] == "ciao � a te"
