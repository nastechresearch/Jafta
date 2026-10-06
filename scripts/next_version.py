#!/usr/bin/env python3
# Host-only: build/maintenance script. Never imported by the Android runtime.
"""Decide which version comes next, from the commits since the last tag.

Lo script non pubblica niente e non scrive nessun file: leghe un commit range,
restituisce un livello di bump (``none``/``patch``/``minor``/``major``) e la
versione risultante. Chi decide cosa fare con quel risultato è
``.github/workflows/auto-tag.yml``, che chiama ``scripts/release.py`` per
scrivere i file e poi crea il tag.

La regola è quella dei Conventional Commits:

===================  ==========  ==================================================
Prefisso             Bump        Nota
===================  ==========  ==================================================
``feat:``            minor       una funzione nuova
``fix:``             patch       un difetto corretto
``perf:``            patch       più veloce, comportamento identico
``refactor:``        patch       il codice è diverso, l'app no
``revert:``          patch       si torna indietro su qualcosa
``!`` ovunque        major       ``feat!:``, oppure un footer ``BREAKING CHANGE:``
docs/chore/ci/test   nessuno     non meritano un APK nuovo
prefisso ignoto      nessuno     non si sa cosa sia: meglio non pubblicare
===================  ==========  ==================================================

Sul *major* c'è una scelta che vale la pena dichiarare: in ``0.x.y`` un cambiamento
incompatibile fa comunque **major**, cioè salta a ``1.0.0``. La tentazione sarebbe di
alzare solo il minor, come fanno npm e cargo, ma il CHANGELOG del progetto promette
già il contrario — *"from 1.0 on, a change that breaks something you rely on gets a new
major number"* — e una promessa scritta nel CHANGELOG vale più di una convenzione
importata da fuori. Il salto a 1.0.0 è comunque una decisione che si prende guardando
la release, non automatizzandola.

Un prefisso sconosciuto non fa una release. Il caso reale è una PR titolata
"Update README" che arriva squashata con un messaggio che nessuno ha scritto secondo
lo standard: pubblicare un APK per quello sarebbe rumore, e il rumore in una serie di
release è il modo più rapido per far smettere di guardare le release. Quando serve
una release che la convenzione non deduce, il tag si crea a mano
(``git tag v0.2.0``) o si forza con ``auto-tag.yml`` in modalità manuale.

Solo stdlib: il progetto è stdlib-only per scelta (vedi FORK_BOUNDARY.md).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Nomi dei bump, dal più piccolo al più grande. L'ordine è quello del confronto.
LEVELS = ("none", "patch", "minor", "major")

#: Un tipo che non arriva in questa tabella non produce una release.
TYPE_BUMPS = {
    "feat": "minor",
    "fix": "patch",
    "perf": "patch",
    "refactor": "patch",
    "revert": "patch",
    # docs, chore, ci, test, style, build: qui appena per symmetry con la
    # documentazione, e per poter dire "nessuno" senza un else.
    "docs": "none",
    "chore": "none",
    "ci": "none",
    "test": "none",
    "style": "none",
    "build": "none",
}

#: Separatore fra i campi di un commit, scelto perché non compare in un messaggio.
FIELD_SEP = "\x1f"
#: Separatore fra un commit e il successivo, idem: non è un carattere di testo.
COMMIT_SEP = "\x1e"

# ``type(scope)!: subject`` — lo scope tra parentesi è facoltativo, il ``!`` no.
HEADER_RE = re.compile(r"^(?P<type>[A-Za-z]+)(?:\([^)]*\))?(?P<bang>!)?:\s")
# Footer di rottura, nelle due grafie che Conventional Commits accetta.
BREAKING_RE = re.compile(r"^BREAKING[ -]CHANGE:\s*\S", re.MULTILINE)


class NextVersionError(RuntimeError):
    """Errore previsto: si stampa il messaggio e si esce, senza traceback."""


def _load_release_module() -> ModuleType:
    """Carica ``scripts/release.py`` per path: ``scripts/`` non è un package."""
    path = REPO_ROOT / "scripts" / "release.py"
    spec = importlib.util.spec_from_file_location("jafta_release_script_for_next_version", path)
    if spec is None or spec.loader is None:  # pragma: no cover - difetto di impianto
        raise NextVersionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Commit:
    """Un commit nel range considerato: subject e body sono ciò che conta."""

    subject: str
    body: str = ""


def level_for_commit(commit: Commit) -> str:
    """Il bump da *commit*: ``none``, ``patch``, ``minor`` o ``major``."""
    header = HEADER_RE.match(commit.subject)
    if header is None:
        # Messaggio che non segue lo standard. Non un errore: semplicemente non
        # abbastanza informazione per decidere, e si non pubblica.
        return "none"
    if header.group("bang") or BREAKING_RE.search(commit.body):
        return "major"
    return TYPE_BUMPS.get(header.group("type").lower(), "none")


def level_for_commits(commits: list[Commit]) -> str:
    """Il bump più grande fra quelli dei singoli commit: vince il major."""
    worst = "none"
    for commit in commits:
        level = level_for_commit(commit)
        if LEVELS.index(level) > LEVELS.index(worst):
            worst = level
    return worst


#: Una versione pubblicabile con il suo eventuale suffisso di pre-release.
#: Validata per intero e non con uno ``split("-")``: ``1.0.0-`` non è una
#: pre-release, è un refuso, e con lo split passerebbe come ``1.0.0``.
VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)(?:-(?P<pre>[0-9A-Za-z][0-9A-Za-z.\-]*))?$")


def bump_version(version: str, level: str) -> str:
    """Applica *level* a *version* (``X.Y.Z``) e restituisce il risultato.

    Solleva su input che non sono una versione pubblicabile: preferisce un errore
    esplicito a un numero silenziosamente sbagliato, che in un manifest finisce
    come "gli utenti non ricevono aggiornamenti" senza che nessuno legga perché.
    """
    match = VERSION_RE.match(version)
    if match is None:
        raise NextVersionError(f"malformed version {version!r}: expected X.Y.Z")
    if level not in LEVELS or level == "none":
        raise NextVersionError(f"cannot bump {version!r} by level {level!r}")

    major, minor, patch = (int(part) for part in match.group("base").split("."))
    if level == "patch":
        patch += 1
    elif level == "minor":
        minor, patch = minor + 1, 0
    else:
        major, minor, patch = major + 1, 0, 0
    return f"{major}.{minor}.{patch}"


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    """Esegue git e restituisce lo stdout, con un errore leggibile se fallisce."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise NextVersionError(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def last_tag(cwd: Path = REPO_ROOT) -> str | None:
    """L'ultimo tag ``vX.Y.Z`` per data di commit, o ``None`` se non ce n'è.

    ``git describe``sceglie l'etichetta valida più vicina, che su un branch con
    merge può non essere l'ultima in ordine di tempo; ``for-each-ref`` con
    ``--sort=-creatordate`` ordina per data di creazione, che è quello che
    interessa: l'ultima release pubblicata.
    """
    out = _git(
        "for-each-ref",
        "--sort=-creatordate",
        "--format=%(refname:short)",
        "refs/tags/v*.*.*",
        cwd=cwd,
    ).split()
    return out[0] if out else None


def commits_since(cwd: Path = REPO_ROOT) -> list[Commit]:
    """I commit dopo l'ultimo tag, in ordine cronologico (primo il più vecchio).

    Senza tag la base è tutto il branch: la prima release automatizzata
    engloba quindi l'intera storia, che è il comportamento giusto — altrimenti
    quei commit non finirebbero mai dentro una release.
    """
    fmt = f"--format=%H{FIELD_SEP}%s{FIELD_SEP}%b{COMMIT_SEP}"
    tag = last_tag(cwd)
    revision = f"{tag}..HEAD" if tag else "HEAD"
    out = _git("log", "--reverse", "--no-merges", fmt, revision, cwd=cwd)

    commits: list[Commit] = []
    for chunk in out.split(COMMIT_SEP):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        fields = chunk.split(FIELD_SEP)
        if len(fields) < 2:  # pragma: no cover - git non produce mai questo
            raise NextVersionError(f"unexpected git log output: {chunk!r}")
        commits.append(Commit(subject=fields[1], body=fields[2] if len(fields) > 2 else ""))
    return commits


@dataclass(frozen=True)
class Decision:
    """Il verdetto: da dove si parte, dove si arriva, e perché."""

    level: str
    current: str
    version: str
    tag: str | None
    commits: list[Commit]
    #: Versione su cui è stato calcolato il bump: il maggiore fra file e tag.
    base: str = ""
    #: True quando i file di versione e l'ultimo tag non coincidono.
    drift: bool = False

    @property
    def releasable(self) -> bool:
        return self.level != "none"

    @property
    def pending_tag(self) -> bool:
        """True when the files already carry a version that was never tagged.

        A run that bumped the files and then failed — the wait step refusing, a
        runner lost, the run cancelled — leaves exactly this state: the version is
        ahead of the last tag and nothing was tagged. Bumping again would burn
        another number for the same single release, which is how 1.0.2 and 1.0.3
        came to exist with no release behind either. The recovery is to tag the
        version already written, not to invent a later one.

        Only true once at least one tag exists: with none, "ahead of" is vacuous
        and the ordinary first-release path applies.
        """
        if self.tag is None:
            return False
        tagged = _tag_version(self.tag)
        return tagged is not None and _compare(self.current, tagged) > 0


def _tag_version(tag: str | None) -> str | None:
    """La versione numerica di un tag ``vX.Y.Z``, o ``None`` se non c'è."""
    if tag is None:
        return None
    stripped = tag[1:] if tag.startswith("v") else tag
    return stripped if VERSION_RE.match(stripped) else None


def decide(cwd: Path = REPO_ROOT, force: str | None = None) -> Decision:
    """Livello di bump, versione corrente e i commit su cui è stato deciso.

    La base del bump è il **maggiore** fra la versione nei file e quella
    dell'ultimo tag, mai la sola prima. I due possono divergere — un tag spinto
    a mano senza il bump, un merge che ha riportato indietro i file — e in quel
    caso basingci sui file produrrebbe una release con un numero **più basso** di
    una già pubblicata: l'app in attesa la rifiuterebbe (``_installable`` pretende
    un ``version_code`` strettamente maggiore) e nessuno riceverebbe l'aggiornamento,
    con un manifest che punta a una versione vecchia. Prendendo il massimo il
    numero sale comunque, e la divergenza viene segnalata invece di essere sommersa.

    Con livello ``none`` la versione di arrivo è quella corrente: restituire un
    valore fittizio costringerebbe il chiamante a distinguere i due casi, e un
    chiamante che sbaglia la distinzione tagga una versione già pubblicata.
    """
    release = _load_release_module()
    current = release.read_current_state(release.VersionFiles.under(cwd)).version
    commits = commits_since(cwd)
    tag = last_tag(cwd)
    tagged = _tag_version(tag)

    drift = tagged is not None and _compare(tagged, current) != 0
    base = current
    if tagged is not None and _compare(tagged, base) > 0:
        base = tagged

    level = force if force is not None else level_for_commits(commits)
    version = base if level == "none" else bump_version(base, level)
    return Decision(
        level=level,
        current=current,
        version=version,
        tag=tag,
        commits=commits,
        base=base,
        drift=drift,
    )


def _compare(left: str, right: str) -> int:
    """Confronto di due versioni sul solo numero, col suffisso ignorato.

    Serve a stabilire qual è la maggiore fra i file e il tag; le regole di
    pre-release di ``release.py`` sono un'altra questione e non servono qui.
    """
    lhs = VERSION_RE.match(left)
    rhs = VERSION_RE.match(right)
    if lhs is None or rhs is None:  # pragma: no cover - lo chiama solo su versioni valide
        raise NextVersionError(f"cannot compare {left!r} with {right!r}")
    a = tuple(int(part) for part in lhs.group("base").split("."))
    b = tuple(int(part) for part in rhs.group("base").split("."))
    return (a > b) - (a < b)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="next_version.py",
        description="Work out the next version from the commits since the last tag.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Reads only. It prints the answer and changes nothing.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help=argparse.SUPPRESS,  # usato dai test per lavorare su una copia
    )
    parser.add_argument(
        "--force",
        choices=("patch", "minor", "major"),
        help="ignore the commits and use this level instead",
    )
    parser.add_argument(
        "--format",
        choices=("shell", "json"),
        default="shell",
        help="shell writes LEVEL=/VERSION=/REASON= lines, json a single object (default: shell)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        decision = decide(args.repo_root, force=args.force)
    except NextVersionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    since = decision.tag or "the first commit"
    if args.force:
        reason = f"{decision.level} forced by --force"
    elif decision.level == "none":
        reason = f"no releasable commit since {since}"
    else:
        reason = f"{decision.level} from {len(decision.commits)} commit(s) since {since}"

    if decision.drift:
        drift = (
            f"version files say {decision.current} but {decision.tag} is published; "
            f"bumping from the higher one ({decision.base})"
        )
        if args.format == "shell":
            # Su stdout: é l Annotated warning che GitHub mostra nella pagina del run.
            print(f"::warning::{drift}")
        else:
            # Su stderr, perché qui lo stdout deve restare JSON valido.
            print(f"warning: {drift}", file=sys.stderr)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "level": decision.level,
                    "current": decision.current,
                    "base": decision.base,
                    "version": decision.version,
                    "tag": decision.tag,
                    "last_tag": decision.tag,
                    "commits": len(decision.commits),
                    "releasable": decision.releasable,
                    "drift": decision.drift,
                    "pending_tag": decision.pending_tag,
                    "reason": reason,
                }
            )
        )
    else:
        print(f"LEVEL={decision.level}")
        print(f"CURRENT={decision.current}")
        print(f"BASE={decision.base}")
        print(f"VERSION={decision.version}")
        print(f"TAG={decision.tag or ''}")
        print(f"COMMITS={len(decision.commits)}")
        print(f"DRIFT={'yes' if decision.drift else 'no'}")
        print(f"PENDING_TAG={'yes' if decision.pending_tag else 'no'}")
        print(f"REASON={reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
