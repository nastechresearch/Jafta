"""Un subagent che esaurisce le iterazioni non ha «finito».

Il ramo dei risultati conosceva ``tool_error`` ed ``error``; tutto il resto era un
successo. Un subagent fermato da ``max_iterations`` veniva annunciato «completed
successfully», con il testo di ripiego «Task completed but no final response was
generated.» come risultato: l'agente principale riferiva all'utente un lavoro
finito che era stato interrotto a metà.
"""

from __future__ import annotations

from jafta.agent.subagent import SubagentManager
from jafta.bus.queue import MessageBus
from jafta.providers.base import LLMResponse, ToolCallRequest
from tests.support.aio import wait_until
from tests.support.subagent_provider_fakes import fake_provider


async def test_budget_exhaustion_is_announced_as_such(tmp_path):
    call = ToolCallRequest(id="c1", name="list_dir", arguments={"path": "."})
    provider = fake_provider([LLMResponse(content="", tool_calls=[call],
                                          finish_reason="tool_calls")])
    bus = MessageBus()
    manager = SubagentManager(provider=provider, workspace=tmp_path, bus=bus, model="m",
                              max_tool_result_chars=16000, max_iterations=3)

    await manager.spawn("scorri l'albero", session_key="unified:default",
                        origin_channel="websocket", origin_chat_id="default")
    await wait_until(lambda: not manager._running_tasks, timeout=5.0)

    announce = await bus.consume_inbound()
    first_line = announce.content.splitlines()[0]
    assert "completed successfully" not in first_line
    assert "iteration budget" in first_line
    assert "Task completed but no final response" not in announce.content
    assert "list_dir" in announce.content  # quel che ha fatto prima di fermarsi
    record = manager.list_records("unified:default")[-1]
    assert record.stop_reason == "max_iterations"
    assert record.state != "done"
