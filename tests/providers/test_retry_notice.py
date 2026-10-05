"""Le righe d'attesa del retry si traducono, e la traduzione le riconosce tutte.

Il provider le scrive in inglese e il dispatcher le traduce nella lingua
dell'agente: se una frase cambia da una parte e non dall'altra, la riga torna a
comparire in inglese senza che niente si rompa. Qui ogni frase che il provider
produce passa per la traduzione.
"""

from __future__ import annotations

import pytest

from jafta.providers import retry_notice
from jafta.providers.base import LLMProvider, LLMResponse


@pytest.mark.parametrize("text, expected", [
    (retry_notice.waiting(3, 1, persistent=False),
     "Il modello non risponde: riprovo fra 3 s (tentativo 1)."),
    (retry_notice.waiting(60, 7, persistent=True),
     "Il modello non risponde: riprovo ancora fra 60 s (tentativo 7)."),
    (retry_notice.stopped(10), "Smetto di riprovare: 10 errori uguali di fila."),
    (retry_notice.gave_up(4), "Il modello non ha risposto dopo 4 tentativi: mi fermo."),
])
def test_every_notice_has_an_italian_line(text: str, expected: str) -> None:
    assert retry_notice.localize(text, "it") == expected


def test_other_text_and_languages_are_left_alone() -> None:
    line = retry_notice.waiting(3, 1, persistent=False)
    assert retry_notice.localize(line, "en") == line
    assert retry_notice.localize(line, None) == line
    assert retry_notice.localize("read_file(foo.py)", "it") == "read_file(foo.py)"


class _AlwaysFailing(LLMProvider):
    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content="503 server error", finish_reason="error",
                           error_status_code=503)

    def get_default_model(self) -> str:
        return "m"


async def test_the_lines_the_provider_writes_are_all_translated(monkeypatch) -> None:
    async def _no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("jafta.providers.base.asyncio.sleep", _no_sleep)
    lines: list[str] = []

    async def _collect(text: str) -> None:
        lines.append(text)

    await _AlwaysFailing().chat_with_retry(
        messages=[{"role": "user", "content": "x"}], on_retry_wait=_collect,
    )

    assert lines
    assert all(retry_notice.localize(line, "it") != line for line in lines)
