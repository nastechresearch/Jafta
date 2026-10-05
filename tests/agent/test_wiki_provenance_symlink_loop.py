"""Un loop di symlink non fa cadere i ganci di provenienza.

Su Python 3.11 ``Path.resolve()`` su un loop di symlink solleva ``RuntimeError``
(dalla 3.13 non piu'), e i due ganci — :func:`_provenance_guard` della passata del
giardiniere e :func:`wiki_page_provenance_guard` della conversazione — lo
catturano: un'eccezione li' diventerebbe un ``write_file`` fallito per un motivo
che il modello non puo' capire. Nessun test lo provava: togliere ``RuntimeError``
dagli ``except`` restava verde. Qui il loop e' vero (e sul 3.11 solleva davvero),
e c'e' la stessa prova con ``resolve`` forzato a sollevare, che vale su ogni
versione.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from jafta.agent.wiki_provenance import _provenance_guard, wiki_page_provenance_guard

JOURNAL = "# 2026-09-26\n\n- 10:00 — [said] Si parte il 12.\n"
DECIDED = "---\ntitle: X\nstate: decided\nsource: {source}\n---\n\n# X\n\nIl contenuto.\n"


@pytest.fixture
def project(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "wikis" / "esempio"
    (root / "wiki").mkdir(parents=True)
    (root / "raw" / "journal").mkdir(parents=True)
    (root / "raw" / "journal" / "20260926.md").write_text(JOURNAL, encoding="utf-8")
    return root


def _loop(directory: pathlib.Path) -> pathlib.Path:
    """``a -> b -> a`` dentro *directory*; torna un percorso che ci passa attraverso."""
    os.symlink(directory / "b", directory / "a")
    os.symlink(directory / "a", directory / "b")
    return directory / "a" / "pagina.md"


def _raise_on_loop(monkeypatch, loop_path: pathlib.Path) -> None:
    """``resolve`` come sul 3.11: ``RuntimeError`` sul percorso del loop."""
    original = pathlib.Path.resolve

    def resolve(self, *args, **kwargs):
        if str(self) == str(loop_path):
            raise RuntimeError(f"Symlink loop from {self!r}")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "resolve", resolve)


def _guards(project: pathlib.Path):
    return (
        _provenance_guard(project.resolve(), (project / "wiki").resolve()),
        wiki_page_provenance_guard(),
    )


def test_a_write_through_a_real_loop_does_not_raise(project) -> None:
    loop_path = _loop(project / "wiki")
    text = DECIDED.format(source="raw/journal/20260926.md#10:00")
    for guard in _guards(project):
        verdict = guard(loop_path, text)
        assert verdict is None or isinstance(verdict, str)


@pytest.mark.parametrize("which", [0, 1], ids=["gardener", "conversation"])
def test_a_loop_that_raises_on_resolve_is_a_no_not_a_crash(project, monkeypatch, which) -> None:
    loop_path = _loop(project / "wiki")
    guard = _guards(project)[which]
    _raise_on_loop(monkeypatch, loop_path)

    assert guard(loop_path, DECIDED.format(source="raw/journal/20260926.md#10:00")) is None


def test_a_source_through_a_loop_cannot_certify(project) -> None:
    """Il verso fail-closed: una ``source:`` che passa da un loop non risolve."""
    _loop(project / "raw")
    page = project / "wiki" / "pagina.md"
    text = DECIDED.format(source="raw/a/20260926.md#10:00")
    for guard in _guards(project):
        verdict = guard(page, text)
        assert isinstance(verdict, str) and verdict
