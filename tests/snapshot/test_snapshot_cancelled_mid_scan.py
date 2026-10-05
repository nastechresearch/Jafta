"""Uno snapshot cancellato a meta' tiene il lock finche' il suo thread non finisce.

``stop()`` cancella il task del timer, e se quel task e' dentro ``snapshot_now``
la cancellazione arriva all'``await`` di ``asyncio.to_thread``: il coroutine
esce, il lock si libera, ma il **thread** continua. Lo snapshot di shutdown che
il container fa subito dopo partiva allora accanto a lui: due ``create_snapshot``
insieme, e il gc della retention poteva togliere i blob che il thread orfano
aveva gia' scritto e il suo manifest, scritto dopo, avrebbe referenziato.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from support.aio import wait_until

from jafta.config.schema import SnapshotConfig
from jafta.snapshot.engine import SnapshotEngine
from jafta.snapshot.service import SnapshotService


async def test_the_shutdown_snapshot_waits_for_the_cancelled_one(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.md").write_text("uno", encoding="utf-8")
    engine = SnapshotEngine(ws, tmp_path / "snapshots")
    service = SnapshotService(engine, SnapshotConfig())

    release = threading.Event()
    inside = 0
    peak = 0
    entered: list[str] = []
    guard = threading.Lock()
    real_create = engine.create_snapshot

    def _slow_create(**kwargs):
        nonlocal inside, peak
        with guard:
            inside += 1
            peak = max(peak, inside)
            entered.append(kwargs["trigger"])
        try:
            if kwargs["trigger"] == "auto":
                release.wait(5)
            return real_create(**kwargs)
        finally:
            with guard:
                inside -= 1

    engine.create_snapshot = _slow_create  # type: ignore[method-assign]

    in_flight = asyncio.ensure_future(service.snapshot_now("auto"))
    await wait_until(lambda: entered == ["auto"], timeout=5)
    in_flight.cancel()  # quel che fa ``stop()`` al task del timer
    shutdown = asyncio.ensure_future(service.snapshot_now("shutdown"))
    await asyncio.sleep(0.2)

    assert entered == ["auto"], "lo snapshot di shutdown e' partito accanto al thread orfano"

    release.set()
    await asyncio.wait([in_flight], timeout=5)
    assert in_flight.cancelled()
    await asyncio.wait_for(shutdown, timeout=5)
    assert peak == 1
    assert entered == ["auto", "shutdown"]
