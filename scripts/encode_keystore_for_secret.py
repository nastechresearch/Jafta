#!/usr/bin/env python3
"""Check the release signing key and publish it as GitHub Actions secrets.

What ``android/app/build.gradle.kts`` needs to sign a release build, all four
or it falls back to an unsigned APK:

===============================  ==========================================
``JAFTA_KEYSTORE_PATH``          path to the decoded ``.keystore``
``JAFTA_KEYSTORE_PASSWORD``      keystore (store) password
``JAFTA_KEY_ALIAS``              key alias inside the keystore
``JAFTA_KEY_PASSWORD``           private key password
===============================  ==========================================

The keystore itself travels as a fifth secret, ``JAFTA_KEYSTORE_BASE64``,
because GitHub Actions secrets are string-valued and a binary file cannot be
one.

This replaces the earlier version of this script, which printed the password
and the whole base64 blob to stdout for a human to copy into a web form. That
put a 30-year release signing key into the terminal scrollback, the clipboard,
and every screenshot taken since. ``--set-secrets`` does the upload instead, by
piping into ``gh secret set``, so the material never leaves the process.

Usage::

    python3 scripts/encode_keystore_for_secret.py              # verify, print no secrets
    python3 scripts/encode_keystore_for_secret.py --set-secrets  # upload to GitHub

Requires ``keytool`` (any JDK) and, for ``--set-secrets``, the ``gh`` CLI with
write access to the repository.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Where the key lives. Overridable so the script still works if the key is
#: restored from a backup to some other path.
KEYSTORE = REPO / "keystore" / "jafta-release.keystore"
STOREPASS_FILE = REPO / "keystore" / ".storepass"

SECRET_KEYSTORE = "JAFTA_KEYSTORE_BASE64"
SECRET_PASSWORD = "JAFTA_KEYSTORE_PASSWORD"
SECRET_ALIAS = "JAFTA_KEY_ALIAS"
SECRET_KEY_PASSWORD = "JAFTA_KEY_PASSWORD"

GITHUB_REPO = "nastechresearch/Jafta"


class SigningKeyError(Exception):
    """Something the operator has to fix. Printed without a traceback."""


def _die(msg: str) -> SigningKeyError:
    return SigningKeyError(msg)


def read_storepass() -> str:
    """The store password, or the ``JAFTA_KEYSTORE_PASSWORD`` env var."""
    env = os.environ.get(SECRET_PASSWORD, "").strip()
    if env:
        return env
    if not STOREPASS_FILE.exists():
        raise _die(
            f"{STOREPASS_FILE} is missing, and {SECRET_PASSWORD} is not set.\n"
            "  The password is not in the repository on purpose. Restore it from the\n"
            "  1Password vault entry 'Jafta Release Signing Key', write it to\n"
            f"  {STOREPASS_FILE} (chmod 600), or export {SECRET_PASSWORD} for this run."
        )
    pw = STOREPASS_FILE.read_text(encoding="utf-8").strip()
    if not pw:
        raise _die(f"{STOREPASS_FILE} is empty.")
    return pw


def keytool(args: list[str], storepass: str) -> str:
    """Run ``keytool`` with the password in the environment, not in argv.

    ``keytool -storepass <pw>`` puts the release key's password in the process
    table, where any user on the machine can read it from ``/proc``. The
    ``:env`` form does not.
    """
    if shutil.which("keytool") is None:
        raise _die("keytool not found. Install a JDK (it ships with Android Studio).")
    env = {**os.environ, "JAFTA_SIGNING_STORE_PASS": storepass}
    proc = subprocess.run(
        ["keytool", *args, "-storepass:env", "JAFTA_SIGNING_STORE_PASS"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if proc.returncode != 0:
        raise _die(
            f"keytool {' '.join(args[:2])} failed:\n{proc.stderr.strip()}\n"
            "  If this says the password is wrong, compare the key against the\n"
            "  fingerprints in keystore/README.md before retrying — a mismatched key\n"
            "  would silently strand every installed app on an un-upgradeable build."
        )
    return proc.stdout


def describe(keystore: Path, storepass: str) -> tuple[str, dict[str, str]]:
    """Alias and fingerprints, straight from the key. Never includes secrets."""
    out = keytool(["-list", "-v", "-keystore", str(keystore)], storepass)
    info: dict[str, str] = {}
    alias = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Alias name:"):
            alias = line.split(":", 1)[1].strip()
        elif line.startswith(("Owner:", "Issuer:", "Valid from:", "Signature algorithm name:")):
            info[line.split(":", 1)[0].lower().replace(" ", "_")] = line.split(":", 1)[1].strip()
        elif line.startswith(("SHA1:", "SHA256:")):
            info[line.split(":", 1)[0].lower()] = line.split(":", 1)[1].strip()
    if alias is None:
        raise _die(f"No alias found in {keystore}. Is it really a keystore?")
    return alias, info


def verify_roundtrip(keystore: Path, storepass: str, alias: str) -> None:
    """Prove the store password really opens the private key, not just the store.

    Reading ``-list`` only shows the certificates; a PKCS12 whose key was
    protected with a different password still lists fine and only fails later,
    during ``apksigner`` in the middle of a release. This round-trips the key
    through ``importkeystore`` first so the failure lands here instead.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "roundtrip.p12"
        keytool(
            [
                "-importkeystore",
                "-srckeystore", str(keystore),
                "-srcstorepass:env", "JAFTA_SIGNING_STORE_PASS",
                "-srcalias", alias,
                "-srckeypass:env", "JAFTA_SIGNING_STORE_PASS",
                "-destkeystore", str(dest),
                "-deststoretype", "PKCS12",
                "-deststorepass:env", "JAFTA_SIGNING_STORE_PASS",
                "-destkeypass:env", "JAFTA_SIGNING_STORE_PASS",
            ],
            storepass,
        )
    print(f"  private key for alias {alias!r} opens with the same password (PKCS12)")


def set_secret(name: str, value: str, repo: str) -> None:
    """Push one secret through ``gh``, value on stdin, never in argv or stdout.

    The value goes in on stdin and ``--body`` is deliberately absent. ``--body``
    takes the value literally: ``--body -`` stores the single character ``-``,
    not stdin, so every secret silently becomes a one-character string. ``gh``
    reports success for that, the secret exists in the repository settings, and
    the first workflow to use it fails with a value that looks merely unset.
    """
    if shutil.which("gh") is None:
        raise _die("gh not found; install the GitHub CLI to upload secrets.")
    proc = subprocess.run(
        ["gh", "secret", "set", name, "--repo", repo],
        input=value,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise _die(f"gh secret set {name} failed:\n{proc.stderr.strip()}")
    print(f"  set {name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--set-secrets",
        action="store_true",
        help="upload the keystore and its credentials as repository secrets via gh",
    )
    ap.add_argument("--repo", default=GITHUB_REPO, help="target repository (default: %(default)s)")
    ap.add_argument("--keystore", type=Path, default=KEYSTORE, help="path to the .keystore")
    args = ap.parse_args()

    keystore: Path = args.keystore

    if not keystore.exists():
        raise _die(
            f"{keystore} not found.\n"
            "  This key is deliberately not in the repository. Restore it from the\n"
            "  1Password vault entry 'Jafta Release Signing Key'. If it is genuinely\n"
            "  gone, see the rotation policy in keystore/README.md — do NOT generate a\n"
            "  replacement in place, that strands every existing install."
        )

    storepass = read_storepass()

    print(f"keystore: {keystore}  ({keystore.stat().st_size} bytes)")
    alias, info = describe(keystore, storepass)
    print(f"alias:    {alias}")
    for key in ("owner", "valid_from", "signature_algorithm_name", "sha1", "sha256"):
        if key in info:
            print(f"{(key + ':'):<24}{info[key]}")
    verify_roundtrip(keystore, storepass, alias)

    if not args.set_secrets:
        print(
            "\nKeystore verified. Nothing was uploaded and no secret was printed.\n"
            f"Run with --set-secrets to publish {SECRET_KEYSTORE}, {SECRET_PASSWORD},\n"
            f"{SECRET_ALIAS} and {SECRET_KEY_PASSWORD} to {args.repo}."
        )
        return 0

    encoded = base64.b64encode(keystore.read_bytes()).decode("ascii")
    print(f"\nuploading to {args.repo} (values go over the GitHub API, not stdout):")
    set_secret(SECRET_KEYSTORE, encoded, args.repo)
    set_secret(SECRET_PASSWORD, storepass, args.repo)
    set_secret(SECRET_ALIAS, alias, args.repo)
    # A PKCS12 keystore cannot hold a key password distinct from the store
    # password, so this equals SECRET_PASSWORD. It is still sent separately
    # because build.gradle.kts reads four independent variables and a future
    # switch to a JKS keystore should not need a workflow change.
    set_secret(SECRET_KEY_PASSWORD, storepass, args.repo)
    print("\ndone. Verify with: gh secret list --repo " + args.repo)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SigningKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
