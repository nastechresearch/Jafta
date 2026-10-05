"""Dopo /stop o un kill la storia ha tutto il turno.

Il checkpoint di un turno in volo portava solo l'**ultima** iterazione: il
messaggio dell'assistente con le sue tool call e i risultati di quelle. Ripristinato
dopo uno /stop, o al turno dopo un kill, faceva sparire dalla storia le tool call
delle iterazioni precedenti — che però avevano girato, e magari scritto file — e i
messaggi dell'utente iniettati a metà turno. Il modello ripartiva senza sapere di
averle fatte.
"""

from __future__ import annotations

import asyncio

from jafta.bus.events import InboundMessage
from jafta.providers.base import LLMResponse, ToolCallRequest
from jafta.session.manager import SessionManager
from tests.support.agent import make_loop, make_provider
from tests.support.aio import wait_until

KEY = "unified:default"


def _three_steps_then_hang(step: dict, hang: asyncio.Event):
    async def chat(**_kw):
        step["n"] += 1
        if step["n"] <= 3:
            return LLMResponse(
                content=f"passo {step['n']}", finish_reason="tool_calls",
                tool_calls=[ToolCallRequest(id=f"c{step['n']}", name="list_dir",
                                            arguments={"path": "."})],
            )
        await hang.wait()
        return LLMResponse(content="mai")

    return chat


def _tool_call_ids(messages: list[dict]) -> list[str]:
    return [tc["id"] for m in messages for tc in (m.get("tool_calls") or [])]


def _tool_result_ids(messages: list[dict]) -> list[str]:
    return [m["tool_call_id"] for m in messages if m.get("role") == "tool"]


async def _run_until_the_fourth_call(tmp_path, *, queue: asyncio.Queue | None = None):
    (tmp_path / "a.txt").write_text("A", encoding="utf-8")
    provider = make_provider()
    step = {"n": 0}
    hang = asyncio.Event()
    chat = _three_steps_then_hang(step, hang)
    provider.chat_with_retry = chat
    provider.chat_stream_with_retry = chat
    loop = make_loop(tmp_path, provider=provider)
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="default",
                         content="fai tre passi")
    if queue is not None:
        loop._pending_queues[KEY] = queue
    task = asyncio.create_task(loop._dispatch(msg, queue) if queue else loop._dispatch(msg))
    loop._active_tasks.setdefault(KEY, []).append(task)
    await wait_until(lambda: step["n"] >= 4, timeout=5.0)
    return loop, task


async def test_stop_keeps_every_tool_call_of_the_turn(tmp_path):
    loop, _task = await _run_until_the_fourth_call(tmp_path)

    await loop._cancel_active_tasks(KEY)
    loop._restore_cancelled_turn(KEY)

    session = loop.sessions.get_or_create(KEY)
    assert _tool_call_ids(session.messages) == ["c1", "c2", "c3"]
    assert _tool_result_ids(session.messages) == ["c1", "c2", "c3"]


async def test_a_kill_keeps_every_tool_call_at_the_next_turn(tmp_path):
    """Il kill: il processo muore, il checkpoint resta nel file di sessione."""
    loop, task = await _run_until_the_fourth_call(tmp_path)
    try:
        # Il processo nuovo rilegge la sessione da disco così com'è a metà turno,
        # con il checkpoint dentro: è quel che trova dopo un kill.
        session = SessionManager(tmp_path).get_or_create(KEY)
        assert loop._restore_runtime_checkpoint(session)

        assert _tool_call_ids(session.messages) == ["c1", "c2", "c3"]
        assert _tool_result_ids(session.messages) == ["c1", "c2", "c3"]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_message_injected_mid_turn_survives_the_stop(tmp_path):
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    queue.put_nowait(InboundMessage(channel="websocket", sender_id="u", chat_id="default",
                                    content="e poi anche la cartella nuova"))
    loop, _task = await _run_until_the_fourth_call(tmp_path, queue=queue)

    await loop._cancel_active_tasks(KEY)
    loop._restore_cancelled_turn(KEY)

    session = loop.sessions.get_or_create(KEY)
    users = [str(m.get("content")) for m in session.messages if m.get("role") == "user"]
    assert any("la cartella nuova" in text for text in users)
    assert _tool_call_ids(session.messages) == ["c1", "c2", "c3"]


async def test_a_message_injected_after_the_last_checkpoint_survives_the_stop(tmp_path):
    """Il messaggio arriva mentre gira l'ultimo tool, e lo /stop cade sulla chiamata dopo.

    Nessuna risposta del modello arriva fra l'iniezione e lo /stop, quindi
    nessun checkpoint di fine iterazione lo porterebbe: lo salva solo il
    checkpoint scritto al momento dell'iniezione.
    """
    (tmp_path / "a.txt").write_text("A", encoding="utf-8")
    provider = make_provider()
    step = {"n": 0}
    hang = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)

    async def chat(**_kw):
        step["n"] += 1
        if step["n"] == 1:
            queue.put_nowait(InboundMessage(channel="websocket", sender_id="u",
                                            chat_id="default", content="MESSAGGIO-TARDIVO"))
            return LLMResponse(content="passo 1", finish_reason="tool_calls",
                               tool_calls=[ToolCallRequest(id="c1", name="list_dir",
                                                           arguments={"path": "."})])
        await hang.wait()
        return LLMResponse(content="mai")

    provider.chat_with_retry = chat
    provider.chat_stream_with_retry = chat
    loop = make_loop(tmp_path, provider=provider)
    loop._pending_queues[KEY] = queue
    msg = InboundMessage(channel="websocket", sender_id="u", chat_id="default", content="vai")
    task = asyncio.create_task(loop._dispatch(msg, queue))
    loop._active_tasks.setdefault(KEY, []).append(task)
    await wait_until(lambda: step["n"] >= 2, timeout=5.0)

    await loop._cancel_active_tasks(KEY)
    loop._restore_cancelled_turn(KEY)

    session = loop.sessions.get_or_create(KEY)
    users = [str(m.get("content")) for m in session.messages if m.get("role") == "user"]
    assert any("MESSAGGIO-TARDIVO" in text for text in users), users
    assert _tool_call_ids(session.messages) == ["c1"]
