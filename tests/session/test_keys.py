"""Test del modello delle chiavi di sessione (unified + chiavi interne).

La conversazione utente è UNA sessione unificata (``unified:default``); il
lavoro interno (Dream, cron) usa chiavi separate via ``session_key_override``.
Questo contratto regge il routing di tutto il gateway: cambiare i valori
letterali romperebbe le sessioni già persistite su disco.
"""

from __future__ import annotations

import pytest

from jafta.session.keys import UNIFIED_SESSION_KEY, session_key_for_channel


def test_unified_key_literal_is_stable() -> None:
    """Il valore è persistito nei file di sessione: non deve cambiare mai."""
    assert UNIFIED_SESSION_KEY == "unified:default"


@pytest.mark.parametrize(
    ("channel", "chat_id"),
    [
        ("websocket", "default"),
        ("websocket", "altro-chat"),
        ("qualunque", "qualunque"),
        ("", ""),
    ],
)
def test_every_channel_chat_maps_to_unified(channel: str, chat_id: str) -> None:
    assert session_key_for_channel(channel, chat_id) == UNIFIED_SESSION_KEY


def test_dream_keys_never_collide_with_unified() -> None:
    """Le chiavi interne di Dream vivono in un namespace separato (``dream:``)."""
    from jafta.agent.memory import MemoryStore

    key = MemoryStore.dream_session_key()
    assert key.startswith("dream:")
    assert key != UNIFIED_SESSION_KEY


@pytest.mark.parametrize("chat_id", ["default", "altro-chat", "12345"])
def test_mapping_a_chat_id_does_not_warn_about_an_unknown_key(chat_id: str) -> None:
    """Un ``chat_id`` non e' una session key.

    ``session_key_for_channel`` chiedeva a ``is_project_session_key`` se il
    ``chat_id`` fosse un progetto, cioe' lo classificava come fosse una chiave di
    sessione: ``"default"`` non sta in nessun vocabolario, e a ogni avvio usciva il
    WARNING «session key 'default' is in no vocabulary».
    """
    from loguru import logger

    from jafta.session import keys as keys_mod

    keys_mod._UNCLASSIFIED_WARNED.discard(chat_id)
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        assert session_key_for_channel("websocket", chat_id) == UNIFIED_SESSION_KEY
    finally:
        logger.remove(sink)
    assert messages == []


def test_a_webui_project_chat_id_still_opens_the_project() -> None:
    assert session_key_for_channel("websocket", "project:orto") == "project:orto"
    assert session_key_for_channel("telegram", "project:orto") == UNIFIED_SESSION_KEY
    assert session_key_for_channel("websocket", "project:../fuori") == UNIFIED_SESSION_KEY


@pytest.mark.parametrize("chat_id", ["default", "altro-chat", "12345"])
def test_reading_the_chat_id_of_a_frame_does_not_warn(chat_id: str) -> None:
    """Il ``chat_id`` di un frame della WebUI non e' una session key.

    Il client aggancia la chat personale con ``chat_id: "default"``: chiedere a
    ``is_project_session_key`` se fosse un progetto lo classificava come chiave,
    e al primo ``attach`` dopo ogni avvio usciva il WARNING «session key
    'default' is in no vocabulary». Vale per ``attach``/``message`` e per
    ``detach``, che rilegge l'esito.
    """
    from loguru import logger

    from jafta.channels.websocket import WebSocketChannel
    from jafta.session import keys as keys_mod

    keys_mod._UNCLASSIFIED_WARNED.discard(chat_id)
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    try:
        cid = WebSocketChannel._envelope_chat_id({"type": "attach", "chat_id": chat_id})
        assert cid == "default"
        assert not keys_mod.is_project_chat_id(cid)
    finally:
        logger.remove(sink)
    assert messages == []
