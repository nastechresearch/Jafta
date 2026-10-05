"""Una rilettura delle Impostazioni partita prima di un salvataggio non lo
cancella a schermo.

Aprire la pagina Impostazioni rilegge ``/api/settings`` (``_openSettings``,
``fresh``), e il payload e' pesante: sul telefono la risposta arriva dopo un
giro. Se nel frattempo scegli un modello in «Chi risponde», il salvataggio
torna col payload nuovo e la stanza lo mostra — poi arriva la rilettura
partita **prima** e ridipinge tutto com'era: modello, marca, nome.
Sul server e' salvato giusto, a schermo no.

La regola: ogni cosa che il guscio sa di nuovo dopo aver chiesto — un
salvataggio, un nome, la finestra flottante, una versione — fa scadere le
letture partite prima.
"""

from __future__ import annotations

from support.home_dom import requires_jsdom, run_home

pytestmark = requires_jsdom

_HEAD = """
import assert from 'node:assert/strict';
import { boot, tick, routes, hooks, ok, $ } from './boot.mjs';
const before = {
  agent: { bot_name: 'Jafta', model: 'old-model' }, default_provider: 'anthropic',
  providers: [{ name: 'anthropic', api_key_hint: 'sk-1' }, { name: 'openai', api_key_hint: 'sk-2' }],
  version: {}, backup: {},
};
routes['/api/settings'] = before;
routes['/api/settings/provider-models'] = { status: 'available', models: [] };
const app = await boot();
await tick(30);
/* Da qui la lettura di `/api/settings` e' lenta: la risposta e' quella di
   quando e' partita, e arriva 150 ms dopo. */
hooks.fetch = async (u) => {
  if (u.pathname === '/api/settings') {
    const answer = ok(routes['/api/settings']);
    await tick(150);
    return answer;
  }
  return undefined;
};
"""


def test_a_model_saved_while_the_settings_are_being_read_stays_on_screen() -> None:
    run_home(_HEAD + """
const after = JSON.parse(JSON.stringify(before));
after.agent.model = 'new-model';
after.default_provider = 'openai';
const slow = hooks.fetch;
hooks.fetch = async (u, init) => (u.pathname === '/api/settings/update' ? ok(after) : slow(u, init));

app.homePages.goToId('settings');   // la rilettura parte
await tick(10);
app.openModel();
app.modelRoom.pickProvider('openai');
await app.modelRoom.pickModel('new-model');
routes['/api/settings'] = after;
assert.equal(app.modelRoom.data.agent.model, 'new-model');

await tick(300);                    // arriva quella partita prima
assert.equal(app.modelRoom.data.default_provider, 'openai', 'la marca e\\u2019 tornata quella di prima');
assert.equal(app.modelRoom.data.agent.model, 'new-model', 'il modello e\\u2019 tornato quello di prima');
""")


def test_a_name_saved_while_the_settings_are_being_read_stays_in_the_strip() -> None:
    run_home(_HEAD + """
app.homePages.goToId('settings');
await tick(10);
app._keepName('Nina');              // come un salvataggio riuscito nella stanza di lei
assert.equal(app._personalName, 'Nina');
await tick(300);
assert.equal(app._personalName, 'Nina', 'la rilettura vecchia ha rimesso il nome di prima');
""")
