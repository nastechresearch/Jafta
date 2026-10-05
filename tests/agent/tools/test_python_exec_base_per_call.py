"""La base di ``python_exec`` è della chiamata, non dell'istanza.

``PythonExecTool.execute`` scriveva la base risolta su ``self.namespace.exec_base``
— un attributo dell'istanza condivisa da tutte le sessioni — e ``_enter_guard``
la rileggeva da lì quando la chiamata non ne passava una. Una chiamata senza
``working_dir`` in coda sul pool trovava la base messa nel frattempo da un'altra
sessione, e scriveva nella sua cartella (anche in un quaderno). Stessa cosa sul
ramo ``yield_time_ms``, dove il thread di sessione chiamava il namespace senza
argomenti.

Si passa dal tool vero (``await PythonExecTool.execute``), che è il percorso di
produzione con il salto in executor.
"""

from __future__ import annotations

import asyncio

from jafta.agent.tools.context import RequestContext, bind_request_context
from jafta.agent.tools.exec_session import ExecSessionManager
from jafta.agent.tools.python_exec import PythonExecTool
from jafta.config.schema import PythonExecConfig


def _tool(ws, manager: ExecSessionManager | None = None) -> PythonExecTool:
    cfg = PythonExecConfig()
    return PythonExecTool(
        working_dir=str(ws),
        timeout=30,
        allowed_modules=cfg.allowed_modules,
        blocked_modules=cfg.blocked_modules,
        restrict_to_workspace=True,
        workspace=str(ws),
        session_manager=manager,
    )


async def _as_session(key: str, coro):
    token = bind_request_context(RequestContext(channel="websocket", chat_id="c", session_key=key))
    try:
        return await coro
    finally:
        from jafta.agent.tools.context import _CURRENT_REQUEST_CONTEXT

        _CURRENT_REQUEST_CONTEXT.reset(token)


def _txt_files(ws) -> list[str]:
    return sorted(str(p.relative_to(ws)) for p in ws.rglob("*.txt"))


async def test_a_queued_call_without_working_dir_writes_at_the_root(tmp_path) -> None:
    ws = tmp_path.resolve()
    (ws / "wikis" / "p").mkdir(parents=True)
    tool = _tool(ws)

    # Il pool one-shot ha 4 worker: occupati tutti, la chiamata A resta in coda.
    busy = [
        asyncio.create_task(tool.execute(code="import time; time.sleep(0.6)"))
        for _ in range(4)
    ]
    await asyncio.sleep(0.1)
    a = asyncio.create_task(
        _as_session("unified:default", tool.execute(code="open('from_a.txt', 'w').write('A')")),
    )
    await asyncio.sleep(0)
    b = asyncio.create_task(
        _as_session("project:p", tool.execute(code="1", working_dir="wikis/p")),
    )
    await asyncio.gather(a, b, *busy)

    assert _txt_files(ws) == ["from_a.txt"], _txt_files(ws)


class _LateStartManager(ExecSessionManager):
    """Il thread della sessione parte dopo un giro del loop.

    Nessuna garanzia dice che il thread legga la base prima che il loop dia la
    mano a un'altra chiamata: qui quell'intervallo si allarga a 200 ms, così la
    gara è deterministica invece di dipendere dal GIL.
    """

    async def start_python(self, **kwargs):
        await asyncio.sleep(0.2)
        return await super().start_python(**kwargs)


async def test_a_session_thread_keeps_its_own_base(tmp_path) -> None:
    ws = tmp_path.resolve()
    (ws / "wikis" / "p").mkdir(parents=True)
    manager = _LateStartManager()
    tool = _tool(ws, manager)
    try:
        # A (ramo sessione, senza working_dir) parte in ritardo: nel frattempo
        # B chiede una base diversa sulla stessa istanza.
        a = asyncio.create_task(
            _as_session(
                "unified:default",
                tool.execute(code="open('from_a.txt', 'w').write('A')", yield_time_ms=2000),
            ),
        )
        await asyncio.sleep(0.05)
        await _as_session("project:p", tool.execute(code="1", working_dir="wikis/p"))
        out = await a
        assert "Exit code: 0" in out, out
    finally:
        manager.shutdown()

    assert _txt_files(ws) == ["from_a.txt"], _txt_files(ws)


async def test_a_session_thread_keeps_an_explicit_base(tmp_path) -> None:
    """Il ramo sessione con ``working_dir``: il thread scrive nella base chiesta.

    Il thread di sessione chiama il namespace senza argomenti, e la base gliela
    porta l'involucro. Qui la chiamata lenta chiede ``wikis/p`` e nel frattempo
    un'altra, sulla stessa istanza, gira alla radice.
    """
    ws = tmp_path.resolve()
    (ws / "wikis" / "p").mkdir(parents=True)
    manager = _LateStartManager()
    tool = _tool(ws, manager)
    try:
        a = asyncio.create_task(
            _as_session(
                "project:p",
                tool.execute(
                    code="open('from_a.txt', 'w').write('A')",
                    working_dir="wikis/p",
                    yield_time_ms=2000,
                ),
            ),
        )
        await asyncio.sleep(0.05)
        await _as_session(
            "unified:default", tool.execute(code="open('from_b.txt', 'w').write('B')"),
        )
        out = await a
        assert "Exit code: 0" in out, out
    finally:
        manager.shutdown()

    assert _txt_files(ws) == ["from_b.txt", "wikis/p/from_a.txt"], _txt_files(ws)
