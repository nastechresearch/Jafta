"""Un percorso restituito da ``grep``/``find_files`` si apre con ``read_file``.

Dentro un progetto i percorsi relativi si misurano dalla cartella del progetto,
ma le letture arrivano a tutta l'installazione (``_read_allowed_root``). Un file
trovato fuori dal progetto — la skill in ``skills/`` — era mostrato relativo alla
radice della *ricerca* (``llm-wiki/SKILL.md``), che ``read_file`` risolveva
dentro il progetto: «File not found» per un percorso che il tool stesso aveva
appena dato.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jafta.agent.tools.filesystem import ReadFileTool
from jafta.agent.tools.search import FindFilesTool, GrepTool
from jafta.security.workspace_access import build_workspace_scope, enter_workspace_scope


@pytest.fixture
def install(tmp_path: Path):
    root = (tmp_path / "ws").resolve()
    (root / "skills" / "llm-wiki").mkdir(parents=True)
    (root / "skills" / "llm-wiki" / "SKILL.md").write_text("# regola della wiki\n", encoding="utf-8")
    project = root / "wikis" / "p"
    (project / "wiki").mkdir(parents=True)
    (project / "wiki" / "index.md").write_text("# regola del progetto\n", encoding="utf-8")
    with enter_workspace_scope(build_workspace_scope(project, "restricted")):
        yield root


def _first_path(out: str) -> str:
    return out.strip().splitlines()[0].split(":", 1)[0].rstrip("/")


async def _readable(root: Path, returned: str) -> str:
    return await ReadFileTool(workspace=root, allowed_dir=root).execute(path=returned)


async def test_a_grep_hit_outside_the_project_can_be_read(install: Path) -> None:
    out = await GrepTool(workspace=install, allowed_dir=install).execute(
        pattern="regola", path=str(install / "skills"),
    )
    returned = _first_path(out)
    assert "regola della wiki" in await _readable(install, returned), returned


async def test_a_find_files_hit_outside_the_project_can_be_read(install: Path) -> None:
    out = await FindFilesTool(workspace=install, allowed_dir=install).execute(
        path=str(install / "skills"), glob="*.md",
    )
    returned = _first_path(out)
    assert "regola della wiki" in await _readable(install, returned), returned


async def test_a_hit_inside_the_project_stays_relative(install: Path) -> None:
    out = await GrepTool(workspace=install, allowed_dir=install).execute(pattern="regola")
    assert _first_path(out) == "wiki/index.md", out


async def test_the_query_filter_ignores_the_folders_above_the_install(install: Path) -> None:
    """Il filtro ``query`` guarda il percorso nell'installazione, non quello assoluto.

    Fuori dal progetto il risultato si mostra assoluto, ma confrontare il
    filtro con quel testo faceva passare ogni file per una parola che sta sopra
    l'installazione (qui il nome della sua cartella, ``ws``, o quello della
    cartella temporanea del test).
    """
    tool = FindFilesTool(workspace=install, allowed_dir=install)
    (install / "skills" / "llm-wiki" / "notes.md").write_text("x\n", encoding="utf-8")
    above = install.parent.name

    assert await tool.execute(path=str(install / "skills"), query=above) == "No files found"
    assert await tool.execute(path=str(install / "skills"), query="ws") == "No files found"

    out = await tool.execute(path=str(install / "skills"), query="llm-wiki notes")
    assert out.strip().splitlines() == [str(install / "skills" / "llm-wiki" / "notes.md")], out
    # Come dentro l'installazione: il percorso conta dalla sua radice.
    out = await tool.execute(path=str(install / "skills"), query="skills SKILL.md")
    assert out.strip().splitlines() == [str(install / "skills" / "llm-wiki" / "SKILL.md")], out
