"""La raccolta del diario di un progetto: leggere senza accorciare.

**Fase D del piano della memoria di progetto, e la fase senza la quale la
corsia esisteva a vuoto.** Aperta la scrittura di ``append_history`` a una chiave
``project:``, il trasporto restava quello della compattazione — un riassunto lo
produce solo chi compatta — e la compattazione per inattivita' i progetti non li
tocca di proposito. Misurato sul telefono l'08/09/2026: **3 sessioni di progetto
su 9** erano mai state consolidate, e fra le sei escluse c'erano quelle da 54,
64, 78 e 80 messaggi, cioe' le conversazioni piu' ricche di fatti sulla persona.

Da cui la forma di questo lavoro, che e' l'opposto di una compattazione: legge i
messaggi nuovi, ne mette un riassunto nella coda **con la chiave del progetto**,
e lascia la sessione esattamente com'era. I due cancelli che difendono la
compattazione di un progetto — il recinto sull'inattivita' e
``_pages_carry_the_project`` — qui non c'entrano: difendono i messaggi
dall'essere buttati, e qui non si butta niente. Il recinto vive in
``test_autocompact_project_fence.py``, e le due meta' vanno lette insieme.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jafta.agent.autocompact import AutoCompact
from jafta.agent.memory import Consolidator, MemoryStore
from jafta.session.manager import SessionManager

PROJECT = "project:palestra"
PERSONAL = "unified:default"


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path)


@pytest.fixture
def consolidator(tmp_path: Path, store: MemoryStore) -> Consolidator:
    """Un ``Consolidator`` vero con un provider finto.

    Vero di proposito: il pezzo da provare e' che il riassunto **arrivi nella
    coda con la chiave giusta**, e quel percorso — ``archive`` →
    ``append_history`` — e' esattamente quel che un doppio nasconderebbe.
    """
    provider = MagicMock()
    provider.chat_with_retry = AsyncMock(
        return_value=MagicMock(content="- fatto sulla persona", finish_reason="stop")
    )
    return Consolidator(
        store=store,
        sessions=SessionManager(tmp_path),
        provider=provider,
        model="m",
        context_window_tokens=100_000,
        build_messages=MagicMock(return_value=[]),
        get_tool_definitions=MagicMock(return_value=[]),
        max_completion_tokens=100,
    )


@pytest.fixture
def autocompact(consolidator: Consolidator) -> AutoCompact:
    return AutoCompact(
        sessions=consolidator.sessions, consolidator=consolidator, session_ttl_minutes=30
    )


def _talked(
    autocompact: AutoCompact, key: str, turns: int = 3, *, stale: bool = True, tag: str = "a"
):
    session = autocompact.sessions.get_or_create(key)
    for i in range(turns):
        session.messages.append({"role": "user", "content": f"messaggio {tag}{i}"})
        session.messages.append({"role": "assistant", "content": f"risposta {tag}{i}"})
    if stale:
        session.updated_at = datetime.now() - timedelta(hours=6)
    autocompact.sessions.save(session)
    return session


class TestTheHarvestReads:
    async def test_the_summary_ends_up_in_the_queue_with_the_project_key(
        self, autocompact, store
    ):
        _talked(autocompact, PROJECT)

        await autocompact._harvest_project_diary(PROJECT)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert [e["content"] for e in entries] == ["- fatto sulla persona"]
        # La chiave e' meta' del confine: senza, la voce entrerebbe in ogni
        # prompt e Dream la estrarrebbe con le regole della conversazione
        # personale.
        assert entries[0]["session_key"] == PROJECT

    async def test_the_session_does_not_lose_a_message(self, autocompact):
        """La differenza con la compattazione, detta come asserzione.

        Un progetto puo' stare fermo tre settimane e riprendere dove era: e' il
        suo mestiere. Se questo lavoro accorciasse la conversazione sarebbe una
        compattazione con un altro nome, e il recinto che la vieta sarebbe
        aggirato da qui.
        """
        _talked(autocompact, PROJECT)
        before = list(autocompact.sessions.get_or_create(PROJECT).messages)

        await autocompact._harvest_project_diary(PROJECT)

        assert autocompact.sessions.get_or_create(PROJECT).messages == before

    async def test_does_not_touch_last_summary(self, autocompact):
        """``_last_summary`` e' il meccanismo della compattazione, non di questo.

        E' quel che ``prepare_session`` reinietta quando una sessione riparte:
        scriverlo qui direbbe alla conversazione del progetto che e' stata
        compattata quando non lo e' stata.
        """
        _talked(autocompact, PROJECT)

        await autocompact._harvest_project_diary(PROJECT)

        assert "_last_summary" not in autocompact.sessions.get_or_create(PROJECT).metadata


class TestTheIndexDoesNotReread:
    async def test_a_second_pass_without_new_messages_does_nothing(
        self, autocompact, store
    ):
        _talked(autocompact, PROJECT)
        await autocompact._harvest_project_diary(PROJECT)

        await autocompact._harvest_project_diary(PROJECT)

        assert len(store.read_unprocessed_history(since_cursor=0)) == 1

    async def test_the_second_pass_summarizes_only_the_new(
        self, autocompact, consolidator
    ):
        _talked(autocompact, PROJECT, turns=2, tag="vecchio")
        await autocompact._harvest_project_diary(PROJECT)
        _talked(autocompact, PROJECT, turns=1, tag="nuovo")

        await autocompact._harvest_project_diary(PROJECT)

        # Il secondo giro ha visto solo lo scambio nuovo: e' la sola prova che
        # l'indice serva a qualcosa invece di essere scritto e mai letto.
        payload = consolidator.provider.chat_with_retry.call_args_list[-1].kwargs[
            "messages"
        ][-1]["content"]
        assert "messaggio vecchio0" not in payload
        assert "messaggio nuovo0" in payload

    async def test_under_the_threshold_does_not_spend_a_call(
        self, autocompact, consolidator
    ):
        """Una sessione senza niente di nuovo non deve costare un turno di LLM.

        Il giro TTL passa ogni minuto: senza questa soglia, ogni progetto fermo
        pagherebbe una chiamata a ogni finestra di inattivita'.
        """
        session = autocompact.sessions.get_or_create(PROJECT)
        session.messages.append({"role": "user", "content": "una riga sola"})
        autocompact.sessions.save(session)

        await autocompact._harvest_project_diary(PROJECT)

        consolidator.provider.chat_with_retry.assert_not_called()

    async def test_an_index_past_the_end_does_not_reread_everything(self, autocompact, store):
        """Se qualcuno compatta in mezzo, l'indice resta indietro rispetto ai
        messaggi ma **avanti** rispetto a quel che e' rimasto.

        Ripartire da zero produrrebbe un doppione di quel che e' gia' nella coda;
        il ``min`` fa ripartire dalla fine, cioe' da niente.
        """
        session = _talked(autocompact, PROJECT, turns=3)
        session.metadata[AutoCompact._DIARY_HARVEST_KEY] = 999
        autocompact.sessions.save(session)

        await autocompact._harvest_project_diary(PROJECT)

        assert store.read_unprocessed_history(since_cursor=0) == []


class TestTheRoundSchedulesTheHarvest:
    def test_an_expired_project_is_harvested(self, autocompact):
        _talked(autocompact, PROJECT)

        scheduled: list = []
        autocompact.check_expired(scheduled.append)

        assert [getattr(c, "__name__", "") for c in scheduled] == ["_harvest_project_diary"]
        for coro in scheduled:
            coro.close()

    def test_a_still_active_project_is_not_harvested(self, autocompact):
        """La sessione su cui l'utente sta scrivendo adesso resta fuori: il
        riassunto di una conversazione a meta' e' una conversazione a meta'."""
        _talked(autocompact, PROJECT, stale=False)

        scheduled: list = []
        autocompact.check_expired(scheduled.append)

        assert scheduled == []

    def test_a_session_mid_turn_stays_out(self, autocompact):
        _talked(autocompact, PROJECT)

        scheduled: list = []
        autocompact.check_expired(scheduled.append, active_session_keys={PROJECT})

        assert scheduled == []

    def test_with_the_knob_on_it_is_not_harvested_twice(self, consolidator):
        """Chi compatta riassume gia', e quel riassunto va nella stessa coda.

        Con ``compact_projects_when_idle`` acceso i due lavori si sovrapporrebbero
        sulla stessa materia: la raccolta si tira indietro e lascia fare alla
        compattazione.
        """
        compacting = AutoCompact(
            sessions=consolidator.sessions,
            consolidator=consolidator,
            session_ttl_minutes=30,
            compact_projects=True,
        )
        _talked(compacting, PROJECT)

        assert PROJECT not in compacting._diary_candidates()

    def test_with_the_knob_off_the_project_is_a_candidate(self, autocompact):
        _talked(autocompact, PROJECT)

        assert autocompact._diary_candidates() == (PROJECT,)
        # E la conversazione personale non passa di qui: ha Dream che la legge
        # dalla sua coda, non un progetto da raccogliere.
        assert PERSONAL not in autocompact._diary_candidates()


class TestTheIndexFollowsTheSession:
    """L'indice segue la sessione, e segna solo quel che e' entrato.

    Era una posizione assoluta nei messaggi: dopo ``/new`` restava al valore di
    prima, e i messaggi nuovi — meno di quelli vecchi — non entravano mai nel
    diario. La prima raccolta ripartiva da zero anche sul prefisso gia'
    consolidato per lunghezza (che nella coda c'e' gia'), e un giro oltre il
    budget di input del Consolidator segnava letti anche i messaggi che il
    troncamento aveva lasciato fuori dal riassunto.
    """

    async def test_after_new_the_new_messages_are_harvested(self, autocompact, consolidator):
        _talked(autocompact, PROJECT, turns=20, tag="vecchio")
        await autocompact._harvest_project_diary(PROJECT)
        # ``/new``, come lo fa ``cmd_new``.
        session = autocompact.sessions.get_or_create(PROJECT)
        session.clear()
        autocompact.sessions.save(session)
        autocompact.sessions.invalidate(PROJECT)
        _talked(autocompact, PROJECT, turns=5, tag="nuovo")

        await autocompact._harvest_project_diary(PROJECT)

        assert consolidator.provider.chat_with_retry.await_count == 2
        payload = consolidator.provider.chat_with_retry.await_args.kwargs["messages"][-1][
            "content"
        ]
        assert "messaggio nuovo0" in payload

    async def test_the_prefix_already_consolidated_is_not_summarized_again(
        self, autocompact, consolidator
    ):
        _talked(autocompact, PROJECT, turns=5, tag="consolidato")
        _talked(autocompact, PROJECT, turns=2, tag="fresco")
        session = autocompact.sessions.get_or_create(PROJECT)
        session.last_consolidated = 10
        autocompact.sessions.save(session)

        await autocompact._harvest_project_diary(PROJECT)

        payload = consolidator.provider.chat_with_retry.await_args.kwargs["messages"][-1][
            "content"
        ]
        assert "consolidato" not in payload
        assert "messaggio fresco0" in payload

    async def test_a_session_over_the_budget_is_read_in_chunks(self, tmp_path, store):
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(content="- fatto", finish_reason="stop")
        )
        small = Consolidator(
            store=store, sessions=SessionManager(tmp_path), provider=provider, model="m",
            context_window_tokens=8_000, build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]), max_completion_tokens=100,
        )
        ac = AutoCompact(sessions=small.sessions, consolidator=small, session_ttl_minutes=30)
        session = ac.sessions.get_or_create(PROJECT)
        for i in range(60):
            session.messages.append({"role": "user", "content": f"msg-{i:02d} " + "y" * 900})
        session.updated_at = datetime.now() - timedelta(hours=6)
        ac.sessions.save(session)

        await ac._harvest_project_diary(PROJECT)

        payloads = [
            call.kwargs["messages"][-1]["content"]
            for call in provider.chat_with_retry.await_args_list
        ]
        assert len(payloads) > 1
        assert not any("(truncated)" in text for text in payloads)
        seen = {i for i in range(60) for text in payloads if f"msg-{i:02d}" in text}
        mark = ac.sessions.get_or_create(PROJECT).metadata[AutoCompact._DIARY_HARVEST_KEY]
        # Letto vuol dire riassunto: l'indice copre esattamente quel che e' partito.
        assert seen == set(range(mark))
        assert mark == 60

    async def test_a_failed_call_leaves_the_index_where_it_was(
        self, autocompact, consolidator, store
    ):
        consolidator.provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("giu'"))
        _talked(autocompact, PROJECT, turns=3)

        await autocompact._harvest_project_diary(PROJECT)

        session = autocompact.sessions.get_or_create(PROJECT)
        assert AutoCompact._DIARY_HARVEST_KEY not in session.metadata
        assert store.read_unprocessed_history(since_cursor=0) == []
