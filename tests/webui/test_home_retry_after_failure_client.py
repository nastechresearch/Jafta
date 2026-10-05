"""Due letture delle stanze delle Impostazioni che, fallite una volta, non si
riprovavano piu'.

- Il catalogo dei modelli in «Chi risponde» si tiene per provider, per non
  richiederlo a ogni apertura: ma si teneva anche il fallimento, e da li'
  fino al riavvio della casa la stanza diceva «l'elenco non e' arrivato»
  senza chiederlo di nuovo.
- Le regole scritte nella stanza di lei si leggono una volta
  (``_rulesAsked``): una lettura fallita lasciava il segno alzato, e il campo
  restava vuoto per sempre.

La casa e' il launcher e vive per giorni: una rete andata male una volta non
deve contare fino al prossimo riavvio.
"""

from __future__ import annotations

from support.home_dom import requires_jsdom, run_home

pytestmark = requires_jsdom

_HEAD = """
import assert from 'node:assert/strict';
import { boot, tick, routes, hooks, ok, failed, rpcAnswers, rpcFailed, $ } from './boot.mjs';
routes['/api/settings'] = {
  agent: { bot_name: 'Jafta', model: 'm' }, default_provider: 'anthropic',
  providers: [{ name: 'anthropic' }], version: {}, backup: {},
};
"""


def test_a_model_list_that_failed_is_asked_again_on_the_next_opening() -> None:
    run_home(_HEAD + """
// Il catalogo e' un comando sul socket (`settings.provider.models`), non piu'
// una GET: la chiave che puo' portare non deve stare in una query.
let asked = 0;
rpcAnswers['settings.provider.models'] = () => {
  asked += 1;
  return asked === 1 ? rpcFailed() : { status: 'available', models: [{ id: 'claude-x' }] };
};
const app = await boot();
app.homePages.goToId('settings');
await tick(30);
app.openModel();
await tick(30);
assert.equal(asked, 1);
app.goBackOneRoom();
await tick(10);
app.openModel();
await tick(30);
assert.equal(asked, 2, 'il fallimento e\\u2019 rimasto in cache');
assert.ok([...document.querySelectorAll('#home-models .home-model')]
  .some((row) => row.dataset.model === 'claude-x'), 'l\\u2019elenco arrivato non e\\u2019 a schermo');
""")


def test_rules_that_could_not_be_read_are_read_again() -> None:
    run_home(_HEAD + """
let reads = 0;
hooks.fetch = async (u) => {
  if (u.pathname !== '/api/workspace/read') return undefined;
  reads += 1;
  return reads === 1 ? failed(503) : ok({ content: 'Be brief.' });
};
const app = await boot();
app.homePages.goToId('settings');
await tick(30);
app.openJafta();
await tick(30);
assert.equal(reads, 1);
app.goBackOneRoom();
await tick(10);
app.openJafta();
await tick(30);
assert.equal(reads, 2, 'dopo un errore le regole non si rileggono piu\\u2019');
assert.equal(app.jaftaRoom.rulesEl.value, 'Be brief.');
""")
