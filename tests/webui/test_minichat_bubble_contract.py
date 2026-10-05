"""Il fumetto della minichat e' scuro, e dentro si legge come un messaggio.

Fino al 28/09/2026 era `--accent` / `--on-accent`: nero su rosa in Synthwave. Lo
stesso giorno l'utente l'ha chiesto «bianco su rosa come gli altri messaggi», e
visto a schermo con una risposta intera dentro ha cambiato idea: «fallo scuro,
che cosi' ti acceca». Adesso e' la superficie delle schede (`--surface`) col
testo della chat.

Il contrasto di ogni parola della chat su `--surface` lo misura gia', tema per
tema, `test_home_you_contract.py::test_every_text_token_reads_in_every_theme`.
Qui si tiene ferma l'altra meta': che il fumetto stia su quel fondo, e che non
torni a un riempimento che accende tutto lo schermo.
"""

from __future__ import annotations

from pathlib import Path

from support import css_levels

ASSETS = Path(__file__).resolve().parents[2] / "jafta" / "templates" / "ui" / "assets"
CSS = (ASSETS / "mobile-style.css").read_text(encoding="utf-8")

# I riempimenti accesi: l'accento, e la bolla dell'utente (rosa pieno in Synthwave).
_BRIGHT = ("--accent", "--on-accent", "--bubble-user-")


def _one(selector: str) -> str:
    bodies = [body for sel, body, _ in css_levels.rules(CSS) if sel.strip() == selector]
    assert len(bodies) == 1, f"{selector}: {len(bodies)} regole"
    return bodies[0]


def test_the_bubble_is_dark_and_reads_like_the_chat() -> None:
    bubble = _one(".jafta-mc-bubble")
    assert "background: var(--surface)" in bubble
    assert "color: var(--text)" in bubble
    assert "var(--border-strong)" in bubble, "senza bordo, scuro su scrim scuro non si stacca"
    assert "var(--radius-bubble)" in bubble
    assert "14.5px" in bubble, "il testo non e' piu' quello dei messaggi"
    for bright in _BRIGHT:
        assert bright not in bubble, f"il fumetto e' tornato acceso: {bright}"


def test_the_tail_matches_the_bubble() -> None:
    tail = _one(".jafta-mc-bubble::after")
    assert "background: var(--surface)" in tail
    assert "var(--border-strong)" in tail, "la coda senza il bordo della bolla"
    assert "border-top" not in tail


def test_the_markdown_inside_uses_the_chat_colours() -> None:
    inside = [(sel, body) for sel, body, _ in css_levels.rules(CSS) if ".jafta-mc-text " in sel]
    assert inside, "il markdown del fumetto non ha stili suoi"
    for sel, body in inside:
        for bright in _BRIGHT:
            assert bright not in body, f"{sel} usa {bright}"
    assert "color: var(--text-accent)" in _one(".jafta-mc-text a")


def test_the_words_scroll_inside_and_the_tail_is_not_cut() -> None:
    text = _one(".jafta-mc-text")
    assert "overflow-y: auto" in text
    bubble = _one(".jafta-mc-bubble")
    assert "overflow" not in bubble, "un overflow sul fumetto taglierebbe la coda"
    assert "max-height" in bubble
    assert "pointer-events: auto" in bubble, "senza, non si scorre e i link non si toccano"
