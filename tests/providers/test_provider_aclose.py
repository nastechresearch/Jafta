"""Un provider sostituito chiude il suo client httpx.

Ogni cambio di impostazioni del provider ne costruisce uno nuovo
(``GatewayContainer._on_settings_changed``), e il vecchio restava con il suo
``httpx.AsyncClient`` aperto: connessioni e pool mai rilasciati, uno per
salvataggio. ``aclose()`` lo chiude; se una richiesta è ancora in volo (un
turno partito col provider vecchio) aspetta che finisca, retry compresi.
"""

from __future__ import annotations

import asyncio
import inspect

import httpx
import pytest

from jafta.providers.anthropic_provider import AnthropicProvider
from jafta.providers.openai_compat_provider import OpenAICompatProvider

MESSAGES = [{"role": "user", "content": "x"}]
OK_CHAT = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}


async def test_openai_compat_aclose_closes_the_client() -> None:
    provider = OpenAICompatProvider(api_key="k", api_base="https://api.example.com/v1")
    await provider._ensure_client()
    client = provider._http_client
    await provider.aclose()
    assert client.is_closed
    await provider.aclose()  # idempotente


async def test_openai_compat_aclose_without_a_client_is_a_noop() -> None:
    provider = OpenAICompatProvider(api_key="k", api_base="https://api.example.com/v1")
    await provider.aclose()
    assert provider._http_client is None


async def test_anthropic_aclose_closes_the_client() -> None:
    provider = AnthropicProvider(api_key="k", api_base="https://api.example.com")
    client = provider._http_client
    await provider.aclose()
    assert client.is_closed


async def test_aclose_waits_for_the_request_in_flight(monkeypatch) -> None:
    release = asyncio.Event()
    calls = {"n": 0}

    async def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        await release.wait()
        return httpx.Response(200, json=OK_CHAT)

    provider = OpenAICompatProvider(api_key="k", api_base="https://api.example.com/v1")
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = provider._http_client

    turn = asyncio.create_task(provider.chat_with_retry(messages=MESSAGES, model="m"))
    while calls["n"] == 0:
        await asyncio.sleep(0.01)

    await provider.aclose()
    assert not client.is_closed  # il turno in corso non viene troncato

    release.set()
    response = await turn
    assert response.content == "ok"
    assert client.is_closed


@pytest.mark.parametrize("cls", [OpenAICompatProvider, AnthropicProvider])
def test_both_providers_expose_aclose(cls) -> None:
    assert inspect.iscoroutinefunction(cls.aclose)
