"""I gruppi delle pagine hanno tinte loro, non quelle degli stati.

Il pallino di un'entita' era `--error` — il colore di «qualcosa e' andato
storto» su ogni persona e luogo di un quaderno — e quello di un concetto era
`--ok`, che in Y2K stava a 1,67:1 sul fondo. Ora `--group-concepts` e
`--group-entities`: un segno grafico, quindi 3:1 su ogni fondo di ogni tema,
e la coppia deve restare distinguibile (la ragione per cui la casa non usa i
colori della legenda del grafo: v. il commento in `home-style.css`).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from support import theme_tokens

CSS = Path(__file__).resolve().parents[2] / "jafta" / "templates" / "ui" / "assets" / "home-style.css"


def _rgb(color: str, under: str) -> tuple[float, float, float]:
    r = theme_tokens.rgba(color)
    b = theme_tokens.rgba(under)
    return tuple(r[i] * r[3] + b[i] * (1 - r[3]) for i in range(3))


def test_the_groups_do_not_borrow_the_state_colours() -> None:
    css = CSS.read_text(encoding="utf-8")
    for selector, prop in (
        (r"\.home-group-concepts", "background"),
        (r"\.home-group-entities", "background"),
        (r"\.home-map-nodes \.home-group-concepts", "fill"),
        (r"\.home-map-nodes \.home-group-entities", "fill"),
    ):
        m = re.search(r"\n" + selector + r" \{ " + prop + r": ([^;]+); \}", css)
        assert m, selector
        assert m.group(1).startswith("var(--group-"), f"{selector}: {m.group(1)}"


def test_the_group_marks_read_and_stay_apart_in_every_theme() -> None:
    problems = []
    for theme in theme_tokens.themes():
        v = theme_tokens.tokens(theme)
        for group in ("group-concepts", "group-entities"):
            assert v.get(group), f"{theme}: manca --{group}"
            assert v[group] not in (v["error"], v["ok"]), f"{theme}: --{group} e' uno stato"
            for ground in ("bg", "surface"):
                ratio = theme_tokens.contrast(v[group], v[ground], v["bg"])
                if ratio < 3:
                    problems.append(f"{theme}: --{group} su --{ground} = {ratio:.2f}")
        c, e = _rgb(v["group-concepts"], v["bg"]), _rgb(v["group-entities"], v["bg"])
        other = _rgb(v["text-faint"], v["bg"])
        # La soglia del commento in home-style.css: sotto ~100 di distanza RGB
        # due pallini a occhio sono lo stesso pallino.
        if math.dist(c, e) < 100:
            problems.append(f"{theme}: concetti ed entita' distano {math.dist(c, e):.0f}")
        if min(math.dist(c, other), math.dist(e, other)) < 100:
            problems.append(f"{theme}: un gruppo si confonde con «altro»")
    assert not problems, problems
