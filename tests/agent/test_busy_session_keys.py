"""Chi scrive adesso sotto quale sessione: ``AgentLoop.busy_session_keys``.

La chiede ``project.rename``, che non deve spostare una conversazione di progetto
mentre qualcuno ci sta scrivendo: altrimenti a fine lavoro quel qualcuno scrive
sotto il nome vecchio, e resta una chat senza cartella. La prima guardia
(``41c7d20``) leggeva solo i turni di chat in volo (``active_session_keys``), e
gli scrittori erano altri due in piu':

- **un subagent** lanciato dal quaderno sopravvive al turno che l'ha creato, e a
  fine lavoro scrive i suoi record e annuncia il risultato sotto la chiave
  d'origine;
- **una passata del giardiniere** gira sotto una chiave sua (``gardener:…``) ma
  scrive nella cartella della wiki.

Poi se n'e' trovato un quarto: **l'autocompact**, che compattando
o raccogliendo il diario rilegge e salva la sessione dopo una chiamata LLM.

``active_session_keys`` resta com'era: l'autocompact e il giardiniere la leggono
con il significato «un turno di chat sta usando la sessione».
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jafta.agent import gardener
from jafta.agent.autocompact import AutoCompact
from jafta.agent.loop import AgentLoop
from jafta.agent.subagent import SubagentManager
from jafta.runtime.container import GatewayContainer


def _subagents(sessions: dict[str, dict[str, bool]]) -> SubagentManager:
    """Un manager con soli i due dizionari che contano: origine → task, vivo o no."""
    manager = SubagentManager.__new__(SubagentManager)
    manager._session_tasks = {key: set(tasks) for key, tasks in sessions.items()}
    manager._running_tasks = {
        tid: SimpleNamespace(done=lambda finished=finished: finished)
        for tasks in sessions.values()
        for tid, finished in tasks.items()
    }
    return manager


def test_a_subagent_still_running_keeps_its_origin_busy() -> None:
    manager = _subagents({
        "project:viaggio": {"t1": False},          # vivo
        "project:orto": {"t2": True},              # finito, non ancora ripulito
        "unified:default": {"t3": True, "t4": False},
    })
    assert set(manager.active_origin_session_keys()) == {"project:viaggio", "unified:default"}


def _autocompact(*, archiving: tuple[str, ...] = (), harvesting: tuple[str, ...] = ()) -> AutoCompact:
    compact = AutoCompact.__new__(AutoCompact)
    compact._archiving = set(archiving)
    compact._harvesting = set(harvesting)
    return compact


def _loop(
    *,
    turns: tuple[str, ...] = (),
    subagent_origins: tuple[str, ...] = (),
    auto_compact: AutoCompact | None = None,
) -> AgentLoop:
    loop = AgentLoop.__new__(AgentLoop)
    loop._pending_queues = {key: asyncio.Queue() for key in turns}
    loop.subagents = SimpleNamespace(active_origin_session_keys=lambda: subagent_origins)
    loop.auto_compact = auto_compact or _autocompact()
    return loop


def test_busy_is_turns_plus_subagents_plus_gardener_passes(monkeypatch) -> None:
    monkeypatch.setattr(gardener, "_PASSES_IN_FLIGHT", {"orto"})
    loop = _loop(turns=("unified:default",), subagent_origins=("project:viaggio",))

    assert set(loop.busy_session_keys()) == {
        "unified:default", "project:viaggio", "project:orto",
    }
    # La domanda stretta non cambia: solo i turni di chat.
    assert loop.active_session_keys() == ("unified:default",)


def test_a_key_busy_twice_is_listed_once(monkeypatch) -> None:
    monkeypatch.setattr(gardener, "_PASSES_IN_FLIGHT", {"viaggio"})
    loop = _loop(turns=("project:viaggio",), subagent_origins=("project:viaggio",))
    assert loop.busy_session_keys() == ("project:viaggio",)


def test_busy_includes_what_the_autocompact_is_rewriting(monkeypatch) -> None:
    monkeypatch.setattr(gardener, "_PASSES_IN_FLIGHT", set())
    compact = _autocompact(archiving=("unified:default",), harvesting=("project:orto",))
    loop = _loop(auto_compact=compact)

    assert set(loop.busy_session_keys()) == {"unified:default", "project:orto"}
    assert loop.active_session_keys() == ()


async def test_a_diary_harvest_keeps_its_project_busy_until_it_saves(tmp_path) -> None:
    """La finestra vera: la sessione si rilegge e si salva **dopo** la chiamata LLM.

    Si entra da ``check_expired``, cioe' dalla porta vera, e non si aggiunge la
    chiave a mano: il test che la aggiungeva da se'
    restava verde anche togliendo l'``add`` di ``check_expired``, cioe' proprio
    la riga che la regressione di M1 aveva perso.
    """
    from datetime import datetime, timedelta

    from jafta.session.manager import SessionManager
    from tests.support.aio import wait_until

    entered, release = asyncio.Event(), asyncio.Event()

    class _Consolidator:
        def messages_fitting_budget(self, messages, *, session_key):
            return len(messages)

        async def archive(self, messages, *, session_key, raw_dump_on_failure):
            entered.set()
            await release.wait()
            return "- riassunto"

    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("project:orto")
    for i in range(3):
        session.add_message("user", f"riga {i}")
    session.updated_at = datetime.now() - timedelta(hours=6)
    sessions.save(session)
    compact = AutoCompact(sessions, _Consolidator(), session_ttl_minutes=30)  # type: ignore[arg-type]
    tasks: list[asyncio.Task] = []

    compact.check_expired(lambda coro: tasks.append(asyncio.ensure_future(coro)))

    assert len(tasks) == 1
    await asyncio.wait_for(entered.wait(), timeout=5.0)
    assert compact.busy_session_keys() == ("project:orto",)
    release.set()
    await asyncio.wait_for(tasks[0], timeout=5.0)
    await wait_until(lambda: compact.busy_session_keys() == (), timeout=5.0)


def test_the_gardener_hands_out_a_copy_of_its_passes(monkeypatch) -> None:
    monkeypatch.setattr(gardener, "_PASSES_IN_FLIGHT", {"orto"})
    copy = gardener.passes_in_flight()
    assert copy == frozenset({"orto"})
    with pytest.raises(AttributeError):
        copy.add("altro")  # type: ignore[attr-defined]


# ── Il collegamento nel container ───────────────────────────────────────────


def test_the_container_asks_the_agent_and_says_nobody_without_one() -> None:
    """Senza questo test un rinomino del metodo passerebbe verde e romperebbe
    ``project.rename`` solo sul telefono."""
    container = GatewayContainer.__new__(GatewayContainer)
    container._agent = None
    assert container._busy_session_keys() == ()

    container._agent = _loop(subagent_origins=("project:viaggio",))
    assert container._busy_session_keys() == ("project:viaggio",)
