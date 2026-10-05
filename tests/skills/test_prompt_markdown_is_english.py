"""I Markdown che il modello legge sono in inglese, esempi compresi.

Perché esiste. Il 30/09/2026, sull'emulatore con il telefono in en-US, la
richiesta «Make me a Jafta App called Miso's Bowl…» ha prodotto un'app tutta in
italiano: descrizione, azioni (``registra_pasto``, ``leggi_oggi``), parametri
(``tipo``, ``grammi``), etichette (``Caricamento…``, ``Salva``). E le risposte in
chat hanno cominciato a mescolare l'italiano, perché i risultati dei tool
portavano nomi e dati italiani. La causa non era una regola sbagliata ma la sua
assenza: ``app-creator`` non diceva quale lingua usare, e ogni esempio che
mostrava (``Piante``, ``lista_piante``, ``<html lang="it">``) era italiano. Il
modello imita gli esempi.

Jafta parla inglese di default, quindi nessun ``.md`` sotto ``jafta/`` — skill,
riferimenti, template del prompt — deve portare italiano: nemmeno nel
frontmatter, che il modello legge per intero con ``read_file``, e nemmeno nei
commenti Jinja. I riassunti per l'utente delle skill integrate stanno per
questo in ``assets/i18n/*.json`` (``skills.userSummary.<nome>``).

Limiti dichiarati: il rilevatore è lessicale. Conta parole che in inglese non
esistono e le vocali accentate tipiche dell'italiano; una frase italiana fatta
solo di parole che collidono con l'inglese gli sfugge, e un nome proprio
accentato («Città») lo fa scattare — lì si riformula.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAFTA = ROOT / "jafta"
APP_CREATOR = JAFTA / "skills" / "app-creator"
I18N = JAFTA / "templates" / "ui" / "assets" / "i18n"

# Due liste. Le parole «forti» non hanno omografi inglesi e ne basta una; le
# «deboli» esistono anche in inglese o in un identificatore («con», «nota»,
# «stato»), e servono in due. «come», «solo», «fare», «ha» restano fuori del
# tutto: una riga inglese qualsiasi le contiene.
_STRONG = frozenset(
    """
    il gli una della delle degli dello nella nelle sulla alla alle dalla questo
    questa questi quello quella perché però anche quando sono cosa dimmi voglio
    fammi dammi ecco grazie già più così che dove tutto tutti ogni sempre oggi
    ieri domani essere vuoi puoi senza abbiamo hanno certo avvisami parlane
    qualcosa propongo cambiamo nuova nuovo umidità
    """.split()
)
_WEAK = frozenset(
    """
    non con va bene ti ci sta qui dei del nel sul dal nota ora tipo lista nome
    azioni stato cura cure pianta piante modo
    """.split()
)
_WORD_RE = re.compile(r"(?<![\w-])([^\W\d_]+)(?![\w-])", re.UNICODE)
# È, à, ì, ò, ù dopo una lettera o da sole: l'accento grave dell'italiano.
_GRAVE_RE = re.compile(r"[àèìòùÈ]")


def _looks_italian(line: str) -> bool:
    words = {w.lower() for w in _WORD_RE.findall(line)}
    return bool(words & _STRONG or len(words & _WEAK) >= 2 or _GRAVE_RE.search(line))


def _prompt_markdown() -> list[Path]:
    return sorted(p for p in JAFTA.rglob("*.md") if "node_modules" not in p.parts)


def _italian_lines(path: Path) -> list[str]:
    hits = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _looks_italian(line):
            hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")
    return hits


def test_the_detector_sees_the_italian_it_is_meant_to_catch() -> None:
    """Senza questo, un rilevatore rotto passerebbe in verde su tutto."""
    probes = {
        "> Certo! Dimmi: cosa dovrebbe fare questa app?": True,
        '  it: "La wiki è il tuo secondo cervello"': True,
        "   file dell'utente: quelli si creano al primo avvio e non si aggiornano mai più.": True,
        "Il routing dei quaderni sta qui, nella coda che nessun gate tocca": True,
        "- Every concept page has a non-empty `sources:` frontmatter.": False,
        "Come back to it when the solo run is done; per the fare rules.": False,
        "> - **Nome:** Piante (`piante`)": True,
        '{ "name": "annota_cura", "description": "Registra una cura fatta a una pianta",': True,
        '{ "name": "log_care", "description": "Log a care task done on a plant",': False,
    }
    for line, expected in probes.items():
        assert _looks_italian(line) is expected, line


def test_no_markdown_under_jenny_carries_italian() -> None:
    hits = [hit for path in _prompt_markdown() for hit in _italian_lines(path)]
    assert hits == [], "Italian in prompt-bound Markdown:\n" + "\n".join(hits)


def test_app_creator_examples_do_not_pull_toward_italian() -> None:
    """Gli identificatori esatti degli esempi di prima, e la lingua della pagina."""
    files = [APP_CREATOR / "SKILL.md", *sorted((APP_CREATOR / "references").glob("*.md"))]
    for path in files:
        text = path.read_text(encoding="utf-8")
        for needle in ('lang="it"', "lista_piante", "Caricamento", "Nome:"):
            assert needle not in text, f"{path.relative_to(ROOT)} still contains {needle!r}"


def test_app_creator_states_which_language_the_app_speaks() -> None:
    text = (APP_CREATOR / "SKILL.md").read_text(encoding="utf-8")
    assert "language the user is speaking" in text
    assert "<html lang>" in text
    for covered in ("action and param names", "UI labels", "placeholders", "empty"):
        assert covered in text, covered


def test_bundled_skill_summaries_live_in_i18n_in_both_languages() -> None:
    """Il riassunto per l'utente di una skill integrata non torna nel frontmatter.

    Ogni chiave ``skills.userSummary.<nome>`` deve nominare una skill che esiste
    — un rename lascerebbe il riassunto orfano e la riga vuota in Mani — e
    nessun ``SKILL.md`` integrato deve riportare ``user_summary``.
    """
    names = {p.parent.name for p in (JAFTA / "skills").glob("*/SKILL.md")}
    for locale in ("it", "en"):
        summaries = json.loads((I18N / f"{locale}.json").read_text(encoding="utf-8"))[
            "skills"
        ]["userSummary"]
        assert set(summaries) <= names, (locale, set(summaries) - names)
        assert all(isinstance(v, str) and v.strip() for v in summaries.values()), locale
    for path in (JAFTA / "skills").glob("*/SKILL.md"):
        assert "user_summary:" not in path.read_text(encoding="utf-8"), path
