"""Test di ``scripts/next_version.py``: quale versione segue a quali commit.

Lo script decide se un merge su ``main`` vale un APK nuovo e di che tipo. Sbagliare
in eccesso costa una release di rumore, sbagliare in difetto costa una correzione
che non arriva mai: i due errori non sono equivalenti e i test coprono entrambi.

La parte che parla con git gira su un repository costruito in ``tmp_path``, con
commit veri e tag veri, perché il formato di ``git log`` è proprio il contratto che
questo script deve onorare — un mock lo avrebbe lasciato libero di inventarlo.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "next_version.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("jafta_next_version_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


nv = _load_module()


PYPROJECT = """\
[project]
name = "jafta"
version = "0.1.0"
"""

INIT_PY = 'def _v() -> str:\n    return _read_pyproject_version() or "0.1.0"\n'

GRADLE = """\
android {
    defaultConfig {
        versionCode = 18
        versionName = "0.1.0"
    }
}
"""


def _git(repo: Path, *args: str, env_extra: dict[str, str] | None = None) -> str:
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(repo),
    }
    env.update(env_extra or {})
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return proc.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Un repository con i tre file di versione e un commit iniziale."""
    root = tmp_path / "repo"
    (root / "jafta").mkdir(parents=True)
    (root / "android" / "app").mkdir(parents=True)
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "jafta" / "__init__.py").write_text(INIT_PY, encoding="utf-8")
    (root / "android" / "app" / "build.gradle.kts").write_text(GRADLE, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore: initial tree")
    return root


def _commit(repo: Path, message: str, *, body: str = "") -> None:
    """Aggiunge un file e committa con subject e body separati."""
    marker = f"// {len(_git(repo, 'log', '--oneline'))}\n"
    (repo / "notes.txt").write_text(marker, encoding="utf-8")
    _git(repo, "add", "-A")
    args = ["commit", "-q", "-m", message]
    if body:
        args += ["-m", body]
    _git(repo, *args)


def _tag(repo: Path, name: str, *, when: str) -> None:
    """Crea un tag *annotato* con una data di tagger precisa.

    Il tag annotato porta la data in cui è stato creato, che è ciò che
    ``--sort=-creatordate`` guarda. Serve a rendere deterministico un test che
    altrimenti dipenderebbe da due tag creati nello stesso secondo — cosa che
    su un filesystem con risoluzione al secondo capita, e fa fallire il test a
    intermittenza invece che sempre.
    """
    _git(repo, "tag", "-a", name, "-m", name, env_extra={"GIT_COMMITTER_DATE": when})


# --------------------------------------------------------------------------
# Classificazione di un singolo commit
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("feat: a new home screen", "minor"),
        ("feat(chat): streaming replies", "minor"),
        ("fix: crash on rotate", "patch"),
        ("perf: smaller APK", "patch"),
        ("refactor: split the updater", "patch"),
        ("revert: the new home screen", "patch"),
        ("docs: fix a typo", "none"),
        ("chore: bump a dependency", "none"),
        ("ci: cache the gradle dir", "none"),
        ("test: cover the manifest", "none"),
        ("style: rename a local", "none"),
        ("build: move a gradle file", "none"),
    ],
)
def test_prefix_decides_the_bump(subject: str, expected: str) -> None:
    assert nv.level_for_commit(nv.Commit(subject)) == expected


def test_bang_suffix_is_major_even_on_a_docs_commit() -> None:
    assert nv.level_for_commit(nv.Commit("docs!: the install page is gone")) == "major"


def test_breaking_change_footer_is_major() -> None:
    commit = nv.Commit(
        subject="feat: new manifest format",
        body="Closes #12\n\nBREAKING CHANGE: the old latest.json is no longer read.",
    )
    assert nv.level_for_commit(commit) == "major"


def test_breaking_change_with_hyphen_is_major_too() -> None:
    """Lo standard ammette due grafie; la regex ne prende una sola e basta."""
    commit = nv.Commit(subject="fix: updater", body="BREAKING-CHANGE: nothing reads it")
    assert nv.level_for_commit(commit) == "major"


def test_the_words_breaking_change_inside_a_sentence_are_not_a_footer() -> None:
    """Il footer sta a inizio riga. In mezzo a una frase è solo prosa."""
    commit = nv.Commit(
        subject="docs: updater notes",
        body="We rewrote the notes; this is a BREAKING CHANGE: of the old file format.",
    )
    assert nv.level_for_commit(commit) == "none"


@pytest.mark.parametrize(
    "subject",
    [
        "Update README",
        "Merge pull request #7 from nastechresearch/thing",
        "WIP",
        "  feat: leading whitespace is not a prefix",
        "feature: nearly feat but not feat",
    ],
)
def test_a_message_that_is_not_conventional_produces_nothing(subject: str) -> None:
    """Il caso più comune in una PR open-source: nessuno ha scritto lo standard.

    Pubblicare un APK per "Update README" è rumore, e il rumore in una serie di
    release è il modo più rapido per far smettere di guardare le release.
    """
    assert nv.level_for_commit(nv.Commit(subject)) == "none"


def test_the_type_is_case_insensitive() -> None:
    assert nv.level_for_commit(nv.Commit("FIX: shouty subject")) == "patch"


def test_the_worst_commit_wins() -> None:
    commits = [
        nv.Commit("docs: a typo"),
        nv.Commit("fix: a crash"),
        nv.Commit("feat: a feature"),
        nv.Commit("chore: a dependency"),
    ]
    assert nv.level_for_commits(commits) == "minor"


def test_a_major_anywhere_wins_over_everything() -> None:
    commits = [nv.Commit("feat: a"), nv.Commit("feat!: b"), nv.Commit("fix: c")]
    assert nv.level_for_commits(commits) == "major"


def test_no_commits_means_no_release() -> None:
    assert nv.level_for_commits([]) == "none"


# --------------------------------------------------------------------------
# Aritmetica della versione
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "level", "expected"),
    [
        ("0.1.0", "patch", "0.1.1"),
        ("0.1.0", "minor", "0.2.0"),
        ("0.1.0", "major", "1.0.0"),
        ("0.9.9", "patch", "0.9.10"),
        ("0.9.9", "minor", "0.10.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.2.3", "minor", "1.3.0"),
        ("1.2.3", "major", "2.0.0"),
    ],
)
def test_bump_arithmetic(current: str, level: str, expected: str) -> None:
    assert nv.bump_version(current, level) == expected


def test_patch_after_minor_zeroes_the_patch() -> None:
    """0.1.7 → 0.2.0 e non 0.2.7: è la differenza fra un bump e una somma."""
    assert nv.bump_version("0.1.7", "minor") == "0.2.0"


def test_breaking_change_on_a_zero_major_goes_straight_to_one() -> None:
    """Il CHANGELOG promette un major sui cambi incompatibili, anche da 0.x.

    npm e cargo alzano solo il minor in 0.x; qui la promessa scritta nel CHANGELOG
    ha la precedenza, e il salto a 1.0.0 resta una decisione che si prende
    guardando la release.
    """
    assert nv.bump_version("0.1.0", "major") == "1.0.0"


def test_a_prerelease_suffix_is_stripped_before_bumping() -> None:
    """L'albero di sviluppo sta a ``X.Y.Z-dev`` e la release che lo promuove è X.Y.Z+1."""
    assert nv.bump_version("0.2.0-dev", "patch") == "0.2.1"


@pytest.mark.parametrize("version", ["1.0", "1.2.3.4", "one.two.three", "1.0.0-", "", "v1.0.0"])
def test_a_malformed_version_is_refused(version: str) -> None:
    """Un numero malformato in un manifest è «nessun aggiornamento», in silenzio.

    ``1.0.0-`` è il caso che ha tenuto vivo il bug: uno ``split("-")`` lo
    legge come ``1.0.0`` e produce ``1.0.1`` da un refuso.
    """
    with pytest.raises(nv.NextVersionError):
        nv.bump_version(version, "patch")


def test_level_none_is_not_a_bump() -> None:
    with pytest.raises(nv.NextVersionError):
        nv.bump_version("1.0.0", "none")


def test_an_unknown_level_is_refused() -> None:
    with pytest.raises(nv.NextVersionError):
        nv.bump_version("1.0.0", "huge")


# --------------------------------------------------------------------------
# Il giro completo dentro un repository vero
# --------------------------------------------------------------------------


def test_nothing_to_release_leaves_the_version_alone(repo: Path) -> None:
    """Il caso silenzioso: dopo un merge di docs la versione resta quella corrente.

    Restituire un numero inventato costringerebbe il chiamante a distinguere i due
    casi, e un chiamante che sbaglia la distinzione tagga una versione già pubblicata.
    """
    _commit(repo, "docs: explain the keystore")
    decision = nv.decide(repo)
    assert decision.level == "none"
    assert decision.current == "0.1.0"
    assert decision.version == "0.1.0"
    assert not decision.releasable


def test_a_fix_bumps_the_patch(repo: Path) -> None:
    _commit(repo, "fix: the updater never offered the update")
    decision = nv.decide(repo)
    assert (decision.level, decision.version) == ("patch", "0.1.1")


def test_only_commits_after_the_last_tag_count(repo: Path) -> None:
    """Un fix anteriore al tag è già dentro una release: ripubblicarlo no.

    Senza questo filtro ogni merge ripubblicherebbe tutto lo storico e la versione
    salirebbe di un patch a ogni passaggio.
    """
    _commit(repo, "fix: the first bug")
    _tag(repo, "v0.1.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "docs: unrelated prose")
    assert nv.decide(repo).level == "none"
    _commit(repo, "fix: the second bug")
    assert nv.decide(repo).version == "0.1.1"


def test_without_any_tag_the_whole_history_counts(repo: Path) -> None:
    """La prima release automatizzata non deve perdere i commit preesistenti."""
    assert nv.last_tag(repo) is None
    _commit(repo, "feat: the thing that ships")
    decision = nv.decide(repo)
    assert decision.tag is None
    assert decision.version == "0.2.0"


def test_merge_commits_are_skipped(repo: Path) -> None:
    """Un merge senza messaggio convenzionale non deve alzare niente.

    ``--no-merges`` li esclude: il contenuto è già nei commit che il merge porta
    dentro, e contarli due volte farebbe saltare la versione senza motivo.
    """
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "chore: on the branch")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #1 from nastechresearch/side", "side")
    assert nv.decide(repo).level == "none"


def test_the_latest_tag_by_creation_date_wins_even_on_an_older_commit(repo: Path) -> None:
    """I tag si ordinano per data di creazione, non per prossimità a HEAD.

    Scenario reale: la v0.2.0 viene pubblicata e poi si corregge qualcosa con un
    merge; il tag della v0.2.1 nasce più avanti nel tempo ma punta a un commit
    precedente a un tag successivo solo per caso. ``git describe`` sceglierebbe il
    tag più vicino a HEAD, che non è necessariamente l'ultimo rilasciato — e
    ripubblicherebbe da capo una versione già fuori.
    """
    _commit(repo, "feat: first")
    _tag(repo, "v0.1.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "feat: second")
    _git(repo, "tag", "v9.9.9", env_extra={"GIT_COMMITTER_DATE": "2026-10-05T09:00:00+00:00"})
    _commit(repo, "docs: prose")
    _tag(repo, "v0.2.0", when="2026-10-06T10:00:00+00:00")
    # v9.9.9 è su un commit più vicino a HEAD di v0.2.0, ma è stato creato prima.
    assert nv.last_tag(repo) == "v0.2.0"


def test_drift_between_the_files_and_the_tag_bumps_from_the_higher_one(repo: Path) -> None:
    """Un merge che riporta indietro i file non può far ripubblicare una versione vecchia.

    I file dicono 0.1.0 mentre v0.4.0 è già in giro. Prendendo i file come base
    il bump produrrebbe v0.1.1: un numero **più basso** di una release pubblicata,
    che l'app in attesa rifiuta (l'updater pretende un ``version_code``
    strettamente maggiore) e che il controllo di sanità segnalerebbe come
    versione che torna indietro. Il numero deve salire, e la divergenza va detto.
    """
    _commit(repo, "feat: something")
    _tag(repo, "v0.4.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: and here is a real bug")
    decision = nv.decide(repo)
    assert decision.current == "0.1.0"
    assert decision.base == "0.4.0"
    assert decision.drift is True
    assert decision.version == "0.4.1"


def test_drift_is_reported_when_the_files_are_ahead_of_the_tag(repo: Path) -> None:
    """Il caso opposto: bump fatto a mano, tag non ancora spinto. È comunque divergenza."""
    (repo / "pyproject.toml").write_text(PYPROJECT.replace('"0.1.0"', '"0.3.0"'), encoding="utf-8")
    (repo / "jafta" / "__init__.py").write_text(
        INIT_PY.replace('"0.1.0"', '"0.3.0"'), encoding="utf-8"
    )
    (repo / "android" / "app" / "build.gradle.kts").write_text(
        GRADLE.replace('"0.1.0"', '"0.3.0"'), encoding="utf-8"
    )
    _commit(repo, "chore: bump by hand")
    _tag(repo, "v0.1.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: a real bug")
    decision = nv.decide(repo)
    assert decision.base == "0.3.0"
    assert decision.drift is True
    assert decision.version == "0.3.1"


def test_no_drift_when_the_files_and_the_tag_agree(repo: Path) -> None:
    """Il caso normale: nessun avviso, base pari ai file."""
    _commit(repo, "fix: a real bug")
    _tag(repo, "v0.1.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: another bug")
    decision = nv.decide(repo)
    assert decision.base == "0.1.0"
    assert decision.drift is False


def test_force_overrides_the_commits(repo: Path) -> None:
    """La via d'uscita quando la convenzione non deduce quello che si voleva.

    Serve per la prima release e per le release decise a mano (un rollback, un
    rilascio anticipato): il bump non si deduce da un messaggio, ma la decisione
    resta esplicita e lascia traccia nei log.
    """
    _commit(repo, "docs: prose only")
    assert nv.decide(repo).level == "none"
    forced = nv.decide(repo, force="minor")
    assert (forced.level, forced.version, forced.releasable) == ("minor", "0.2.0", True)


def test_a_body_breaking_change_survives_the_git_round_trip(repo: Path) -> None:
    """La rottura sta spesso nel footer, non nell'oggetto: il body deve arrivare."""
    _commit(repo, "feat: replace the manifest format", body="BREAKING CHANGE: the schema changed")
    assert nv.decide(repo).level == "major"


# --------------------------------------------------------------------------
# La CLI, che è ciò che chiama il workflow
# --------------------------------------------------------------------------


def test_cli_prints_key_value_lines(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _commit(repo, "feat: something")
    assert nv.main(["--repo-root", str(repo)]) == 0
    out = capsys.readouterr().out
    values = dict(line.split("=", 1) for line in out.strip().splitlines())
    assert values["LEVEL"] == "minor"
    assert values["CURRENT"] == "0.1.0"
    assert values["VERSION"] == "0.2.0"
    assert values["TAG"] == ""


def test_cli_json_is_machine_readable(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _commit(repo, "fix: a crash")
    assert nv.main(["--repo-root", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["level"] == "patch"
    assert payload["version"] == "0.1.1"
    assert payload["releasable"] is True


def test_cli_reports_an_empty_tag_as_null_not_as_an_empty_string(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nel JSON una stringa vuota si confonde con un tag chiamato "".

    Il workflow decide con ``if [ -n "$TAG" ]``: un tag vuoto che arriva come
    stringa vuota viene trattato come «nessun tag» anche in JSON, ma in un file
    o in un log la differenza si legge male. ``null`` è inequivocabile.
    """
    assert nv.main(["--repo-root", str(repo), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["tag"] is None


def test_cli_exit_code_is_zero_even_when_there_is_nothing_to_release(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """«Non c'è niente da rilasciare» è un esito normale, non un guasto.

    Un exit 1 farebbe fallire il workflow su ogni merge di documentazione e
    macchierebbe di rosso una serie di run che non hanno errori.
    """
    _commit(repo, "docs: prose")
    assert nv.main(["--repo-root", str(repo)]) == 0
    assert "LEVEL=none" in capsys.readouterr().out


def test_cli_prints_the_base_alongside_the_version(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Il workflow scrive nei file la versione di arrivo; il log deve dire da dove viene.

    Se i file e il tag divergono, BASE e CURRENT sono diversi e nel log si vede:
    un operatore che legge solo VERSION non capirebbe perché il numero è saltato.
    """
    _commit(repo, "feat: something")
    _tag(repo, "v0.4.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: and a real bug")
    assert nv.main(["--repo-root", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "CURRENT=0.1.0" in out
    assert "BASE=0.4.0" in out
    assert "VERSION=0.4.1" in out
    assert "DRIFT=yes" in out


def test_cli_warns_on_drift(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """L'avviso finisce su stdout, dove GitHub lo trasforma in annotazione sul run."""
    _commit(repo, "feat: something")
    _tag(repo, "v0.4.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: and a real bug")
    assert nv.main(["--repo-root", str(repo)]) == 0
    assert "::warning::" in capsys.readouterr().out


def test_cli_json_keeps_stdout_parseable_on_drift(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un avviso su stdout renderebbe il JSON illeggibile per chi lo sta parsando."""
    _commit(repo, "feat: something")
    _tag(repo, "v0.4.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: and a real bug")
    assert nv.main(["--repo-root", str(repo), "--format", "json"]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["drift"] is True
    assert payload["base"] == "0.4.0"
    assert "warning" in captured.err


def test_cli_json_reports_drift_as_false_when_they_agree(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _commit(repo, "fix: a real bug")
    _tag(repo, "v0.1.0", when="2026-10-05T10:00:00+00:00")
    _commit(repo, "fix: another bug")
    assert nv.main(["--repo-root", str(repo), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["drift"] is False
    assert payload["base"] == payload["current"] == "0.1.0"
