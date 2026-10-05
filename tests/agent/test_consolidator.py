"""Tests for the lightweight Consolidator — append-only to HISTORY.md."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from jafta.agent.memory import (
    _ARCHIVE_SUMMARY_MAX_CHARS,
    Consolidator,
    MemoryStore,
)
from jafta.providers.base import LLMResponse
from jafta.session.manager import Session
from jafta.utils.prompt_templates import render_template


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path)


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.chat_with_retry = AsyncMock()
    return p


@pytest.fixture
def consolidator(store, mock_provider):
    sessions = MagicMock()
    sessions.save = MagicMock()
    # When maybe_consolidate_by_tokens refreshes the session reference via
    # get_or_create(session.key), it should get back the same object the test
    # passed in.  Store sessions by key so the lookup is transparent.
    _session_cache: dict[str, MagicMock] = {}
    sessions.get_or_create = MagicMock(side_effect=lambda key: _session_cache.get(key, MagicMock()))
    sessions._session_cache = _session_cache
    return Consolidator(
        store=store,
        provider=mock_provider,
        model="test-model",
        sessions=sessions,
        context_window_tokens=1000,
        build_messages=MagicMock(return_value=[]),
        get_tool_definitions=MagicMock(return_value=[]),
        max_completion_tokens=100,
    )


def _tool_round(call_id: str) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": call_id, "type": "function", "function": {"name": "x", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "name": "x", "content": "ok"},
    ]


class TestConsolidatorSummarize:
    async def test_summarize_appends_to_history(self, consolidator, mock_provider, store):
        """Consolidator should call LLM to summarize, then append to HISTORY.md."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module."
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await consolidator.archive(messages)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1

    async def test_summarize_appends_session_key_to_history(
        self,
        consolidator,
        mock_provider,
        store,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [{"role": "user", "content": "fix the auth bug"}]

        await consolidator.archive(messages, session_key="websocket:chat-1")

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "websocket:chat-1"

    async def test_summarize_raw_dumps_on_llm_failure(self, consolidator, mock_provider, store):
        """On LLM failure, raw-dump messages to HISTORY.md."""
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]
        result = await consolidator.archive(messages)
        assert result is None  # no summary on raw dump fallback
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]

    async def test_raw_dump_fallback_appends_session_key(
        self,
        consolidator,
        mock_provider,
        store,
    ):
        mock_provider.chat_with_retry.side_effect = Exception("API error")
        messages = [{"role": "user", "content": "hello"}]

        await consolidator.archive(messages, session_key="websocket:chat-2")

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "websocket:chat-2"

    async def test_summarize_skips_empty_messages(self, consolidator):
        result = await consolidator.archive([])
        assert result is None


class TestConsolidatorPromptContract:
    def test_archive_prompt_outputs_attribute_tags_without_missing_context_claims(self, tmp_path, monkeypatch):
        from jafta.utils.helpers import sync_workspace_templates
        from jafta.utils.prompt_templates import _environment

        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        sync_workspace_templates(workspace, silent=True)
        _environment.cache_clear()
        prompt = render_template("agent/consolidator_archive.md", strip=True)

        assert "SNIP" in prompt
        for mark in ("[permanent]", "[durable]", "[ephemeral]", "[correction]", "[skip]"):
            assert mark in prompt
        assert "check context below" not in prompt.lower()
        # La riga precedente diceva di non usare *mai* la memoria di lungo
        # termine come motivo per uno [skip], e aveva ragione finché il modello
        # quella memoria non la vedeva: "potrebbe già esserci" era un'ipotesi, e
        # uno [skip] su un'ipotesi perde il fatto. Con la fase 4 il prompt gliela
        # mostra quando c'è, quindi la regola non è più "non usarla" ma "non
        # tirare a indovinare" — vera in entrambi gli stati, che è ciò che un
        # template statico deve essere visto che il blocco è dinamico.
        assert "Never mark something [skip] on a guess" in prompt
        assert "let Dream deduplicate" in prompt


class TestConsolidatorArchiveErrorHandling:
    """archive() must fall back to raw_archive when the LLM returns an error
    response (finish_reason == 'error'), e.g. overloaded / quota exceeded.
    """

    async def test_archive_falls_back_on_error_finish_reason(self, consolidator, mock_provider, store):
        """LLM returning finish_reason='error' should trigger raw_archive, not write error text."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Error: {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'overloaded_error (529)'}}",
            finish_reason="error",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done, fixed the race condition."},
        ]
        result = await consolidator.archive(messages)
        assert result is None
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" in entries[0]["content"]
        assert "Error:" not in entries[0]["content"]

    async def test_archive_preserves_summary_on_success(self, consolidator, mock_provider, store):
        """Normal LLM response should still produce a proper summary entry."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="User fixed a bug in the auth module.",
            finish_reason="stop",
        )
        messages = [
            {"role": "user", "content": "fix the auth bug"},
            {"role": "assistant", "content": "Done."},
        ]
        result = await consolidator.archive(messages)
        assert result == "User fixed a bug in the auth module."
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "[RAW]" not in entries[0]["content"]


class TestConsolidatorTokenBudget:
    async def test_prompt_below_threshold_does_not_consolidate(self, consolidator):
        """No consolidation when tokens are within budget."""
        session = MagicMock()
        session.last_consolidated = 0
        session.messages = [{"role": "user", "content": "hi"}]
        session.key = "test:key"
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value=True)
        await consolidator.maybe_consolidate_by_tokens(session)
        consolidator.archive.assert_not_called()

    async def test_estimate_uses_full_unconsolidated_tail(self, consolidator):
        """Consolidation pressure must see messages hidden by the replay window."""
        session = Session(key="test:full-tail")
        for i in range(160):
            session.add_message("user", f"msg-{i}")

        captured: dict[str, list[dict]] = {}

        def build_messages(**kwargs):
            captured["history"] = kwargs["history"]
            return kwargs["history"]

        consolidator._build_messages = build_messages

        consolidator.estimate_session_prompt_tokens(session)

        assert len(captured["history"]) == 160
        assert captured["history"][0]["content"].endswith("msg-0")

    async def test_replay_window_overflow_is_archived_even_under_token_budget(
        self,
        consolidator,
    ):
        """Old messages that cannot be replayed should be materialized first."""
        consolidator._SAFETY_BUFFER = 0
        session = Session(key="test:replay-overflow")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")

        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="old conversation summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=6,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert archived_chunk[0]["content"] == "u0"
        assert archived_chunk[-1]["content"] == "a6"
        assert session.last_consolidated == 14
        assert session.metadata["_last_summary"]["text"] == "old conversation summary"
        consolidator.sessions.save.assert_called()

    async def test_replay_window_overflow_extends_to_long_recent_user_turn(
        self,
        consolidator,
    ):
        """Replay-window consolidation must not cut into the latest user turn."""
        session = Session(key="test:replay-tool-boundary")
        session.add_message("user", "old")
        session.add_message("assistant", "old answer")
        session.add_message("user", "record this")
        for i in range(4):
            session.messages.extend(_tool_round(f"call-{i}"))
        session.add_message("assistant", "final answer")

        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="tool turn summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=4,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert [m["content"] for m in archived_chunk] == ["old", "old answer"]
        assert session.last_consolidated == 2

        history = session.get_history(max_messages=4, extend_to_user=True)
        assert len(history) > 4
        assert history[0]["content"] == "record this"
        assert history[-1]["content"] == "final answer"

    async def test_replay_window_overflow_uses_newer_user_inside_window(
        self,
        consolidator,
    ):
        """Do not extend to an older long turn when the hard window has a newer user."""
        session = Session(key="test:replay-newer-user")
        session.add_message("user", "old")
        session.add_message("assistant", "old answer")
        session.add_message("user", "long older turn")
        for i in range(8):
            session.messages.extend(_tool_round(f"older-{i}"))
        session.add_message("assistant", "older final")
        session.add_message("user", "new question")
        session.add_message("assistant", "new answer")

        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(100, "tiktoken"))
        consolidator.archive = AsyncMock(return_value="older turn summary")

        await consolidator.maybe_consolidate_by_tokens(
            session,
            replay_max_messages=6,
        )

        archived_chunk = consolidator.archive.await_args.args[0]
        assert archived_chunk[2]["content"] == "long older turn"
        assert archived_chunk[-1]["content"] == "older final"
        assert session.last_consolidated == len(session.messages) - 2

        history = session.get_history(max_messages=6, extend_to_user=True)
        assert [m["content"] for m in history] == ["new question", "new answer"]

    async def test_large_chunk_archived_without_cap(self, consolidator):
        """Without chunk cap, the full range from pick_consolidation_boundary is archived."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {
                "role": "user" if i in {0, 50, 61} else "assistant",
                "content": f"m{i}",
            }
            for i in range(70)
        ]
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        # Use real pick_consolidation_boundary — it will find boundary at idx=50
        # (user message at 50, token budget met)
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        archived_chunk = consolidator.archive.await_args.args[0]
        # pick_consolidation_boundary returns (50, tokens) — user turn at idx 50
        assert archived_chunk[0]["content"] == "m0"
        assert session.last_consolidated > 0

    async def test_a_failed_summary_does_not_advance_last_consolidated(self, consolidator):
        """Un riassunto fallito non conta come consolidato.

        Il cursore avanzava comunque, con un dump grezzo tagliato a 16.000
        caratteri per «briciola»: i messaggi dopo il taglio restavano nella
        sessione, ma oltre ``last_consolidated``, e la compattazione per
        inattività successiva li buttava senza che fossero mai entrati nel diario.
        Ora il chunk resta da consolidare e il turno dopo riprova; niente dump,
        quindi niente doppioni.
        """
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 50} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1200, "tiktoken"))
        consolidator.archive = AsyncMock(return_value=None)

        await consolidator.maybe_consolidate_by_tokens(session)

        consolidator.archive.assert_awaited_once()
        assert consolidator.archive.await_args.kwargs["raw_dump_on_failure"] is False
        assert session.last_consolidated == 0

    async def test_repeated_failures_fall_back_to_the_raw_dump(self, consolidator):
        """Il freno: un chunk che fallisce sempre non blocca la sessione per sempre.

        Al terzo fallimento di fila si torna al comportamento di prima — dump
        grezzo e cursore avanti — perche' un chunk che il modello rifiuta per la
        sua forma farebbe altrimenti una chiamata sprecata a ogni turno, e la
        sessione crescerebbe senza fine.
        """
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 50} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1200, "tiktoken"))
        consolidator.archive = AsyncMock(return_value=None)

        for _ in range(2):
            await consolidator.maybe_consolidate_by_tokens(session)
        assert session.last_consolidated == 0
        await consolidator.maybe_consolidate_by_tokens(session)

        assert consolidator.archive.await_args.kwargs["raw_dump_on_failure"] is True
        assert session.last_consolidated == 50

    async def test_failures_are_counted_per_turn_not_per_call(self, tmp_path):
        """«Tre fallimenti di fila» vuol dire tre turni, non tre chiamate.

        Un turno chiama la consolidazione due volte (prima di costruire il
        prompt e dopo il salvataggio): contando le chiamate, la resa al dump
        grezzo arrivava a metà del secondo turno con il modello giù, e il dump è
        tagliato — i fatti oltre il taglio uscivano dal diario. Qui con un
        ``SessionManager`` vero e il turno legato come lo lega il loop.
        """
        import re

        from jafta.agent.tools.context import bind_turn_id, reset_turn_id
        from jafta.session.manager import SessionManager

        store = MemoryStore(tmp_path)
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(side_effect=RuntimeError("down"))
        sessions = SessionManager(tmp_path)
        c = Consolidator(
            store=store, provider=provider, model="m", sessions=sessions,
            context_window_tokens=12000, build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]), max_completion_tokens=100,
        )
        s = sessions.get_or_create("unified:default")
        for i in range(60):
            s.add_message("user", f"FACT-{i:02d} " + "z" * 1000)
            s.add_message("assistant", f"ok {i}")
        sessions.save(s)

        def est(session):
            tail = session.messages[session.last_consolidated:]
            return sum(len(str(m.get("content"))) for m in tail) // 4, "est"

        c.estimate_session_prompt_tokens = est

        async def turn(turn_id: str, calls: int) -> None:
            token = bind_turn_id(turn_id)
            try:
                for _ in range(calls):
                    await c.maybe_consolidate_by_tokens(s)
            finally:
                reset_turn_id(token)

        # Turno 1 intero (prima e dopo), turno 2 intero: due turni, niente resa.
        await turn("t1", 2)
        await turn("t2", 2)
        assert s.last_consolidated == 0
        assert store.read_unprocessed_history(since_cursor=0) == []
        assert c._token_failures == {"unified:default": 2}

        # Il terzo turno giù è la soglia: dump grezzo e cursore avanti.
        await turn("t3", 1)
        assert s.last_consolidated > 0
        diary = "\n".join(e["content"] for e in store.read_unprocessed_history(since_cursor=0))
        assert re.search(r"FACT-00", diary)

    async def test_failures_outside_a_turn_count_one_per_call(self, consolidator):
        """Senza un turno legato ogni chiamata è un tentativo a sé."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 50} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1200, "tiktoken"))
        consolidator.archive = AsyncMock(return_value=None)
        for _ in range(2):
            await consolidator.maybe_consolidate_by_tokens(session)
        assert consolidator._token_failures == {"test:key": 2}

    async def test_a_success_resets_the_failure_count(self, consolidator):
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 50} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(return_value=(1200, "tiktoken"))
        consolidator.archive = AsyncMock(side_effect=[None, None, "- [durable] ok"])
        for _ in range(3):
            await consolidator.maybe_consolidate_by_tokens(session)
        assert session.last_consolidated == 50
        assert consolidator._token_failures == {}

    async def test_raw_archive_fallback_breaks_round_loop(self, consolidator):
        """A degraded LLM should not trigger more archive() calls within the
        same maybe_consolidate_by_tokens invocation — bail after one fallback."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {"role": "user" if i in {0, 20, 40, 60} else "assistant", "content": f"m{i}"}
            for i in range(70)
        ]
        session.metadata = {}
        consolidator.sessions._session_cache[session.key] = session
        # Keep estimates high so the loop would otherwise run multiple rounds.
        consolidator.estimate_session_prompt_tokens = MagicMock(
            return_value=(1200, "tiktoken")
        )
        consolidator.archive = AsyncMock(return_value=None)

        await consolidator.maybe_consolidate_by_tokens(session)

        # Exactly one fallback per call — not _MAX_CONSOLIDATION_ROUNDS.
        assert consolidator.archive.await_count == 1

    async def test_boundary_respected_when_no_intermediate_user_turn(self, consolidator):
        """When boundary points past a long tool chain, the full chunk is archived."""
        consolidator._SAFETY_BUFFER = 0
        session = MagicMock()
        session.last_consolidated = 0
        session.key = "test:key"
        session.messages = [
            {
                "role": "user" if i in {0, 61} else "assistant",
                "content": f"m{i}",
            }
            for i in range(70)
        ]
        consolidator.sessions._session_cache[session.key] = session
        consolidator.estimate_session_prompt_tokens = MagicMock(
            side_effect=[(1200, "tiktoken"), (400, "tiktoken")]
        )
        consolidator.archive = AsyncMock(return_value=True)

        await consolidator.maybe_consolidate_by_tokens(session)

        consolidator.archive.assert_awaited_once()
        # pick_consolidation_boundary finds the only boundary at idx=61
        assert session.last_consolidated == 61


class TestCompactIdleSession:
    """Tests for Consolidator.compact_idle_session — lock-protected idle truncation."""

    @pytest.fixture
    def real_consolidator(self, store, mock_provider):
        """Create a Consolidator with a real SessionManager (not a mock)."""
        from jafta.session.manager import SessionManager

        sessions = SessionManager(store.workspace)
        return Consolidator(
            store=store,
            provider=mock_provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=1000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
            max_completion_tokens=100,
        )

    @pytest.mark.asyncio
    async def test_archives_prefix_keeps_suffix(self, real_consolidator, mock_provider):
        """20 user/assistant turns → compact with max_suffix=8 → messages ≤ 8,
        last_consolidated=0, _last_summary stored."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of old conversation.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:test")
        for i in range(20):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("internal:test", max_suffix=8)
        assert result == "Summary of old conversation."

        reloaded = sessions.get_or_create("internal:test")
        assert len(reloaded.messages) <= 8
        assert reloaded.last_consolidated == 0
        meta = reloaded.metadata.get("_last_summary")
        assert meta is not None
        assert meta["text"] == "Summary of old conversation."
        assert "last_active" in meta

    @pytest.mark.asyncio
    async def test_summarizes_retained_suffix_not_just_dropped_prefix(
        self, real_consolidator, mock_provider
    ):
        """idleCompact must summarize over the full unconsolidated tail, including
        the recent suffix it retains. Otherwise a late user correction / final
        result that lands in the kept suffix is excluded from the persisted
        summary, leaving a stale wrong conclusion in history. Regression for #4264."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:correction")
        for i in range(18):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        # Final correction exchange lands inside the retained max_suffix window.
        session.add_message("user", "no, that's wrong, use approach B")
        session.add_message("assistant", "CORRECTED_FINAL_RESULT_alpha")
        sessions.save(session)

        await real_consolidator.compact_idle_session("internal:correction", max_suffix=8)

        summarized = mock_provider.chat_with_retry.call_args.kwargs["messages"][1]["content"]
        assert "CORRECTED_FINAL_RESULT_alpha" in summarized

    @pytest.mark.asyncio
    async def test_llm_failure_dumps_nothing_and_keeps_the_session(
        self, real_consolidator, mock_provider, store
    ):
        """A LLM giu' la compattazione per inattivita' non tronca.

        Prima tagliava comunque, e il dump grezzo che doveva fare da copia era
        troncato a 16.000 caratteri: in una conversazione lunga la maggior parte
        dei messaggi spariva da sessione **e** diario. Ora la sessione resta
        intera e scaduta, e la finestra dopo riprova; niente dump, perche' ogni
        riprova ne scriverebbe un altro.
        """
        mock_provider.chat_with_retry.side_effect = RuntimeError("LLM unavailable")
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("unified:default")
        for i in range(30):
            session.add_message("user", f"FACT-{i:02d} " + "z" * 1000)
            session.add_message("assistant", f"reply {i}")
        sessions.save(session)
        before = sessions.get_or_create("unified:default").updated_at

        result = await real_consolidator.compact_idle_session("unified:default", max_suffix=8)

        assert result is None
        assert store.read_unprocessed_history(since_cursor=0) == []
        sessions.invalidate("unified:default")
        reloaded = sessions.get_or_create("unified:default")
        assert len(reloaded.messages) == 60
        assert reloaded.last_consolidated == 0
        assert reloaded.updated_at == before

        # Il provider torna: la finestra dopo compatta, e il riassunto vede tutto.
        mock_provider.chat_with_retry.side_effect = None
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="- [durable] riassunto", finish_reason="stop",
        )
        result = await real_consolidator.compact_idle_session("unified:default", max_suffix=8)
        assert result == "- [durable] riassunto"
        sent = mock_provider.chat_with_retry.await_args.kwargs["messages"][1]["content"]
        assert "FACT-00" in sent

    @pytest.mark.asyncio
    async def test_idle_compact_writes_session_key_to_history(
        self,
        real_consolidator,
        mock_provider,
        store,
    ):
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of old conversation.", finish_reason="stop"
        )
        session = real_consolidator.sessions.get_or_create("internal:test")
        for i in range(10):
            session.add_message("user", f"user msg {i}")
            session.add_message("assistant", f"assistant msg {i}")
        real_consolidator.sessions.save(session)

        await real_consolidator.compact_idle_session("internal:test", max_suffix=4)

        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "internal:test"

    async def test_a_summarized_compaction_marks_the_kept_suffix_harvested(
        self, real_consolidator, mock_provider,
    ):
        """L'indice della raccolta del diario non resta sui messaggi di prima.

        Rimasto al valore vecchio dopo la troncatura, puntava oltre la fine della
        sessione accorciata: la raccolta ripartiva da ``min(indice, len)`` e
        saltava i messaggi nuovi finché la sessione non tornava lunga come prima.
        Il riassunto della compattazione copre anche la coda tenuta, quindi
        quella coda è già nella coda del diario.
        """
        from jafta.session.manager import DIARY_HARVEST_METADATA_KEY

        mock_provider.chat_with_retry.return_value = MagicMock(
            content="- [durable] riassunto", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("project:esempio")
        for i in range(20):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        session.metadata[DIARY_HARVEST_METADATA_KEY] = 30
        sessions.save(session)

        await real_consolidator.compact_idle_session("project:esempio", max_suffix=8)

        sessions.invalidate("project:esempio")
        after = sessions.get_or_create("project:esempio")
        assert len(after.messages) == 8
        assert after.metadata[DIARY_HARVEST_METADATA_KEY] == 8

    async def test_a_compaction_without_summary_slides_the_harvest_mark(
        self, real_consolidator, mock_provider,
    ):
        """Niente da riassumere, ma il prefisso consolidato esce: l'indice scorre."""
        from jafta.session.manager import DIARY_HARVEST_METADATA_KEY

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("project:esempio")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        session.last_consolidated = 16
        session.metadata[DIARY_HARVEST_METADATA_KEY] = 18
        sessions.save(session)

        await real_consolidator.compact_idle_session("project:esempio", max_suffix=8)

        mock_provider.chat_with_retry.assert_not_awaited()
        sessions.invalidate("project:esempio")
        after = sessions.get_or_create("project:esempio")
        assert [m["content"] for m in after.messages] == ["u8", "a8", "u9", "a9"]
        # u8 e a8 erano gia' raccolti (indici 16 e 17), u9 e a9 no.
        assert after.metadata[DIARY_HARVEST_METADATA_KEY] == 2

    @pytest.mark.asyncio
    async def test_empty_session_refreshes_timestamp(self, real_consolidator):
        """Empty session with old updated_at → refreshed after call, returns ''."""
        from datetime import datetime, timedelta

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:empty")
        old_ts = datetime.now() - timedelta(hours=2)
        session.updated_at = old_ts
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("internal:empty")
        assert result == ""

        reloaded = sessions.get_or_create("internal:empty")
        assert reloaded.updated_at > old_ts

    @pytest.mark.asyncio
    async def test_nothing_summary_not_stored(self, real_consolidator, mock_provider):
        """LLM returns '(nothing)' → _last_summary NOT in metadata."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="(nothing)", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:nothing")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("internal:nothing", max_suffix=4)
        assert result == "(nothing)"

        reloaded = sessions.get_or_create("internal:nothing")
        assert "_last_summary" not in reloaded.metadata

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_truncate(self, real_consolidator, mock_provider, store):
        """LLM raises RuntimeError → nothing dumped, session left whole, returns None."""
        mock_provider.chat_with_retry.side_effect = RuntimeError("LLM unavailable")
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:fail")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("internal:fail", max_suffix=4)
        assert result is None

        assert store.read_unprocessed_history(since_cursor=0) == []
        sessions.invalidate("internal:fail")
        reloaded = sessions.get_or_create("internal:fail")
        assert len(reloaded.messages) == 20

    @pytest.mark.asyncio
    async def test_respects_last_consolidated(self, real_consolidator, mock_provider):
        """30 turns with last_consolidated=50 → only unconsolidated tail considered."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Tail summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:offset")
        for i in range(30):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        session.last_consolidated = 50  # Only 10 messages unconsolidated
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("internal:offset", max_suffix=4)
        assert result == "Tail summary."

        # Verify only the unconsolidated tail was processed:
        # 10 unconsolidated messages (50-59), keep suffix of 4 → archive 6
        archived_call = mock_provider.chat_with_retry.call_args
        user_content = archived_call.kwargs["messages"][1]["content"]
        # Should contain only tail messages, not early ones
        assert "u0" not in user_content
        assert "u25" in user_content or "a25" in user_content

    @pytest.mark.asyncio
    async def test_non_contiguous_suffix_archives_actual_dropped_messages(
        self,
        real_consolidator,
        mock_provider,
    ):
        """Assistant-only tails extend back to the latest user turn, so archive
        the actual dropped messages rather than a computed prefix."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Tail summary.", finish_reason="stop"
        )
        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:noncontiguous")
        for i in range(15):
            session.add_message("user", f"user-{i:02d}")
        for i in range(10):
            session.add_message("assistant", f"assistant-{i:02d}")
        sessions.save(session)

        result = await real_consolidator.compact_idle_session("internal:noncontiguous", max_suffix=6)
        assert result == "Tail summary."

        reloaded = sessions.get_or_create("internal:noncontiguous")
        assert [m["content"] for m in reloaded.messages] == [
            "user-14",
            "assistant-00",
            "assistant-01",
            "assistant-02",
            "assistant-03",
            "assistant-04",
            "assistant-05",
            "assistant-06",
            "assistant-07",
            "assistant-08",
            "assistant-09",
        ]

        # #4264: idle compaction now summarizes the full unconsolidated tail, so
        # the dropped head (user-00) and retained suffix (user-14 through
        # assistant-09) are all summarized.
        archived_call = mock_provider.chat_with_retry.call_args
        user_content = archived_call.kwargs["messages"][1]["content"]
        assert "user-00" in user_content
        assert "assistant-09" in user_content
        assert "user-14" in user_content

    @pytest.mark.asyncio
    async def test_acquires_consolidation_lock(self, real_consolidator, mock_provider):
        """Verify lock is held during execution."""
        import asyncio

        # Use a slow LLM response to ensure the lock is held while we check
        started = asyncio.Event()
        release_chat = asyncio.Event()

        async def slow_chat(**kwargs):
            started.set()
            await release_chat.wait()
            return LLMResponse(content="Summary.", finish_reason="stop")

        mock_provider.chat_with_retry = slow_chat

        sessions = real_consolidator.sessions
        session = sessions.get_or_create("internal:lock")
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        lock = real_consolidator.get_lock("internal:lock")
        assert not lock.locked()

        task = asyncio.ensure_future(
            real_consolidator.compact_idle_session("internal:lock", max_suffix=4)
        )
        await started.wait()
        assert lock.locked()
        release_chat.set()
        await task
        assert not lock.locked()


class TestConsolidatorSessionRefresh:
    """Background consolidation must detect stale session references."""

    @pytest.mark.asyncio
    async def test_reloads_before_empty_session_guard(self, tmp_path):
        """A stale empty reference must not skip a non-empty cached session."""
        from jafta.agent.memory import Consolidator, MemoryStore
        from jafta.session.manager import Session, SessionManager

        store = MemoryStore(tmp_path)
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(content="summary", finish_reason="stop")
        )
        provider.generation.max_tokens = 4096
        provider.estimate_prompt_tokens = MagicMock(return_value=(10, "test"))
        sessions = SessionManager(tmp_path)
        consolidator = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
        )

        fresh = sessions.get_or_create("internal:test")
        fresh.add_message("user", "fresh message")
        sessions.save(fresh)
        stale_empty = Session(key="internal:test")

        seen: dict[str, Session] = {}

        def estimate(session: Session):
            seen["session"] = session
            return 10, "test"

        consolidator.estimate_session_prompt_tokens = MagicMock(side_effect=estimate)

        await consolidator.maybe_consolidate_by_tokens(stale_empty)

        assert seen["session"] is fresh

    @pytest.mark.asyncio
    async def test_reloads_stale_session_after_compact(self, tmp_path):
        """After compact_idle_session replaces the session, a concurrent
        maybe_consolidate_by_tokens with the old reference should use the
        fresh session from cache instead of overwriting."""
        from jafta.agent.memory import Consolidator, MemoryStore
        from jafta.session.manager import SessionManager

        store = MemoryStore(tmp_path)
        provider = MagicMock()
        provider.chat_with_retry = AsyncMock(
            return_value=MagicMock(content="summary", finish_reason="stop")
        )
        provider.generation.max_tokens = 4096
        provider.estimate_prompt_tokens = MagicMock(return_value=(10, "test"))
        sessions = SessionManager(tmp_path)
        consolidator = Consolidator(
            store=store,
            provider=provider,
            model="test-model",
            sessions=sessions,
            context_window_tokens=128_000,
            build_messages=MagicMock(return_value=[]),
            get_tool_definitions=MagicMock(return_value=[]),
        )

        # Populate session with many messages
        session = sessions.get_or_create("internal:test")
        for i in range(20):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}")
        sessions.save(session)

        # Simulate: background consolidation captures old reference
        old_ref = session

        # AutoCompact runs first and truncates to 8
        await consolidator.compact_idle_session("internal:test", max_suffix=8)

        # Background consolidation runs with stale reference —
        # should detect the session was replaced and not undo the compact.
        await consolidator.maybe_consolidate_by_tokens(old_ref)

        session_after = sessions.get_or_create("internal:test")
        # Messages should still be truncated (not restored to 40)
        assert len(session_after.messages) <= 8


class TestRawArchiveTruncation:
    """raw_archive() must cap entry size to avoid bloating history.jsonl."""

    def test_raw_archive_truncates_large_content(self, store):
        """Large messages should be truncated to _RAW_ARCHIVE_MAX_CHARS."""
        big = "x" * 50_000
        messages = [{"role": "user", "content": big}]
        store.raw_archive(messages)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert len(entries[0]["content"]) < 50_000
        assert "[RAW]" in entries[0]["content"]

    def test_raw_archive_preserves_small_content(self, store):
        """Small messages should not be truncated."""
        messages = [{"role": "user", "content": "hello"}]
        store.raw_archive(messages)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries) == 1
        assert "hello" in entries[0]["content"]

    def test_raw_archive_preserves_session_key(self, store):
        messages = [{"role": "user", "content": "hello"}]
        store.raw_archive(messages, session_key="websocket:chat-1")
        entries = store.read_unprocessed_history(since_cursor=0)
        assert entries[0]["session_key"] == "websocket:chat-1"

    def test_raw_archive_custom_max_chars(self, store):
        """max_chars parameter should override default limit."""
        messages = [{"role": "user", "content": "a" * 200}]
        store.raw_archive(messages, max_chars=100)
        entries = store.read_unprocessed_history(since_cursor=0)
        assert len(entries[0]["content"]) < 200


class TestArchiveTruncation:
    """archive() must truncate formatted text before sending to consolidation LLM."""

    async def test_archive_truncates_large_formatted_text(self, consolidator, mock_provider, store):
        """Large formatted text should be truncated to token budget before LLM call."""
        # context_window_tokens=1000, max_completion_tokens=100, _SAFETY_BUFFER=1024
        # budget = 1000 - 100 - 1024 = -124 → fallback via truncate_text(budget*4)
        big_messages = [{"role": "user", "content": "x" * 100_000}]
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary of large input.", finish_reason="stop"
        )
        await consolidator.archive(big_messages)

        call_args = mock_provider.chat_with_retry.call_args
        user_content = call_args.kwargs["messages"][1]["content"]
        # Should be significantly shorter than 100K
        assert len(user_content) < 50_000

    async def test_archive_truncates_with_small_token_budget(self, consolidator, mock_provider, store):
        """Small context window: truncation uses actual tokenizer count."""
        consolidator.context_window_tokens = 500
        big_messages = [{"role": "user", "content": "word " * 50_000}]
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        await consolidator.archive(big_messages)

        sent_messages = mock_provider.chat_with_retry.call_args.kwargs["messages"]
        user_content = sent_messages[1]["content"]
        # budget = 500 - 100 - 1024 = negative, fallback char-based
        # Should be truncated
        assert len(user_content) < 250_000

    async def test_oversized_summary_is_capped_before_append(self, consolidator, mock_provider, store):
        """A pathologically large LLM summary must not land full-length in
        history.jsonl — that would re-open the #3412 bloat vector from the
        *success* path instead of the fallback path."""
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="S" * (_ARCHIVE_SUMMARY_MAX_CHARS * 10),
            finish_reason="stop",
        )
        await consolidator.archive([{"role": "user", "content": "hi"}])

        entry = store.read_unprocessed_history(since_cursor=0)[0]
        assert len(entry["content"]) <= _ARCHIVE_SUMMARY_MAX_CHARS + 50

    async def test_archive_truncates_via_char_heuristic_with_positive_budget(self, consolidator, mock_provider, store):
        """Positive token budget should use the char heuristic for truncation."""
        consolidator.context_window_tokens = 10_000
        consolidator._SAFETY_BUFFER = 0
        # budget = 10000 - 100 - 0 = 9900 tokens -> ~39600 chars
        big_messages = [{"role": "user", "content": "word " * 50_000}]
        mock_provider.chat_with_retry.return_value = MagicMock(
            content="Summary.", finish_reason="stop"
        )
        await consolidator.archive(big_messages)

        sent_content = mock_provider.chat_with_retry.call_args.kwargs["messages"][1]["content"]
        assert len(sent_content) <= 9_900 * 4 + 100
