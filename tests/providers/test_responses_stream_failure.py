"""Uno stream Responses che fallisce o si chiude a metà è un errore classificato.

``response.failed`` e l'evento ``error`` diventavano un ``RuntimeError`` nudo:
senza status né tipo la retry policy leggeva solo il testo, e un
``server_error`` passeggero finiva in chat come definitivo. E uno stream chiuso
senza ``response.completed`` diventava ``stop`` col testo arrivato fin lì: una
risposta troncata salvata come buona.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from jafta.providers.base import LLMProvider
from jafta.providers.openai_compat_provider import OpenAICompatProvider

MESSAGES = [{"role": "user", "content": "x"}]
TEXT = {"type": "response.output_text.delta", "delta": "Ecco la ri"}


class _FakeResponse:
    def __init__(self, *events: dict) -> None:
        self._events = events

    async def aiter_lines(self):
        for event in self._events:
            yield f"data: {json.dumps(event)}"
            yield ""

    async def aclose(self) -> None:
        pass


async def _stream(*events: dict):
    provider = OpenAICompatProvider(api_key="k", api_base="https://api.openai.com/v1",
                                    default_model="gpt-5", api_type="responses")
    response = _FakeResponse(*events)
    with patch.object(provider, "_http_request", new=AsyncMock(return_value=response)):
        return await provider.chat_stream(messages=MESSAGES)


async def test_a_failed_response_carries_status_and_is_retried() -> None:
    result = await _stream(TEXT, {
        "type": "response.failed",
        "response": {"status": "failed",
                     "error": {"code": "server_error", "message": "The server had an error"}},
    })

    assert result.finish_reason == "error"
    assert result.error_status_code == 500
    assert result.error_code == "server_error"
    assert "The server had an error" in (result.content or "")
    assert result.partial_content == "Ecco la ri"
    assert LLMProvider._is_transient_response(result)


async def test_an_error_event_is_classified_by_its_code() -> None:
    result = await _stream(TEXT, {
        "type": "error", "code": "rate_limit_exceeded",
        "message": "Rate limit reached", "param": None,
    })

    assert result.finish_reason == "error"
    assert result.error_status_code == 429
    assert "Rate limit reached" in (result.content or "")
    assert LLMProvider._is_transient_response(result)


async def test_a_request_error_is_not_retried() -> None:
    result = await _stream({
        "type": "response.failed",
        "response": {"status": "failed",
                     "error": {"code": "invalid_prompt", "message": "Invalid prompt"}},
    })

    assert result.finish_reason == "error"
    assert not LLMProvider._is_transient_response(result)


async def test_a_stream_closed_before_completion_is_a_truncation() -> None:
    result = await _stream(TEXT)

    assert result.finish_reason == "error"
    assert result.error_kind == "connection"
    assert result.partial_content == "Ecco la ri"
    assert LLMProvider._is_transient_response(result)


async def test_a_truncated_tool_call_is_not_executed() -> None:
    result = await _stream(
        {"type": "response.output_item.added",
         "item": {"type": "function_call", "call_id": "c1", "id": "fc1",
                  "name": "write_file", "arguments": ""}},
        {"type": "response.function_call_arguments.delta", "call_id": "c1",
         "delta": '{"path": "a.t'},
    )

    assert result.finish_reason == "error"
    assert not result.should_execute_tools


async def test_a_completed_stream_is_still_a_stop() -> None:
    result = await _stream(
        TEXT, {"type": "response.completed", "response": {"status": "completed"}},
    )

    assert (result.finish_reason, result.content) == ("stop", "Ecco la ri")


# ── Il ramo non-stream ────────────────────────────────────────────────────
#
# Una risposta intera con ``status: "failed"`` e' lo stesso errore di
# ``response.failed``: deve arrivare alla retry policy con gli stessi metadati,
# anche quando il server non scrive il corpo dell'errore.


def _parsed(response: dict):
    from jafta.providers.openai_responses import parse_response_output

    return parse_response_output(response)


@pytest.mark.parametrize("error", [None, "absent"])
def test_a_failed_whole_response_without_error_details_is_a_provider_error(error) -> None:
    body: dict = {"output": [], "status": "failed", "usage": {}}
    if error != "absent":
        body["error"] = error
    result = _parsed(body)

    assert result.finish_reason == "error"
    assert result.error_kind == "stream_error"
    assert result.content == "Error: the response failed"


def test_a_failed_whole_response_keeps_its_error_details() -> None:
    result = _parsed({
        "output": [], "status": "failed",
        "error": {"code": "server_error", "message": "The server had an error"},
    })

    assert result.finish_reason == "error"
    assert result.error_kind == "stream_error"
    assert result.error_status_code == 500
    assert "The server had an error" in (result.content or "")
    assert LLMProvider._is_transient_response(result)


async def test_a_stream_failed_without_details_matches_the_whole_response() -> None:
    streamed = await _stream({"type": "response.failed",
                              "response": {"status": "failed", "error": None}})
    whole = _parsed({"output": [], "status": "failed", "error": None})

    assert (whole.content, whole.error_kind) == (streamed.content, streamed.error_kind)
