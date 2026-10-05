"""Un ``app.json`` con un tipo sbagliato e' un'app rotta, non un'eccezione.

``op``, ``method`` e ``view.kind`` si confrontavano con un ``set`` senza
guardarne il tipo: una lista o un dict sollevava ``TypeError: unhashable``, che
``load_app`` non raccoglie, fino alla costruzione di ``AgentLoop`` — il gateway
non partiva. Idem ``required`` con un dict dentro.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from jafta.apps.manifest import load_app, scan_apps

_BASE = {
    "name": "Piante",
    "description": "Monitoraggio piante",
    "server": {"baseUrl": "http://plants.test"},
    "actions": [
        {"name": "annota", "description": "Annota", "kind": "storage",
         "op": "append", "collection": "cure",
         "params": {"nota": {"type": "string"}}, "required": ["nota"]},
        {"name": "lista", "description": "Elenco", "kind": "http",
         "method": "GET", "path": "/plants"},
    ],
}


def _with(path: tuple, value) -> dict:
    data = copy.deepcopy(_BASE)
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return data


_CASES = {
    "op-list": _with(("actions", 0, "op"), ["append"]),
    "op-dict": _with(("actions", 0, "op"), {"append": 1}),
    "method-list": _with(("actions", 1, "method"), ["GET"]),
    "method-dict": _with(("actions", 1, "method"), {"GET": 1}),
    "view-kind-list": {**_BASE, "view": {"kind": ["external"]}},
    "view-kind-dict": {**_BASE, "view": {"kind": {"external": 1}}},
    "required-dict": _with(("actions", 0, "required"), [{"nota": 1}]),
    "required-list": _with(("actions", 0, "required"), [["nota"]]),
    "kind-list": _with(("actions", 0, "kind"), ["storage"]),
}


def _write(root: Path, slug: str, data) -> Path:
    app_dir = root / "apps" / slug
    app_dir.mkdir(parents=True)
    (app_dir / "app.json").write_text(json.dumps(data), encoding="utf-8")
    return app_dir


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_wrong_type_is_a_broken_app(tmp_path, case) -> None:
    app = load_app(_write(tmp_path, "piante", _CASES[case]))

    assert app.broken is True
    assert app.manifest is None
    assert app.error and "Traceback" not in app.error


def test_scan_apps_survives_every_broken_manifest(tmp_path) -> None:
    for i, case in enumerate(sorted(_CASES)):
        _write(tmp_path, f"app-{i}", _CASES[case])
    _write(tmp_path, "buona", _BASE)

    apps = scan_apps(tmp_path)

    assert {a.slug: a.broken for a in apps}["buona"] is False
    assert sum(a.broken for a in apps) == len(_CASES)


def test_scan_apps_never_raises_even_if_a_folder_cannot_be_read(tmp_path, monkeypatch) -> None:
    _write(tmp_path, "buona", _BASE)

    def _refuse(self, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_text", _refuse)

    apps = scan_apps(tmp_path)

    assert [a.broken for a in apps] == [True]
