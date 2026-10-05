"""Una riga più lunga del tetto di ``read_file`` si legge a pezzi.

Con la prima riga della finestra oltre i 128K caratteri il taglio non teneva
nessuna riga: «Showing lines 1-0 … Use offset=1 to continue», cioè lo stesso
invito all'infinito, e un JS minificato restava illeggibile. Ora si mostra la
testa della riga e si dice un argomento che fa avanzare davvero.
"""

from __future__ import annotations

import re
from pathlib import Path

from jafta.agent.tools.filesystem import ReadFileTool

_CAP = ReadFileTool._MAX_CHARS


async def test_a_single_huge_line_shows_its_head_and_never_loops(tmp_path: Path) -> None:
    (tmp_path / "min.js").write_text("x" * 200_000, encoding="utf-8")

    out = await ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path).execute(path="min.js")

    assert out.startswith("1| xxx"), out[:80]
    assert out.count("x") >= _CAP // 2, "della riga non si vede quasi niente"
    assert len(out) <= _CAP + 1_000
    assert "lines 1-0" not in out and "offset=1 " not in out and "offset=1." not in out, out[-400:]
    assert "200,000" in out, out[-400:]


async def test_the_next_offset_moves_past_the_long_line(tmp_path: Path) -> None:
    (tmp_path / "mixed.txt").write_text(
        "y" * 150_000 + "\nseconda riga\nterza riga\n", encoding="utf-8",
    )
    tool = ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path)

    out = await tool.execute(path="mixed.txt")
    match = re.search(r"offset=(\d+)", out)
    assert match, out[-400:]
    assert int(match.group(1)) == 2, out[-400:]

    out = await tool.execute(path="mixed.txt", offset=int(match.group(1)))
    assert "2| seconda riga" in out and "3| terza riga" in out, out
