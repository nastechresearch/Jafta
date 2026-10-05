"""Gli errori di trasporto di httpx sono transitori, su entrambi i provider.

``RemoteProtocolError`` («Server disconnected without sending a response») è il
keep-alive che il server ha chiuso mentre la richiesta partiva: la seconda
richiesta, su una connessione nuova, passa. Il suo nome non contiene né
«timeout» né «connection», e il testo non ha nessuno dei marker: veniva quindi
mostrato in chat come errore definitivo invece di essere ritentato. Stessa sorte
per ``ReadError`` (connessione resettata). Sul ramo Anthropic, poi, ogni
eccezione di httpx arrivava in chat senza metadati, compreso ``ReadTimeout``.
"""

from __future__ import annotations

import httpx
import pytest

from jafta.providers.anthropic_provider import AnthropicProvider
from jafta.providers.openai_compat_provider import OpenAICompatProvider
from jafta.providers.retry_policy import is_transient_response

MESSAGES = [{"role": "user", "content": "ciao"}]


def _raising(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc
    return handler


@pytest.mark.parametrize("exc", [
    httpx.RemoteProtocolError("Server disconnected without sending a response."),
    httpx.ReadError("Connection reset by peer"),
])
def test_openai_handle_error_marks_transport_errors_transient(exc: Exception) -> None:
    response = OpenAICompatProvider._handle_error(exc)
    assert response.error_kind == "connection"
    assert is_transient_response(response)


@pytest.mark.parametrize("exc, kind", [
    (httpx.RemoteProtocolError("Server disconnected without sending a response."), "connection"),
    (httpx.ReadError("Connection reset by peer"), "connection"),
    (httpx.ReadTimeout("timed out"), "timeout"),
])
async def test_anthropic_stream_classifies_transport_errors(exc: Exception, kind: str) -> None:
    provider = AnthropicProvider(api_key="k", api_base="https://api.example.com")
    provider._http_client = httpx.AsyncClient(
        base_url="https://api.example.com", transport=httpx.MockTransport(_raising(exc)),
    )
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert response.error_kind == kind
    assert is_transient_response(response)


async def test_openai_stream_retries_a_dropped_keepalive(monkeypatch) -> None:
    calls = {"n": 0}
    body = (
        'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return httpx.Response(200, content=body.encode())

    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("jafta.providers.base.asyncio.sleep", _no_sleep)
    provider = OpenAICompatProvider(api_key="k", api_base="https://api.example.com/v1")
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await provider.chat_stream_with_retry(messages=MESSAGES, model="m")
    assert response.finish_reason == "stop"
    assert response.content == "ok"
    assert calls["n"] == 2
