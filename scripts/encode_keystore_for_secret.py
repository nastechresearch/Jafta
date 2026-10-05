#!/usr/bin/env python3
"""
Helper: encode keystore to base64 for GitHub Actions secret.

Usage:
    python3 scripts/encode_keystore_for_secret.py

Reads: keystore/jafta-release.keystore + keystore/.storepass
Prints: base64 string to paste into JAFTA_KEYSTORE_BASE64 secret
Also prints: key alias, SHA1, SHA256, validity dates.
"""
from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KS = REPO / "keystore" / "jafta-release.keystore"
PW = REPO / "keystore" / ".storepass"


def main() -> int:
    if not KS.exists():
        print(f"ERROR: {KS} missing. Run keytool -genkeypair first.", file=sys.stderr)
        return 1
    if not PW.exists():
        print(f"ERROR: {PW} missing.", file=sys.stderr)
        return 1
    pw = PW.read_text().strip()
    b64 = base64.b64encode(KS.read_bytes()).decode()
    print("=" * 72)
    print("PASTE THE LINE BELOW INTO:")
    print("  GitHub → nastechresearch/Jafta → Settings → Secrets → Actions")
    print("  New repository secret: JAFTA_KEYSTORE_BASE64")
    print("=" * 72)
    print(b64)
    print("=" * 72)
    print()
    print("ALSO SET THESE SECRETS:")
    print(f"  JAFTA_KEYSTORE_PASSWORD  =  {pw}")
    print()
    print("=" * 72)
    print("KEY METADATA (for CHANGELOG / docs):")
    print("=" * 72)
    out = subprocess.check_output(
        ["keytool", "-list", "-v", "-keystore", str(KS), "-storepass", pw],
        text=True,
    )
    for line in out.splitlines():
        if any(k in line for k in ("Alias", "Creation", "Valid", "SHA1", "SHA256", "Owner", "Issuer")):
            print(line)


if __name__ == "__main__":
    rc = main()
    sys.exit(rc if rc is not None else 0)
