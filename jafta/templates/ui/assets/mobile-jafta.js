/** Jafta companion — la mascotte che vive sul bordo di ogni vista dell'officina.
 *
 * A riposo sporge dal bordo destro, e ci torna anche quando la si lancia
 * altrove: il lato non si sceglie più (le sue chiavi sono fra quelle ritirate
 * in `shared/mascot.js`), e l'arrivo del volo lo decide `settle()` in
 * `shared/mascot-drag.js`. Fuori dalla chat, richiamata, apre la minichat.
 *
 * **Jafta in sé non è qui**: arte, stati, parlato, umore e lettura dei frame
 * stanno in `shared/jafta-mascot.js`, e la minichat in `shared/jafta-minichat.js`,
 * e sono gli stessi della casa. Qui resta quel che l'officina ha di suo: le
 * viste che non sono la chat, e dove manda la domanda della minichat.
 */

import { AppState } from './shared/state.js';
import { wsManager } from './shared/ws-manager.js';
import { sessionManager } from './shared/session-manager.js';
import { mascotVisible } from './shared/mascot.js';
import { JaftaWithMinichat } from './shared/jafta-minichat.js';

export class JaftaCompanion extends JaftaWithMinichat {
  constructor() {
    super(document.getElementById('app'), {
      mode: AppState.currentMode || 'chat',
      minichat: {
        send: (text) => {
          sessionManager.ensureAttached();
          return wsManager.sendToChat(sessionManager.currentKey, text);
        },
        /* Il placeholder della chat vera, **letto dal suo campo**: lo tiene
           aggiornato lo scope chip (`syncPlaceholder` in `shared/scope-chip.js`)
           col progetto e con la sola lettura, cioè con dove va il messaggio. */
        placeholder: () => document.getElementById('chat-input')?.placeholder || '',
        /* Lo scambio è nello storico della sessione: al prossimo ingresso in
           chat la vista si ricarica per mostrarlo. */
        onTurnClosed: () => window.mobileApp?.controllers?.chat?.invalidateHistory(),
      },
    });
    AppState.on('currentMode', (mode) => this.setMode(mode));
  }

  /* ── Modalità vista ── */

  _enterInitialState() {
    this.setMode(this.mode, true);
  }

  setMode(mode, initial = false) {
    if (this._abortFlight) this._abortFlight();
    // Al primo giro `mode` è già quella del costruttore: niente da cambiare.
    if (!initial) this._placeChanged(mode);
    // Nascosta per preferenza utente (la stanza «Jafta» della casa →
    // visibile, v. shared/mascot.js).
    const hidden = !mascotVisible();
    this.el.classList.toggle('hidden-mode', hidden);
    // Coerente col media-query landscape: nascondi anche gli overlay
    // (minichat e scrim), non solo il duo, per evitare residui interattivi.
    this.mc.classList.toggle('hidden-mode', hidden);
    this.scrim.classList.toggle('hidden-mode', hidden);
    if (hidden) {
      this._updateGestureExclusion();
      return;
    }

    if (mode === 'chat') {
      // Presenza pura: all'angolo sopra la barra di input, senza minichat.
      this.el.classList.add('in-chat', 'out');
    } else {
      this.el.classList.remove('in-chat', 'out', 'mini');
    }
    this._syncArt();
    this._updateGestureExclusion();
  }

  /* Le preferenze passano da `setMode`, che sa anche degli overlay della
     minichat. */
  _applyVisibility() {
    this.setMode(this.mode, true);
  }
}
