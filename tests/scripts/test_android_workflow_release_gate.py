"""Ogni evento deve girare **un** build release, e su un PR deve girare R8.

Il difetto che questo file chiude: il passo che poteva vedere un R8 fallito era
`- name: Build signed release APK` con

    if: github.event_name == 'push' && github.ref == 'refs/heads/main'

quindi R8 girava **solo dopo il merge**. E `assembleDebug` non gira R8, e
`kotlinc` risolve in silenzio una chiamata a una classe assente: una dipendenza
che manca solo per R8 passava ogni build debug. Il risultato e' stato PR #23 e
PR #24 verdi mentre `main` non produceva un build release — e la firma del
rilievo arriva solo su main, per la versione pubblicata.

Il punto non e' "costruire anche su PR": e' che **la firma non e' cio' che fa
girare R8**. R8shrinka prima che l'APK venga impacchettato e firmato, quindi
`assembleRelease` fa esattamente lo stesso passaggio di R8 con o senza keystore.
Senza, `hasReleaseSigning` si limita a un `logger.warn`.

Una volta accettato questo, la domanda diventa meccanica: i due passi release
(devono girare in alternativa) e i loro `if` (devono essere complementari, senza
sovrapposizione e senza buco). Sono condizioni su una stringa, quindi si
verificano per enumerazione: tre eventi reali, e per ognuno esattamente uno dei
due deve essere vero.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "android.yml"

# I tre eventi che il workflow tratta davvero: una PR, un push su un branch, e il
# push su main. Gli ultimi due condividono lo stesso valore di `event_name` e si
# distinguono solo per `ref` — ed e' esattamente la distinzione che i due `if`
# stanno facendo, quindi ometterli lascerebbe il caso meno interessante scoperto.
PR = ("pull_request", "refs/pull/1/merge")
PUSH_BRANCH = ("push", "refs/heads/feat/some-branch")
PUSH_MAIN = ("push", "refs/heads/main")
EVENTS = {"PR": PR, "push su un branch": PUSH_BRANCH, "push su main": PUSH_MAIN}

MAIN_ONLY = "github.event_name == 'push' && github.ref == 'refs/heads/main'"


def _build_steps() -> list[dict]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["build"]["steps"]


def _find(name: str) -> dict:
    for step in _build_steps():
        if name in step.get("name", ""):
            return step
    raise AssertionError(f"nessun passo chiamato {name!r} in {WORKFLOW}")


def test_the_unsigned_release_build_runs_on_pull_requests() -> None:
    """Il passo che gira R8 senza keystore deve esserci, e non essere ristretto
    a main. Se qualcuno lo rimuove, la protezione sparisce in silenzio: nessun
    test può notare un passo che non c'è più."""
    step = _find("Build release APK (unsigned")
    condition = step.get("if")
    assert condition, (
        "il build release unsigned deve avere una condizione, altrimenti gira "
        "anche su main e duplica quello firmato"
    )
    assert "refs/heads/main" in condition, "la condizione deve distinguere main dal resto"
    # Su una PR la condizione deve essere vera: e' il caso che copriamo.
    assert _evaluate(condition, *PR), (
        "su una PR questo passo deve girare: e' l'unico che vede R8 prima del merge"
    )


def test_the_signed_build_still_only_runs_on_main() -> None:
    """La firma resta un affare di main: la chiave non esiste sulle PR di un
    fork, e verificare un certificato su un albero non firmato non ha senso."""
    step = _find("Build signed release APK")
    assert step.get("if") == MAIN_ONLY, (
        f"il build firmato deve restare limitato a main, trovato {step.get('if')!r}"
    )


def test_every_event_runs_exactly_one_release_build() -> None:
    """Complementari', non solo presenti.

    Una sovrapposizione fa girare due build release a ogni merge (il costo della
    pipeline raddoppia per niente); un buco lascia un evento senza nessun R8, che
    e' esattamente il difetto da cui siamo partiti. Nessuno dei due si vede
    leggendo i due `if` uno dopo l'altro: si vede solo enumerando.
    """
    unsigned = _find("Build release APK (unsigned").get("if")
    signed = _find("Build signed release APK").get("if")

    for label, (event, ref) in EVENTS.items():
        runs_unsigned = _evaluate(unsigned, event, ref)
        runs_signed = _evaluate(signed, event, ref)
        assert runs_unsigned != runs_signed, (
            f"{label}: unsigned={runs_unsigned} signed={runs_signed} — "
            "i due passi devono girare in alternativa, mai insieme e mai nessuno"
        )


def test_the_signature_verification_stays_on_main() -> None:
    """Anche la verifica del certificato resta su main. Senza keystore non c'è
    un APK firmato da controllare, e il passo deve dirselo invece di tentare il
    confronto e fallire con un errore che sembra un problema di firma."""
    step = _find("Verify the release APK is signed")
    assert step.get("if") == MAIN_ONLY


def test_the_unsigned_build_actually_invokes_assemble_release() -> None:
    """Il nome del passo promette R8; il comando e' cio' che lo fa. Un passo
    chiamato "R8 gate" che lancia `assembleDebug` tornerebbe a non verificare
    niente, e questa volta senza che nessuno se ne accorga."""
    step = _find("Build release APK (unsigned")
    run = step.get("run", "")
    assert _launches_assemble_release(step), (
        "il passo deve lanciare ./gradlew assembleRelease, non assembleDebug"
    )
    assert "assembleDebug" not in run


def test_no_step_gates_r8_behind_a_push_to_main() -> None:
    """Il controllo finale, sul file intero: nessun passo che lancia
    `assembleRelease` puo' essere ristretto al push su main.

    I due passi release sono gia' coperti dai test precedenti; questo guarda
    *tutti* i passi, cosi' un terzo passo aggiunto in futuro — magari un
    `assembleRelease` "di controllo" con un nome nuovo — non reintroduce lo stesso
    buco senza che nessuno lo noti.
    """
    # La verifica cerca solo il comando `./gradlew … assembleRelease`, non la
    # stringa: il passo che verifica la firma la nomina in un messaggio di errore
    # (`assembleRelease produced no APK at …`) senza lanciarla, e cercandola a
    # metà si segnalerebbe un passo che è solo consumatore del risultato.
    offenders = [
        step["name"]
        for step in _build_steps()
        if _launches_assemble_release(step)
        and step.get("if") == MAIN_ONLY
        and "Build signed release APK" not in step.get("name", "")
    ]
    assert not offenders, f"passi che girano R8 solo su main: {offenders}"


def _launches_assemble_release(step: dict) -> bool:
    """Vero se il passo lancia davvero `./gradlew … assembleRelease`.

    Si cerca il comando e non la stringa: il passo che verifica la firma nomina
    `assembleRelease` dentro un messaggio di errore («assembleRelease produced no
    APK at …») senza lanciarlo. Cercandolo a metà, quel passo — che e' solo
    consumatore del risultato — verrebbe segnalato come un altro passo che gira
    R8 solo su main, e il test griderebbe per un problema che non esiste.
    """
    return re.search(r"\./gradlew[^\n]*\bassembleRelease\b", step.get("run", "")) is not None


def _evaluate(condition: str, event: str, ref: str) -> bool:
    """Valuta la condizione di un passo con i valori che GitHub ci metterebbe.

    Le condizioni di questo file sono solo AND/OR di due confronti di uguaglianza
    su due variabili, quindi si sostituiscono e si ragiona sul risultato. Niente
    ``eval``: l'espressione viene ricostruita passo passo, e un valore che non
    combacia con nessuno dei confronti noti solleva invece di passare in silenzio.
    """
    normalized = re.sub(r"\s+", " ", condition.strip())
    terms = [part.strip() for part in normalized.split("||")]
    return any(
        all(
            _compare(clause, event, ref)
            for clause in (part.strip() for part in term.split("&&"))
            if clause
        )
        for term in terms
    )


def _compare(clause: str, event: str, ref: str) -> bool:
    """Un solo confronto, `==` o `!=`, su una delle due variabili.

    `!=` serve perche' la condizione complementare di `main` e' scritta nella
    forma negata: senza questo ramo l'evaluator non saprebbe cosa fare e
    fallirebbe su una condizione che funziona, che e' il modo peggiore in cui
    puo' fallire un test di questo tipo.
    """
    for operator in ("==", "!="):
        match = re.fullmatch(rf"github\.event_name {operator} '([^']+)'", clause)
        if match:
            return (event == match.group(1)) if operator == "==" else (event != match.group(1))
        match = re.fullmatch(rf"github\.ref {operator} '([^']+)'", clause)
        if match:
            return (ref == match.group(1)) if operator == "==" else (ref != match.group(1))
    raise AssertionError(f"clausola non riconosciuta: {clause!r}")
