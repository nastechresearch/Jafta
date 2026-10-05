"""Lo slug del repo non può diventare uno che non esiste.

Il ribranding ha lasciato in giro ``nastechresearch/jafta-android-ai-agent``:
un repo che non è mai esistito, e che non esisterà. Compariva in 24 posti, e la
CI lo ha lasciato passare per anni perché i test che lo riguardavano lo
confrontavano **solo con un'altra costante sbagliata nello stesso modo** —
``assert release.DEFAULT_REPO in update_check.DEFAULT_MANIFEST_URL`` regge
qualsiasi slug, purché sia sbagliato in modo coerente. Nessuno chiedeva se quel
repo esistesse.

Non è un problema di link morti. Due di quei punti finiscono nell'APK:

* ``runtime/update_manifest.DEFAULT_MANIFEST_URL`` è l'URL che l'app interroga
  a ogni avvio per cercare aggiornamenti. Con lo slug sbagliato l'update check
  non ha semplicemente restituito "nessun aggiornamento": ha fatto una richiesta
  di rete a un host che non esiste, ogni volta, e l'ha trattata come risposta
  valida.
* ``providers.openai_compat_helpers._DEFAULT_OPENROUTER_HEADERS`` finisce
  nell'header ``HTTP-Referer`` di ogni chiamata OpenRouter.

Per questo i tre test qui sotto hanno tre forme diverse, e non è ridondanza:

1. ``test_repo_slug_stays_canonical`` — percorre i file tracciati e rifiuta
   qualunque slug della nostra organizzazione che non sia quello giusto.
   Copre documentazione, workflow e issue template: posti che nessun test
   funzionale guarda, e dove il prossimo ribranding lascerebbe di nuovo lo
   stesso casino.
2. ``test_the_shipped_repo_constants_are_pinned`` — fissa i letterali delle
   tre costanti che finiscono dentro l'app. Letterali, non costanti derivate:
   è l'unico modo che un confronto fra due valori sbagliati non possa passare.
3. ``test_upstream_is_still_credited_where_it_is_the_only_source`` — impedisce
   la correzione opposta, cioè riscrivere a ``Jafta`` anche i riferimenti che
   esistono **solo** upstream.

Il confronto sullo slug è case-insensitive (``nastechresearch/jafta`` va bene e
GitHub lo redirige), ma il canonicalizzazione viene verificata esattamente nei
punti che contano: i tre letterali del test 2.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from jafta.providers import openai_compat_helpers
from jafta.runtime import update_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]

#: L'unico repo dell'organizzazione. Tutti gli altri slug sono sbagliati per
#: definizione: non c'è un allowlist da mantenere, c'è un solo nome giusto.
CANONICAL_REPO = "jafta"

#: Riferimenti che devono restare su Jenny: non sono dimenticanze del
#: ribranding, sono gli unici punti in cui quell'informazione esiste.
UPSTREAM_REPO = "flagdizero/jenny-android-ai-agent"

_SLUG_RE = re.compile(r"github\.com[/:](?P<org>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+)")

#: Directory che non contengono sorgente tracciato e/o possono essere enormi.
_SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "__pycache__", "node_modules", ".gradle", "build", "dist", ".pytest_cache"}
)


def _tracked_files() -> list[Path]:
    """I file tracciati da git, o l'albero della repo se git non è disponibile."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        # Fuori da un checkout (sdist, installazione) non sappiamo cosa è
        # tracciato; l'albero è più rumoroso ma copre comunque i sorgenti.
        return [
            p
            for p in REPO_ROOT.rglob("*")
            if p.is_file() and not any(part in _SKIP_DIRS for part in p.relative_to(REPO_ROOT).parts)
        ]
    return [REPO_ROOT / name for name in out.stdout.decode("utf-8").split("\0") if name]


def _text(path: Path) -> str:
    """Il contenuto come testo, senza morire sui binari.

    ``templates/ui/assets/mobile-chat.js`` contiene un byte NUL (un separatore
    ``'\\0'`` in un join upstream): decodificare con ``errors="ignore"`` è quindi
    un requisito, non una scorciatoia.
    """
    try:
        return path.read_bytes().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def test_repo_slug_stays_canonical() -> None:
    """Nessun riferimento alla nostra organizzazione può puntare a un altro repo."""
    wrong: list[str] = []

    for path in _tracked_files():
        if path.suffix == ".py" and path.name == Path(__file__).name:
            continue  # questo file contiene gli slug come dati di test
        try:
            rel = path.relative_to(REPO_ROOT)
        except ValueError:  # pragma: no cover - difensivo
            continue
        for line_no, line in enumerate(_text(path).splitlines(), 1):
            for m in _SLUG_RE.finditer(line):
                if m.group("org").lower() != "nastechresearch":
                    continue
                repo = m.group("repo").removesuffix(".git").removesuffix(".")
                if repo.lower() != CANONICAL_REPO:
                    wrong.append(f"{rel}:{line_no}: {m.group(0)}")

    assert not wrong, (
        "slug inesistenti per nastechresearch — l'unico repo è "
        f"{CANONICAL_REPO!r}:\n  " + "\n  ".join(sorted(wrong))
    )


def test_the_shipped_repo_constants_are_pinned() -> None:
    """Le tre costanti che finiscono nell'APK, fissate per esteso."""
    from scripts import release as release_script  # noqa: PLC0415 - import tardi per ciclo

    assert release_script.DEFAULT_REPO == "nastechresearch/Jafta", (
        "scripts/release.py pubblica su DEFAULT_REPO: se lo slug è sbagliato "
        "il manifest viene pubblicato su un repo che non esiste e nessuno "
        "scarica l'APK"
    )

    assert update_manifest.DEFAULT_MANIFEST_URL == (
        "https://github.com/nastechresearch/Jafta/releases/latest/download/latest.json"
    ), "è l'URL che l'app interroga a ogni avvio per cercare aggiornamenti"

    assert (
        openai_compat_helpers._DEFAULT_OPENROUTER_HEADERS["HTTP-Referer"]
        == "https://github.com/nastechresearch/Jafta"
    ), "va in ogni richiesta OpenRouter dell'app"


def test_upstream_is_still_credited_where_it_is_the_only_source() -> None:
    """Riferimenti che valgono solo su Jenny: riscriverli li renderebbe morti.

    ``nastechresearch/Jafta`` non ha issue e non ha tag. I due punti che
    citano ``#12`` e ``v0.3.0`` descrivono la storia di Jenny e i numeri vivono
    solo nel repo upstream: spostarli su ``Jafta`` produrrebbe due link rotti
    al posto di due link corretti.
    """
    providers = (REPO_ROOT / "docs" / "reference" / "providers.md").read_text(encoding="utf-8")
    assert f"github.com/{UPSTREAM_REPO}/issues/12" in providers, (
        "l'issue #12 (certificato CA non applicato a caldo) è di Jenny: sta a monte"
    )

    release_script = (REPO_ROOT / "scripts" / "release.py").read_text(encoding="utf-8")
    assert f"github.com/{UPSTREAM_REPO}/releases/tag/v0.3.0" in release_script, (
        "la prima release che pubblicava la chiave di firma è la 0.3.0 di Jenny: sta a monte"
    )
