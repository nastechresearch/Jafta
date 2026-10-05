/** La casa — il chip dei subagent al lavoro.
 *
 *  Un turno non aspetta piu' i subagent che lancia (02/10/2026): Jafta dice «ci
 *  sto lavorando» e il turno finisce, mentre il lavoro va avanti per minuti. La
 *  riga di lavoro (`home-activity.js`) vive solo finche' il turno e' aperto, e
 *  senza questo chip la conversazione restava muta fino al risultato — «non
 *  vedo che stanno lavorando», detto davanti a un quaderno.
 *
 *  **Dice soltanto *che* qualcuno lavora**: quanti, come si chiama se e' uno, e
 *  se e' fermo. Stato, tempi, strumenti, Ferma e Riprova stanno in officina, e
 *  il tocco lungo porta li', come per la riga di lavoro. E' l'eccezione datata
 *  alla regola di `home-chat.js` («i subagent non si leggono»).
 *
 *  I dati sono lo snapshot che il gateway pubblica a ogni transizione
 *  (`subagent_status`, gia' limitato alla sessione che li ha lanciati), piu' una
 *  lettura di `/api/subagents?session_key=` quando lo snapshot non arriva da
 *  se': all'avvio, a ogni riconnessione e a ogni cambio di conversazione —
 *  l'attach non lo rimanda. Niente timer e niente polling: il chip cambia solo
 *  quando cambia lo stato.
 */

import { i18n } from './shared/i18n.js';
import { setupLongPress } from './shared/longpress.js';
import { saIsTerminal } from './shared/subagent-policy.js';

export class SubagentChip {
  /**
   * @param {HTMLElement} el
   * @param {{ fetchSnapshot: (sessionKey: string) => Promise<any>,
   *           currentKey: () => string,
   *           onOpenInWorkshop?: () => void }} deps
   */
  constructor(el, { fetchSnapshot, currentKey, onOpenInWorkshop } = {}) {
    this.el = el;
    this._fetch = fetchSnapshot;
    this._currentKey = currentKey;
    this.running = [];
    /* Ogni frame alza il contatore: una lettura HTTP partita prima di un frame
       porta uno stato piu' vecchio di quello che il frame ha gia' detto, e non
       deve sovrascriverlo. */
    this._frames = 0;

    this.icon = document.createElement('i');
    this.icon.className = 'ti ti-users';
    this.icon.setAttribute('aria-hidden', 'true');
    this.text = document.createElement('span');
    this.text.className = 'home-subagents-text';
    this.el.append(this.icon, this.text);

    if (onOpenInWorkshop) {
      setupLongPress(this.el, () => {
        if (!this.el.hidden) onOpenInWorkshop();
      });
      // Il flag lo posa `setupLongPress` e va consumato da chi lo chiama.
      this.el.addEventListener('click', () => {
        if (this.el.dataset.longpress) delete this.el.dataset.longpress;
      });
    }
  }

  /** Rilegge lo stato della conversazione a schermo. Un errore lascia il chip
   *  com'era: e' un'informazione in piu', non una cosa che puo' rompere. */
  async load() {
    const key = this._currentKey();
    const framesBefore = this._frames;
    let snapshot;
    try {
      snapshot = await this._fetch(key);
    } catch {
      return;
    }
    // Nel frattempo si e' cambiata conversazione, o un frame ha detto di piu'.
    if (key !== this._currentKey() || framesBefore !== this._frames) return;
    this.render(snapshot);
  }

  /** Uno snapshot `subagent_status` della conversazione a schermo (il filtro
   *  per chat lo fa chi chiama, con la stessa regola degli altri frame). */
  ingest(snapshot) {
    this._frames += 1;
    this.render(snapshot);
  }

  /** Si cambia conversazione: quel che si vedeva era dell'altra. */
  clear() {
    this._frames += 1;
    this.render(null);
  }

  render(snapshot) {
    const running = Array.isArray(snapshot?.running)
      ? snapshot.running.filter((entry) => entry && !saIsTerminal(entry.state))
      : [];
    this.running = running;
    this._paint();
  }

  applyTranslations() {
    this._paint();
  }

  _paint() {
    const running = this.running;
    if (!running.length) {
      this.el.hidden = true;
      this.el.classList.remove('is-stalled');
      this.text.textContent = '';
      return;
    }
    const stalled = running.some((entry) => entry.state === 'stalled');
    const label = running.length === 1 ? String(running[0].label || '').trim() : '';
    let text;
    if (running.length === 1 && stalled) {
      text = label ? i18n.t('home.subagents.oneStalled', { label })
                   : i18n.t('home.subagents.stalled');
    } else if (running.length === 1) {
      text = label ? i18n.t('home.subagents.one', { label })
                   : i18n.t('home.subagents.oneUnnamed');
    } else {
      text = i18n.t(stalled ? 'home.subagents.manyStalled' : 'home.subagents.many',
                    { count: running.length });
    }
    this.text.textContent = text;
    this.el.classList.toggle('is-stalled', stalled);
    this.el.setAttribute('aria-label', `${text}. ${i18n.t('home.subagents.openInWorkshop')}`);
    this.el.hidden = false;
  }
}
