/** La minichat di Jafta — una domanda a un turno, fuori dalla chat.
 *
 *  Richiamata con un tocco (o uno swipe verso l'interno) dove la chat non e' a
 *  schermo, Jafta esce con un campo in basso; pensa, e risponde in un fumetto
 *  sopra la testa. In chat niente minichat: la conversazione vera e' gia'
 *  aperta, e lei e' solo presente all'angolo.
 *
 *  Fino al 28/09/2026 era dell'officina sola (`mobile-jafta.js`), e la casa la
 *  lasciava fuori perche' «in casa la chat e' lo schermo». Non era piu' vero da
 *  quando la casa ha pagine e stanze senza composer: li' il tocco la faceva
 *  uscire e non succedeva nient'altro. Adesso e' di tutti e due i gusci, e
 *  quel che ciascuno ha di suo passa da un adattatore:
 *
 *    - `send(text) → boolean`: manda nella conversazione aperta (la casa ci
 *      disegna anche la bolla nel filo, l'officina no);
 *    - `placeholder() → string`: le parole del campo della chat vera, che
 *      dicono dove va il messaggio;
 *    - `onTurnClosed()`: il turno chiesto qui e' finito (l'officina invalida lo
 *      storico della chat, che fuori vista non riceve lo stream).
 *
 *  Il fumetto contiene **tutta** la risposta, formattata come in chat, e scorre
 *  (decisione dell'utente, 28/09/2026). E i suoi colori sono quelli della bolla
 *  dei messaggi dell'utente, tema per tema.
 */

import { wsManager } from './ws-manager.js';
import { i18n } from './i18n.js';
import { JaftaMascot } from './jafta-mascot.js';
import { describeWireError } from './wire-error.js';
import { renderMarkdown } from './markdown.js';
import { renderRich } from './rich-content.js';
import { contentLinkOf, openContentLink } from './content-link.js';
import { showToast } from './utils.js';

const CONNECT_TIMEOUT_MS = 6000;
const REPLY_TIMEOUT_MS = 90000;
// Quanto vicino al fondo conta come «in fondo» (v. `_onBubbleScroll`).
const STICK_SLACK_PX = 8;

export class JaftaWithMinichat extends JaftaMascot {
  /**
   * @param {HTMLElement} host  v. `JaftaMascot`
   * @param {{mode?: string, minichat: {send: (text: string) => boolean,
   *   placeholder: () => string, onTurnClosed?: () => void}}} opts
   */
  constructor(host, { mode = 'chat', minichat } = {}) {
    super(host, { mode });
    this._adapter = minichat;
    this._replyTimer = null;
    /* Un turno della conversazione e' in volo, da qualunque parte sia partito
       (v. `_noteLiveTurn`): e' lui a spegnere l'invio mentre Jafta risponde. */
    this._chatRunning = false;
    this._resetReply();

    this.askForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = this.input.value.trim();
      if (!text || this._busy()) return;
      this.input.value = '';
      this.input.blur();
      this._send(text);
    });
  }

  _buildDom() {
    this.scrim = document.createElement('button');
    this.scrim.className = 'jafta-scrim';
    this.scrim.addEventListener('click', () => this._setOut(false));

    this.mc = document.createElement('div');
    this.mc.className = 'jafta-mc';
    this.mc.dataset.state = 'ask';
    this.mc.innerHTML = `
      <div class="jafta-mc-bubble"><div class="jafta-mc-text"></div></div>
      <div class="jafta-mc-think">…</div>
      <form class="jafta-mc-ask compose-row">
        <div class="compose-pill">
          <input class="jafta-mc-input" type="text" autocomplete="off">
        </div>
        <button class="jafta-mc-send compose-send" type="submit" disabled>
          <i class="ti ti-arrow-up" aria-hidden="true"></i>
        </button>
      </form>`;

    this.host.appendChild(this.scrim);
    this.host.appendChild(this.mc);
    // Lo sprite dopo la minichat, come e' sempre stato: e' l'ordine del DOM.
    super._buildDom();

    this.bubble = this.mc.querySelector('.jafta-mc-text');
    this.askForm = this.mc.querySelector('.jafta-mc-ask');
    this.input = this.mc.querySelector('.jafta-mc-input');
    this.sendBtn = this.mc.querySelector('.jafta-mc-send');

    // Come in chat: il send si accende solo quando c'e' testo (e lei e' libera).
    this.input.addEventListener('input', () => this._syncSend());
    this.bubble.addEventListener('scroll', () => this._onBubbleScroll());
    /* I link della risposta si aprono con la regola della chat: il markdown
       finisce in `innerHTML`, e un link lasciato navigare porterebbe via il
       guscio (v. `shared/content-link.js`). */
    this.bubble.addEventListener('click', (e) => {
      const link = contentLinkOf(e.target);
      if (!link || !this.bubble.contains(link) || e.defaultPrevented) return;
      openContentLink(e, link, this.bubble, (type) => {
        showToast(i18n.t('common.linkNotOpenable'), type);
      });
    });

    /* Le parole si scrivono adesso e di nuovo quando arrivano le traduzioni:
       questo costruttore gira prima di `i18n.load()`, e fino ad allora `i18n.t`
       torna le chiavi grezze. */
    const translate = () => {
      this.scrim.setAttribute('aria-label', i18n.t('jafta.closeMinichat'));
      this.input.setAttribute('aria-label', i18n.t('jafta.askJafta'));
      this.sendBtn.setAttribute('aria-label', i18n.t('jafta.send'));
      if (this._adapter) this._syncPlaceholder();
    };
    translate();
    i18n.load(i18n.locale).then(translate).catch(() => {});
  }

  /** La minichat e' aperta: la casa lo chiede prima di prendersi un tasto. */
  get minichatOpen() {
    return this.mc.classList.contains('open');
  }

  /* ── Dove si trova ── */

  /** La chat e' a schermo, o no. E' il solo ingresso che la minichat chiede a
   *  chi la ospita: la posizione (al bordo, fuori) resta di chi la ospita. */
  setChatOnScreen(on) {
    this._placeChanged(on ? 'chat' : 'away');
  }

  /* Un cambio di vista chiude la minichat, ma **non smette di seguire** la
     domanda in volo: la risposta arriva lo stesso, e la trovi riaprendola.
     Prima un cambio fra due viste qualunque la buttava via. */
  _placeChanged(mode) {
    // Con la vista di prima: chiudendo la manda al bordo, come fa lo scrim.
    if (this.minichatOpen) this._setOut(false);
    if (mode === this.mode) return;
    this.mode = mode;
    // In chat la risposta la mostra la chat: il fumetto non ha piu' niente da dire.
    if (mode === 'chat') this._resetReply();
    if (this._pendingTurn) return;
    /* Nessuna domanda nostra in volo: il turno che lei animava non lo segue piu'
       nessuno — fuori dalla chat i suoi frame si scartano — e restare a
       pensare vorrebbe dire aspettare un `turn_end` che non guarda nessuno. */
    this._turnActive = false;
    this._streamTurnId = null;
    this._setAgentState('idle');
  }

  /* ── Drag / tap ── */

  /* La minichat si chiude quando il trascinamento comincia. */
  _onDragCommit() {
    if (this.minichatOpen) this._closeMini();
  }

  _onOutChange(out) {
    if (this.mode === 'chat') return;
    this.el.classList.toggle('mini', out);
    if (out) this._openMini();
    else this._closeMini();
  }

  /* Tasto Indietro hardware: con la minichat aperta lo si consuma per
     richiuderla (scrim e tastiera comprese), come il tap sullo scrim.
     Ritorna false se non c'era niente di aperto. */
  handleBack() {
    if (!this.mc?.classList.contains('open')) return false;
    this._setOut(false);
    return true;
  }

  /* ── Apertura e chiusura ── */

  _openMini() {
    this.scrim.classList.add('open');
    this.mc.classList.add('open');
    // Una risposta arrivata a minichat chiusa: aprendo la si vede, e da qui conta come letta.
    if (!this._pendingTurn && this._blocks.length) this._replySeen = true;
    this._paintState();
    this._syncPlaceholder();
    this._syncSend();
    if (this._stick) this._scrollToEnd();
    // Il campo prende il fuoco da solo: la minichat si apre per scrivere, e
    // chiederle di aprirla e poi toccare il campo e' un tap di troppo. Va fatto
    // qui e in modo sincrono — siamo ancora dentro il gesto dell'utente
    // (tap o rilascio del drag), l'unico momento in cui la WebView Android
    // accetta di alzare la tastiera senza che l'utente tocchi l'input.
    this.input.focus();
  }

  /* Chiudere non ferma niente: la domanda in volo resta seguita (v.
     `_placeChanged`). Si dimentica solo una risposta finita e gia' vista. */
  _closeMini() {
    // Simmetrico al focus di _openMini: chiudendola la tastiera se ne deve
    // andare con lei, non restare aperta su un campo che non si vede piu'.
    this.input.blur();
    this.scrim.classList.remove('open');
    this.mc.classList.remove('open');
    this.input.value = '';
    this._syncSend();
    this.el.classList.remove('mini');
    if (this._pendingTurn) return;
    if (this._replySeen) this._resetReply();
    this._setAgentState('idle');
  }

  /* ── Il campo ── */

  /* Mentre Jafta risponde il tasto resta spento — decisione dell'utente del
     28/09/2026 — **anche** se la risposta e' partita dalla chat: una domanda
     mandata adesso finirebbe dentro quel turno. Si puo' scrivere lo stesso. */
  _busy() {
    return this._pendingTurn || this._chatRunning;
  }

  _syncSend() {
    this.sendBtn.disabled = this._busy() || !this.input.value.trim();
    this._syncPlaceholder();
  }

  /* Lo stesso placeholder della chat vera, che dice dove va il messaggio — un
     quaderno o un progetto, la sola lettura — e se Jafta e' occupata, perche'
     il tasto e' spento. Si rilegge a ogni apertura: finche' la minichat e'
     aperta, chi lo tiene aggiornato non si puo' toccare. */
  _syncPlaceholder() {
    if (this._busy()) {
      this.input.placeholder = i18n.t('jafta.busy');
      return;
    }
    const words = this._adapter?.placeholder?.();
    this.input.placeholder = words || i18n.t('jafta.askHere');
  }

  /* ── La domanda ── */

  async _send(text) {
    this._resetReply();
    this._turnActive = true;
    this._pendingTurn = true;
    // Un'attesa nuova: il turno, se parte, lo dira' il suo `running`.
    this._runSeen = false;
    // A turno fermo si adotta il primo frame che lo apre (v. `_trackedTurnMatches`).
    this._streamTurnId = null;
    this._setAgentState('thinking'); // ferma un eventuale parlato precedente; _syncArt -> think
    this._paintState();
    this._syncSend();

    try {
      await this._ensureConnected();
      if (!this._adapter.send(text)) throw new Error('ws send failed');
      /* Il turno lento non si chiude: si dice che sta ancora lavorando, e la
         risposta, quando arriva, prende il posto della nota. Prima questo timer
         smetteva di seguire il turno, e il fumetto restava sulla nota per
         sempre — un turno con qualche strumento li passa, i 90 secondi. */
      this._replyTimer = setTimeout(() => {
        this._replyTimer = null;
        if (!this._pendingTurn || this._blocks.length) return;
        this._note = i18n.t('jafta.workingReply');
        this._paintBlocks();
      }, REPLY_TIMEOUT_MS);
    } catch (err) {
      console.error('Jafta send failed:', err);
      // Niente e' partito: nessun turn_end arrivera' a chiudere il turno.
      this._pendingTurn = false;
      this._turnActive = false;
      this._setAgentState('idle');
      this._addPlainBlock(i18n.t('jafta.connectionError'), 'error');
    }
  }

  _ensureConnected() {
    wsManager.connectChat();
    if (wsManager.chatConnected) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        wsManager.removeEventListener('chat:open', onOpen);
        reject(new Error('ws connect timeout'));
      }, CONNECT_TIMEOUT_MS);
      const onOpen = () => {
        clearTimeout(timer);
        wsManager.removeEventListener('chat:open', onOpen);
        resolve();
      };
      wsManager.addEventListener('chat:open', onOpen);
    });
  }

  /* Il filo e' caduto. Col tasto spento fino al `turn_end`, un `turn_end` che
     non arrivera' piu' lo terrebbe spento per sempre: la domanda si lascia
     andare e il fumetto dice perche'. Al rientro la chat rilegge il filo da se'. */
  _onWireClose() {
    const asked = this._pendingTurn;
    this._chatRunning = false;
    this._clearReplyTimer();
    this._note = null;
    super._onWireClose();
    if (asked) this._addPlainBlock(i18n.t('jafta.connectionError'), 'error');
    this._paintState();
    this._syncSend();
  }

  /* ── I frame ── */

  /* Un turno in volo nella conversazione, da ogni frame. Lo apre
     `goal_status: running`, che ogni turno vero manda per primo; lo chiudono
     `idle`, `turn_end` ed `error`. Prima si guardava l'id dei frame, e la
     risposta di un comando — un id, e nessuna chiusura dopo — teneva il tasto
     spento fino al turno seguente. */
  _noteLiveTurn(msg) {
    const was = this._chatRunning;
    if (msg.event === 'goal_status') this._chatRunning = msg.status === 'running';
    else if (msg.event === 'turn_end' || msg.event === 'error') this._chatRunning = false;
    if (was !== this._chatRunning) this._syncSend();
  }

  _handleFrame(msg) {
    this._noteLiveTurn(msg);
    if (this.mode === 'chat') {
      this._handleChatStream(msg);
      return;
    }
    /* Fuori dalla chat si segue solo la domanda fatta qui, **aperta o chiusa
       che sia la minichat**: un turno partito dalla chat non ha niente da
       dire nel fumetto. */
    if (!this._pendingTurn) return;
    // Un turno estraneo — l'avviso proattivo atterrato durante l'attesa — non
    // chiude la domanda in volo, la cui risposta sta ancora arrivando.
    const mine = this._trackedTurnMatches(msg);
    if (!mine) return;
    this._handleChatStream(msg, mine);
  }

  /* Il fumetto sopra la macchina a stati della madre, che resta l'unica. Si
     arriva qui solo da `_handleFrame` fuori dalla chat e oltre la sua
     guardia: una chiusura, qui, e' sempre della domanda seguita. */
  _beforeChatState(msg) {
    if (this.mode === 'chat') return;
    switch (msg.event) {
      case 'delta':
        this._appendDelta(msg.text || '');
        break;
      case 'stream_end':
        this._closeSegment(msg.text || '');
        break;
      case 'message':
        if (msg.text && msg.kind !== 'tool_hint' && msg.kind !== 'progress') {
          this._addBlock(msg.text);
          // La risposta di un comando chiude la domanda: dopo, non arriva altro.
          if (this._isCommandReply(msg)) {
            this._endTurn();
            this._adapter.onTurnClosed?.();
          }
        }
        break;
      case 'goal_status':
        // `idle` senza che il `turn_end` sia stato riconosciuto: chiude lo stesso.
        if (msg.status === 'idle') {
          this._endTurn();
          if (!this._blocks.length) this._addPlainBlock('✿');
          this._adapter.onTurnClosed?.();
        }
        break;
      case 'turn_end':
        this._endTurn();
        if (!this._blocks.length) this._addPlainBlock('✿');
        this._adapter.onTurnClosed?.();
        break;
      case 'error':
        this._endTurn();
        /* Le parole di un rifiuto sono quelle della chat: `detail` e' per il
           log, e `reason` e' un identificatore. E' gia' testo: niente markdown. */
        this._addPlainBlock(describeWireError(msg, (key) => i18n.t(key)).text, 'error');
        break;
    }
  }

  _endTurn() {
    this._clearReplyTimer();
    this._note = null;
    if (this.minichatOpen) this._replySeen = true;
    // Il flag lo chiude anche la madre, dopo; qui serve gia' al tasto.
    this._pendingTurn = false;
    this._paintState();
    this._syncSend();
  }

  /* Al cambio di conversazione si dimentica anche la minichat: la domanda in
     volo, il suo timer e la risposta (v. il cappello di `_releaseTrackedTurn`
     in shared/jafta-mascot.js). */
  _releaseTrackedTurn() {
    this._chatRunning = false;
    this._resetReply();
    if (this.minichatOpen) this._setOut(false);
    super._releaseTrackedTurn();
    this._paintState();
    this._syncSend();
  }

  _clearReplyTimer() {
    if (this._replyTimer) {
      clearTimeout(this._replyTimer);
      this._replyTimer = null;
    }
  }

  /* ── Il fumetto ──
     Un blocco per segmento, come la chat: il testo che scorre fino al suo
     `stream_end`, poi un altro. Prima i segmenti si incollavano a meta' frase
     in un testo piano tagliato a 280 caratteri, e dopo un giro di strumenti si
     leggeva il preambolo («Ora controllo…») invece della risposta. */

  _resetReply() {
    this._blocks = [];
    this._note = null;
    this._replySeen = false;
    this._stick = true;
    this._clearReplyTimer?.();
    if (this.bubble) this.bubble.replaceChildren();
    if (this.mc) this._paintState();
  }

  _openBlock() {
    const last = this._blocks[this._blocks.length - 1];
    return last && !last.closed ? last : null;
  }

  _appendDelta(text) {
    let block = this._openBlock();
    if (!block) {
      block = { text: '', closed: false, plain: false };
      this._blocks.push(block);
    }
    block.text += text;
    this._paintBlocks();
  }

  /* `stream_end` porta a volte il testo intero del segmento, che vince sui
     delta; senza, il segmento resta com'era. */
  _closeSegment(text) {
    const block = this._openBlock();
    if (block) {
      if (text) block.text = text;
      block.closed = true;
    } else if (text) {
      this._blocks.push({ text, closed: true, plain: false });
    }
    this._paintBlocks();
  }

  _addBlock(text) {
    const open = this._openBlock();
    if (open) open.closed = true;
    this._blocks.push({ text, closed: true, plain: false });
    this._paintBlocks();
  }

  _addPlainBlock(text, kind = '') {
    const open = this._openBlock();
    if (open) open.closed = true;
    this._blocks.push({ text, closed: true, plain: true, kind });
    this._paintBlocks();
  }

  /* Ridisegna i blocchi. Il markdown si rifa' a ogni delta, come nella chat
     (`home-chat.js`); formule e diagrammi solo a blocco chiuso, perche' a meta'
     sono sintassi rotta. Un blocco chiuso e gia' disegnato non si tocca. */
  _paintBlocks() {
    // La nota del turno lento sta da sola, finche' non arriva la prima parola.
    if (this._note && !this._blocks.length) {
      this.bubble.replaceChildren(this._blockNode(this._note, 'note'));
      this._paintState();
      return;
    }
    if (this.bubble.firstElementChild?.dataset.kind === 'note') this.bubble.replaceChildren();
    const nodes = this.bubble.children;
    this._blocks.forEach((block, i) => {
      let node = nodes[i];
      if (!node) {
        node = this._blockNode('', block.kind || '');
        this.bubble.appendChild(node);
      }
      if (node.dataset.done === '1') return;
      if (block.plain) node.textContent = block.text;
      else node.innerHTML = renderMarkdown(block.text);
      if (block.closed) {
        node.dataset.done = '1';
        if (!block.plain) renderRich(node).catch(() => {});
      }
    });
    this._paintState();
    this._follow();
  }

  _blockNode(text, kind) {
    const node = document.createElement('div');
    node.className = 'jafta-mc-block';
    if (kind) node.dataset.kind = kind;
    if (text) node.textContent = text;
    return node;
  }

  /* Cosa mostra la minichat: il pensa finche' non c'e' niente da leggere, poi
     il fumetto; a riposo solo il campo. */
  _paintState() {
    if (!this.mc) return;
    const words = this._blocks.length > 0 || !!this._note;
    if (words) this.mc.dataset.state = 'reply';
    else this.mc.dataset.state = this._pendingTurn ? 'think' : 'ask';
  }

  /* Il fondo si segue solo se ci si era, con la regola della chat: chi sta
     rileggendo piu' su non viene tirato giu' dalla parola dopo. */
  _onBubbleScroll() {
    const b = this.bubble;
    this._stick = b.scrollTop + b.clientHeight >= b.scrollHeight - STICK_SLACK_PX;
  }

  _follow() {
    if (this._stick && this.minichatOpen) this._scrollToEnd();
  }

  _scrollToEnd() {
    this.bubble.scrollTop = this.bubble.scrollHeight;
  }
}
