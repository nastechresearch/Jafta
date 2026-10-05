"""L'invariante al confine delle impostazioni agente.

> **Ogni alias che ``_apply_agent_settings`` accetta o sposta l'impronta del
> provider — e allora l'agente vivo lo prende a caldo — oppure fa dichiarare
> ``requires_restart`` alla risposta, e allora la UI lo dice.**

Il terzo caso e' il difetto: un campo che si salva, non cambia niente in memoria
e non avverte nessuno. ``context_window_tokens`` era esattamente li' — lo si
scriveva, il gancio del rebuild non partiva perche' il suo nome non era in un
elenco tenuto a mano da un'altra parte, e la risposta non chiedeva il riavvio.
Config giusto su disco, «Saved!» nella UI, e l'agente che continuava con la
finestra vecchia. Prima ancora era toccato ai parametri di generazione, e su un
altro piano a ``caBundle`` (issue #12).

**Gli alias non sono elencati qui: si scoprono.** Un elenco scritto a mano in un
test e' lo stesso oggetto che ha causato il difetto tre volte — invecchia da
solo, e proprio nel momento in cui qualcuno aggiunge un campo. Qui si leggono
invece le stringhe letterali dal sorgente della funzione e si chiede *alla
funzione stessa* quali di quelle sa accettare: un campo nuovo entra nella
parametrizzazione da solo, e se non e' ne' a caldo ne' dichiarato, diventa
rosso senza che nessuno debba ricordarsi di questo file.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from jafta.config.schema import Config, ProviderConfig, ProvidersConfig
from jafta.providers.factory import provider_fingerprint
from jafta.webui.settings_api import WebUISettingsError, _apply_agent_settings

# Un valore plausibile per ogni forma di campo che la funzione accetta: nome
# IANA, finestra di contesto ammessa, temperatura, sforzo di ragionamento, un
# intero dentro i bound di ``tool_hint_max_length``, il nome di un provider che
# esiste, e una stringa qualunque. Basta che **uno** venga accettato perche'
# l'alias si riveli.
_CANDIDATE_VALUES = (
    "Europe/Rome",
    "262144",
    "0.7",
    "high",
    "120",
    "riserva",
    "un-valore",
)


def _baseline() -> Config:
    """Config con due provider, cosi' anche ``default_provider`` ha un valore valido."""
    return Config(
        providers=ProvidersConfig(
            providers=[
                ProviderConfig(name="attivo", format="openai_compat", api_key="k"),
                ProviderConfig(name="riserva", format="openai_compat", api_key="k2"),
            ],
            default="attivo",
        )
    )


def _discover_aliases() -> dict[str, str]:
    """Alias accettati da ``_apply_agent_settings``, chiesti alla funzione stessa.

    Si parte dalle stringhe letterali del suo sorgente — che comprendono nomi di
    attributi, docstring e messaggi, cioe' molta roba che alias non e' — e si
    tiene solo cio' che, passato come parametro di query, le fa dire
    ``changed=True``. Niente lista da mantenere, e nessuna lista di esclusioni:
    quel che non e' un alias non viene accettato e cade da solo.
    """
    tree = ast.parse(inspect.getsource(_apply_agent_settings))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    accepted: dict[str, str] = {}
    for literal in sorted(literals):
        for value in _CANDIDATE_VALUES:
            try:
                changed, _ = _apply_agent_settings(_baseline(), {literal: [value]})
            except WebUISettingsError:
                continue  # valore sbagliato per quel campo: si prova il prossimo
            if changed:
                accepted[literal] = value
                break
    return accepted


_ACCEPTED_ALIASES = _discover_aliases()


def test_discovery_actually_found_the_known_aliases() -> None:
    """La scoperta deve funzionare, o l'invariante sotto passerebbe a vuoto.

    Un test parametrizzato su un insieme vuoto e' verde e non dimostra niente:
    questi quattro sono i rappresentanti delle due classi (due a caldo, due da
    riavvio) e la loro presenza prova che il meccanismo legge davvero il
    sorgente e interroga davvero la funzione.
    """
    assert {
        "model",
        "context_window_tokens",
        "timezone",
        "toolHintMaxLength",
    } <= set(_ACCEPTED_ALIASES)


@pytest.mark.parametrize("alias", sorted(_ACCEPTED_ALIASES))
def test_every_accepted_alias_is_live_or_declares_a_restart(alias: str) -> None:
    config = _baseline()
    before = provider_fingerprint(config)

    changed, restart_required = _apply_agent_settings(config, {alias: [_ACCEPTED_ALIASES[alias]]})

    assert changed, f"{alias}: scoperto come accettato ma non applica niente"
    moves_the_provider = provider_fingerprint(config) != before
    assert moves_the_provider or restart_required, (
        f"{alias}: si salva su disco ma non cambia niente in memoria e non "
        "dichiara requires_restart — l'utente vede «Saved!» e nessun effetto"
    )
