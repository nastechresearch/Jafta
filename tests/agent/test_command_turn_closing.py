"""Un comando risposto senza turno si chiude, e si chiude dopo la sua risposta.

Misurato sull'emulatore il 28/09/2026 con un client WebSocket che manda come la
WebUI: ``/status`` e ``/stop`` a riposo rispondevano con un solo ``message``,
senza ``turn_end`` ne' ``goal_status: idle``; ``/stop`` a turno in corso mandava
``turn_end`` e ``idle`` **prima** di «Stopped 1 task(s).». In tutti e tre i casi
il client restava in attesa, e la mascotte a pensare per sempre.

Qui si prova ``AgentLoop._dispatch_command_inline`` col suo ``_close_if_idle``
vero, su un loop finto che registra in che ordine esce cosa.
"""

from __future__ import annotations

from types import SimpleNamespace

from jafta.agent.loop import AgentLoop
from jafta.bus.events import InboundMessage, OutboundMessage


def _loop(*, running: bool = False):
    log: list[str] = []

    async def publish_outbound(out: OutboundMessage) -> None:
        log.append(f"reply:{out.content}")

    async def turn_completed(**kwargs) -> None:
        log.append("turn_end")

    async def run_status_changed(msg, key, status) -> None:
        log.append(f"goal_status:{status}")

    events = SimpleNamespace(turn_completed=turn_completed, run_status_changed=run_status_changed)
    loop = SimpleNamespace(
        bus=SimpleNamespace(publish_outbound=publish_outbound),
        _pending_queues={"websocket:c1": object()} if running else {},
        _runtime_events=lambda: events,
    )
    loop._close_if_idle = lambda msg, key: AgentLoop._close_if_idle(loop, msg, key)
    return loop, log


def _msg(text: str) -> InboundMessage:
    return InboundMessage(channel="websocket", sender_id="u1", chat_id="c1", content=text)


def _reply(text: str):
    async def dispatch(ctx):
        return OutboundMessage(channel="websocket", chat_id="c1", content=text)

    return dispatch


async def test_a_command_at_rest_is_closed_after_its_reply() -> None:
    """`/status` e `/stop` a riposo: la risposta, poi `turn_end` e `idle`."""
    loop, log = _loop()
    await AgentLoop._dispatch_command_inline(loop, _msg("/status"), "websocket:c1", "/status",
                                             _reply("jafta v0.11.0"))
    assert log == ["reply:jafta v0.11.0", "turn_end", "goal_status:idle"]


async def test_a_command_during_a_turn_leaves_the_closing_to_that_turn() -> None:
    """Un `turn_end` in piu' troncherebbe la risposta che sta ancora arrivando."""
    loop, log = _loop(running=True)
    await AgentLoop._dispatch_command_inline(loop, _msg("/status"), "websocket:c1", "/status",
                                             _reply("jafta v0.11.0"))
    assert log == ["reply:jafta v0.11.0"]


async def test_stop_answers_before_closing_the_turn_it_stopped() -> None:
    """Il caso di `/stop` a turno in corso: prima «Stopped», poi la chiusura che
    l'handler ha lasciato in `after_reply` — e nessuna seconda chiusura."""
    loop, log = _loop(running=True)

    async def dispatch(ctx):
        async def close_the_stopped_turn() -> None:
            log.append("stop_turn_end")

        ctx.after_reply.append(close_the_stopped_turn)
        return OutboundMessage(channel="websocket", chat_id="c1", content="Stopped 1 task(s).")

    await AgentLoop._dispatch_command_inline(loop, _msg("/stop"), "websocket:c1", "/stop", dispatch)
    assert log == ["reply:Stopped 1 task(s).", "stop_turn_end"]


async def test_a_command_that_answers_nothing_is_closed_all_the_same() -> None:
    loop, log = _loop()

    async def dispatch(ctx):
        return None

    await AgentLoop._dispatch_command_inline(loop, _msg("/x"), "websocket:c1", "/x", dispatch)
    assert log == ["turn_end", "goal_status:idle"]
