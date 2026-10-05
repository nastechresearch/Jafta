"""Un valore fuori da un ``Literal`` costa il suo campo, non il file.

Prima un ``providerRetryMode`` che questa versione non conosce (scritto da una
versione piu' nuova, o a mano) faceva rifiutare ``config.json`` intero — e il
``.bak``, che porta lo stesso valore: il gateway ripartiva sui default di tutto,
provider compresi.
"""

from __future__ import annotations

import json
from typing import Literal

import pytest
from loguru import logger as loguru_logger

from jafta.config.loader import load_config
from jafta.pydantic_compat import BaseModel, ValidationError, lenient_literals
from jafta.runtime.context import get_runtime_context


@pytest.fixture(autouse=True)
def _clean_recovery_flags():
    ctx = get_runtime_context()
    ctx.config_recovered_from = None
    ctx.config_quarantine_path = None
    yield
    ctx.config_recovered_from = None
    ctx.config_quarantine_path = None


def _warnings_while(fn) -> tuple[object, list[str]]:
    records: list[str] = []
    handler = loguru_logger.add(lambda m: records.append(str(m)), level="WARNING")
    try:
        result = fn()
    finally:
        loguru_logger.remove(handler)
    return result, records


def test_an_unknown_literal_falls_back_on_its_own_default(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "agents": {"defaults": {"providerRetryMode": "aggressive", "maxTokens": 1234}},
        "providers": {"providers": [
            {"name": "p", "format": "openai_compat", "apiBase": "http://llm.test"},
        ]},
    }), encoding="utf-8")

    config, warnings = _warnings_while(lambda: load_config(path))

    assert config.agents.defaults.provider_retry_mode == "standard"
    assert config.agents.defaults.max_tokens == 1234
    assert [p.name for p in config.providers.providers] == ["p"]
    assert get_runtime_context().config_recovered_from is None
    assert not list(tmp_path.glob("config.corrupt-*"))
    assert any("provider_retry_mode" in w and "aggressive" in w for w in warnings)


def test_an_unknown_literal_inside_a_list_item_keeps_the_item(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"providers": {"providers": [
        {"name": "p", "format": "openai_compat", "apiType": "future_api"},
    ]}}), encoding="utf-8")

    config = load_config(path)

    assert config.providers.providers[0].api_type == "auto"
    assert get_runtime_context().config_recovered_from is None


def test_a_required_literal_still_rejects_the_file(tmp_path) -> None:
    """Senza un default su cui ricadere non c'e' niente da tenere: si recupera come prima."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"providers": {"providers": [
        {"name": "p", "format": "future_format"},
    ]}}), encoding="utf-8")

    load_config(path)

    assert get_runtime_context().config_recovered_from == "defaults"


class _Mode(BaseModel):
    kind: Literal["a", "b"] = "a"


def test_outside_the_block_a_literal_is_as_strict_as_pydantic() -> None:
    with pytest.raises(ValidationError):
        _Mode.model_validate({"kind": "z"})


def test_inside_the_block_the_fallback_is_reported() -> None:
    with lenient_literals() as fallbacks:
        model = _Mode.model_validate({"kind": "z"})

    assert model.kind == "a"
    assert fallbacks == [("_Mode", "kind", "z")]
