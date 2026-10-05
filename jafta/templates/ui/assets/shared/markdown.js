/** Il markdown di un messaggio, reso in HTML sanificato. Fallisce chiuso.
 *
 *  Era scritto due volte — la chat della casa e quella dell'officina — con la
 *  stessa regola di sicurezza: se il sanificatore (DOMPurify) non c'e', o se il
 *  parse fallisce, il testo esce con l'HTML neutralizzato, mai iniettato
 *  com'e'. Un testo del modello e' un input non fidato, e `innerHTML` non
 *  perdona.
 *
 *  **Le opzioni di base sono qui** (`MARKED_OPTIONS`), per tutte e due: una
 *  riga singola va a capo. Fino al 24/09/2026 le metteva solo l'officina, e in
 *  casa una lista scritta a righe singole si fondeva in un paragrafo — la
 *  stessa risposta letta in due modi (la finestra flottante, con Markwon, sta
 *  con l'officina). Quel che resta dell'officina — highlight.js e la riga
 *  «Copia» sui blocchi di codice — lo aggiunge il suo `initMarked`.
 */

import { escapeHtml } from './utils.js';

export const MARKED_OPTIONS = Object.freeze({ gfm: true, breaks: true });

/** Cosa il sanificatore toglie **oltre** ai suoi default.
 *
 *  La configurazione di base di DOMPurify lascia passare i controlli di un
 *  modulo — `<form>`, `<input>`, `<button>`, `<textarea>`, `<select>` — e la CSP
 *  della shell non ha `form-action`: un `<form action="https://…">` scritto nel
 *  testo di una risposta diventava un modulo vero, che mandava fuori quel che
 *  l'utente ci digitava dentro. Nessun contenuto legittimo di una risposta o di
 *  una pagina ha bisogno di un campo o di un bottone; i due che servivano li
 *  genera il client **dopo** la sanificazione o senza HTML: la casella di una
 *  lista di cose da fare (v. `configureOnce`) e il «Copia» dei blocchi di
 *  codice dell'officina (`restoreCopyButtons` in `mobile-chat.js`).
 *
 *  Vale anche per il lettore delle pagine del quaderno, che sanifica l'HTML del
 *  server con la stessa regola.
 */
export const SANITIZE_CONFIG = Object.freeze({
  FORBID_TAGS: ['form', 'input', 'button', 'textarea', 'select', 'area', 'map'],
  SANITIZE_NAMED_PROPS: true,
});
/*  Le altre tre righe, del 26/09/2026:
 *
 *  - **`SANITIZE_NAMED_PROPS`**: DOMPurify di serie conserva `id` e `name`. Una
 *    risposta con `<span id="oc-confirm-ok">` metteva nel documento un secondo
 *    elemento con l'id del «Conferma» vero, e `getElementById` trovava quello
 *    della risposta: il dialogo restava muto. Non e' XSS, e' *clobbering*. Con
 *    l'opzione ogni `id`/`name` del contenuto esce prefissato `user-content-`,
 *    quindi non coincide piu' con nessun id del guscio. Le ancore interne (i
 *    titoli delle pagine, che il `toc` del server numera) restano raggiungibili:
 *    chi scorre a un `#id` lo cerca con `findContentAnchor`
 *    (`shared/content-link.js`), che conosce il prefisso.
 *  - **`area`, `map`**: un `<area href>` dentro una `<map>` e' un link che non e'
 *    un `<a>`, e le chat intercettano i tocchi con `closest('a[href]')`: il tocco
 *    navigava il frame principale verso un documento del guscio, senza `#bs=`,
 *    e la SPA si de-autenticava. Nessuna risposta ha bisogno di una mappa.
 *  - la terza non e' un'opzione ma un hook (`installHooks`): un `<a>` dentro un
 *    `<svg>` porta il suo `href`/`xlink:href`, e ha lo stesso effetto dell'area.
 *    Il link resta testo; il disegno resta. Lo stesso hook riallinea al
 *    prefisso i riferimenti interni del disegno (v. `svgHref`). */

const SVG_NS = 'http://www.w3.org/2000/svg';
let hooked = false;

/* **Un disegno si riferisce a se stesso per id.** Un gradiente, una freccia in
   fondo a una linea, una maschera: `fill="url(#g)"`, `marker-end="url(#a)"`,
   un `<linearGradient href="#base">` che eredita da un altro. Il prefisso di
   `SANITIZE_NAMED_PROPS` rinomina `id="g"` in `id="user-content-g"`, e i
   riferimenti restavano a `#g`: il gradiente spariva, la freccia pure. Si
   prefissano anche loro, e solo quelli a un `#…` di questo documento — un
   `url(https://…)` non e' un riferimento interno e resta com'e'.

   Il prefisso e' lo stesso di `SANITIZED_ID_PREFIX` in `shared/content-link.js`
   (fisso nella libreria); qui e' ripetuto per non legare questo modulo a un
   altro: diversi banchi lo caricano da solo. */
const ID_PREFIX = 'user-content-';
const URL_REF_ATTRS = new Set([
  'fill', 'stroke', 'marker-start', 'marker-mid', 'marker-end', 'clip-path', 'mask', 'filter', 'style',
]);
const LOCAL_URL_REF = /url\(\s*(['"]?)#([^'")\s]+)\1\s*\)/g;
/* Le immagini di un disegno: un `data:image/…` o un indirizzo di questo
   stesso gateway, senza schema e senza `//` (un'altra origine, che la CSP
   rifiuterebbe comunque). Un'immagine si guarda e basta: non naviga. */
const SAFE_IMAGE_HREF = /^(?:data:image\/|(?![a-z][a-z0-9+.-]*:|\/\/))/i;

function prefixedId(id) {
  return id.startsWith(ID_PREFIX) ? id : ID_PREFIX + id;
}

/* Il valore che un `href` di un nodo SVG conserva, o `null` se se ne va. */
function svgHref(node, value) {
  const v = String(value ?? '').trim();
  // Un `<a>` in un disegno e' un link che non passa da `a[href]`: via sempre.
  if (node.localName === 'a' || !v) return null;
  if (v.startsWith('#')) return `#${prefixedId(v.slice(1))}`;
  if ((node.localName === 'image' || node.localName === 'feImage') && SAFE_IMAGE_HREF.test(v)) return v;
  return null;
}

/* Una volta per libreria: gli hook di DOMPurify sono globali alla sua istanza,
   quindi valgono anche per il lettore delle pagine che sanifica da se' con
   `SANITIZE_CONFIG`. Si prova gia' al caricamento del modulo (le librerie sono
   `defer`, e un `type="module"` gira dopo di loro), e di nuovo a ogni resa per
   chi l'avesse caricata piu' tardi. */
function installHooks() {
  if (hooked || typeof DOMPurify === 'undefined' || typeof DOMPurify.addHook !== 'function') return;
  DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
    if (node.namespaceURI !== SVG_NS) return;
    if (data.attrName === 'href' || data.attrName === 'xlink:href') {
      const kept = svgHref(node, data.attrValue);
      if (kept === null) data.keepAttr = false;
      else data.attrValue = kept;
    } else if (URL_REF_ATTRS.has(data.attrName) && typeof data.attrValue === 'string') {
      data.attrValue = data.attrValue.replace(
        LOCAL_URL_REF, (_, q, id) => `url(${q}#${prefixedId(id)}${q})`,
      );
    }
  });
  hooked = true;
}

installHooks();

/** L'HTML di un contenuto non fidato, sanificato con la regola di questo file.
 *  Per chi ha gia' l'HTML (il lettore delle pagine) e non il markdown. */
export function sanitizeContent(html) {
  installHooks();
  return DOMPurify.sanitize(html || '', SANITIZE_CONFIG);
}

let configured = false;

/* Una volta, alla prima resa con la libreria caricata. `setOptions` fonde con
   quel che c'e': un renderer messo prima (quello dell'officina) resta.

   La casella di una lista di cose da fare (`- [ ] latte`) marked la scrive come
   `<input type="checkbox" disabled>`, cioe' un tag che `SANITIZE_CONFIG` toglie:
   la si scrive come segno invece che come campo, cosi' la lista resta leggibile.
   `use` e non `setOptions`: aggiunge un metodo al renderer che c'e', senza
   rimpiazzarlo. */
function configureOnce() {
  if (configured) return;
  marked.setOptions({ ...MARKED_OPTIONS });
  if (typeof marked.use === 'function') {
    marked.use({ renderer: { checkbox: ({ checked }) => (checked ? '\u2611' : '\u2610') } });
  }
  configured = true;
}

export function renderMarkdown(text) {
  if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') {
    return escapeHtml(text);
  }
  try {
    // Dentro il ``try``: anche una configurazione che fallisce ripiega sul
    // testo neutralizzato, invece di lasciar salire l'errore a chi disegna.
    configureOnce();
    return sanitizeContent(marked.parse(text));
  } catch (e) {
    console.error('Markdown parse error:', e);
    return escapeHtml(text);
  }
}
