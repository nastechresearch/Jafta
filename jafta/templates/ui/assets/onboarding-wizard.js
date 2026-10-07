/** Il wizard del primo avvio, in quattro passi.
 *
 *  Vive in un documento suo, `onboarding.html`, ospitato da `onboarding-app.js`:
 *  non appartiene ne' alla casa ne' all'officina. Era un «modo» dell'officina, e
 *  quando la casa e' diventata il documento di partenza nessuno ci arrivava piu',
 *  perche' il controllo del primo avvio stava solo nell'officina. Dall'host
 *  vuole soltanto `window.mobileApp.whenShellReady`. */

import { api } from './shared/api-client.js';
import { escapeHtml, showToast } from './shared/utils.js';
import { i18n } from './shared/i18n.js';
import { runImportFlow } from './shared/backup-flow.js';
import { TelegramPairingWidget } from './shared/telegram-pairing.js';
import { BatteryExemptionCard } from './shared/battery-exemption.js';
import { getProviderBrand } from './shared/provider-brand.js';
// Con l'autocorrezione accesa «http://» diventava «Http:/» e partiva cosi'.
import { NO_AUTOCORRECT, normalizeApiBase } from './shared/api-base.js';

/* ── Mini Jafta sul footer ──
   Decorativa, fuori da #onboarding-content (che viene ri-renderizzato a ogni
   step): cade dall'alto, atterra stordita, poi saluta. Stessi asset e stessa
   logica a frame discreti della mascotte di mobile-jafta.js. */
const JAFTA_POSES = {
  fall: '/html-mobile/assets/jafta-fall.webp',
  ground: '/html-mobile/assets/jafta-ground.webp',
  hello1: '/html-mobile/assets/jafta-hello1.webp',
  hello2: '/html-mobile/assets/jafta-hello2.webp',
  idle: '/html-mobile/assets/jafta-idle.webp',
};
const GROUND_HOLD_MS = 800; // stordita a terra prima di rialzarsi
const WAVE_FRAME_MS = 450; // alternanza hello1/hello2
const WAVE_CYCLES = 3; // cicli di saluto all'ingresso
const WAVE_REST_MS = 300; // braccio alzato un attimo prima dell'idle
const REWAVE_EVERY_MS = 5000; // ogni tanto risaluta
const REWAVE_CYCLES = 2;

/* Base URL di default per formato: mostrata come placeholder nello step 1 e
   usata davvero quando il campo resta vuoto (fetch modelli e salvataggio). */
const DEFAULT_API_BASE = {
  'openai_compat': 'https://api.openai.com/v1',
  'anthropic': 'https://api.anthropic.com',
};

/* Il suffisso delle chiavi i18n dei segnaposto dello step 1, per formato: il
   nome e la chiave d'esempio erano quelli di Claude anche scegliendo OpenAI. */
const PLACEHOLDER_SUFFIX = {
  'openai_compat': 'Openai',
  'anthropic': 'Anthropic',
};


export class OnboardingController {
  constructor() {
    this.contentEl = document.getElementById('onboarding-content');
    this.step = 0;
    this.format = null;
    this.providerName = '';
    this.apiKey = '';
    this.apiBase = '';
    this.model = '';
    this.botName = 'Jafta';
    this.models = [];
    // Formato, chiave e indirizzo con cui e' stata chiesta la lista dello step
    // 2: se al ritorno sono cambiati, il modello scelto era di un altro
    // provider e non vale piu'.
    this._modelsFor = null;
    this._showCustomModel = false;
    this.saving = false;
    // Token della fetch modelli: la risposta che torna dopo un cambio di step
    // scriverebbe nel form nuovo (o riaprirebbe il campo custom su uno step che
    // non ce l'ha). Monotono, si invalida uscendo dallo step 2.
    this._modelsToken = 0;
    this.jaftaEl = null;
    this.jaftaImg = null;
    this._jaftaTimers = [];
  }

  activate() {
    this.render();
    // La caduta deve partire a loading nativo sparito: se scatta durante il
    // boot (WebView ancora nascosto), scorre invisibile e se ne vede solo la
    // coda. whenShellReady la posticipa al momento giusto (o subito nel browser).
    window.mobileApp.whenShellReady(() => this._startJafta());
  }

  /* Tasto Indietro hardware: risale di uno step, esattamente come il pulsante
     "Indietro" del wizard. Consuma *sempre* la pressione — dall'onboarding non
     si esce col back (step 0 non ha un prima, e dallo step 3 la config è già
     salvata: tornare indietro riaprirebbe un form che non ha più effetto).

     C'era un'eccezione — il wizard riaperto da Impostazioni, che allo step 0
     doveva poter *uscire* — e se n'è andata il 21/09/2026 col resto di quella
     strada: «Riesegui configurazione» era uscito il 20/09 per una ragione
     misurata (`save_onboarding` **sostituisce** l'elenco dei provider invece di
     aggiungere, quindi rifare il giro cancellava le marche già messe), ma la
     porta per rientrarci era rimasta lì senza maniglia da nessuno dei due lati.
     Adesso l'unico modo di essere qui è il primo avvio, e dal primo avvio non
     si esce. */
  handleBack() {
    // Salvataggio in volo: la config sta già partendo verso il gateway e lo
    // step successivo è deciso. Rimettere a schermo il form precedente
    // mostrerebbe campi che non hanno più effetto, e la continuazione di
    // `_save()` ci scriverebbe sopra lo step 3 un istante dopo. La pressione si
    // consuma e non produce niente: è l'unico caso in cui va bene, perché a
    // schermo c'è già l'overlay di caricamento.
    if (this.saving) return true;
    if (this.step === 1) this._goToStep0();
    else if (this.step === 2) this._goBackToStep1();
    return true;
  }

  deactivate() {
    // Una fetch modelli in volo non deve più scrivere niente: al rientro il
    // wizard riparte dallo step in cui era, e il form è stato ri-renderizzato.
    this._modelsToken++;
    this._stopJafta();
    if (this._tgWidget) {
      this._tgWidget.destroy();
      this._tgWidget = null;
    }
  }

  render() {
    if (!this.contentEl) return;
    switch (this.step) {
      case 0: this._renderStep0(); break;
      case 1: this._renderStep1(); break;
      case 2: this._renderStepRuntime(); break;
      case 3: this._renderStep2(); break;
      case 4: this._renderStep3(); break;
    }
  }

  _progress() {
    const dots = [];
    for (let i = 0; i < 5; i++) {
      const cls = i < this.step ? 'onboarding-dot done' : i === this.step ? 'onboarding-dot active' : 'onboarding-dot';
      dots.push(`<div class="${cls}"></div>`);
    }
    return `<div class="onboarding-progress">${dots.join('')}</div>`;
  }

  // ── Step 0: Format ──────────────────────────────────────────────────

  _renderStep0() {
    this.contentEl.innerHTML = `
      <div class="onboarding-step onboarding-center">
        <h2 class="onboarding-heading">${i18n.t('onboarding.selectFormat')}</h2>
        <p class="onboarding-desc">${i18n.t('onboarding.selectFormatDesc')}</p>
        ${this._progress()}
        <div class="format-cards">
          <button class="format-card${this.format === 'openai_compat' ? ' selected' : ''}" data-format="openai_compat">
            <i class="ti ti-brand-openai" aria-hidden="true"></i>
            <span class="format-label">${i18n.t('onboarding.openaiCompat')}</span>
            <span class="format-hint">${i18n.t('onboarding.openaiCompatHint')}</span>
          </button>
          <button class="format-card${this.format === 'anthropic' ? ' selected' : ''}" data-format="anthropic">
            ${getProviderBrand('anthropic').logo}
            <span class="format-label">${i18n.t('onboarding.anthropicCompat')}</span>
            <span class="format-hint">${i18n.t('onboarding.anthropicCompatHint')}</span>
          </button>
        </div>
        <div class="onboarding-nav onboarding-nav-center">
          <button id="btn-next-0" class="onboarding-btn onboarding-btn-primary onboarding-btn-lg" ${this.format ? '' : 'disabled'}>${i18n.t('onboarding.next')}</button>
        </div>
        <button id="btn-restore-backup" class="onboarding-btn" style="margin-top:18px;opacity:.85">
          <i class="ti ti-file-import" aria-hidden="true"></i> ${i18n.t('onboarding.restoreFromBackup')}
        </button>
        <p class="onboarding-desc" style="font-size:11px;margin-top:6px">${i18n.t('onboarding.restoreFromBackupHint')}</p>
      </div>`;

    this.contentEl.querySelectorAll('.format-card').forEach(card => {
      card.addEventListener('click', () => this._selectFormat(card.dataset.format));
    });
    this.contentEl.querySelector('#btn-next-0').addEventListener('click', () => this._goToStep1());
    // Ripristino da backup: al riavvio post-restore la config importata ha già
    // i provider, quindi first_run è false e il guscio nativo riparte dalla
    // casa (`?mode=chat`). Qui non c'è niente da ripulire: nessun marcatore,
    // nessun dock da riaccendere — il riavvio lo fa `runImportFlow`.
    this.contentEl.querySelector('#btn-restore-backup').addEventListener('click', () => {
      runImportFlow();
    });
  }

  _selectFormat(format) {
    if (format !== this.format) this.model = '';
    this.format = format;
    this.contentEl.querySelectorAll('.format-card').forEach(c => c.classList.remove('selected'));
    this.contentEl.querySelector(`[data-format="${format}"]`).classList.add('selected');
    this.contentEl.querySelector('#btn-next-0').disabled = false;
  }

  _goToStep1() {
    if (!this.format) return;
    this.step = 1;
    this.render();
  }

  // ── Step 1: Credentials ─────────────────────────────────────────────

  _renderStep1() {
    const defaults = DEFAULT_API_BASE;
    const suffix = PLACEHOLDER_SUFFIX[this.format] || 'Openai';
    // Nasce acceso se nome e chiave ci sono gia' (ritorno da Indietro): prima
    // era spento fisso, e si riaccendeva solo scrivendo in un campo.
    const canContinue = this.providerName && this.apiKey;

    this.contentEl.innerHTML = `
      <div class="onboarding-step onboarding-center">
        <h2 class="onboarding-heading">${i18n.t('onboarding.connectProvider')}</h2>
        ${this._progress()}
        <div class="onboarding-field">
          <label class="onboarding-label" for="provider-name">${i18n.t('onboarding.providerName')}</label>
          <input type="text" class="onboarding-input" id="provider-name" ${NO_AUTOCORRECT}
                 placeholder="${i18n.t(`onboarding.providerNamePlaceholder${suffix}`)}" value="${escapeHtml(this.providerName)}">
          <span class="onboarding-hint">${i18n.t('onboarding.providerNameHint')}</span>
        </div>
        <div class="onboarding-field">
          <label class="onboarding-label" for="api-key">${i18n.t('onboarding.apiKey')}</label>
          <input type="password" class="onboarding-input" id="api-key" ${NO_AUTOCORRECT} data-lpignore="true"
                 placeholder="${i18n.t(`onboarding.apiKeyPlaceholder${suffix}`)}" value="${escapeHtml(this.apiKey)}">
        </div>
        <div class="onboarding-field">
          <label class="onboarding-label" for="api-base">${i18n.t('onboarding.baseUrl')}</label>
          <input type="url" inputmode="url" class="onboarding-input" id="api-base" ${NO_AUTOCORRECT}
                 placeholder="${escapeHtml(defaults[this.format] || '')}" value="${escapeHtml(this.apiBase)}">
          <span class="onboarding-hint">${i18n.t('onboarding.baseUrlHint')}</span>
        </div>
        <div class="onboarding-nav">
          <button class="onboarding-btn onboarding-btn-secondary" id="btn-back-1">${i18n.t('onboarding.back')}</button>
          <button class="onboarding-btn onboarding-btn-primary" id="btn-next-1" ${canContinue ? '' : 'disabled'}>${i18n.t('onboarding.next')}</button>
        </div>
      </div>`;

    ['provider-name', 'api-key', 'api-base'].forEach(id => {
      const el = this.contentEl.querySelector(`#${id}`);
      if (el) el.addEventListener('input', () => this._validateStep1());
    });
    this.contentEl.querySelector('#btn-back-1').addEventListener('click', () => this._goToStep0());
    this.contentEl.querySelector('#btn-next-1').addEventListener('click', () => this._goToStep2());
  }

  _validateStep1() {
    const name = this.contentEl.querySelector('#provider-name').value.trim();
    const key = this.contentEl.querySelector('#api-key').value.trim();
    this.contentEl.querySelector('#btn-next-1').disabled = !(name.length > 0 && key.length > 0);
  }

  /** Travasa i campi dello step 1 nello stato prima che il DOM che li contiene
   *  venga rimpiazzato. `_renderStep1` li ridisegna dai valori dello stato,
   *  quindi ciò che non è catturato qui è semplicemente perso. */
  _captureStep1() {
    const name = this.contentEl?.querySelector('#provider-name');
    const key = this.contentEl?.querySelector('#api-key');
    const base = this.contentEl?.querySelector('#api-base');
    if (name) this.providerName = name.value.trim();
    if (key) this.apiKey = key.value.trim();
    if (base) this.apiBase = base.value.trim();
  }

  /** L'impronta del provider per cui si chiede la lista dei modelli. */
  _modelsFingerprint() {
    return `${this.format}|${this.apiKey}|${this.apiBase}`;
  }

  /* Cattura i campi come fa il gemello `_goBackToStep1`. Prima non li
     catturava: tornare allo step 0 — col pulsante "Indietro" o col tasto
     hardware — cancellava nome provider, chiave API e base URL appena
     digitati, e la chiave è la cosa più scomoda da riscrivere. */
  _goToStep0() {
    this._captureStep1();
    this._modelsToken++;
    this.step = 0;
    this.render();
  }

  _goToStep2() {
    this._captureStep1();
    this.step = 2;
    this.render();
  }

  // ── Step 2: Runtime ─────────────────────────────────────────────────

  async _renderStepRuntime() {
    const r = (await api.getRuntimeStatus()) || { status: 'absent' };
    const status = r.status || 'absent';
    const progress = Math.max(0, Math.min(100, Math.round(Number(r.progress) || 0)));
    const abiOk = r.abi_supported !== false;

    const statusNoteKey = {
      absent: 'onboarding.runtime.statusAbsent',
      downloading: 'onboarding.runtime.statusDownloading',
      extracting: 'onboarding.runtime.statusExtracting',
      activating: 'onboarding.runtime.statusActivating',
      starting: 'onboarding.runtime.statusStarting',
      ready: 'onboarding.runtime.statusReady',
      error: 'onboarding.runtime.statusError',
      unsupported: 'onboarding.runtime.statusUnsupported',
      prompt: 'onboarding.runtime.statusPrompt',
    }[r.status] || 'onboarding.runtime.statusAbsent';

    const installing = ['downloading','extracting','activating','starting'].includes(r.status);
    const terminal = ['ready','error','unsupported','prompt'].includes(r.status);

    this.contentEl.innerHTML = `
      <div class="onboarding-step onboarding-center">
        <h2 class="onboarding-heading">${i18n.t('onboarding.runtime.title')}</h2>
        <p class="onboarding-desc">${i18n.t('onboarding.runtime.desc')}</p>
        ${this._progress()}

        <div class="runtime-onboarding-panel" data-status="${r.status}" aria-live="polite" aria-atomic="true">
          <div class="runtime-header">
            <h3>${i18n.t('onboarding.runtime.title')}</h3>
            <span class="runtime-phase-badge">${i18n.t(phaseNoteKey)} ${['ready','error','unsupported','prompt'].includes(r.status) ? '' : Math.max(0, Math.min(100, Math.round(Number(r.progress) || 0))) + '%'}</span>
          </div>

          <div class="runtime-progress-wrap" role="progressbar" aria-valuenow="${Math.max(0, Math.min(100, Math.round(Number(r.progress) || 0)))}" aria-valuemin="0" aria-valuemax="100" aria-label="${i18n.t('settings.runtime.status')}">
            <div class="runtime-progress-bar" style="width:${Math.max(0, Math.min(100, Math.round(Number(r.progress) || 0)))}%"></div>
          </div>

          <div class="runtime-actions" style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">
            ${['absent','error','unsupported'].includes(r.status)
              ? `<button class="onboarding-btn onboarding-btn-primary" id="btn-runtime-install" ${!abiOk ? 'disabled' : ''} aria-disabled="${!abiOk}"><i class="ti ti-download" aria-hidden="true"></i> ${i18n.t('onboarding.runtime.install')}</button>`
              : ''}
            ${!['absent','ready','error','unsupported','prompt'].includes(r.status)
              ? `<button class="onboarding-btn onboarding-btn-secondary" id="btn-runtime-stop" aria-busy="${['downloading','extracting','activating','starting'].includes(r.status)}"><i class="ti ti-stop" aria-hidden="true"></i> ${i18n.t('onboarding.runtime.stop')}</button>`
              : ''}
            ${r.status === 'ready'
              ? `<button class="onboarding-btn onboarding-btn-secondary" id="btn-runtime-diag"><i class="ti ti-activity-heartbeat" aria-hidden="true"></i> ${i18n.t('onboarding.runtime.diagnostics')}</button>`
              : ''}
            ${!['absent','unsupported'].includes(r.status)
              ? `<button class="onboarding-btn onboarding-btn-danger" id="btn-runtime-delete"><i class="ti ti-trash" aria-hidden="true"></i> ${i18n.t('onboarding.runtime.delete')}</button>`
              : ''}
          </div>

          ${!abiOk
            ? `<p class="runtime-abi-warning" style="margin-top:12px;padding:8px;background:var(--error);color:var(--on-error);border-radius:var(--radius);font-size:13px"><i class="ti ti-alert-triangle" aria-hidden="true"></i> ${i18n.t('onboarding.runtime.noAbi')}</p>`
            : ''}

          <p class="onboarding-hint" style="margin-top:12px;font-size:12px;color:var(--text-faint)">${i18n.t('onboarding.runtime.installHint')}</p>
        </div>

        <div class="onboarding-nav">
          <button class="onboarding-btn onboarding-btn-secondary" id="btn-back-runtime">${i18n.t('onboarding.back')}</button>
          <button class="onboarding-btn onboarding-btn-primary" id="btn-next-runtime" ${['ready','error','unsupported'].includes(r.status) ? '' : 'disabled'}>${i18n.t('onboarding.next')}</button>
        </div>
      </div>`;

    this.contentEl.querySelector('#btn-back-runtime').addEventListener('click', () => this._goToStep1());
    this.contentEl.querySelector('#btn-next-runtime').addEventListener('click', () => this._goToStep3());

    if (this.contentEl.querySelector('#btn-runtime-install')) {
      this.contentEl.querySelector('#btn-runtime-install').addEventListener('click', async () => {
        await api.postRuntimeInstall();
        showToast(i18n.t('onboarding.runtime.installing'), 'info');
        this._pollRuntimeStatus();
      });
    }
    if (this.contentEl.querySelector('#btn-runtime-stop')) {
      this.contentEl.querySelector('#btn-runtime-stop').addEventListener('click', async () => {
        await api.postRuntimeStop();
        showToast(i18n.t('onboarding.runtime.stopping'), 'info');
        this._pollRuntimeStatus();
      });
    }
    if (this.contentEl.querySelector('#btn-runtime-delete')) {
      this.contentEl.querySelector('#btn-runtime-delete').addEventListener('click', async () => {
        if (!confirm(i18n.t('onboarding.runtime.deleteConfirm'))) return;
        await api.postRuntimeDelete();
        showToast(i18n.t('onboarding.runtime.deleting'), 'info');
        this._pollRuntimeStatus();
      });
    }
    if (this.contentEl.querySelector('#btn-runtime-diag')) {
      this.contentEl.querySelector('#btn-runtime-diag').addEventListener('click', async () => {
        const diag = await api.getRuntimeDiagnostics();
        // Show diag in a modal or toast
        showToast(JSON.stringify(diag), 'info');
      });
    }
  }

  _pollRuntimeStatus() {
    const poll = async () => {
      const r = await api.getRuntimeStatus();
      if (['ready','error','unsupported','prompt'].includes(r.status)) {
        this._renderStepRuntime();
        return;
      }
      // Update progress bar live
      const bar = this.contentEl.querySelector('.runtime-progress-bar');
      const badge = this.contentEl.querySelector('.runtime-phase-badge');
      if (bar) bar.style.width = Math.max(0, Math.min(100, Math.round(Number(r.progress) || 0))) + '%';
      if (badge) {
        const noteKey = {
          absent: 'onboarding.runtime.statusAbsent',
          downloading: 'onboarding.runtime.statusDownloading',
          extracting: 'onboarding.runtime.statusExtracting',
          activating: 'onboarding.runtime.statusActivating',
          starting: 'onboarding.runtime.statusStarting',
          ready: 'onboarding.runtime.statusReady',
          error: 'onboarding.runtime.statusError',
          unsupported: 'onboarding.runtime.statusUnsupported',
          prompt: 'onboarding.runtime.statusPrompt',
        }[r.status] || 'onboarding.runtime.statusAbsent';
        badge.textContent = `${i18n.t(noteKey)} ${Math.max(0, Math.min(100, Math.round(Number(r.progress) || 0)))}%`;
      }
      if (!['ready','error','unsupported','prompt'].includes(r.status)) {
        setTimeout(poll, 3000);
      }
    };
    poll();
  }

  _goToStep3() {
    this.step = 3;
    this.render();
  }

  // ── Step 3: Model + Launch ──────────────────────────────────────────

  async _loadModels() {
    // La fetch dura secondi: nel frattempo l'utente può essere tornato allo
    // step 1 (o allo 0, o uscito dalla sezione). Senza token la risposta in
    // ritardo scriveva nel DOM dello step nuovo — o, dal ramo d'errore,
    // riapriva il campo "modello personalizzato" su un form che non ce l'ha.
    const token = ++this._modelsToken;
    // Il fallback custom si rivaluta a ogni fetch: se la lista arriva, sparisce.
    this._showCustomModel = false;
    this._renderStep2();
    const listEl = this.contentEl.querySelector('#model-list');
    listEl.innerHTML = `<div class="onboarding-hint" style="padding:12px">${i18n.t('onboarding.loadingModels')}</div>`;

    try {
      const apiBase = this.apiBase || DEFAULT_API_BASE[this.format] || '';
      const resp = await api.getProviderModels(this.providerName || this.format, this.apiKey, apiBase, this.format);
      if (token !== this._modelsToken) return;
      this.models = (resp.models || []).map(m => m.id || m);
      // Il backend risponde 200 anche quando la lista è vuota (credenziale
      // rifiutata, errore di rete, base URL mancante, ...) e spiega il perché in
      // `message`: senza propagarlo l'utente vedrebbe solo "nessun modello".
      this._modelsMessage = resp.models && resp.models.length ? '' : (resp.message || '');
      this._renderModelList();
    } catch (e) {
      if (token !== this._modelsToken) return;
      const detail = e && e.message ? `: ${escapeHtml(e.message)}` : '';
      listEl.innerHTML = `<div class="onboarding-hint" style="padding:12px">${i18n.t('onboarding.couldNotFetch')}${detail}</div>`;
      this._showCustomModelField();
    }
  }

  _renderStep2() {
    const modelListId = 'model-list-' + Date.now();
    this.contentEl.innerHTML = `
      <div class="onboarding-step onboarding-center">
        <h2 class="onboarding-heading">${i18n.t('onboarding.selectModel')}</h2>
        ${this._progress()}
        <div class="onboarding-field">
          <label class="onboarding-label" for="model-search">${i18n.t('onboarding.searchModels')}</label>
          <input type="text" class="onboarding-input" id="model-search" placeholder="${i18n.t('onboarding.searchModelsPlaceholder')}"
                 autocomplete="off">
        </div>
        <div class="onboarding-model-list" id="model-list">
          <div class="onboarding-hint" style="padding:12px">${i18n.t('onboarding.loadingModels')}</div>
        </div>
        <div class="onboarding-selected-model" id="selected-model-display" style="${this.model ? '' : 'display:none'}">
          <span class="onboarding-selected-label">${i18n.t('onboarding.selected')}:</span>
          <strong>${escapeHtml(this.model || '')}</strong>
        </div>
        <div class="onboarding-field" id="custom-model-field" style="${this._showCustomModel ? '' : 'display:none'}">
          <label class="onboarding-label" for="custom-model">${i18n.t('onboarding.orCustomModel')}</label>
          <input type="text" class="onboarding-input" id="custom-model" placeholder="${i18n.t('onboarding.customModelPlaceholder')}"
                 value="${escapeHtml(this.model)}">
        </div>
        <div class="onboarding-field">
          <label class="onboarding-label" for="bot-name">${i18n.t('onboarding.botName')}</label>
          <input type="text" class="onboarding-input" id="bot-name" value="${escapeHtml(this.botName)}">
        </div>
        <div class="onboarding-summary" id="summary-display" style="display:none"></div>
        <div class="onboarding-nav">
          <button class="onboarding-btn onboarding-btn-secondary" id="btn-back-2">${i18n.t('onboarding.back')}</button>
          <button class="onboarding-btn onboarding-btn-primary" id="btn-launch" ${this.model ? '' : 'disabled'}>${i18n.t('onboarding.launch')}</button>
        </div>
      </div>`;

    const searchInput = this.contentEl.querySelector('#model-search');
    const listEl = this.contentEl.querySelector('#model-list');
    const customInput = this.contentEl.querySelector('#custom-model');
    const nameInput = this.contentEl.querySelector('#bot-name');

    if (searchInput) {
      searchInput.addEventListener('input', () => this._filterModels());
    }
    if (customInput) {
      customInput.addEventListener('input', () => {
        this.model = customInput.value.trim();
        this.contentEl.querySelectorAll('.onboarding-model-item').forEach(el => el.classList.remove('selected'));
        this._updateSelectedDisplay();
        this._validateLaunch();
      });
    }
    if (nameInput) {
      nameInput.addEventListener('input', () => { this.botName = nameInput.value; });
    }
    this.contentEl.querySelector('#btn-back-2').addEventListener('click', () => this._goBackToStep1());
    this.contentEl.querySelector('#btn-launch').addEventListener('click', () => this._save());
  }

  _renderModelList() {
    const listEl = this.contentEl.querySelector('#model-list');
    if (!listEl) return;
    if (!this.models.length) {
      const hint = this._modelsMessage
        ? escapeHtml(this._modelsMessage)
        : i18n.t('onboarding.noModels');
      listEl.innerHTML = `<div class="onboarding-hint" style="padding:12px">${hint}</div>`;
      this._showCustomModelField();
      return;
    }
    listEl.innerHTML = this.models.map(m => `
      <div class="onboarding-model-item${this.model === m ? ' selected' : ''}" data-model="${escapeHtml(m)}">
        ${escapeHtml(m)}
      </div>
    `).join('');

    listEl.querySelectorAll('.onboarding-model-item').forEach(item => {
      item.addEventListener('click', () => {
        this.model = item.dataset.model;
        this.contentEl.querySelector('#custom-model').value = '';
        listEl.querySelectorAll('.onboarding-model-item').forEach(el => el.classList.remove('selected'));
        item.classList.add('selected');
        this._updateSelectedDisplay();
        this._validateLaunch();
      });
    });

    // Watchdog: su viewport bassi (Titan 2) il flex può collassare la lista a
    // ~2px pur avendola renderizzata — nessun errore JS, modelli invisibili.
    // Se succede ancora, auto-ripara inline e segnala al gateway.
    requestAnimationFrame(() => {
      if (!this.models.length || !listEl.isConnected) return;
      const h = listEl.getBoundingClientRect().height;
      if (h >= 24) return;
      listEl.style.flexShrink = '0';
      listEl.style.minHeight = '120px';
      api.clientLog(
        'warning',
        'onboarding-model-list',
        `list collapsed to ${Math.round(h)}px with ${this.models.length} models `
          + `(viewport ${window.innerWidth}x${window.innerHeight}); self-healed inline`,
      );
    });
  }

  _filterModels() {
    const query = this.contentEl.querySelector('#model-search').value.toLowerCase();
    this.contentEl.querySelectorAll('.onboarding-model-item').forEach(el => {
      el.style.display = el.dataset.model.toLowerCase().includes(query) ? '' : 'none';
    });
  }

  _updateSelectedDisplay() {
    const display = this.contentEl.querySelector('#selected-model-display');
    if (!display) return;
    if (this.model) {
      display.style.display = '';
      display.querySelector('strong').textContent = this.model;
    } else {
      display.style.display = 'none';
    }
  }

  _validateLaunch() {
    const btn = this.contentEl.querySelector('#btn-launch');
    if (btn) btn.disabled = !this.model;
  }

  /* Il campo custom è il fallback: appare solo se la lista modelli non
     arriva (endpoint /models assente o fetch fallito). */
  _showCustomModelField() {
    this._showCustomModel = true;
    const field = this.contentEl.querySelector('#custom-model-field');
    if (field) field.style.display = '';
  }

  _goBackToStep1() {
    const nameEl = this.contentEl?.querySelector('#bot-name');
    if (nameEl) this.botName = nameEl.value.trim() || 'Jafta';
    this._modelsToken++;
    this.step = 1;
    this.render();
  }

  // ── Save ────────────────────────────────────────────────────────────

  async _save() {
    if (this.saving) return;
    this.saving = true;

    this.botName = this.contentEl.querySelector('#bot-name').value.trim() || 'Jafta';
    const model = this.model;
    if (!model) {
      showToast(i18n.t('onboarding.selectOrEnterModel'), 'error');
      this.saving = false;
      return;
    }

    this._showLoadingOverlay();
    try {
      const result = await api.saveOnboarding({
        provider_name: this.providerName,
        format: this.format,
        api_key: this.apiKey,
        api_base: this.apiBase,
        model,
        bot_name: this.botName,
        locale: i18n.locale,
      });
      // Config salvata e agente in avvio: lo step Telegram è opzionale e
      // saltabile, il completamento vero avviene in _complete().
      this._hideLoadingOverlay();
      this.saving = false;
      this.step = 3;
      this.render();
    } catch (err) {
      this._hideLoadingOverlay();
      showToast(err.message || i18n.t('onboarding.failedToSave'), 'error');
      this.saving = false;
    }
  }

  // ── Step 3: Telegram (opzionale) ────────────────────────────────────

  _renderStep3() {
    this.contentEl.innerHTML = `
      <div class="onboarding-step onboarding-center">
        <h2 class="onboarding-heading">${i18n.t('onboarding.telegram.title')}</h2>
        <p class="onboarding-desc">${i18n.t('onboarding.telegram.desc')}</p>
        ${this._progress()}
        <div id="tg-pairing-widget"></div>
        <div id="battery-exempt-card" style="margin-top:18px"></div>
        <button id="btn-skip-telegram" class="onboarding-btn" style="margin-top:18px;opacity:.85">
          ${i18n.t('onboarding.telegram.skip')}
        </button>
      </div>`;

    if (this._tgWidget) this._tgWidget.destroy();
    this._tgWidget = new TelegramPairingWidget(
      this.contentEl.querySelector('#tg-pairing-widget'),
      {
        mode: 'onboarding',
        onPaired: () => {
          showToast(i18n.t('onboarding.telegram.pairedToast'), 'info');
          const skip = this.contentEl.querySelector('#btn-skip-telegram');
          if (skip) skip.textContent = i18n.t('onboarding.telegram.finish');
        },
      },
    );
    this._tgWidget.refresh();

    /* Esenzione batteria: chiesta qui e non solo dentro la card Telegram,
       perché il doze differisce cron, promemoria e controlli proattivi anche
       a chi salta questo passo. Non è uno step suo — sarebbe un quinto muro
       davanti alla chat — ma un riquadro che si disegna solo su Android e
       solo se l'esenzione manca davvero. */
    if (this._batteryCard) this._batteryCard.destroy();
    this._batteryCard = new BatteryExemptionCard(
      this.contentEl.querySelector('#battery-exempt-card'),
      { tone: 'notice' },
    );
    this._batteryCard.render();

    this.contentEl.querySelector('#btn-skip-telegram')
      .addEventListener('click', () => this._complete());
  }

  _complete() {
    if (this._tgWidget) {
      this._tgWidget.destroy();
      this._tgWidget = null;
    }
    if (this._batteryCard) {
      this._batteryCard.destroy();
      this._batteryCard = null;
    }
    // Alla casa, su Jafta, dove il saluto scritto da `onboarding.save` aspetta.
    // `replace`: Indietro dalla casa non deve riportare a un wizard concluso.
    api.navigate('/html-mobile/', { replace: true });
  }

  _showLoadingOverlay() {
    let overlay = document.getElementById('onboarding-loading-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'onboarding-loading-overlay';
      overlay.className = 'onboarding-loading-overlay';
      overlay.innerHTML = `
        <div class="onboarding-loading-content">
          <div class="onboarding-spinner"></div>
          <h2>${i18n.t('onboarding.configuring')}</h2>
          <p>${i18n.t('onboarding.configuringDesc')}</p>
        </div>`;
      document.body.appendChild(overlay);
    }
    overlay.style.display = 'flex';
  }

  _hideLoadingOverlay() {
    const overlay = document.getElementById('onboarding-loading-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  // ── Mini Jafta ──────────────────────────────────────────────────────

  _startJafta() {
    const view = document.getElementById('view-onboarding');
    if (!view) return;
    this._stopJafta();

    if (!this.jaftaEl) {
      this.jaftaEl = document.createElement('div');
      this.jaftaEl.className = 'onboarding-jafta';
      this.jaftaEl.setAttribute('aria-hidden', 'true');
      this.jaftaImg = document.createElement('img');
      this.jaftaImg.alt = '';
      this.jaftaImg.draggable = false;
      this.jaftaEl.appendChild(this.jaftaImg);
      view.appendChild(this.jaftaEl);
    }

    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.jaftaImg.src = JAFTA_POSES.idle;
      return;
    }

    // Precarica le pose: al primo swap non deve esserci un frame vuoto.
    Object.values(JAFTA_POSES).forEach((src) => { new Image().src = src; });

    // fall (caduta CSS) -> ground (stordita) -> saluto -> idle.
    this.jaftaImg.src = JAFTA_POSES.fall;
    this.jaftaEl.classList.remove('dropping');
    void this.jaftaEl.offsetWidth; // riavvia l'animazione se era già corsa
    this.jaftaEl.classList.add('dropping');
    this._onJaftaLanded = () => {
      this.jaftaImg.src = JAFTA_POSES.ground;
      this._jaftaAfter(GROUND_HOLD_MS, () => {
        this._jaftaWave(WAVE_CYCLES, () => this._jaftaRewaveLoop());
      });
    };
    this.jaftaEl.addEventListener('animationend', this._onJaftaLanded, { once: true });
  }

  _stopJafta() {
    this._jaftaTimers.forEach(clearTimeout);
    this._jaftaTimers = [];
    if (this.jaftaEl && this._onJaftaLanded) {
      this.jaftaEl.removeEventListener('animationend', this._onJaftaLanded);
      this._onJaftaLanded = null;
    }
  }

  _jaftaAfter(ms, fn) {
    this._jaftaTimers.push(setTimeout(fn, ms));
  }

  /* Alterna hello1/hello2 per `cycles` cicli, resta col braccio alzato un
     attimo, poi torna in idle e chiama `done`. */
  _jaftaWave(cycles, done) {
    const frames = cycles * 2;
    const tick = (i) => {
      if (i >= frames) {
        this.jaftaImg.src = JAFTA_POSES.hello2;
        this._jaftaAfter(WAVE_REST_MS, () => {
          this.jaftaImg.src = JAFTA_POSES.idle;
          if (done) done();
        });
        return;
      }
      this.jaftaImg.src = i % 2 ? JAFTA_POSES.hello2 : JAFTA_POSES.hello1;
      this._jaftaAfter(WAVE_FRAME_MS, () => tick(i + 1));
    };
    tick(0);
  }

  _jaftaRewaveLoop() {
    this._jaftaAfter(REWAVE_EVERY_MS, () => {
      this._jaftaWave(REWAVE_CYCLES, () => this._jaftaRewaveLoop());
    });
  }
}
