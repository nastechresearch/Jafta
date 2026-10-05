from types import SimpleNamespace

from jafta.providers.anthropic_provider import AnthropicProvider
from jafta.providers.base import LLMProvider, LLMResponse
from jafta.providers.openai_compat_provider import OpenAICompatProvider


def test_openai_compat_error_captures_retry_after_from_headers() -> None:
    err = Exception("boom")
    err.doc = None
    err.response = SimpleNamespace(
        text='{"error":{"message":"Rate limit exceeded"}}',
        headers={"Retry-After": "20"},
    )

    response = OpenAICompatProvider._handle_error(err)

    assert response.retry_after == 20.0


def test_anthropic_error_captures_retry_after_from_headers() -> None:
    err = Exception("boom")
    err.response = SimpleNamespace(
        headers={"Retry-After": "20"},
    )

    response = AnthropicProvider._handle_error(err)

    assert response.retry_after == 20.0


# ── Il Retry-After ha un tetto anche in standard ──────────────────────────────


async def test_a_huge_retry_after_is_capped_in_standard_mode(monkeypatch) -> None:
    """``Retry-After: 3600`` in modalità standard bloccava la sessione ~3 ore.

    La modalità persistente aveva già il suo tetto (``_PERSISTENT_MAX_DELAY``);
    la standard aspettava alla lettera, tre volte. Ora ogni attesa si ferma a
    ``_STANDARD_MAX_DELAY``.
    """

    class _RateLimited(LLMProvider):
        async def chat(self, **_kwargs):
            return LLMResponse(
                content="Error: rate limited", finish_reason="error",
                error_status_code=429, error_retry_after_s=3600.0,
            )

        def get_default_model(self) -> str:
            return "m"

    slept: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("jafta.providers.base.asyncio.sleep", _fake_sleep)
    response = await _RateLimited().chat_with_retry(messages=[{"role": "user", "content": "x"}])

    assert response.finish_reason == "error"
    # Prima: 3 × 3600 s. Ora ogni attesa si ferma a un minuto al massimo.
    assert sum(slept) <= 60 * len(LLMProvider._CHAT_RETRY_DELAYS)
