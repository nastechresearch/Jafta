/** Il primo avvio: la domanda che fanno tutti e tre i documenti della WebUI.
 *
 *  La casa e l'officina rimandano a `onboarding.html` quando la risposta e' si';
 *  l'onboarding rimanda alla casa quando e' no. La risposta e' `first_run` di
 *  `/api/settings` (vero se non c'e' ancora nessun provider).
 *
 *  **Le risposte sono tre, non due.** Una lettura fallita — gateway a meta'
 *  avvio, token non ancora valido — restituisce `null`, e chi chiama non la
 *  tratta come nessuna delle altre due: un «non lo so» preso per «configurato»
 *  lasciava una Jafta senza provider e senza strada verso il wizard, e preso
 *  per «primo avvio» manderebbe al wizard chi ha gia' i suoi provider (che
 *  `onboarding.save` sostituirebbe). */

/** `true`, `false`, o `null` se le impostazioni non si leggono.
 *
 *  `readSettings` e' la lettura da usare: la casa passa la propria, che tiene
 *  in cache la promessa (`_askSettings`), cosi' la domanda non costa una
 *  richiesta in piu'. Quella lettura un fallimento non lo lancia, lo rende
 *  come `null`: anche una risposta vuota vale quindi «non lo so», non «no». */
export async function isFirstRun(readSettings) {
  let settings;
  try {
    settings = await readSettings();
  } catch {
    return null;
  }
  if (!settings || typeof settings !== 'object') return null;
  return settings.first_run === true;
}
