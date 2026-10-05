"""Un campo della config scritto con un'altra grafia.

``config.json`` accetta ``max_tokens`` come ``maxTokens``, ma lo riscrive sempre con
la grafia del modello. Prima il loader riportava la grafia vecchia in coda al dump
come chiave «ignota», e alla lettura dopo vinceva lei: ogni modifica dalla UI si
salvava e restava senza effetto, per sempre, con un avviso che la diceva «ignorata».
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger as loguru_logger

from jafta.config.loader import load_config, load_config_with_raw
from jafta.config.schema import CURRENT_CONFIG_VERSION, AgentDefaults
from jafta.config.store import mutate


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _warnings_while(fn) -> list[str]:
    records: list[str] = []
    handler = loguru_logger.add(lambda m: records.append(str(m)), level="WARNING")
    try:
        fn()
    finally:
        loguru_logger.remove(handler)
    return records


def _set_max_tokens(value: int):
    def apply(cfg) -> None:
        cfg.agents.defaults.max_tokens = value

    return apply


async def test_a_snake_case_key_is_read_and_a_ui_change_to_it_sticks(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"configVersion": CURRENT_CONFIG_VERSION,
                  "agents": {"defaults": {"max_tokens": 4096}}})
    assert load_config(path).agents.defaults.max_tokens == 4096

    await mutate(_set_max_tokens(9999), config_path=path)

    defaults = json.loads(path.read_text())["agents"]["defaults"]
    assert defaults["maxTokens"] == 9999
    assert "max_tokens" not in defaults
    assert load_config(path).agents.defaults.max_tokens == 9999


def test_a_lone_snake_case_key_is_not_reported_as_ignored(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"agents": {"defaults": {"max_tokens": 4096}}})

    warnings = _warnings_while(lambda: load_config_with_raw(path))

    assert [w for w in warnings if "max_tokens" in w] == []


def test_the_camel_case_spelling_wins_whatever_the_order(tmp_path) -> None:
    path = tmp_path / "config.json"
    # La grafia vecchia **dopo** quella del modello: era il caso che vinceva.
    path.write_text(
        '{"agents": {"defaults": {"maxTokens": 9999, "max_tokens": 4096}}}',
        encoding="utf-8",
    )

    assert load_config(path).agents.defaults.max_tokens == 9999


def test_the_shadowed_spelling_is_named_in_a_truthful_warning(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"agents": {"defaults": {"maxTokens": 9999, "max_tokens": 4096}}})

    warnings = _warnings_while(lambda: load_config_with_raw(path))

    assert not [w for w in warnings if "not recognised" in w]
    shadowed = [w for w in warnings if "two spellings" in w]
    assert len(shadowed) == 1 and "agents.defaults.max_tokens" in shadowed[0]


async def test_the_shadowed_spelling_is_dropped_on_the_first_write(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"agents": {"defaults": {"maxTokens": 9999, "max_tokens": 4096}}})

    await mutate(lambda _cfg: None, config_path=path)

    defaults = json.loads(path.read_text())["agents"]["defaults"]
    assert defaults["maxTokens"] == 9999 and "max_tokens" not in defaults


async def test_a_synonym_that_is_not_the_snake_form_is_dropped_too(tmp_path) -> None:
    """``sessionTtlMinutes`` e' la grafia generata; il modello scrive l'alias dichiarato."""
    assert AgentDefaults.model_fields["session_ttl_minutes"].serialization_alias == (
        "idleCompactAfterMinutes"
    )
    path = tmp_path / "config.json"
    _write(path, {"agents": {"defaults": {"sessionTtlMinutes": 7}}})

    await mutate(lambda _cfg: None, config_path=path)

    defaults = json.loads(path.read_text())["agents"]["defaults"]
    assert defaults["idleCompactAfterMinutes"] == 7
    assert "sessionTtlMinutes" not in defaults


async def test_hand_written_model_presets_follow_ui_changes(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"modelPresets": {"fast": {"model": "model-a", "maxTokens": 512}}})

    def change(cfg) -> None:
        cfg.model_presets["fast"].model = "model-b"

    await mutate(change, config_path=path)

    data = json.loads(path.read_text())
    assert data["modelPresets"]["fast"]["model"] == "model-b"
    assert "model_presets" not in data
    assert load_config(path).model_presets["fast"].model == "model-b"


async def test_the_legacy_model_presets_key_is_rewritten_camel_case(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"model_presets": {"fast": {"model": "model-a", "max_tokens": 512}}})

    await mutate(lambda _cfg: None, config_path=path)

    data = json.loads(path.read_text())
    assert "model_presets" not in data
    assert data["modelPresets"]["fast"] == {**data["modelPresets"]["fast"], "maxTokens": 512}
    assert "max_tokens" not in data["modelPresets"]["fast"]
    assert load_config(path).model_presets["fast"].max_tokens == 512


async def test_a_spelling_inside_a_list_item_is_reported_when_shadowed(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"providers": {"providers": [
        {"name": "p", "format": "openai_compat", "apiBase": "http://a.test",
         "api_base": "http://b.test"},
    ]}})

    warnings = _warnings_while(lambda: load_config_with_raw(path))

    assert load_config(path).providers.providers[0].api_base == "http://a.test"
    assert any("providers.providers[0].api_base" in w for w in warnings if "two spellings" in w)


async def test_truly_unknown_keys_are_still_kept_and_reported(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"agents": {"defaults": {"futureKnob": 1, "max_tokens": 4096}}})

    warnings = _warnings_while(lambda: load_config_with_raw(path))
    await mutate(lambda _cfg: None, config_path=path)

    assert any("agents.defaults.futureKnob" in w for w in warnings if "not recognised" in w)
    defaults = json.loads(path.read_text())["agents"]["defaults"]
    assert defaults["futureKnob"] == 1 and "max_tokens" not in defaults


async def test_extract_document_text_is_read_under_its_documented_name(tmp_path) -> None:
    """La documentazione scrive ``extractDocumentText``, e il modello lo leggeva
    come chiave ignota: l'impostazione non aveva effetto."""
    path = tmp_path / "config.json"
    _write(path, {"extractDocumentText": True})
    assert load_config(path).extract_document_text is True

    await mutate(lambda _cfg: None, config_path=path)

    data = json.loads(path.read_text())
    assert data["extractDocumentText"] is True and "extract_document_text" not in data


async def test_the_old_extract_document_text_spelling_is_still_read(tmp_path) -> None:
    path = tmp_path / "config.json"
    _write(path, {"extract_document_text": True})

    await mutate(lambda _cfg: None, config_path=path)

    data = json.loads(path.read_text())
    assert data["extractDocumentText"] is True and "extract_document_text" not in data
    assert load_config(path).extract_document_text is True
