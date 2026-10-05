"""La read timeout di httpx non scade prima del budget del primo token.

Su un endpoint remoto la read timeout era 120 s e il budget del primo token 300:
un modello che ragiona in silenzio veniva tagliato da httpx a 120 s, con un
``ReadTimeout`` al posto del messaggio giusto, e i retry ripetevano il taglio
(~8 minuti). Qui: la read timeout copre il budget, connect/write restano
stretti, e il silenzio lo misura il budget del primo token. Anche lo stream
della Responses API ha ora i due budget, che prima non aveva affatto.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from jafta.config.runtime_env import resolve_first_output_timeout_s
from jafta.providers.anthropic_provider import AnthropicProvider
from jafta.providers.endpoint_budget import DEFAULT_REQUEST_TIMEOUT_S, read_timeout_s
from jafta.providers.openai_compat_provider import OpenAICompatProvider

MESSAGES = [{"role": "user", "content": "x"}]


@pytest.mark.parametrize("local", [False, True])
def test_the_read_timeout_is_longer_than_the_first_output_budget(local: bool) -> None:
    assert read_timeout_s(local=local) > resolve_first_output_timeout_s(local=local)


async def test_remote_clients_read_long_but_connect_tight() -> None:
    openai = OpenAICompatProvider(api_key="k", api_base="https://api.example.com/v1")
    await openai._ensure_client()
    anthropic = AnthropicProvider(api_key="k", api_base="https://api.example.com")
    for client in (openai._http_client, anthropic._http_client):
        assert client.timeout.read == read_timeout_s(local=False)
        assert client.timeout.read > resolve_first_output_timeout_s(local=False)
        assert client.timeout.connect == DEFAULT_REQUEST_TIMEOUT_S


async def _silent_server(reader, writer) -> None:
    await reader.read(65536)
    writer.write(
        b"HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n"
        b"transfer-encoding: chunked\r\n\r\n"
    )
    await writer.drain()
    await asyncio.sleep(5)  # il modello "pensa" in silenzio
    writer.close()


@pytest.mark.parametrize("provider_cls", [OpenAICompatProvider, AnthropicProvider])
async def test_a_silent_model_hits_the_first_output_budget_not_httpx(
    monkeypatch, provider_cls,
) -> None:
    monkeypatch.setenv("JAFTA_LLM_HTTP_TIMEOUT_S", "0.2")
    monkeypatch.setenv("JAFTA_STREAM_IDLE_TIMEOUT_S", "0.3")
    monkeypatch.setenv("JAFTA_STREAM_FIRST_OUTPUT_TIMEOUT_S", "0.6")
    server = await asyncio.start_server(_silent_server, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        # Il loopback conta come locale: il budget letto è quello da env, 0.6 s.
        provider = provider_cls(
            api_key="k", api_base=f"http://127.0.0.1:{port}/v1", default_model="m",
        )
        started = time.monotonic()
        response = await provider.chat_stream(messages=MESSAGES)
        elapsed = time.monotonic() - started
    finally:
        server.close()
    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"
    assert response.content == "Error calling LLM: no output from the model within 0.6 seconds"
    assert elapsed >= 0.5


class _StalledResponse:
    async def aiter_lines(self):
        await asyncio.sleep(30)
        yield ""  # pragma: no cover

    async def aclose(self) -> None:
        return None


async def test_the_responses_stream_has_a_first_output_budget(monkeypatch) -> None:
    monkeypatch.setenv("JAFTA_STREAM_IDLE_TIMEOUT_S", "0.05")
    monkeypatch.setenv("JAFTA_STREAM_FIRST_OUTPUT_TIMEOUT_S", "0.2")
    provider = OpenAICompatProvider(
        api_key="k", api_base="https://api.openai.com/v1", default_model="gpt-5",
        api_type="responses",
    )
    with patch.object(provider, "_http_request", new=AsyncMock(return_value=_StalledResponse())):
        response = await asyncio.wait_for(provider.chat_stream(messages=MESSAGES), timeout=5)
    assert response.finish_reason == "error"
    assert response.error_kind == "timeout"
    assert response.content == "Error calling LLM: no output from the model within 0.2 seconds"
