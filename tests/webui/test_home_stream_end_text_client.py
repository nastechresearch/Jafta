"""Uno ``stream_end`` che porta il testo intero, senza delta prima.

Sotto backpressure il bus scarta dei delta; per non perdere il testo, lo
``stream_end`` di quello stream porta il testo intero dello stream (lato
server). Se un segmento ha perso **tutti** i suoi delta,
nella casa non c'era un blocco aperto, e ``_streamEnd`` quel testo lo
ignorava: dal vivo la risposta non si vedeva, e compariva solo rileggendo.
"""

from __future__ import annotations

from support.home_dom import requires_jsdom, run_home

pytestmark = requires_jsdom

_HEAD = """
import assert from 'node:assert/strict';
import { boot, tick, frame, thread } from './boot.mjs';
const app = await boot();
"""


def test_a_stream_end_with_text_and_no_delta_shows_the_answer() -> None:
    run_home(_HEAD + """
frame({ event: 'stream_end', chat_id: 'default', turn_id: 'x', text: 'The whole answer' });
await tick(10);
assert.deepEqual(thread(), ['jafta: The whole answer']);
""")


def test_a_stream_end_with_text_after_its_deltas_is_not_drawn_twice() -> None:
    run_home(_HEAD + """
frame({ event: 'delta', chat_id: 'default', turn_id: 'y', text: 'The whole' });
frame({ event: 'stream_end', chat_id: 'default', turn_id: 'y', text: 'The whole answer' });
await tick(10);
assert.deepEqual(thread(), ['jafta: The whole answer']);
""")
