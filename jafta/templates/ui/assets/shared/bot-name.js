/** Il nome dell'assistente, uno per documento.
 *
 *  «Jafta» e' il nome dell'app (la pillola «⌂ Jafta» dell'officina, le
 *  notifiche, il titolo); il nome scelto nell'onboarding o nella stanza Jafta
 *  e' quello di **lei**, e va dove si parla con lei o di lei. Rinominata,
 *  l'officina la chiamava ancora «Jafta» ovunque, perche' nessun suo file
 *  leggeva `bot_name` (collaudo del 27/09/2026).
 *
 *  Chi legge le impostazioni lo scrive (`set`), chi lo mostra lo legge (`get`)
 *  e si iscrive ai cambi (`onChange`). Vuoto vuol dire il ripiego, come sul
 *  server (`agents.defaults.bot_name`). */

export const DEFAULT_BOT_NAME = 'Jafta';

let current = DEFAULT_BOT_NAME;
const listeners = new Set();

export const botName = {
  get() {
    return current;
  },

  set(name) {
    const next = (typeof name === 'string' && name.trim()) || DEFAULT_BOT_NAME;
    if (next === current) return;
    current = next;
    for (const fn of [...listeners]) {
      try { fn(next); } catch (err) { console.warn('botName listener failed', err); }
    }
  },

  /** Iscrive *fn* ai cambi; torna la funzione che la disiscrive. */
  onChange(fn) {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
};
