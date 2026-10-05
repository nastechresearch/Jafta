#!/usr/bin/env python3
"""
Jafta brand audit — fails CI if any forbidden brand string appears in source.

Forbidden:
- jenny / Jenny / JENNY (upstream project name)
- flagdizero / FlagDiZero / FLAGDIZERO (upstream maintainer)
- HKUDS (upstream upstream, nanobot)
- nanobot (upstream upstream)

Allowed paths (immutable contributor records):
- THIRD_PARTY_NOTICES.md (upstream license chain)
- LICENSE (upstream license)
- keystore/ (signing key, has no brand refs anyway)
- .git/

Exits 0 on clean, 1 on any violation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = [
    re.compile(r"\bjenny\b", re.IGNORECASE),
    re.compile(r"\bflagdizero\b", re.IGNORECASE),
    re.compile(r"\bHKUDS\b"),
    re.compile(r"\bnanobot\b", re.IGNORECASE),
]
EXEMPT_DIRS = {".git", "keystore", "node_modules", "__pycache__", ".venv", "build", "dist"}
EXEMPT_FILES = {"LICENSE", "THIRD_PARTY_NOTICES.md", "SECURITY.md"}
SCAN_EXTS = {
    ".py", ".kt", ".java", ".js", ".ts", ".html", ".css", ".md",
    ".toml", ".json", ".yml", ".yaml", ".gradle", ".kts",
    ".xml", ".txt", ".sh",
}


def is_exempt(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in EXEMPT_DIRS for p in parts):
        return True
    if Path(rel).name in EXEMPT_FILES:
        return True
    return False


def main() -> int:
    violations: list[tuple[str, str, int, str]] = []  # (file, pattern, line, text)
    count_scanned = 0
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if is_exempt(str(rel)):
            continue
        if path.suffix.lower() not in SCAN_EXTS:
            continue
        count_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for pat in FORBIDDEN:
                if pat.search(line):
                    violations.append((str(rel), pat.pattern, i, line.strip()[:120]))
                    break
    if not violations:
        print(f"OK — {count_scanned} files scanned, no forbidden brand strings.")
        return 0
    print(f"FAIL — {len(violations)} brand violation(s) in {count_scanned} files:")
    by_file: dict[str, list[tuple[str, int, str]]] = {}
    for f, p, line_no, t in violations:
        by_file.setdefault(f, []).append((p, line_no, t))
    for f, items in sorted(by_file.items()):
        print(f"\n  {f}")
        for p, line_no, t in items[:5]:
            print(f"    L{line_no} [{p}]: {t}")
        if len(items) > 5:
            print(f"    ...and {len(items) - 5} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
