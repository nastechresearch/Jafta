"""Tests for OpenAICompatProvider handling custom/direct endpoints."""

from jafta.providers.openai_compat_provider import OpenAICompatProvider


def test_custom_provider_parse_handles_empty_choices() -> None:
    provider = OpenAICompatProvider(api_key="", api_base="", default_model="")

    result = provider._parse({"choices": []})

    assert result.finish_reason == "error"
    assert "empty choices" in result.content


def test_custom_provider_parse_accepts_dict_response() -> None:
    provider = OpenAICompatProvider(api_key="", api_base="", default_model="")

    result = provider._parse({
        "choices": [{
            "message": {"content": "hello from dict"},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
    })

    assert result.finish_reason == "stop"
    assert result.content == "hello from dict"
    assert result.usage["total_tokens"] == 3


def test_custom_provider_parse_chunks_deduplicates_parallel_tool_call_ids() -> None:
    chunks = [{
        "choices": [{
            "finish_reason": "tool_calls",
            "delta": {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_dup",
                        "function": {"name": "read_file", "arguments": '{"path":"a.txt"}'},
                    },
                    {
                        "index": 1,
                        "id": "call_dup",
                        "function": {"name": "read_file", "arguments": '{"path":"b.txt"}'},
                    },
                ],
            },
        }],
    }]

    result = OpenAICompatProvider._parse_chunks(chunks)
    ids = [tool_call.id for tool_call in result.tool_calls or []]

    assert ids[0] == "call_dup"
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_parallel_tool_calls_without_index_are_not_merged() -> None:
    """Chiamate parallele senza ``index``, una per chunk, con id distinti.

    Senza ``index`` il ripiego era la posizione nel chunk, cioè 0 per tutte: gli
    argomenti delle due chiamate finivano concatenati in una sola, con il nome
    dell'ultima. Un id nuovo apre una chiamata nuova; un frammento senza id né
    index continua l'ultima aperta.
    """
    def _chunk(tool_call: dict) -> dict:
        return {"choices": [{"delta": {"tool_calls": [tool_call]}}]}

    chunks = [
        _chunk({"id": "call_a", "function": {"name": "read_file", "arguments": '{"path":'}}),
        _chunk({"function": {"arguments": '"a.txt"}'}}),
        _chunk({"id": "call_b", "function": {"name": "list_dir", "arguments": '{"path":"."}'}}),
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert [(tc.id, tc.name, tc.arguments) for tc in result.tool_calls] == [
        ("call_a", "read_file", {"path": "a.txt"}),
        ("call_b", "list_dir", {"path": "."}),
    ]

    # Due chiamate senza id né index nello stesso chunk: distinte per posizione.
    same_chunk = [{"choices": [{"delta": {"tool_calls": [
        {"function": {"name": "a", "arguments": "{}"}},
        {"function": {"name": "b", "arguments": "{}"}},
    ]}}]}]
    names = [tc.name for tc in OpenAICompatProvider._parse_chunks(same_chunk).tool_calls]
    assert names == ["a", "b"]


def test_a_call_opened_with_an_index_continues_by_its_id_alone() -> None:
    """Il primo chunk ha ``index`` e id, i successivi solo l'id.

    L'id visto col suo ``index`` non era registrato: il chunk dopo, senza
    index, lo trovava nuovo e apriva una seconda chiamata, spezzando gli
    argomenti in due metà che nessuna delle due sapeva leggere.
    """
    def _chunk(tool_call: dict) -> dict:
        return {"choices": [{"delta": {"tool_calls": [tool_call]}}]}

    chunks = [
        _chunk({"index": 0, "id": "c1",
                "function": {"name": "read_file", "arguments": '{"path":'}}),
        _chunk({"id": "c1", "function": {"arguments": '"a.txt"}'}}),
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]

    result = OpenAICompatProvider._parse_chunks(chunks)

    assert [(tc.id, tc.name, tc.arguments) for tc in result.tool_calls] == [
        ("c1", "read_file", {"path": "a.txt"}),
    ]


def test_custom_provider_parse_deduplicates_parallel_tool_call_ids() -> None:
    """Un provider che riusa un id lo fa anche fuori dallo streaming.

    Il path a chunk deduplicava già; questo no, e a valle l'id è una chiave —
    il transcript scarta l'evento duplicato e i risultati grossi collidono sullo
    stesso file. Stessa semantica del gemello sopra: la prima chiamata tiene
    l'id del wire.
    """
    provider = OpenAICompatProvider(api_key="", api_base="", default_model="")

    result = provider._parse({
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {
                "content": None,
                "tool_calls": [
                    {"id": "call_dup", "function": {"name": "read_file", "arguments": '{"path":"a"}'}},
                    {"id": "call_dup", "function": {"name": "read_file", "arguments": '{"path":"b"}'}},
                ],
            },
        }],
    })
    ids = [tool_call.id for tool_call in result.tool_calls]

    assert ids[0] == "call_dup"
    assert len(set(ids)) == 2
    assert [tc.arguments["path"] for tc in result.tool_calls] == ["a", "b"]


def test_custom_provider_parse_keeps_a_non_string_id_as_text() -> None:
    """Un id intero va reso stringa, non scartato: il path a chunk fa così."""
    provider = OpenAICompatProvider(api_key="", api_base="", default_model="")

    result = provider._parse({
        "choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": None, "tool_calls": [
                {"id": 5, "function": {"name": "x", "arguments": "{}"}},
            ]},
        }],
    })

    assert [tool_call.id for tool_call in result.tool_calls] == ["5"]
