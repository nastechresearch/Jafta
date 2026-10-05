"""``my set`` con una chiave puntata passa dalla stessa allowlist delle chiavi semplici.

Una chiave semplice su un attributo reale del loop è modificabile solo se è in
``RESTRICTED`` (o è ``model_preset``): capability fail-closed. Con una chiave
puntata il controllo guardava solo il primo segmento contro ``BLOCKED`` e la
foglia contro i dunder e i nomi sensibili, poi faceva ``setattr``:
``tools_config.restrict_to_workspace=false`` passava (con ``allowSet`` acceso,
spento di serie). Ora ogni segmento passa da ``BLOCKED`` e un attributo annidato
non è mai scrivibile; ``tools_config`` è bloccato anche in lettura, come gli
altri confini di sicurezza.
"""

from __future__ import annotations

import pytest

from jafta.agent.tools.self import MyTool
from jafta.config.schema import ToolsConfig


class _Loop:
    """La forma minima di ``AgentLoop`` che ``my`` tocca."""

    def __init__(self) -> None:
        self.tools_config = ToolsConfig()
        self.max_tool_result_chars = 16_000
        self.provider_retry_mode = "standard"
        self._runtime_vars: dict = {}
        self._last_usage: dict = {}


@pytest.mark.parametrize(
    "key, value",
    [
        ("tools_config.restrict_to_workspace", False),
        ("tools_config.python_exec.allowed_modules", ["subprocess"]),
        ("tools_config.python_exec.enable", True),
        ("provider_retry_mode.real", "x"),
    ],
)
async def test_a_dotted_key_cannot_reach_a_nested_runtime_attribute(key: str, value) -> None:
    loop = _Loop()
    before_restrict = loop.tools_config.restrict_to_workspace
    before_modules = list(loop.tools_config.python_exec.allowed_modules)

    out = await MyTool(loop, modify_allowed=True).execute(action="set", key=key, value=value)

    assert out.startswith("Error:"), out
    assert loop.tools_config.restrict_to_workspace == before_restrict
    assert loop.tools_config.python_exec.allowed_modules == before_modules


async def test_a_blocked_name_anywhere_in_the_path_is_refused() -> None:
    loop = _Loop()
    loop.holder = type("Holder", (), {})()
    loop.holder.restrict_to_workspace = True

    out = await MyTool(loop, modify_allowed=True).execute(
        action="set", key="holder.restrict_to_workspace", value=False,
    )
    assert out.startswith("Error:"), out
    assert loop.holder.restrict_to_workspace is True


async def test_tools_config_is_not_even_readable() -> None:
    out = await MyTool(_Loop(), modify_allowed=True).execute(
        action="check", key="tools_config.restrict_to_workspace",
    )
    assert "not accessible" in out, out


async def test_whitelisted_and_scratchpad_keys_still_work() -> None:
    loop = _Loop()
    tool = MyTool(loop, modify_allowed=True)
    assert "Set scratchpad.nota" in await tool.execute(action="set", key="nota", value="x")
