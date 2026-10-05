"""Un loop di symlink **vero** davanti al gate di path, su 3.11 come su 3.14.

``test_symlink_loop_resolve.py`` simula il loop facendo sollevare
``Path.resolve`` a mano; qui il loop c'e' davvero sul disco. Su Python 3.11 —
quello del telefono — ``Path.resolve(strict=False)`` davanti a un loop solleva
``RuntimeError``; dal 3.13 ``pathlib`` passa da ``os.path.realpath`` e il loop
resta nel percorso, irrisolto. ``_resolve_path`` lasciava uscire la
``RuntimeError`` dal gate unico: le rotte del file manager rispondevano 500, il
wrapper di ``python_exec`` la girava al codice dell'utente, e il loop non
si poteva nemmeno cancellare, perche' anche la cancellazione passa dal gate.

Questi test vanno fatti girare **su 3.11** (il venv del repo): su 3.14 erano
verdi anche prima.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jafta.config.loader import load_config, save_config
from jafta.config.schema import Config
from jafta.runtime.context import get_runtime_context
from jafta.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    root = (tmp_path / "ws").resolve()
    root.mkdir()
    # Un loop su se stesso e un loop a due, i due casi che ``realpath`` vede.
    os.symlink("ciclo", root / "ciclo")
    os.symlink("b", root / "a")
    os.symlink("a", root / "b")
    return root


def test_a_loop_inside_the_workspace_resolves_without_raising(workspace: Path) -> None:
    for name in ("ciclo", "a", "ciclo/sotto"):
        resolved = resolve_allowed_path(name, workspace=workspace, allowed_root=workspace)
        assert resolved.is_relative_to(workspace)


def test_strict_resolution_of_a_loop_is_an_oserror(workspace: Path) -> None:
    with pytest.raises(OSError) as exc:
        resolve_allowed_path("ciclo", workspace=workspace, allowed_root=workspace, strict=True)
    # Non un rifiuto del confine: il percorso e' dentro, e' il file che non c'e'.
    assert not isinstance(exc.value, WorkspaceBoundaryError)


def test_a_loop_still_cannot_reach_outside(tmp_path: Path, workspace: Path) -> None:
    """Il ripiego non apre il confine: un percorso fuori resta fuori."""
    outside = tmp_path / "fuori"
    outside.mkdir()
    os.symlink("ciclo", outside / "ciclo")
    with pytest.raises(WorkspaceBoundaryError):
        resolve_allowed_path(str(outside / "ciclo"), workspace=workspace, allowed_root=workspace)


# ---------------------------------------------------------------------------
# Le rotte del file manager: 4xx, mai 500
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    monkeypatch.setattr(get_runtime_context(), "config_path", path)
    config = load_config(path)
    config.workspace.enabled = True
    save_config(config, path)
    return path


@pytest.mark.parametrize(
    ("route", "query"),
    [
        ("/api/workspace/list", "path=ciclo"),
        ("/api/workspace/read", "path=ciclo"),
        ("/api/workspace/download", "path=ciclo"),
        ("/api/workspace/list", "path=a"),
    ],
)
async def test_the_workspace_routes_answer_a_loop_with_a_4xx(
    workspace: Path, config_path: Path, route: str, query: str
) -> None:
    from websockets.datastructures import Headers
    from websockets.http11 import Request as WsRequest

    from jafta.webui.workspace_routes import WorkspaceRoutes

    routes = WorkspaceRoutes(check_api_token=lambda _r: True, get_workspace_root=lambda: workspace)
    reply = await routes.dispatch(WsRequest(path=f"{route}?{query}", headers=Headers()), route)
    assert reply is not None
    assert 400 <= reply.status_code < 500


# ---------------------------------------------------------------------------
# python_exec: il codice dell'utente vede un OSError, e il loop si cancella
# ---------------------------------------------------------------------------


def _namespace(workspace: Path):
    from jafta.agent.tools.python_exec import PythonNamespace
    from jafta.config.tool_schemas import PythonExecConfig

    cfg = PythonExecConfig()
    return PythonNamespace(
        working_dir=str(workspace),
        allowed_modules=cfg.allowed_modules,
        blocked_modules=cfg.blocked_modules,
        restrict_to_workspace=True,
        workspace=str(workspace),
    )


def test_python_exec_opening_a_loop_raises_an_oserror(workspace: Path) -> None:
    code = (
        "try:\n"
        "    open('ciclo').read()\n"
        "except OSError as e:\n"
        "    print('oserror')\n"
    )
    stdout, stderr, _ = _namespace(workspace).execute(code)
    assert "RuntimeError" not in stderr
    assert "oserror" in stdout


def test_python_exec_can_remove_a_loop(workspace: Path) -> None:
    _stdout, stderr, _ = _namespace(workspace).execute("import os; os.unlink('ciclo')")
    assert stderr == ""
    assert not os.path.lexists(workspace / "ciclo")
