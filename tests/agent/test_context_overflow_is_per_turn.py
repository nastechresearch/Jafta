"""Un overflow di contesto riduce la finestra del turno, non del processo.

Il callback ``_on_context_overflow`` scriveva la finestra dimezzata in
``AgentLoop.context_window_tokens`` e nel Consolidator: da lì valeva per ogni
turno successivo di **ogni** sessione, fino al riavvio, e un solo overflow (anche
un falso allarme di un provider che non dice il limite) dimezzava per sempre la
storia rimandata al modello. Ora la riduzione vive nello ``spec`` del turno in
corso, e la compattazione che il callback lancia la vede solo lei.
"""

from __future__ import annotations

from jafta.providers.base import LLMResponse
from tests.support.agent import make_loop, make_provider


async def test_one_overflow_does_not_halve_the_window_for_later_turns(tmp_path):
    provider = make_provider()
    calls = {"n": 0}

    async def chat(**_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # Un overflow senza numero (solo il codice, alla OpenRouter).
            return LLMResponse(content="context_length_exceeded", finish_reason="error",
                               error_code="context_length_exceeded")
        return LLMResponse(content="ok")

    provider.chat_with_retry = chat
    provider.chat_stream_with_retry = chat
    loop = make_loop(tmp_path, provider=provider, context_window_tokens=128_000)
    seen_windows: list[int] = []
    original = loop.consolidator.maybe_consolidate_by_tokens

    async def spy(session, **kwargs):
        seen_windows.append(loop.consolidator._window)
        return await original(session, **kwargs)

    loop.consolidator.maybe_consolidate_by_tokens = spy

    await loop.process_direct("ciao", session_key="unified:default",
                              channel="websocket", chat_id="default")

    assert calls["n"] == 2  # l'overflow è stato recuperato nel turno
    # La compattazione del callback ha visto la finestra ridotta...
    assert 64_000 in seen_windows
    # ...e dopo il turno la finestra è quella configurata, per tutti.
    assert loop.context_window_tokens == 128_000
    assert loop.consolidator.context_window_tokens == 128_000
    assert loop.consolidator._window == 128_000
