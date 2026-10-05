"""Il chip degli agenti al lavoro, nella casa vera.

Un turno non aspetta piu' i subagent che lancia (02/10/2026): Jafta risponde e
il turno finisce, il lavoro no. Il 02/10 sul telefono la riga di lavoro si era
spenta col `turn_end` e il quaderno «Piante» non diceva piu' niente per i
minuti in cui un subagent scriveva sei pagine. Qui si prova che il chip dice
che lavorano, solo nella conversazione loro, e che sparisce quando finiscono.

Si gira l'``index.html`` vero con ``home-app.js`` vero (``support.home_dom``):
il chip vive fra tre fonti — l'avvio, il frame ``subagent_status``, il cambio di
conversazione — e il difetto possibile sta proprio fra loro.
"""

from __future__ import annotations

from support.home_dom import requires_jsdom, run_home

pytestmark = requires_jsdom

_HEAD = """
import assert from 'node:assert/strict';
import { boot, tick, frame, calls, hooks, ok, $ } from './boot.mjs';
/* Lo snapshot per sessione, come lo serve `/api/subagents?session_key=`. */
const byKey = {};
hooks.fetch = (u) => {
  if (u.pathname !== '/api/subagents') return undefined;
  const key = u.searchParams.get('session_key') || '';
  return ok(byKey[key] || { running: [], recent: [] });
};
const worker = (over = {}) => ({ task_id: 't1', label: 'plant cards', state: 'running', ...over });
const chip = () => $('home-subagents');
"""


def test_the_chip_says_who_is_working_in_this_notebook() -> None:
    run_home(_HEAD + """
const app = await boot();
await app.showConversation('project:orto');
await tick(20);
assert.equal(chip().hidden, true, 'senza agenti il chip non occupa spazio');

frame({ event: 'subagent_status', chat_id: 'project:orto', running: [worker()], recent: [] });
assert.equal(chip().hidden, false);
assert.match(chip().textContent, /plant cards/);

frame({ event: 'subagent_status', chat_id: 'project:orto',
        running: [worker(), worker({ task_id: 't2', label: 'other' })], recent: [] });
assert.match(chip().textContent, /2/);

frame({ event: 'subagent_status', chat_id: 'project:orto', running: [],
        recent: [worker({ state: 'done' })] });
assert.equal(chip().hidden, true, 'il lavoro e\\u2019 finito e il chip e\\u2019 ancora li\\u2019');
""")


def test_another_conversations_agents_do_not_show_here() -> None:
    run_home(_HEAD + """
const app = await boot();
await app.showConversation('project:orto');
await tick(20);
frame({ event: 'subagent_status', chat_id: 'default', running: [worker()], recent: [] });
assert.equal(chip().hidden, true, 'gli agenti della chat personale sono comparsi nel quaderno');
""")


def test_the_chip_is_read_back_when_the_conversation_opens() -> None:
    """L'attach non rimanda lo snapshot: aprendo un quaderno con un agente gia'
    al lavoro, il chip si legge dalla rotta, con la chiave di quel quaderno."""
    run_home(_HEAD + """
byKey['project:orto'] = { running: [worker()], recent: [] };
const app = await boot();
assert.equal(chip().hidden, true, 'gli agenti del quaderno sono comparsi nella chat personale');
await app.showConversation('project:orto');
await tick(20);
assert.ok(calls.includes('/api/subagents?session_key=project%3Aorto'), calls.join(' '));
assert.equal(chip().hidden, false);

await app.showConversation('websocket:default');
await tick(20);
assert.equal(chip().hidden, true, 'il chip del quaderno e\\u2019 rimasto nella chat personale');
""")


def test_a_stuck_agent_reads_as_stuck() -> None:
    run_home(_HEAD + """
const app = await boot();
frame({ event: 'subagent_status', chat_id: 'default',
        running: [worker({ state: 'stalled' })], recent: [] });
assert.equal(chip().classList.contains('is-stalled'), true);
assert.notEqual(chip().textContent, '');
""")


def test_a_late_read_does_not_undo_a_newer_frame() -> None:
    """Una lettura partita prima di un frame porta uno stato piu' vecchio."""
    run_home(_HEAD + """
let release;
const app = await boot();
hooks.fetch = (u) => {
  if (u.pathname !== '/api/subagents') return undefined;
  return new Promise((r) => { release = () => r(ok({ running: [worker()], recent: [] })); });
};
const reading = app.subagents.load();
frame({ event: 'subagent_status', chat_id: 'default', running: [], recent: [] });
release();
await reading;
assert.equal(chip().hidden, true, 'una lettura vecchia ha riacceso il chip');
""")
