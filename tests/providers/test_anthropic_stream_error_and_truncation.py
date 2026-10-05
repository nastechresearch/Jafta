"""Uno stream Anthropic che si interrompe non è una risposta completa.

Due modi di interrompersi, entrambi osservati dall'audit:
un ``event: error`` a metà stream (``overloaded_error`` sotto
carico) e lo stream chiuso senza ``message_stop``. In tutti e due i casi il
provider restituiva ``finish_reason="stop"`` col testo arrivato fin lì — una
risposta troncata salvata come completa, senza retry — e un ``tool_use`` a
metà veniva eseguito con gli argomenti che c'erano.
"""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from jafta.providers.anthropic_provider import AnthropicProvider
from jafta.providers.retry_policy import is_transient_response

MESSAGES = [{"role": "user", "content": "ciao"}]


def _sse(*events: dict) -> bytes:
    out = []
    for event in events:
        out.append(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n")
    return "".join(out).encode()


START = {"type": "message_start", "message": {"usage": {"input_tokens": 10}}}
TEXT_START = {"type": "content_block_start", "index": 0,
              "content_block": {"type": "text", "text": ""}}


def _text(text: str) -> dict:
    return {"type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": text}}


END = [
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
     "usage": {"output_tokens": 3}},
    {"type": "message_stop"},
]


def _provider(*bodies: bytes) -> tuple[AnthropicProvider, dict]:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        body = bodies[min(calls["n"], len(bodies) - 1)]
        calls["n"] += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    provider = AnthropicProvider(api_key="k", api_base="https://api.example.com")
    provider._http_client = httpx.AsyncClient(
        base_url="https://api.example.com", transport=httpx.MockTransport(handler),
    )
    return provider, calls


def _error(kind: str, message: str) -> dict:
    return {"type": "error", "error": {"type": kind, "message": message}}


async def test_an_error_event_mid_stream_is_an_error_with_partial_content() -> None:
    provider, _ = _provider(_sse(START, TEXT_START, _text("La risposta a metà"),
                                 _error("overloaded_error", "Overloaded")))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert response.error_type == "overloaded_error"
    assert response.error_kind == "stream_error"
    assert "Overloaded" in (response.content or "")
    assert response.partial_content == "La risposta a metà"
    assert is_transient_response(response)


@pytest.mark.parametrize("kind, transient", [
    ("overloaded_error", True),
    ("api_error", True),
    ("rate_limit_error", True),
    ("invalid_request_error", False),
    ("authentication_error", False),
])
async def test_error_event_types_are_classified(kind: str, transient: bool) -> None:
    provider, _ = _provider(_sse(START, _error(kind, "boom")))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert is_transient_response(response) is transient


async def test_an_overloaded_error_before_any_output_is_retried(monkeypatch) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("jafta.providers.base.asyncio.sleep", _no_sleep)
    provider, calls = _provider(
        _sse(START, _error("overloaded_error", "Overloaded")),
        _sse(START, TEXT_START, _text("ok"), *END),
    )
    response = await provider.chat_stream_with_retry(messages=MESSAGES)
    assert calls["n"] == 2
    assert response.finish_reason == "stop"
    assert response.content == "ok"


async def test_a_stream_closed_without_message_stop_is_truncated() -> None:
    provider, _ = _provider(_sse(START, TEXT_START, _text("Tronca")))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert response.partial_content == "Tronca"
    assert is_transient_response(response)


async def test_a_truncated_tool_use_is_never_executed() -> None:
    tool_start = {"type": "content_block_start", "index": 0,
                  "content_block": {"type": "tool_use", "id": "toolu_1", "name": "write_file"}}
    partial_args = {"type": "content_block_delta", "index": 0,
                    "delta": {"type": "input_json_delta",
                              "partial_json": '{"path": "a.txt", "content": "abc'}}
    provider, _ = _provider(_sse(START, tool_start, partial_args))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "error"
    assert not response.should_execute_tools


async def test_an_overloaded_error_is_a_529_without_reading_the_text() -> None:
    # Il messaggio non dice «overloaded»: a decidere il retry è lo status che
    # il tipo d'errore porta con sé, non un marker trovato nel testo.
    provider, _ = _provider(_sse(START, _error("overloaded_error", "please wait")))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.error_status_code == 529
    assert is_transient_response(replace(response, content="Error: please wait"))


@pytest.mark.parametrize("end", [
    pytest.param([END[0], END[1]], id="stop_reason-without-message_stop"),
    pytest.param([END[0], {"type": "message_stop"}], id="message_stop-without-stop_reason"),
])
async def test_either_end_signal_makes_the_stream_complete(end: list[dict]) -> None:
    # Basta uno dei due: lo ``stop_reason`` di ``message_delta`` arriva dopo
    # l'ultimo blocco, quindi il testo è già tutto; ``message_stop`` chiude.
    provider, _ = _provider(_sse(START, TEXT_START, _text("Tutto"), *end))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "stop"
    assert response.content == "Tutto"


async def test_a_complete_stream_is_unchanged() -> None:
    provider, _ = _provider(_sse(START, TEXT_START, _text("Tutto"), *END))
    response = await provider.chat_stream(messages=MESSAGES)
    assert response.finish_reason == "stop"
    assert response.content == "Tutto"
    assert response.usage["prompt_tokens"] == 10
