"""``tools.pythonExec.maxOutputChars`` è il tetto vero dell'output.

``create`` passava il valore di config al costruttore, che lo salvava in
``self.max_output_chars``; ma ``execute`` ripiegava sulla costante di classe
``_MAX_OUTPUT`` (10.000), e la descrizione per il modello diceva «10000» fisso.
Alzare il tetto in config non cambiava niente.
"""

from __future__ import annotations

from types import SimpleNamespace

from jafta.agent.tools.python_exec import PythonExecTool
from jafta.config.schema import PythonExecConfig


def _tool(ws, limit: int) -> PythonExecTool:
    return PythonExecTool(
        working_dir=str(ws), workspace=str(ws), max_output_chars=limit,
        restrict_to_workspace=True,
    )


async def test_the_configured_ceiling_is_the_default(tmp_path) -> None:
    out = await _tool(tmp_path, 50_000).execute(code="print('x' * 30000)")
    assert out.count("x") == 30_000, len(out)

    out = await _tool(tmp_path, 2_000).execute(code="print('x' * 30000)")
    assert "chars truncated" in out and out.count("x") == 2_000, len(out)


async def test_an_explicit_argument_still_wins(tmp_path) -> None:
    out = await _tool(tmp_path, 50_000).execute(code="print('x' * 30000)", max_output_chars=1_000)
    assert out.count("x") == 1_000


async def test_write_stdin_defaults_to_the_configured_ceiling(tmp_path) -> None:
    """Un poll senza ``max_output_chars`` usa il tetto di config, come ``python_exec``."""
    from jafta.agent.tools.exec_session import ExecSessionManager, WriteStdinTool

    cfg = PythonExecConfig(max_output_chars=50_000)
    ctx = SimpleNamespace(
        config=SimpleNamespace(python_exec=cfg, restrict_to_workspace=True),
        workspace=tmp_path,
    )
    manager = ExecSessionManager()
    tool = PythonExecTool(
        working_dir=str(tmp_path), workspace=str(tmp_path), max_output_chars=50_000,
        restrict_to_workspace=True, session_manager=manager,
    )
    stdin = WriteStdinTool.create(ctx)
    stdin._manager = manager
    try:
        started = await tool.execute(
            code="import time\ntime.sleep(0.3)\nprint('x' * 30000)", yield_time_ms=0,
        )
        session_id = started.split("session_id: ")[1].split()[0]
        out = await stdin.execute(session_id=session_id, yield_time_ms=5000)
        assert "truncated" not in out, out[-200:]
        assert "x" * 30_000 in out, len(out)
    finally:
        manager.shutdown()


def test_create_wires_the_config_and_the_description_tells_it(tmp_path) -> None:
    cfg = PythonExecConfig(max_output_chars=25_000)
    ctx = SimpleNamespace(
        config=SimpleNamespace(python_exec=cfg, restrict_to_workspace=True),
        workspace=tmp_path,
    )
    tool = PythonExecTool.create(ctx)
    assert tool.max_output_chars == 25_000
    assert "25000" in tool.description and "10000 chars" not in tool.description
