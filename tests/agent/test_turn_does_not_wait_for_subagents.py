"""Un turno non aspetta i subagent che ha lanciato.

Fino al 02/10/2026 ``_drain_pending`` teneva il turno fermo fino a 300 secondi
dopo gli strumenti *e* dopo la risposta, finche' un subagent lanciato nel turno
era vivo: il riscontro all'utente arrivava dopo cinque minuti e quaranta, la
chat restava occupata undici, e il subagent e' finito comunque dopo. Il turno ora
finisce appena ha risposto; il risultato rientra in un turno suo, e cio' che
arriva mentre il turno gira entra ancora dalla coda.
"""

from __future__ import annotations

import asyncio

from jafta.bus.events import InboundMessage
from jafta.providers.base import LLMResponse, ToolCallRequest
from tests.support.agent import make_loop, make_provider

KEY = "unified:default"


def _loop_answering(tmp_path, chat, running: set[str]):
    provider = make_provider()
    provider.chat_with_retry = chat
    provider.chat_stream_with_retry = chat
    loop = make_loop(tmp_path, provider=provider)
    loop.subagents.get_running_ids_by_session = (
        lambda key: frozenset(running) if key == KEY else frozenset()
    )
    loop.subagents.get_running_count_by_session = lambda key: len(running) if key == KEY else 0
    return loop


def _message(content: str) -> InboundMessage:
    return InboundMessage(channel="websocket", sender_id="u", chat_id="default", content=content)


async def test_a_subagent_spawned_in_this_turn_is_not_waited_for(tmp_path):
    running: set[str] = set()
    calls = {"n": 0}

    async def chat(**_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # Il modello «lancia» un subagent, che resta vivo per tutto il test.
            running.add("nuovo")
            return LLMResponse(
                content="", finish_reason="tool_calls",
                tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
            )
        return LLMResponse(content="ci sto lavorando, ti scrivo appena torna")

    loop = _loop_answering(tmp_path, chat, running)
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    loop._pending_queues[KEY] = queue

    await asyncio.wait_for(loop._dispatch(_message("lancia un aiutante"), queue), timeout=5.0)

    assert calls["n"] == 2
    assert running == {"nuovo"}


async def test_a_result_that_arrives_mid_turn_is_still_injected(tmp_path):
    running: set[str] = set()
    calls = {"n": 0}
    seen: list[str] = []

    async def chat(**kw):
        calls["n"] += 1
        seen.append(str(kw.get("messages", [])[-1].get("content")))
        if calls["n"] == 1:
            running.add("svelto")
            # Il subagent torna mentre il turno sta ancora lavorando.
            queue.put_nowait(InboundMessage(
                channel="websocket", sender_id="subagent", chat_id="default",
                content="risultato dell'aiutante",
            ))
            running.clear()
            return LLMResponse(
                content="", finish_reason="tool_calls",
                tool_calls=[ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})],
            )
        return LLMResponse(content="ecco cosa ha trovato")

    loop = _loop_answering(tmp_path, chat, running)
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    loop._pending_queues[KEY] = queue

    await asyncio.wait_for(loop._dispatch(_message("lancia un aiutante"), queue), timeout=5.0)

    assert calls["n"] == 2
    assert "risultato dell'aiutante" in seen[-1]


async def test_a_plain_answer_with_an_earlier_subagent_alive_ends_at_once(tmp_path):
    async def chat(**_kw):
        return LLMResponse(content="Ciao! Tutto bene.")

    loop = _loop_answering(tmp_path, chat, {"vecchio"})
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    loop._pending_queues[KEY] = queue

    await asyncio.wait_for(loop._dispatch(_message("ciao"), queue), timeout=5.0)
