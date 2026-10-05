"""Parse Responses API SSE streams and SDK response objects."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, AsyncGenerator

import httpx
from loguru import logger

from jafta.providers.base import (
    LLMResponse,
    StreamTimeout,
    ToolCallRequest,
    parse_tool_arguments,
    stream_error_response,
    stream_truncated_response,
)

FINISH_REASON_MAP = {
    "completed": "stop",
    "incomplete": "length",
    "failed": "error",
    "cancelled": "error",
}


class ResponsesStreamError(RuntimeError):
    """Lo stream è finito senza una risposta valida; *response* è l'errore da dare.

    Due casi: il server ha scritto un errore nello stream (``response.failed``,
    ``error``), o lo stream si è chiuso prima di ``response.completed``. In
    entrambi *response* ha i metadati per la retry policy e il testo già
    mostrato in ``partial_content``.
    """

    def __init__(self, response: LLMResponse) -> None:
        super().__init__(response.content or "")
        self.response = response


def _stream_error_detail(event: dict[str, Any]) -> dict[str, Any]:
    """Il corpo dell'errore di un evento ``response.failed`` o ``error``.

    ``response.failed`` lo porta in ``response.error``; l'evento ``error`` ha
    ``code`` e ``message`` in cima (il suo ``type`` è il nome dell'evento, non
    il tipo dell'errore), o talvolta sotto ``error``.
    """
    if event.get("type") == "response.failed":
        response_obj = event.get("response") or {}
        nested = response_obj.get("error") if isinstance(response_obj, dict) else None
    else:
        nested = event.get("error")
    if isinstance(nested, dict):
        return nested
    detail = {key: event[key] for key in ("code", "message") if event.get(key)}
    if not detail.get("message"):
        detail["message"] = str(nested or "the response failed")[:500]
    return detail


def map_finish_reason(status: str | None) -> str:
    """Map a Responses API status string to a Chat-Completions-style finish_reason."""
    return FINISH_REASON_MAP.get(status or "completed", "stop")


def _as_mapping(value: Any) -> dict[str, Any] | None:
    """*value* come dizionario, sia che arrivi dal JSON sia da un modello SDK."""
    if isinstance(value, dict):
        return value
    if value is None:
        return None
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump()
        return dumped if isinstance(dumped, dict) else None
    try:
        return vars(value)
    except TypeError:
        return None


def _usage_from_response_obj(response: Any) -> dict[str, int]:
    usage_raw = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    if not usage_raw:
        return {}
    usage_raw = _as_mapping(usage_raw)
    if usage_raw is None:
        return {}
    prompt_tokens = int(usage_raw.get("input_tokens") or usage_raw.get("prompt_tokens") or 0)
    completion_tokens = int(
        usage_raw.get("output_tokens") or usage_raw.get("completion_tokens") or 0
    )
    total_tokens = int(usage_raw.get("total_tokens") or prompt_tokens + completion_tokens)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }

    # ``cached_tokens`` sotto la chiave che l'API Responses usa. Mancava, quindi
    # su questo endpoint il risparmio da cache risultava sempre zero — mentre il
    # ramo Chat-Completions lo normalizza da tre posti diversi. I nomi
    # ``prompt_tokens_details``/``cached_tokens`` restano accettati perché un
    # gateway compatibile può rispondere con quelli su /responses.
    for key in ("input_tokens_details", "prompt_tokens_details"):
        details = _as_mapping(usage_raw.get(key))
        if details and details.get("cached_tokens"):
            usage["cached_tokens"] = int(details["cached_tokens"])
            break
    else:
        if usage_raw.get("cached_tokens"):
            usage["cached_tokens"] = int(usage_raw["cached_tokens"])

    return usage


def _parse_tool_call_arguments(args_raw: Any, name: str | None) -> Any:
    parsed = parse_tool_arguments(args_raw)
    if parsed == args_raw and isinstance(args_raw, str) and args_raw.strip():
        logger.warning(
            "Failed to parse tool call arguments for '{}': {}",
            name,
            args_raw[:200],
        )
    return parsed


def _tool_arguments_source(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return "{}"


async def iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    """Yield parsed JSON events from a Responses API SSE stream."""
    buffer: list[str] = []

    def _flush() -> dict[str, Any] | None:
        data_lines = [line[5:].strip() for line in buffer if line.startswith("data:")]
        buffer.clear()
        if not data_lines:
            return None
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            return None
        try:
            return json.loads(data)
        except Exception:
            logger.warning("Failed to parse SSE event JSON: {}", data[:200])
            return None

    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                event = _flush()
                if event is not None:
                    yield event
            continue
        buffer.append(line)

    # Flush any remaining buffer at EOF (#10)
    if buffer:
        event = _flush()
        if event is not None:
            yield event


async def consume_sse_with_reasoning(
    response: httpx.Response,
    on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    *,
    idle_timeout_s: float | None = None,
    first_output_timeout_s: float | None = None,
) -> tuple[str, list[ToolCallRequest], str, dict[str, int], str | None]:
    """Consume a Responses API SSE stream, including visible reasoning summaries.

    Con *idle_timeout_s* l'attesa di ogni evento ha un tetto, e solleva
    ``StreamTimeout`` come il ramo Chat Completions: *first_output_timeout_s*
    (il budget lungo) vale finché non è arrivato niente, poi l'idle.
    """
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    tool_call_args_emitted: set[str] = set()
    finish_reason = "stop"
    usage: dict[str, int] = {}
    reasoning_content: str | None = None
    streamed_reasoning = False
    saw_terminal = False

    async for event in _events_with_budget(
        iter_sse(response), idle_timeout_s, first_output_timeout_s,
    ):
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                arguments = item.get("arguments")
                tool_call_buffers[call_id] = {
                    "id": item.get("id") or "fc_0",
                    "name": item.get("name"),
                    "arguments": "" if arguments is None else arguments,
                }
                if on_tool_call_delta:
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(item.get("name") or ""),
                        "arguments_delta": "",
                    })
        elif event_type == "response.output_text.delta":
            delta_text = event.get("delta") or ""
            content += delta_text
            if on_content_delta and delta_text:
                await on_content_delta(delta_text)
        elif event_type == "response.reasoning_summary_text.delta":
            delta_text = event.get("delta") or ""
            if delta_text:
                reasoning_content = (reasoning_content or "") + delta_text
                streamed_reasoning = True
        elif event_type == "response.reasoning_summary_text.done":
            text = event.get("text") or ""
            if text and not streamed_reasoning and not reasoning_content:
                reasoning_content = text
        elif event_type == "response.reasoning_summary_part.done":
            part = event.get("part") or {}
            text = part.get("text") if part.get("type") == "summary_text" else None
            if text and not streamed_reasoning and not reasoning_content:
                reasoning_content = text
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                delta = event.get("delta") or ""
                current = tool_call_buffers[call_id].get("arguments")
                if not isinstance(current, str):
                    current = ""
                tool_call_buffers[call_id]["arguments"] = current + delta
                if on_tool_call_delta and delta:
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(tool_call_buffers[call_id].get("name") or ""),
                        "arguments_delta": str(delta),
                    })
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                arguments = event.get("arguments")
                tool_call_buffers[call_id]["arguments"] = arguments
                if on_tool_call_delta:
                    tool_call_args_emitted.add(str(call_id))
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(tool_call_buffers[call_id].get("name") or ""),
                        "arguments": "" if arguments is None else str(arguments),
                    })
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buf = tool_call_buffers.get(call_id) or {}
                args_raw = _tool_arguments_source(buf.get("arguments"), item.get("arguments"))
                if on_tool_call_delta and str(call_id) not in tool_call_args_emitted:
                    tool_call_args_emitted.add(str(call_id))
                    await on_tool_call_delta({
                        "call_id": str(call_id),
                        "name": str(buf.get("name") or item.get("name") or ""),
                        "arguments": str(args_raw),
                    })
                args = _parse_tool_call_arguments(
                    args_raw,
                    buf.get("name") or item.get("name"),
                )
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or item.get('id') or 'fc_0'}",
                        name=buf.get("name") or item.get("name") or "",
                        arguments=args,
                    )
                )
            elif item.get("type") == "reasoning" and not reasoning_content:
                summary = _extract_reasoning_summary_from_output([item])
                if summary:
                    reasoning_content = summary
        elif event_type in {"response.completed", "response.incomplete"}:
            # ``response.incomplete`` è l'evento terminale al posto di
            # ``completed`` quando la risposta si ferma al tetto di token: il suo
            # ``status`` è "incomplete" → ``length``, come nel ramo non-stream, e
            # porta l'usage. Ignorarlo dava ``stop`` e un usage vuoto.
            saw_terminal = True
            response_obj = event.get("response") or {}
            status = response_obj.get("status") or (
                "incomplete" if event_type == "response.incomplete" else None
            )
            finish_reason = map_finish_reason(status)
            usage = _usage_from_response_obj(response_obj) or usage
            if not reasoning_content:
                summary = _extract_reasoning_summary_from_output(response_obj.get("output") or [])
                if summary:
                    reasoning_content = summary
        elif event_type in {"error", "response.failed"}:
            # Lo status si ricava dal corpo (``server_error`` → 500): con un
            # ``RuntimeError`` nudo la retry policy vedeva solo il testo.
            raise ResponsesStreamError(stream_error_response(
                _stream_error_detail(event), partial_content=content or None,
            ))

    if not saw_terminal:
        # Chiuso prima della fine: il testo è un frammento, e una tool call
        # aperta ha argomenti a metà che non vanno eseguiti.
        raise ResponsesStreamError(stream_truncated_response(content or None))
    return content, tool_calls, finish_reason, usage, reasoning_content


async def _events_with_budget(
    events: AsyncGenerator[dict[str, Any], None],
    idle_timeout_s: float | None,
    first_output_timeout_s: float | None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Gli eventi di *events*, ciascuno atteso al più il budget in vigore.

    Senza budget è un passante. Finché il modello non ha prodotto output vale
    il budget lungo (sta ancora ragionando), dopo l'idle; allo scadere
    ``StreamTimeout`` dice quale dei due. Gli eventi di servizio che aprono lo
    stream (``response.created``, ``in_progress``, l'annuncio di un item) non
    contano: arrivano subito, e un ragionamento muto può durare minuti.
    """
    if idle_timeout_s is None:
        async for event in events:
            yield event
        return
    first_budget = first_output_timeout_s or idle_timeout_s
    saw_output = False
    iterator = events.__aiter__()
    while True:
        budget = idle_timeout_s if saw_output else first_budget
        try:
            event = await asyncio.wait_for(iterator.__anext__(), timeout=budget)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            raise StreamTimeout(budget, saw_output=saw_output) from exc
        if not saw_output:
            saw_output = _is_output_event(event)
        yield event


def _is_output_event(event: dict[str, Any]) -> bool:
    """Vero se *event* porta output del modello: testo, ragionamento, tool call."""
    event_type = str(event.get("type") or "")
    if event_type == "response.output_item.added":
        item = event.get("item") or {}
        return isinstance(item, dict) and item.get("type") == "function_call"
    if event_type.startswith("response.function_call_arguments."):
        return True
    if event_type.endswith(".delta"):
        return bool(event.get("delta"))
    if event_type in {"response.output_text.done", "response.reasoning_summary_text.done"}:
        return bool(event.get("text"))
    return False


def _extract_reasoning_summary_from_output(output: Any) -> str | None:
    parts: list[str] = []
    for item in output or []:
        if not isinstance(item, dict):
            dump = getattr(item, "model_dump", None)
            item = dump() if callable(dump) else vars(item)
        if item.get("type") != "reasoning":
            continue
        for summary in item.get("summary") or []:
            if not isinstance(summary, dict):
                dump = getattr(summary, "model_dump", None)
                summary = dump() if callable(dump) else vars(summary)
            if summary.get("type") == "summary_text" and summary.get("text"):
                parts.append(summary["text"])
    return "".join(parts) or None


def parse_response_output(response: Any) -> LLMResponse:
    """Parse an SDK ``Response`` object into an ``LLMResponse``."""
    if not isinstance(response, dict):
        dump = getattr(response, "model_dump", None)
        response = dump() if callable(dump) else vars(response)

    output = response.get("output") or []
    content_parts: list[str] = []
    tool_calls: list[ToolCallRequest] = []
    reasoning_content = _extract_reasoning_summary_from_output(output)

    for item in output:
        if not isinstance(item, dict):
            dump = getattr(item, "model_dump", None)
            item = dump() if callable(dump) else vars(item)

        item_type = item.get("type")
        if item_type == "message":
            for block in item.get("content") or []:
                if not isinstance(block, dict):
                    dump = getattr(block, "model_dump", None)
                    block = dump() if callable(dump) else vars(block)
                if block.get("type") == "output_text":
                    content_parts.append(block.get("text") or "")
        elif item_type == "function_call":
            call_id = item.get("call_id") or ""
            item_id = item.get("id") or "fc_0"
            args_raw = _tool_arguments_source(item.get("arguments"))
            args = _parse_tool_call_arguments(args_raw, item.get("name"))
            tool_calls.append(ToolCallRequest(
                id=f"{call_id}|{item_id}",
                name=item.get("name") or "",
                arguments=args,
            ))

    usage = _usage_from_response_obj(response)

    status = response.get("status")
    if status == "failed":
        # Una risposta ``failed`` non e' una risposta vuota ma un errore del
        # provider, come ``response.failed`` nel ramo stream: stessi metadati per
        # la retry policy, e un messaggio generico quando ``error`` manca o e'
        # ``null``. Senza, la turn vedeva un ``finish_reason="error"`` muto.
        nested = _as_mapping(response.get("error"))
        detail = nested if nested else {"message": "the response failed"}
        return stream_error_response(detail, partial_content="".join(content_parts) or None)
    finish_reason = map_finish_reason(status)

    return LLMResponse(
        content="".join(content_parts) or None,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        usage=usage,
        reasoning_content=reasoning_content if isinstance(reasoning_content, str) else None,
    )
