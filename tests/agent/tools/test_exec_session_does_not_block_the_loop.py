"""L'attesa di una sessione ``python_exec`` non ferma l'event loop.

``_PythonSession.poll()`` faceva ``time.sleep()`` sul thread del loop: con
``python_exec(yield_time_ms=30000)`` tutto il gateway (WebSocket, cron, gli altri
turni) restava fermo 30 s, fino a 120 s con ``write_stdin(wait_for=…)``. Qui un
ticker da 50 ms conta i propri giri mentre il tool aspetta: se l'attesa dorme sul
loop, i giri sono zero o uno.

Si passa dal tool vero, non dal gestore: è ``execute`` che il runner chiama.
"""

from __future__ import annotations

import asyncio
import time

from jafta.agent.tools.exec_session import ExecSessionManager, WriteStdinTool
from jafta.agent.tools.python_exec import PythonExecTool
from jafta.config.schema import PythonExecConfig

_LONG_CODE = "import time\nfor _ in range(200):\n    time.sleep(0.05)\n"


def _tool(ws, manager: ExecSessionManager) -> PythonExecTool:
    cfg = PythonExecConfig()
    tool = PythonExecTool(
        working_dir=str(ws),
        timeout=30,
        allowed_modules=cfg.allowed_modules,
        blocked_modules=cfg.blocked_modules,
        restrict_to_workspace=True,
        workspace=str(ws),
    )
    tool._session_manager = manager
    return tool


async def _ticks_during(coro) -> tuple[int, float, object]:
    ticks = 0
    stop = asyncio.Event()

    async def ticker() -> None:
        nonlocal ticks
        while not stop.is_set():
            await asyncio.sleep(0.05)
            ticks += 1

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)
    t0 = time.monotonic()
    try:
        out = await coro
    finally:
        stop.set()
        await task
    return ticks, time.monotonic() - t0, out


async def test_python_exec_yield_keeps_the_loop_running(tmp_path) -> None:
    manager = ExecSessionManager()
    tool = _tool(tmp_path, manager)
    try:
        ticks, elapsed, out = await _ticks_during(
            tool.execute(code=_LONG_CODE, yield_time_ms=800),
        )
        assert "session_id: " in str(out), out
        assert elapsed >= 0.7, elapsed
        # 800 ms a 50 ms fanno ~16 giri; ne basta meno della metà.
        assert ticks >= 6, f"il loop è rimasto fermo: {ticks} giri in {elapsed:.2f}s"
    finally:
        manager.shutdown()


async def test_write_stdin_yield_and_wait_for_keep_the_loop_running(tmp_path) -> None:
    manager = ExecSessionManager()
    tool = _tool(tmp_path, manager)
    stdin = WriteStdinTool(manager=manager)
    try:
        out = await tool.execute(code=_LONG_CODE, yield_time_ms=0)
        sid = str(out).split("session_id: ")[1].split()[0]

        ticks, elapsed, _ = await _ticks_during(
            stdin.execute(session_id=sid, yield_time_ms=800),
        )
        assert ticks >= 6, f"write_stdin(yield): {ticks} giri in {elapsed:.2f}s"

        ticks, elapsed, out = await _ticks_during(
            stdin.execute(session_id=sid, wait_for="never printed", wait_timeout_ms=1200),
        )
        assert "Wait target not observed" in str(out), out
        assert ticks >= 10, f"write_stdin(wait_for): {ticks} giri in {elapsed:.2f}s"
    finally:
        manager.shutdown()


async def test_the_wait_ends_as_soon_as_the_session_finishes(tmp_path) -> None:
    """Un'attesa lunga su un codice breve torna appena il thread ha finito."""
    manager = ExecSessionManager()
    tool = _tool(tmp_path, manager)
    try:
        t0 = time.monotonic()
        out = await tool.execute(
            code="import time\ntime.sleep(0.3)\nprint('fatto')", yield_time_ms=10_000,
        )
        assert "fatto" in str(out) and "Exit code: 0" in str(out), out
        assert time.monotonic() - t0 < 5, "ha aspettato tutto yield_time_ms"
    finally:
        manager.shutdown()
