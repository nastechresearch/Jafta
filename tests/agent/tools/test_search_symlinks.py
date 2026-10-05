"""``grep`` e ``find_files`` non seguono un link che esce dal confine.

``read_file`` rifiuta un symlink del workspace che punta fuori; ``grep`` lo apriva
e ne stampava il contenuto (``apiKey=…`` di un file esterno), e ``find_files``
lo elencava come un file qualunque. Ora un file-symlink conta solo se il suo
bersaglio passa lo stesso controllo di lettura di ``read_file``; un link che
resta dentro continua a funzionare.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jafta.agent.tools.filesystem import ReadFileTool
from jafta.agent.tools.search import FindFilesTool, GrepTool


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("apiKey=sk-OUTSIDE\n", encoding="utf-8")
    root = tmp_path / "ws"
    root.mkdir()
    (root / "real.txt").write_text("apiKey=dentro\n", encoding="utf-8")
    os.symlink(outside / "secret.txt", root / "notes.txt")
    os.symlink(root / "real.txt", root / "alias.txt")
    return root


async def test_read_file_refuses_the_outside_link(ws: Path) -> None:
    out = await ReadFileTool(workspace=ws, allowed_dir=ws).execute(path="notes.txt")
    assert "OUTSIDE" not in out


async def test_grep_does_not_follow_a_link_outside(ws: Path) -> None:
    out = await GrepTool(workspace=ws, allowed_dir=ws).execute(
        pattern="apiKey", output_mode="content",
    )
    assert "OUTSIDE" not in out and "notes.txt" not in out, out
    assert "real.txt" in out and "alias.txt" in out, out


async def test_find_files_does_not_list_a_link_outside(ws: Path) -> None:
    out = await FindFilesTool(workspace=ws, allowed_dir=ws).execute(glob="*.txt")
    assert "notes.txt" not in out, out
    assert "real.txt" in out and "alias.txt" in out, out
