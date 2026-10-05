"""``read_file`` e ``grep`` misurano un file prima di leggerlo.

``grep`` leggeva ogni file per intero e solo dopo guardava il tetto: 600 MB di
RSS per saltare un video. ``read_file`` leggeva il file due volte (tre con la
deduplica) e senza nessun tetto, tutto sul thread del loop. Ora la dimensione si
chiede a ``stat``, il contenuto si legge una volta sola e, per ``read_file`` e i
file grandi di ``grep``, fuori dal loop.

Le letture si contano sostituendo ``Path.read_bytes``: un file oltre il tetto
che venisse letto farebbe esplodere la sonda invece di passare in silenzio.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from jafta.agent.tools.filesystem import ReadFileTool
from jafta.agent.tools.search import GrepTool


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch):
    """Registra ogni ``Path.read_bytes``: (nome del file, thread che legge)."""
    calls: list[tuple[str, int]] = []
    real = Path.read_bytes

    def _spy(self: Path) -> bytes:
        calls.append((self.name, threading.get_ident()))
        if self.name.startswith("huge"):
            raise AssertionError(f"{self.name} è oltre il tetto: non andava letto")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", _spy)
    return calls


def _sparse(path: Path, size: int) -> Path:
    with open(path, "wb") as fh:
        fh.truncate(size)
    return path


async def test_grep_skips_an_oversized_file_without_reading_it(tmp_path: Path, reads) -> None:
    (tmp_path / "notes.md").write_text("hello world\n", encoding="utf-8")
    _sparse(tmp_path / "huge.mp4", GrepTool._MAX_FILE_BYTES + 1)

    out = await GrepTool(workspace=tmp_path, allowed_dir=tmp_path).execute(pattern="hello")

    assert "notes.md" in out and "skipped 1 large files" in out, out
    assert [name for name, _ in reads] == ["notes.md"]


async def test_grep_reads_a_large_file_off_the_loop(tmp_path: Path, reads) -> None:
    big = tmp_path / "big.log"
    big.write_text(("riga qualunque\n" * 20_000) + "ago nel pagliaio\n", encoding="utf-8")

    out = await GrepTool(workspace=tmp_path, allowed_dir=tmp_path).execute(
        pattern="pagliaio", output_mode="content",
    )

    assert "ago nel pagliaio" in out, out
    [(name, ident)] = reads
    assert name == "big.log" and ident != threading.get_ident()


async def test_read_file_refuses_an_oversized_file_without_reading_it(
    tmp_path: Path, reads,
) -> None:
    _sparse(tmp_path / "huge.log", ReadFileTool._MAX_FILE_BYTES + 1)

    out = await ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path).execute(path="huge.log")

    assert "too large" in out and "python_exec" in out, out
    assert reads == []


async def test_read_file_reads_once_and_off_the_loop(tmp_path: Path, reads) -> None:
    (tmp_path / "a.txt").write_text("uno\ndue\n", encoding="utf-8")
    tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)

    out = await tool.execute(path="a.txt")
    assert "1| uno" in out, out
    assert len(reads) == 1, reads
    assert reads[0][1] != threading.get_ident(), "letto sul thread del loop"

    # Anche la seconda lettura, quella che finisce nella deduplica.
    reads.clear()
    out = await tool.execute(path="a.txt")
    assert "File unchanged" in out, out
    assert len(reads) == 1, reads
