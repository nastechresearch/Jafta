"""``wiki_lint``/``wiki_audit``/``wiki_scaffold`` eseguono la copia impacchettata.

Gli script si caricavano da ``<workspace>/skills/llm-wiki/scripts``, dentro
``_path_guard_bypass()``, e il commento diceva che lì «non c'è niente da
contenere» perché il percorso è fisso. Il percorso sì, il contenuto no: quella
cartella è nel workspace, quindi il modello la scrive con ``write_file``, e il
codice di primo livello dello script girava senza confine di percorso. Ora il
sorgente viene dal pacchetto (``jafta/skills``, sul telefono l'asset dell'APK),
cioè dagli stessi byte che l'avvio copia nel workspace; la copia del workspace
non si esegue più.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jafta.agent.tools import python_exec_builtins
from jafta.agent.tools.python_exec import PythonExecTool
from jafta.agent.tools.python_exec_builtins import _register_builtin_functions
from jafta.config.paths import get_workspace_path, set_workspace_dir
from jafta.config.tool_schemas import PythonExecConfig
from jafta.utils.android_assets import read_asset
from jafta.utils.helpers import sync_workspace_templates

_PACKAGED = Path(python_exec_builtins.__file__).resolve().parents[2] / "skills" / "llm-wiki"
_SCRIPTS = ("lint_wiki.py", "audit_review.py", "scaffold.py", "reindex_wikis.py")


@pytest.fixture
def workspace(tmp_path: Path):
    ws = (tmp_path / "workspace").resolve()
    (ws / "wikis" / "p" / "wiki").mkdir(parents=True)
    try:
        previous = get_workspace_path()
    except RuntimeError:
        previous = None
    set_workspace_dir(ws)
    try:
        yield ws
    finally:
        set_workspace_dir(previous) if previous else set_workspace_dir("")


def _tool(ws: Path) -> PythonExecTool:
    cfg = PythonExecConfig()
    tool = PythonExecTool(
        working_dir=str(ws),
        timeout=60,
        allowed_modules=cfg.allowed_modules,
        blocked_modules=cfg.blocked_modules,
        restrict_to_workspace=True,
        workspace=str(ws),
    )
    _register_builtin_functions(tool.namespace, workspace=str(ws), restrict_to_workspace=True)
    return tool


@pytest.mark.parametrize(
    "script, call",
    [
        ("lint_wiki.py", "wiki_lint('wikis/p')"),
        ("audit_review.py", "wiki_audit('wikis/p')"),
        ("reindex_wikis.py", "wiki_lint('wikis/p')"),
    ],
)
async def test_a_script_written_in_the_workspace_is_not_executed(
    workspace: Path, tmp_path: Path, script: str, call: str,
) -> None:
    escaped = tmp_path / "escaped.txt"
    # Come all'avvio: le copie vere nel workspace, poi una riscritta dal modello.
    # Il caso ``reindex_wikis.py`` è il fratello importato per nome dal lint.
    sync_workspace_templates(workspace, silent=True)
    scripts = workspace / "skills" / "llm-wiki" / "scripts"
    (scripts / script).write_text(
        f"open({str(escaped)!r}, 'w').write('ESCAPED')\n"
        "def lint(root):\n    print('finto')\n    return 0\n"
        "def main(root, mode):\n    print('finto')\n",
        encoding="utf-8",
    )

    out = await _tool(workspace).execute(code=f"print({call})")

    assert not escaped.exists(), f"lo script del workspace è girato senza confine: {out!r}"
    assert "finto" not in out, out


async def test_the_packaged_lint_runs(workspace: Path) -> None:
    out = await _tool(workspace).execute(code="print(wiki_lint('wikis/p'))")
    assert "Error" not in out.splitlines()[0], out
    assert "finto" not in out


def test_the_packaged_copy_is_what_boot_puts_in_the_workspace(tmp_path: Path) -> None:
    """La copia eseguita e quella del workspace sono gli stessi byte, finché nessuno la tocca."""
    sync_workspace_templates(tmp_path, silent=True)
    for name in _SCRIPTS:
        rel = f"llm-wiki/scripts/{name}"
        packaged = read_asset("jafta.skills", rel)
        assert packaged is not None, f"{rel} non si legge dal pacchetto"
        assert packaged == (_PACKAGED / "scripts" / name).read_bytes()
        assert packaged == (tmp_path / "skills" / rel).read_bytes()


def test_every_sibling_import_is_preloaded() -> None:
    """Un ``import <script fratello>`` non caricato prima cadrebbe su ``sys.path``.

    Cioè sulla prima cartella che lo contiene — magari quella del workspace. La
    lista dei fratelli va allungata quando uno script ne importa uno nuovo.
    """
    names = {n.removesuffix(".py") for n in _SCRIPTS}
    preloaded = {n.removesuffix(".py") for n in python_exec_builtins._WIKI_SCRIPT_SIBLINGS}
    for name in _SCRIPTS:
        tree = ast.parse((_PACKAGED / "scripts" / name).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module}
            else:
                continue
            missing = (imported & names) - preloaded
            assert not missing, f"{name} importa {missing}, che non è fra i fratelli precaricati"
