"""Ogni sessione ha il suo namespace ``python_exec``.

Il tool è uno per processo e il suo ``PythonNamespace`` teneva un solo dizionario
di globali per tutte le sessioni: una variabile assegnata dentro un quaderno si
leggeva dalla chat personale, e un ``def read_file(...)`` scritto in una sessione
sostituiva il builtin registrato per tutte, fino al riavvio.

La chiave è la session key del turno (``RequestContext.session_key``). Dentro la
stessa sessione lo stato resta, com'è sempre stato: è ciò che rende utile
``python_exec`` da una chiamata all'altra. Si passa dal tool vero, sia dal ramo
one-shot (executor) sia dal ramo ``yield_time_ms`` (thread di sessione).
"""

from __future__ import annotations

from jafta.agent.tools.context import (
    _CURRENT_REQUEST_CONTEXT,
    RequestContext,
    bind_request_context,
)
from jafta.agent.tools.exec_session import ExecSessionManager
from jafta.agent.tools.python_exec import PythonExecTool
from jafta.agent.tools.python_exec_builtins import _register_builtin_functions
from jafta.config.schema import PythonExecConfig


def _tool(ws, manager: ExecSessionManager) -> PythonExecTool:
    cfg = PythonExecConfig()
    tool = PythonExecTool(
        working_dir=str(ws),
        timeout=30,
        allowed_modules=cfg.allowed_modules,
        blocked_modules=cfg.blocked_modules,
        restrict_to_workspace=True,
        workspace=str(ws),
        session_manager=manager,
    )
    _register_builtin_functions(tool.namespace, workspace=str(ws), restrict_to_workspace=True)
    return tool


async def _run(key: str, tool: PythonExecTool, **kwargs) -> str:
    token = bind_request_context(RequestContext(channel="websocket", chat_id="c", session_key=key))
    try:
        return await tool.execute(**kwargs)
    finally:
        _CURRENT_REQUEST_CONTEXT.reset(token)


async def test_a_notebook_variable_is_not_visible_from_the_personal_chat(tmp_path) -> None:
    ws = tmp_path.resolve()
    manager = ExecSessionManager()
    tool = _tool(ws, manager)
    try:
        await _run("project:acme", tool, code="client_notes = 'segreto del quaderno'")
        # Stessa sessione: lo stato resta.
        assert "segreto del quaderno" in await _run("project:acme", tool, code="client_notes")

        out = await _run("unified:default", tool, code="client_notes")
        assert "segreto" not in out, out
        assert "NameError" in out, out

        # Anche dal ramo sessione (thread grezzo).
        out = await _run("unified:default", tool, code="print(client_notes)", yield_time_ms=2000)
        assert "segreto" not in out and "NameError" in out, out
        out = await _run("project:acme", tool, code="print(client_notes)", yield_time_ms=2000)
        assert "segreto del quaderno" in out, out
    finally:
        manager.shutdown()


async def test_redefining_a_builtin_breaks_only_its_own_session(tmp_path) -> None:
    ws = tmp_path.resolve()
    (ws / "SOUL.md").write_text("io\n", encoding="utf-8")
    manager = ExecSessionManager()
    tool = _tool(ws, manager)
    try:
        await _run("project:acme", tool, code="def read_file(p):\n    return 'shadowed'")
        assert "shadowed" in await _run("project:acme", tool, function="read_file", args=["SOUL.md"])

        out = await _run("unified:default", tool, function="read_file", args=["SOUL.md"])
        assert "shadowed" not in out and "io" in out, out
        out = await _run("unified:default", tool, code="read_file('SOUL.md')")
        assert "shadowed" not in out and "io" in out, out
    finally:
        manager.shutdown()


def _make_project(ws, name: str, wiki_id: str):
    root = ws / "wikis" / name
    (root / "wiki").mkdir(parents=True)
    (root / "AGENTS.md").write_text(f"---\nid: {wiki_id}\n---\n", encoding="utf-8")
    return root


async def _run_in_project(name: str, tool: PythonExecTool, ws, **kwargs) -> str:
    from jafta.security.workspace_access import (
        bind_workspace_scope,
        build_workspace_scope,
        reset_workspace_scope,
    )

    scope = bind_workspace_scope(build_workspace_scope(ws / "wikis" / name, "restricted"))
    try:
        return await _run(f"project:{name}", tool, **kwargs)
    finally:
        reset_workspace_scope(scope)


async def test_a_recreated_project_does_not_find_the_old_globals(tmp_path) -> None:
    """Cancellato e ricreato con lo stesso nome, un progetto è un progetto nuovo."""
    import shutil

    ws = tmp_path.resolve()
    manager = ExecSessionManager()
    tool = _tool(ws, manager)
    try:
        root = _make_project(ws, "acme", "aaaaaaaaaaaa")
        await _run_in_project("acme", tool, ws, code="client_notes = 'del vecchio'")
        assert "del vecchio" in await _run_in_project("acme", tool, ws, code="client_notes")

        shutil.rmtree(root)
        _make_project(ws, "acme", "bbbbbbbbbbbb")

        out = await _run_in_project("acme", tool, ws, code="client_notes")
        assert "del vecchio" not in out and "NameError" in out, out
    finally:
        manager.shutdown()


async def test_deleted_and_renamed_projects_release_their_globals(tmp_path) -> None:
    import shutil

    ws = tmp_path.resolve()
    manager = ExecSessionManager()
    tool = _tool(ws, manager)
    try:
        gone = _make_project(ws, "via", "aaaaaaaaaaaa")
        moved = _make_project(ws, "vecchio", "bbbbbbbbbbbb")
        await _run_in_project("via", tool, ws, code="x = 1")
        await _run_in_project("vecchio", tool, ws, code="y = 2")
        assert {"project:via", "project:vecchio"} <= set(tool.namespace.session_keys())

        shutil.rmtree(gone)
        moved.rename(ws / "wikis" / "nuovo")
        # Una chiamata qualunque, anche dalla chat personale, fa la pulizia.
        await _run("unified:default", tool, code="1")

        keys = set(tool.namespace.session_keys())
        assert "project:via" not in keys and "project:vecchio" not in keys, keys
        assert "unified:default" in keys
    finally:
        manager.shutdown()


async def test_a_function_registered_later_reaches_every_session(tmp_path) -> None:
    ws = tmp_path.resolve()
    manager = ExecSessionManager()
    tool = _tool(ws, manager)
    try:
        await _run("project:acme", tool, code="x = 1")
        tool.namespace.register_function("late_helper", lambda: "arrivato")
        assert "arrivato" in await _run("project:acme", tool, code="late_helper()")
        assert "arrivato" in await _run("unified:default", tool, code="late_helper()")
    finally:
        manager.shutdown()


async def test_a_monitor_job_run_leaves_no_python_globals(tmp_path) -> None:
    """La sessione ``cron:<id>`` di un monitor non porta variabili da un run all'altro."""
    from jafta.bus.events import InboundMessage
    from jafta.providers.base import LLMResponse, ToolCallRequest
    from tests.support.agent import make_loop, make_provider

    provider = make_provider()
    step = {"n": 0}

    async def chat(**_kw):
        step["n"] += 1
        if step["n"] % 2 == 1:
            return LLMResponse(content="", finish_reason="tool_calls", tool_calls=[
                ToolCallRequest(id=f"c{step['n']}", name="python_exec",
                                arguments={"code": "z = 5"}),
            ])
        return LLMResponse(content="fatto")

    provider.chat_with_retry = chat
    provider.chat_stream_with_retry = chat
    # Col modo orchestratore (il default) il loop principale non ha
    # ``python_exec``, e i subagent si fanno un registro nuovo a ogni run.
    loop = make_loop(tmp_path, provider=provider, orchestrator_mode=False)
    tool = loop.tools.get("python_exec")
    assert tool is not None

    await loop.process_direct("controlla", session_key="cron:job-1")
    assert step["n"] == 2
    assert "cron:job-1" not in tool.namespace.session_keys()

    await loop._dispatch(InboundMessage(
        channel="websocket", sender_id="u", chat_id="default", content="controlla",
        session_key_override="cron:job-2",
    ))
    assert step["n"] == 4
    assert "cron:job-2" not in tool.namespace.session_keys()

    # La chat personale invece tiene i suoi.
    await loop.process_direct("calcola", session_key="unified:default")
    assert step["n"] == 6
    assert "unified:default" in tool.namespace.session_keys()
