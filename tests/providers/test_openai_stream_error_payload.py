"""Un ``{"error": ...}`` dentro uno stream Chat Completions è un errore.

Lo status della risposta era 200: il gateway (OpenRouter, o un proxy davanti a un
modello sovraccarico) scrive l'errore come chunk SSE. Il ramo Chat Completions lo
scartava: ``finish_reason="stop"`` col testo arrivato fin lì, o vuoto, e nessun
retry: tre casi riprodotti, e qui ci sono gli stessi tre.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from jafta.providers.openai_compat_provider import OpenAICompatProvider
from jafta.providers.retry_policy import is_transient_response

MESSAGES = [{"role": "user", "content": "x"}]


def _d(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


HALF = _d({"choices": [{"delta": {"content": "Metà risposta"}}]})
OK = (
    _d({"choices": [{"delta": {"content": "ok"}}]})
    + _d({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    + "data: [DONE]\n\n"
)


def _provider(*bodies: str) -> tuple[OpenAICompatProvider, dict]:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        body = bodies[min(calls["n"], len(bodies) - 1)]
        calls["n"] += 1
        return httpx.Response(200, content=body.encode())

    provider = OpenAICompatProvider(
        api_key="k", api_base="https://openrouter.ai/api/v1", default_model="x/y",
    )
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider, calls


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("jafta.providers.base.asyncio.sleep", _sleep)


async def _delta(_text: str) -> None:
    await asyncio.sleep(0)


async def test_error_with_choices_mid_stream_keeps_the_partial_text() -> None:
    provider, calls = _provider(HALF + _d({
        "error": {"code": 502, "message": "Provider returned error"},
        "choices": [{"delta": {"content": ""}, "finish_reason": "error"}],
    }))
    response = await provider.chat_stream_with_retry(messages=MESSAGES, on_content_delta=_delta)
    assert response.finish_reason == "error"
    assert response.error_status_code == 502
    assert "Provider returned error" in (response.content or "")
    assert response.partial_content == "Metà risposta"
    assert is_transient_response(response)
    # Il testo era già sullo schermo: non si ritenta (come per ogni altro errore
    # arrivato dopo l'output), ma l'errore non si perde.
    assert calls["n"] == 1


async def test_error_without_choices_mid_stream_is_not_lost() -> None:
    provider, _ = _provider(HALF + _d({
        "error": {"code": "server_error", "message": "upstream overloaded"},
    }))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert "upstream overloaded" in (response.content or "")
    assert response.partial_content == "Metà risposta"
    assert is_transient_response(response)


async def test_error_before_any_output_is_retried() -> None:
    provider, calls = _provider(_d({"error": {"code": 529, "message": "Overloaded"}}), OK)
    response = await provider.chat_stream_with_retry(messages=MESSAGES, on_content_delta=_delta)
    assert calls["n"] == 2
    assert response.finish_reason == "stop"
    assert response.content == "ok"


async def test_a_permanent_error_is_not_retried() -> None:
    provider, calls = _provider(
        _d({"error": {"code": 401, "message": "No auth credentials found"}}), OK,
    )
    response = await provider.chat_stream_with_retry(messages=MESSAGES, on_content_delta=_delta)
    assert calls["n"] == 1
    assert response.finish_reason == "error"
    assert not is_transient_response(response)


AFTER = (
    _d({"choices": [{"delta": {"content": " e poi altro"}}]})
    + _d({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    + "data: [DONE]\n\n"
)


async def test_the_stream_stops_at_the_error_chunk() -> None:
    # Quello che il gateway scrive dopo il suo errore non fa parte di nessuna
    # risposta buona: non va sullo schermo né nel testo parziale.
    provider, _ = _provider(HALF + _d({"error": {"code": 502, "message": "x"}}) + AFTER)
    shown: list[str] = []

    async def collect(text: str) -> None:
        shown.append(text)

    response = await provider.chat_stream(messages=MESSAGES, on_content_delta=collect)
    assert response.finish_reason == "error"
    assert shown == ["Metà risposta"]
    assert response.partial_content == "Metà risposta"


def test_the_chunk_fold_stops_at_the_error_chunk() -> None:
    chunks = [
        {"choices": [{"delta": {"content": "Metà risposta"}}]},
        {"error": {"code": 502, "message": "x"}},
        {"choices": [{"delta": {"content": " e poi altro"}, "finish_reason": "stop"}]},
    ]
    response = OpenAICompatProvider._parse_chunks(chunks)
    assert response.finish_reason == "error"
    assert response.partial_content == "Metà risposta"


# Lo stesso errore, fuori dallo stream: una risposta non-stream a 200 il cui
# corpo è solo ``{"error": ...}``. Diventava «API returned empty choices», senza
# status: il 502 di un gateway non si ritentava, e il suo messaggio si perdeva.

OK_JSON = json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})


async def test_a_non_stream_error_body_keeps_status_and_message() -> None:
    provider, _ = _provider(json.dumps(
        {"error": {"code": 502, "message": "Provider returned error"}},
    ))
    response = await provider.chat(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert response.error_status_code == 502
    assert "Provider returned error" in (response.content or "")
    assert is_transient_response(response)


async def test_a_non_stream_error_body_is_retried() -> None:
    provider, calls = _provider(
        json.dumps({"error": {"code": 503, "message": "busy"}}), OK_JSON,
    )
    response = await provider.chat_with_retry(messages=MESSAGES)
    assert calls["n"] == 2
    assert (response.finish_reason, response.content) == ("stop", "ok")


async def test_a_permanent_non_stream_error_body_is_not_retried() -> None:
    provider, calls = _provider(
        json.dumps({"error": {"code": 401, "message": "No auth credentials found"}}), OK_JSON,
    )
    response = await provider.chat_with_retry(messages=MESSAGES)
    assert calls["n"] == 1
    assert response.error_status_code == 401
    assert not is_transient_response(response)
