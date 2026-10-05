"""I token dei subagent e del Consolidator si contano.

``TokenUsageHook`` era montato solo sui turni di ``AgentLoop``: un subagent gira
nel suo ``AgentRunner`` e il Consolidator chiama il provider da sé, quindi la loro
spesa non arrivava mai in ``token-usage.json`` e il cruscotto la sottostimava.
Ora ``AgentLoop`` passa a entrambi i suoi hook di misura — quelli che dichiarano
``runs_when_ephemeral``, cioè ``TokenUsageHook`` — e la spesa si registra sotto la
chiave della sessione per cui è stata fatta.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from jafta.agent import token_usage
from jafta.agent.consolidator import Consolidator
from jafta.agent.memory import MemoryStore
from jafta.agent.subagent import SubagentManager
from jafta.agent.token_usage import TokenUsageHook
from jafta.bus.queue import MessageBus
from jafta.providers.base import LLMResponse
from jafta.session.manager import SessionManager
from tests.support.agent import make_loop, make_provider
from tests.support.aio import wait_until
from tests.support.subagent_provider_fakes import fake_provider


def _capture(monkeypatch) -> list[tuple[dict, dict]]:
    calls: list[tuple[dict, dict]] = []
    monkeypatch.setattr(
        token_usage, "record_token_usage", lambda usage, **kw: calls.append((usage, kw)),
    )
    return calls


async def test_a_subagent_run_records_its_tokens(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    provider = fake_provider([
        LLMResponse(content="fatto", usage={"prompt_tokens": 5000, "completion_tokens": 300}),
    ])
    manager = SubagentManager(
        provider=provider, workspace=tmp_path, bus=MessageBus(), model="m",
        max_tool_result_chars=16000, usage_hooks=[TokenUsageHook(timezone_name="UTC")],
    )

    await manager.spawn("fai una cosa", session_key="unified:default",
                        origin_channel="websocket", origin_chat_id="default")
    await wait_until(lambda: not manager._running_tasks, timeout=5.0)

    assert [usage["prompt_tokens"] for usage, _ in calls] == [5000]
    assert calls[0][1]["source"] == "user"


async def test_a_consolidation_records_its_tokens(tmp_path, monkeypatch):
    calls = _capture(monkeypatch)
    provider = fake_provider([
        LLMResponse(content="- [durable] x", usage={"prompt_tokens": 9000,
                                                    "completion_tokens": 200}),
    ])
    provider.generation.max_tokens = 4096
    consolidator = Consolidator(
        store=MemoryStore(tmp_path), provider=provider, model="m",
        sessions=SessionManager(tmp_path), context_window_tokens=65536,
        build_messages=lambda **_k: [], get_tool_definitions=lambda: [],
        usage_hooks=[TokenUsageHook(timezone_name="UTC")],
    )

    summary = await consolidator.archive(
        [{"role": "user", "content": "ciao", "timestamp": "2026-09-26T10:00"}],
        session_key="unified:default",
    )

    assert summary
    assert [usage["prompt_tokens"] for usage, _ in calls] == [9000]
    assert calls[0][1]["source"] == "user"


def test_the_loop_hands_its_measuring_hooks_to_both(tmp_path):
    usage_hook = TokenUsageHook(timezone_name="UTC")
    speaking_hook = MagicMock()
    speaking_hook.runs_when_ephemeral.return_value = False
    loop = make_loop(tmp_path, provider=make_provider(), hooks=[usage_hook, speaking_hook])

    assert loop.subagents.usage_hooks == [usage_hook]
    assert loop.consolidator.usage_hooks == [usage_hook]
