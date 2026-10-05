"""La minichat legge i frame del turno come la mascotte madre, e ci mette sopra il fumetto.

Dal 28/09/2026 la minichat e' dei due gusci (``shared/jafta-minichat.js``), e
cambia in tre punti misurati nel codice prima di toccarlo:

* il fumetto contiene **tutta** la risposta, formattata, un blocco per segmento
  (prima: testo piano tagliato a 280 caratteri, segmenti incollati a meta' frase,
  e dopo un giro di strumenti si leggeva il preambolo);
* chiudere la minichat, o cambiare vista, **non smette di seguire** la domanda:
  la risposta la trovi riaprendola (prima si perdeva), e il turno lento non si
  chiude allo scadere dei 90 secondi (prima il fumetto restava sulla nota);
* mentre Jafta risponde il tasto e' spento, anche se la risposta e' partita
  dalla chat (decisione dell'utente), e un filo caduto lo riaccende.

In node, coi moduli veri (``shared/jafta-minichat.js`` e ``shared/jafta-mascot.js``)
e i vicini finti. L'istanza nasce da ``Object.create`` senza costruttore: il
costruttore disegna il DOM, e qui interessa la lettura dei frame. Lo stato di
Jafta e l'umore si registrano invece di disegnarli; il markdown si riconosce dal
prefisso ``md:`` del finto ``renderMarkdown``.
"""

from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path

from support.js_harness import requires_node, run_module

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "jafta" / "templates" / "ui" / "assets"

pytestmark = requires_node

_NEIGHBORS = {
    "ws-manager.js": """
export const wsManager = Object.assign(new EventTarget(), {
  connectChat() {}, chatConnected: true,
});
""",
    "session-manager.js": "export const sessionManager = new EventTarget();\n",
    "i18n.js": "export const i18n = { t: (k) => k, locale: 'it', load: async () => {} };\n",
    "mascot.js": """
export const OUT_SHIFT_RATIO = 0.5;
export function mascotVisible() { return true; }
export function applyMascotSize() {}
""",
    "mascot-drag.js": """
export function bindMascotDrag() {}
export function buildFlyLayer() {}
""",
    "markdown.js": "export function renderMarkdown(t) { return 'md:' + t; }\n",
    "rich-content.js": """
export const richened = [];
export async function renderRich(node) { richened.push(node.innerHTML); }
""",
    "content-link.js": "export function contentLinkOf() { return null; }\n"
    "export function openContentLink() {}\n",
    "utils.js": "export function showToast() {}\n",
}

_PRELUDE = """
import assert from 'node:assert/strict';
globalThis.window = { matchMedia: () => ({ matches: false }) };

/* Un elemento finto, quanto basta al fumetto: figli, testo, markdown, scroll. */
class El {
  constructor() {
    this.children = []; this.dataset = {}; this._html = ''; this.textContent = '';
    this.scrollTop = 0; this.scrollHeight = 500; this.clientHeight = 100; this.className = '';
  }
  get firstElementChild() { return this.children[0] || null; }
  appendChild(c) { this.children.push(c); return c; }
  replaceChildren(...cs) { this.children = cs; }
  set innerHTML(v) { this._html = v; this.textContent = v; }
  get innerHTML() { return this._html; }
}
globalThis.document = { createElement: () => new El(), getElementById: () => null };

/* Il timer della risposta lenta si tiene in mano: lo fa scattare il banco. */
const timers = [];
globalThis.setTimeout = (fn) => { timers.push(fn); return timers.length; };
globalThis.clearTimeout = () => {};

const { JennyWithMinichat } = await import('./shared/jafta-minichat.js');
const { richened } = await import('./shared/rich-content.js');
const { wsManager } = await import('./shared/ws-manager.js');

function classes(...initial) {
  const s = new Set(initial);
  return {
    add: (c) => s.add(c), remove: (...cs) => cs.forEach((c) => s.delete(c)),
    contains: (c) => s.has(c), toggle: (c, on) => (on ? s.add(c) : s.delete(c)),
  };
}

/* Una minichat fuori dalla chat; `asked` = una domanda sua in volo, alzata come
   la alza `_send`, e col suo turno gia' partito (`goal_status: running` visto):
   la risposta di un comando, che quel `running` non lo manda, ha i suoi test. */
function minichat({ open = true, asked = true, sends = true } = {}) {
  const j = Object.create(JennyWithMinichat.prototype);
  Object.assign(j, {
    mode: 'away', _turnActive: asked, _pendingTurn: asked,
    _streamTurnId: null, _lastClosedTurnId: null, _chatRunning: false, _replyTimer: null,
    _runSeen: asked,
    _talk: { timer: null },
    el: { classList: classes() },
    mc: { classList: open ? classes('open') : classes(), dataset: {} },
    scrim: { classList: classes() },
    bubble: new El(),
    input: { value: '', placeholder: '', focus() {}, blur() {} },
    sendBtn: { disabled: true },
  });
  j.sent = [];
  j.closed = 0;
  j._adapter = {
    send: (text) => { j.sent.push(text); return sends; },
    placeholder: () => 'Scrivi a Jafta',
    onTurnClosed: () => { j.closed += 1; },
  };
  j.states = [];
  j.moods = [];
  j.outs = [];
  j._setAgentState = (s) => { j.states.push(s); j._agentState = s; };
  j._applyMood = (m) => j.moods.push(m);
  j._clearMood = () => {};
  j._syncArt = () => {};
  j._setOut = (out) => { j.outs.push(out); j._onOutChange(out); };
  j._resetReply();
  return j;
}
const last = (j) => j.states[j.states.length - 1];
const blocks = (j) => j.bubble.children.map((c) => c.textContent);
"""


def _run(body: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "shared").mkdir()
        for name in ("jafta-minichat.js", "jafta-mascot.js", "wire-error.js", "bot-name.js"):
            shutil.copy(ASSETS / "shared" / name, root / "shared" / name)
        for name, text in _NEIGHBORS.items():
            (root / "shared" / name).write_text(text, encoding="utf-8")
        entry = root / "prova.mjs"
        entry.write_text(_PRELUDE + textwrap.dedent(body), encoding="utf-8")
        run_module(entry)


# ── Il fumetto: tutta la risposta, formattata ────────────────────────────────


def test_deltas_accumulate_into_one_formatted_block() -> None:
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'Ciao ', turn_id: 't1' });
        j._handleFrame({ event: 'delta', text: '**Luca**', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['md:Ciao **Luca**'], 'markdown, accumulato, non tagliato');
        assert.equal(j.mc.dataset.state, 'reply');
        assert.equal(last(j), 'talking');
        assert.equal(j._streamTurnId, 't1', 'il primo frame adotta il turno');
        assert.deepEqual(richened, [], 'formule e diagrammi solo a blocco chiuso');
        """
    )


def test_every_segment_is_its_own_block_and_all_of_them_stay() -> None:
    """Il caso del preambolo: prima i segmenti si incollavano («controllo.La
    risposta») e il taglio in testa mostrava solo il primo."""
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'Ora controllo.', turn_id: 't1' });
        j._handleFrame({ event: 'stream_end', turn_id: 't1' });
        j._handleFrame({ event: 'message', kind: 'tool_hint', text: 'leggo il file', turn_id: 't1' });
        j._handleFrame({ event: 'delta', text: 'La risposta ', turn_id: 't1' });
        j._handleFrame({ event: 'delta', text: 'e\\' 42.', turn_id: 't1' });
        j._handleFrame({ event: 'stream_end', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['md:Ora controllo.', "md:La risposta e' 42."]);
        assert.deepEqual(richened, ['md:Ora controllo.', "md:La risposta e' 42."]);
        const long = 'x'.repeat(1200);
        j._handleFrame({ event: 'message', text: long, turn_id: 't1' });
        assert.equal(blocks(j)[2], 'md:' + long, 'una risposta lunga resta intera');
        """
    )


def test_stream_end_text_wins_over_its_deltas_and_then_settles() -> None:
    """Il fumetto prima, lo stato dopo: lo stato che il frame lascia viene per
    ultimo, dalla madre."""
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'Fat', turn_id: 't1' });
        j._turnActive = false;
        j._handleFrame({ event: 'stream_end', text: 'Fatto.', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['md:Fatto.']);
        assert.equal(last(j), 'idle');
        j._turnActive = true;
        j._handleFrame({ event: 'stream_end', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['md:Fatto.'], 'senza testo il fumetto resta');
        assert.equal(last(j), 'thinking', 'col turno in corso si torna a pensare');
        """
    )


def test_a_message_with_text_is_shown_and_a_hint_is_not() -> None:
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'message', kind: 'tool_hint', text: 'leggo il file' });
        assert.deepEqual(blocks(j), [], 'un suggerimento non va nel fumetto');
        assert.equal(j.mc.dataset.state, 'think');
        assert.equal(last(j), 'thinking');
        j._handleFrame({ event: 'message', kind: 'progress', text: 'ancora un attimo' });
        assert.deepEqual(blocks(j), []);
        j._handleFrame({ event: 'message', tool_events: [{}] });
        assert.equal(last(j), 'thinking');
        j._handleFrame({ event: 'message', text: 'Eccola' });
        assert.deepEqual(blocks(j), ['md:Eccola']);
        assert.equal(last(j), 'talking');
        """
    )


def test_turn_end_without_a_reply_shows_the_flower_and_closes_the_turn() -> None:
    _run(
        """
        const j = minichat();
        j._replyTimer = 7;
        j._handleFrame({ event: 'turn_end', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['✿']);
        assert.equal(last(j), 'idle', 'il fiore non lascia Jafta a parlare');
        assert.equal(j._pendingTurn, false);
        assert.equal(j._replyTimer, null, 'il timer della risposta lenta va spento');
        assert.equal(j._lastClosedTurnId, 't1');
        assert.equal(j.closed, 1, 'chi la ospita sa che il turno e\\' finito');
        """
    )


def test_turn_end_after_a_reply_keeps_the_reply() -> None:
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'Risposta', turn_id: 't1' });
        j._handleFrame({ event: 'turn_end', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['md:Risposta']);
        assert.equal(last(j), 'idle');
        assert.equal(j._streamTurnId, null);
        """
    )


def test_error_shows_its_words_and_the_sad_face() -> None:
    """Le parole del rifiuto sono quelle di ``describeWireError``, come in
    chat, e sono gia' testo: niente markdown."""
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'error', reason: 'size', detail: 'image_rejected' });
        assert.deepEqual(blocks(j), ['common.wireError.size']);
        assert.equal(j.bubble.children[0].dataset.kind, 'error');
        assert.equal(last(j), 'idle');
        assert.deepEqual(j.moods, ['sad']);
        assert.equal(j._pendingTurn, false);

        const u = minichat();
        u._handleFrame({ event: 'error', reason: 'provider_down' });
        assert.deepEqual(blocks(u), ['common.wireError.unknown (provider_down)']);
        """
    )


def test_the_closing_frame_of_a_foreign_turn_is_ignored() -> None:
    """L'avviso proattivo atterrato durante l'attesa non chiude la domanda."""
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'sto', turn_id: 'mio' });
        j._handleFrame({ event: 'turn_end', turn_id: 'avviso' });
        j._handleFrame({ event: 'error', turn_id: 'avviso', detail: 'no' });
        assert.equal(j._pendingTurn, true);
        assert.deepEqual(blocks(j), ['md:sto']);
        assert.equal(j.closed, 0);
        assert.deepEqual(j.moods, []);
        """
    )


def test_without_a_question_of_its_own_nothing_reaches_the_bubble() -> None:
    """Fuori dalla chat, un turno partito dalla chat non ha niente da dire nel
    fumetto."""
    _run(
        """
        const j = minichat({ asked: false });
        j._handleFrame({ event: 'delta', text: 'dalla chat', turn_id: 'c1' });
        j._handleFrame({ event: 'turn_end', turn_id: 'c1' });
        assert.deepEqual(blocks(j), []);
        assert.deepEqual(j.states, []);
        assert.equal(j.closed, 0);
        """
    )


# ── Chiusa, riaperta, lenta: la domanda resta seguita ────────────────────────


def test_a_closed_minichat_still_follows_its_question() -> None:
    """Il difetto: chiuderla a meta' turno buttava via la risposta, e riaprendola
    c'era il campo vuoto. Adesso la risposta arriva anche a minichat chiusa, e
    riaprendola la trovi; una volta vista, la chiusura dopo la dimentica."""
    _run(
        """
        const j = minichat({ open: false });
        j._handleFrame({ event: 'delta', text: 'Arriva', turn_id: 't1' });
        j._handleFrame({ event: 'stream_end', text: 'Arrivata.', turn_id: 't1' });
        j._handleFrame({ event: 'turn_end', turn_id: 't1' });
        assert.deepEqual(blocks(j), ['md:Arrivata.']);
        assert.equal(j.closed, 1);
        assert.equal(j._replySeen, false, 'a minichat chiusa non l\\'ha vista nessuno');

        j._openMini();
        assert.equal(j.mc.dataset.state, 'reply', 'riaprendola c\\'e\\' la risposta');
        assert.equal(j._replySeen, true);
        j._closeMini();
        assert.deepEqual(blocks(j), [], 'vista e chiusa: si dimentica');
        j._openMini();
        assert.equal(j.mc.dataset.state, 'ask');
        """
    )


def test_closing_mid_turn_and_reopening_shows_where_it_is() -> None:
    _run(
        """
        const j = minichat();
        j._paintState();
        assert.equal(j.mc.dataset.state, 'think');
        j._closeMini();
        assert.equal(j._pendingTurn, true, 'chiudere non ferma niente');
        assert.deepEqual(j.states, [], 'ne\\' la manda a riposo: sta ancora pensando');
        j._openMini();
        assert.equal(j.mc.dataset.state, 'think', 'riaperta pensa ancora');
        j._handleFrame({ event: 'delta', text: 'Eccomi', turn_id: 't1' });
        j._closeMini();
        assert.deepEqual(blocks(j), ['md:Eccomi'], 'una risposta a meta\\' non si dimentica');
        j._openMini();
        assert.equal(j.mc.dataset.state, 'reply');
        """
    )


def test_a_slow_turn_says_so_and_keeps_listening() -> None:
    """Allo scadere dei 90 secondi il fumetto diceva «ci sto lavorando» e smetteva
    di seguire il turno: la risposta vera non compariva piu'. Adesso la nota sta
    li' finche' non arriva la prima parola, e il turno resta seguito."""
    _run(
        """
        const j = minichat({ asked: false });
        timers.length = 0;
        await j._send('una cosa lunga');
        assert.deepEqual(j.sent, ['una cosa lunga']);
        assert.equal(timers.length, 1);
        timers[0]();
        assert.deepEqual(blocks(j), ['jafta.workingReply']);
        assert.equal(j.bubble.children[0].dataset.kind, 'note');
        assert.equal(j._pendingTurn, true, 'il turno lento non si chiude');
        j._handleFrame({ event: 'delta', text: 'Finito!', turn_id: 't9' });
        assert.deepEqual(blocks(j), ['md:Finito!'], 'la risposta prende il posto della nota');
        j._handleFrame({ event: 'turn_end', turn_id: 't9' });
        assert.equal(j._pendingTurn, false);
        """
    )


def test_changing_view_keeps_the_question_and_the_chat_takes_it_over() -> None:
    """Fra due viste che non sono la chat la minichat si chiude ma la domanda
    resta seguita; entrando in chat il fumetto si dimentica, perche' la
    risposta la mostra la chat."""
    _run(
        """
        const j = minichat();
        j.mode = 'files';
        j._handleFrame({ event: 'delta', text: 'Meta\\'', turn_id: 't1' });
        j._placeChanged('cron');
        assert.deepEqual(j.outs, [false], 'si chiude, e lei torna al bordo');
        assert.equal(j._pendingTurn, true);
        assert.equal(j._streamTurnId, 't1');
        j._handleFrame({ event: 'delta', text: ' e fine', turn_id: 't1' });
        assert.deepEqual(blocks(j), ["md:Meta' e fine"]);
        j._placeChanged('chat');
        assert.deepEqual(blocks(j), [], 'in chat la risposta la mostra la chat');
        assert.equal(j._pendingTurn, true, 'e la madre la segue fino al turn_end');
        """
    )


def test_leaving_the_chat_with_nothing_asked_puts_her_to_rest() -> None:
    _run(
        """
        const j = minichat({ asked: false });
        j.mode = 'chat';
        j._turnActive = true;
        j._streamTurnId = 'c1';
        j._placeChanged('away');
        assert.equal(j._turnActive, false);
        assert.equal(j._streamTurnId, null);
        assert.equal(last(j), 'idle');
        """
    )


# ── Il tasto: spento mentre lei risponde ─────────────────────────────────────


def test_the_send_is_off_while_any_turn_is_in_flight() -> None:
    """Decisione dell'utente (28/09/2026): mentre Jafta risponde non parte
    niente, anche se la risposta e' partita dalla chat. Il campo dice perche'."""
    _run(
        """
        const j = minichat({ asked: false });
        j.input.value = 'che ore sono?';
        j._syncSend();
        assert.equal(j.sendBtn.disabled, false);
        assert.equal(j.input.placeholder, 'Scrivi a Jafta', 'dove va il messaggio');
        // In chat il turno c1 sta scorrendo; la minichat non lo disegna.
        j._handleFrame({ event: 'goal_status', status: 'running' });
        j._handleFrame({ event: 'delta', text: 'Ecco il riassunto', turn_id: 'c1' });
        assert.deepEqual(blocks(j), []);
        assert.equal(j.sendBtn.disabled, true, 'col turno in volo il tasto si spegne');
        assert.equal(j.input.placeholder, 'jafta.busy');
        j._handleFrame({ event: 'turn_end', turn_id: 'c1' });
        assert.equal(j.sendBtn.disabled, false, 'finito il turno si riaccende');
        assert.equal(j.input.placeholder, 'Scrivi a Jafta');
        j._handleFrame({ event: 'goal_status', status: 'running' });
        j._handleFrame({ event: 'goal_status', status: 'idle' });
        assert.equal(j.sendBtn.disabled, false, 'anche idle lo riaccende');
        """
    )


def test_its_own_question_keeps_the_send_off_until_the_end() -> None:
    _run(
        """
        const j = minichat({ asked: false });
        await j._send('ciao');
        j.input.value = 'e poi?';
        j._syncSend();
        assert.equal(j.sendBtn.disabled, true);
        j._handleFrame({ event: 'delta', text: 'Ciao!', turn_id: 't2' });
        assert.equal(j._streamTurnId, 't2', 'a turno fermo adotta il suo');
        assert.equal(j.sendBtn.disabled, true);
        j._handleFrame({ event: 'turn_end', turn_id: 't2' });
        assert.equal(j.sendBtn.disabled, false);
        """
    )


def test_a_dropped_wire_lets_the_question_go_and_says_why() -> None:
    """Col tasto spento fino al ``turn_end``, un ``turn_end`` che non arrivera'
    lo terrebbe spento per sempre."""
    _run(
        """
        const j = minichat();
        j._chatRunning = true;
        j._onWireClose();
        assert.equal(j._pendingTurn, false);
        assert.equal(j._chatRunning, false);
        assert.deepEqual(blocks(j), ['jafta.connectionError']);
        j.input.value = 'riprovo';
        j._syncSend();
        assert.equal(j.sendBtn.disabled, false);

        const k = minichat({ asked: false });
        k._onWireClose();
        assert.deepEqual(blocks(k), [], 'senza domanda in volo non c\\'e\\' niente da dire');
        """
    )


def test_a_send_that_never_left_says_so() -> None:
    _run(
        """
        const j = minichat({ asked: false, sends: false });
        await j._send('ciao');
        assert.equal(j._pendingTurn, false, 'niente e\\' partito: nessun turn_end arrivera\\'');
        assert.equal(j._turnActive, false);
        assert.deepEqual(blocks(j), ['jafta.connectionError']);
        """
    )


# ── La madre, sotto ──────────────────────────────────────────────────────────


def test_goal_status_and_reasoning_move_the_state() -> None:
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'goal_status', status: 'running' });
        assert.equal(j._turnActive, true);
        assert.equal(last(j), 'thinking');
        assert.equal(j._chatRunning, true, 'col turno partito il tasto si spegne');
        j._handleFrame({ event: 'reasoning_delta', text: 'uhm' });
        j._handleFrame({ event: 'file_edit' });
        assert.equal(last(j), 'thinking');
        j._handleFrame({ event: 'goal_status', status: 'idle' });
        assert.equal(j._turnActive, false);
        assert.equal(last(j), 'idle');
        """
    )


def test_in_the_chat_view_the_bubble_is_not_touched() -> None:
    """In chat la minichat non c'e': il frame va alla macchina della madre."""
    _run(
        """
        const j = minichat({ asked: false });
        j.mode = 'chat';
        j._handleFrame({ event: 'delta', text: 'in chat', turn_id: 'c1' });
        assert.deepEqual(blocks(j), []);
        assert.equal(last(j), 'talking');
        j._handleFrame({ event: 'turn_end', turn_id: 'c1' });
        assert.deepEqual(blocks(j), []);
        assert.equal(j.closed, 0);
        assert.equal(last(j), 'idle');
        """
    )


def test_an_empty_message_means_thinking_as_in_the_mother() -> None:
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'message' });
        assert.deepEqual(j.states, ['thinking']);
        assert.deepEqual(blocks(j), []);
        """
    )


def test_a_conversation_switch_forgets_the_minichat() -> None:
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'vecchia', turn_id: 't1' });
        j._releaseTrackedTurn();
        assert.deepEqual(blocks(j), []);
        assert.equal(j._pendingTurn, false);
        assert.equal(j._chatRunning, false);
        assert.deepEqual(j.outs, [false], 'aperta, si chiude');
        """
    )


def test_the_placeholder_falls_back_when_the_shell_has_none() -> None:
    _run(
        """
        const j = minichat({ asked: false });
        j._adapter.placeholder = () => '';
        j._syncPlaceholder();
        assert.equal(j.input.placeholder, 'jafta.askHere');
        """
    )


# ── Mai piu' a pensare per sempre ────────────────────────────────────────────


def test_a_command_reply_closes_the_question() -> None:
    """`/status` dal fumetto: risponde un solo ``message``, senza `running` prima
    e (da un gateway di prima del 28/09/2026) senza niente dopo. Prima la domanda
    restava in volo per sempre, e con lei il tasto spento."""
    _run(
        """
        const j = minichat({ asked: false });
        await j._send('/status');
        j._handleFrame({ event: 'message', text: 'jafta v0.11.0', turn_id: 's1' });
        assert.deepEqual(blocks(j), ['md:jafta v0.11.0']);
        assert.equal(j._pendingTurn, false, 'la risposta di un comando chiude la domanda');
        assert.equal(j._turnActive, false);
        assert.equal(j._streamTurnId, null, 'e non lascia un id appeso');
        assert.equal(j.closed, 1);
        j.input.value = 'altro';
        j._syncSend();
        assert.equal(j.sendBtn.disabled, false);
        """
    )


def test_an_idle_closes_the_question_even_without_its_turn_end() -> None:
    """Il `turn_end` di `/stop` porta l'id di `/stop`, non del turno fermato:
    non si riconosce, e a chiudere resta `goal_status: idle`."""
    _run(
        """
        const j = minichat();
        j._handleFrame({ event: 'delta', text: 'Sto', turn_id: 'a1' });
        j._handleFrame({ event: 'turn_end', turn_id: 'stop1' });
        assert.equal(j._pendingTurn, true, 'il turn_end di un altro non chiude');
        j._handleFrame({ event: 'goal_status', status: 'idle' });
        assert.equal(j._pendingTurn, false);
        assert.equal(j._streamTurnId, null, 'nessun id seguito resta appeso');
        assert.equal(j.closed, 1);
        assert.equal(last(j), 'idle');
        """
    )
