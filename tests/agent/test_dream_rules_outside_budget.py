"""Le regole dell'utente in SOUL.md restano fuori dal budget ovunque.

Il blocco con le regole che l'utente ha dato a Jafta non e' di Dream — lo proietta
l'app da ``.jafta/soul_rules.md`` — e il budget esiste per limitare quel che scrive
Dream. ``FileBudget.skip_user_rules`` lo toglie dal conto, e c'erano test per il
report e per il guard. Non per le due misure prese *dopo*: la crescita con cui
``dream_cycle.consolidation_landed`` decide se un batch e' atterrato, e la
rimisura con cui ``dream_review._measure`` conta quanto un review ha liberato. Se
una delle due contasse il blocco, un salvataggio delle regole a meta' passata
varrebbe come un fatto consolidato, o come spazio consumato dal review.
"""

from __future__ import annotations

from pathlib import Path

from jafta.agent import dream_review
from jafta.agent.dream_cycle import consolidation_landed
from jafta.agent.memory import MemoryStore
from jafta.agent.memory_budget import budget_report
from jafta.agent.soul_rules import save_rules

SOUL = "# Soul\n\nSono Jafta.\n\n## Come parlo\n\nBreve.\n"
RULES = "- Non chiamarmi mai per cognome.\n- Rispondi sempre in italiano."


def _store(tmp_path: Path) -> MemoryStore:
    store = MemoryStore(tmp_path)
    store.soul_file.write_text(SOUL, encoding="utf-8")
    return store


def _report(store: MemoryStore):
    return budget_report(store, memory_chars=0, user_chars=0, soul_chars=5_000)


def test_rules_saved_mid_pass_do_not_count_as_a_landed_fact(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before = _report(store)

    save_rules(store.soul_file.parent, RULES)

    assert RULES.splitlines()[0] in store.soul_file.read_text(encoding="utf-8")
    assert not consolidation_landed(before)


def test_a_line_dream_writes_in_soul_still_counts(tmp_path: Path) -> None:
    """La controprova: il blocco e' escluso, SOUL.md no."""
    store = _store(tmp_path)
    save_rules(store.soul_file.parent, RULES)
    before = _report(store)

    with store.soul_file.open("a", encoding="utf-8") as f:
        f.write("\n- Una cosa nuova che Dream ha imparato.\n")

    assert consolidation_landed(before)


def test_the_review_measure_leaves_the_rules_out(tmp_path: Path) -> None:
    store = _store(tmp_path)
    report = _report(store)
    plain = dream_review._measure(report)["SOUL.md"]

    save_rules(store.soul_file.parent, RULES)

    assert dream_review._measure(report)["SOUL.md"] == plain
    assert plain == len(SOUL)
