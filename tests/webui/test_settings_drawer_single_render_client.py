"""Passare da un cassetto all'altro disegna una volta, non due.

Cervello, Mani e Memoria sono un
controller solo: ``switchMode`` chiama ``setDrawer`` (che ridisegna coi dati in
cache) e poi ``activate()`` (che rilegge ``/api/settings`` e ridisegnava di
nuovo). Due render per ingresso, e con loro due giri delle letture dei blocchi
in ritardo — SSH, cron, Telegram, skill. Il commento di ``setDrawer`` diceva che
non si ricaricava niente.

Si eseguono in node ``setDrawer`` e ``loadSettings`` veri.
"""

from __future__ import annotations

from support.js_harness import ASSETS, member, requires_node, run_js

pytestmark = requires_node

SRC = (ASSETS / "mobile-settings.js").read_text(encoding="utf-8")

_HARNESS = (
    """
import assert from 'node:assert/strict';
let payload = { agent: { model: 'a' }, providers: [] };
const api = { getSettings: async () => JSON.parse(JSON.stringify(payload)) };
/* Il nome di lei (`shared/bot-name.js`): qui quello di partenza. */
const botName = { get: () => 'Jafta', set() {}, onChange() { return () => {}; } };
const i18n = { t: (k) => k };
const escapeHtml = (s) => s;
class Settings {
  constructor() {
    this._gen = 0; this.data = null; this._drawer = null;
    this._loadedJson = null; this._paintedFromCache = false;
    this.renders = [];
  }
  showLoading() {}
  hideLoading() {}
  _stale(gen) { return gen !== this._gen; }
  _realignPanel() {}
  render() { this.renders.push(this._drawer); }
"""
    + member(SRC, "setDrawer")
    + member(SRC, "_resetBrandVisit")
    + "\n"
    + member(SRC, "loadSettings")
    + """
  activate() { return this.loadSettings(); }
}
const s = new Settings();
"""
)


def test_switching_drawer_with_unchanged_data_renders_once() -> None:
    run_js(
        _HARNESS
        + """
      s.setDrawer('brain');
      await s.activate();
      assert.deepEqual(s.renders, ['brain'], 'primo ingresso: nessuna cache, un render');
      s.renders.length = 0;
      s.setDrawer('hands');
      await s.activate();
      assert.deepEqual(s.renders, ['hands'], 'un render per ingresso');
    """
    )


def test_changed_data_is_still_drawn() -> None:
    run_js(
        _HARNESS
        + """
      s.setDrawer('brain');
      await s.activate();
      s.renders.length = 0;
      payload = { agent: { model: 'b' }, providers: [] };
      s.setDrawer('hands');
      await s.activate();
      assert.deepEqual(s.renders, ['hands', 'hands'], 'la cache subito, poi i dati nuovi');
      assert.equal(s.data.agent.model, 'b');
    """
    )


def test_a_plain_reload_still_draws() -> None:
    """Chi rilegge senza cambiare cassetto (dopo un salvataggio) ridisegna."""
    run_js(
        _HARNESS
        + """
      s.setDrawer('brain');
      await s.activate();
      s.renders.length = 0;
      await s.loadSettings();
      assert.deepEqual(s.renders, ['brain']);
    """
    )
