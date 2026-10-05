"""La risposta in streaming si chiude sempre, anche quando lo stream non finisce.

Un ``/stop`` (cancellazione del task), uno stallo o un'eccezione a metà lasciavano
la risposta httpx aperta: la connessione restava in piedi e l'upstream
continuava a generare — e a fatturare — una risposta che nessuno leggeva più.
httpx la chiude da sé solo quando lo stream è letto fino in fondo.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from jafta.providers.openai_compat_provider import OpenAICompatProvider

MESSAGES = [{"role": "user", "content": "x"}]
CONTENT = {"choices": [{"delta": {"content": "hi"}}]}


class _FakeResponse:
    def __init__(self, lines: list[str] | None = None, *, stall: bool = False) -> None:
        self.closed = 0
        self._lines = lines or []
        self._stall = stall

    async def aiter_lines(self):
        for line in self._lines:
            yield line
        if self._stall:
            await asyncio.sleep(30)

    async def aclose(self) -> None:
        self.closed += 1


def _chat_provider() -> OpenAICompatProvider:
    return OpenAICompatProvider(api_key="k", api_base="https://api.example.com/v1",
                                default_model="m")


def _sse(*events: dict) -> list[str]:
    lines: list[str] = []
    for event in events:
        lines += [f"data: {json.dumps(event)}", ""]
    return lines


@pytest.fixture
def fast_budgets(monkeypatch):
    monkeypatch.setenv("JENNY_STREAM_IDLE_TIMEOUT_S", "0.05")
    monkeypatch.setenv("JENNY_STREAM_FIRST_OUTPUT_TIMEOUT_S", "0.1")


async def _run_chat(provider, response, **kwargs):
    with patch.object(provider, "_http_request", new=AsyncMock(return_value=response)):
        return await provider.chat_stream(messages=MESSAGES, **kwargs)


async def test_chat_stream_closes_on_a_stall(fast_budgets) -> None:
    response = _FakeResponse(_sse(CONTENT), stall=True)
    result = await _run_chat(_chat_provider(), response)
    assert result.error_kind == "timeout"
    assert response.closed == 1


async def test_chat_stream_closes_on_an_exception() -> None:
    response = _FakeResponse(_sse(CONTENT))

    async def boom(_text: str) -> None:
        raise RuntimeError("consumer failed")

    result = await _run_chat(_chat_provider(), response, on_content_delta=boom)
    assert result.finish_reason == "error"
    assert response.closed == 1


async def test_chat_stream_closes_on_cancellation() -> None:
    response = _FakeResponse(_sse(CONTENT), stall=True)
    provider = _chat_provider()
    with patch.object(provider, "_http_request", new=AsyncMock(return_value=response)):
        task = asyncio.create_task(provider.chat_stream(messages=MESSAGES))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert response.closed == 1


async def test_chat_stream_closes_after_an_error_chunk() -> None:
    response = _FakeResponse(_sse(CONTENT, {"error": {"code": 502, "message": "x"}}),
                             stall=True)
    result = await _run_chat(_chat_provider(), response)
    assert result.finish_reason == "error"
    assert response.closed == 1


async def test_responses_stream_closes_on_a_stall(fast_budgets) -> None:
    provider = OpenAICompatProvider(api_key="k", api_base="https://api.openai.com/v1",
                                    default_model="gpt-5", api_type="responses")
    response = _FakeResponse(
        _sse({"type": "response.output_text.delta", "delta": "hi"}), stall=True,
    )
    result = await _run_chat(provider, response)
    assert result.error_kind == "timeout"
    assert response.closed == 1
