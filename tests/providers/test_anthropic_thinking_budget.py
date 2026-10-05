"""Il budget di thinking Anthropic sta dentro il ``max_tokens`` configurato.

Con effort ``high`` il budget era ``max(8192, max_tokens)`` e il ``max_tokens``
finale ``budget + 4096``: con un ``max_tokens`` configurato al tetto del modello
(32000 su un Opus 4) la richiesta partiva a 36096 e l'API la rifiutava. E
``minimal``, che sul ramo OpenAI spegne il thinking, qui lo accendeva con il
budget di default.
"""

from __future__ import annotations

import pytest

from jafta.providers.anthropic_provider import AnthropicProvider

MESSAGES = [{"role": "user", "content": "ciao"}]


def _kwargs(max_tokens: int, effort: str | None) -> dict:
    provider = AnthropicProvider(api_key="k", api_base="https://api.example.com")
    return provider._build_kwargs(
        MESSAGES, None, "claude-opus-4-1", max_tokens, 0.7, effort, None,
    )


@pytest.mark.parametrize("max_tokens", [16_000, 32_000, 64_000])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_the_final_max_tokens_never_exceeds_a_large_configured_one(
    max_tokens: int, effort: str,
) -> None:
    kwargs = _kwargs(max_tokens, effort)
    assert kwargs["max_tokens"] == max_tokens
    assert kwargs["thinking"]["budget_tokens"] < kwargs["max_tokens"]


def test_high_effort_still_gets_the_big_budget() -> None:
    kwargs = _kwargs(32_000, "high")
    assert kwargs["thinking"]["budget_tokens"] >= 8192
    assert kwargs["thinking"]["budget_tokens"] > _kwargs(32_000, "medium")["thinking"]["budget_tokens"]


def test_a_small_max_tokens_is_still_raised_to_fit_the_budget() -> None:
    kwargs = _kwargs(1024, "high")
    assert kwargs["max_tokens"] > kwargs["thinking"]["budget_tokens"] >= 8192


@pytest.mark.parametrize("effort", ["minimal", "minimum", "none"])
def test_minimal_turns_thinking_off_like_the_openai_branch(effort: str) -> None:
    kwargs = _kwargs(4096, effort)
    assert "thinking" not in kwargs
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 4096
