# Signing Key

Jafta is signed with a permanent RSA-4096 key for release builds. The keystore
lives at `keystore/jafta-release.keystore` and is **not in the repository**. The
same keystore is required to publish updates to an existing install —
**rotating it means users must uninstall and reinstall, losing all on-device
memory**.

This file *is* tracked, because the fingerprints below are the only thing a
user has to check an install against. Losing the key means losing the ability to
update the app; losing this file means nobody can tell a real build from a fake
one.

## Key identity

| Field | Value |
|---|---|
| Alias / Key ID | `jafta` |
| Algorithm | RSA 4096-bit |
| Signature | SHA384withRSA |
| Subject DN | `CN=Nsamba (NasTech Research), OU=Jafta, O=NasTech Research, L=Johannesburg, ST=Gauteng, C=ZA` |
| Keystore type | PKCS12 |
| Validity | 30 years (2026-10-05 → 2056-09-27) |
| Created | 2026-10-05 (Africa/Johannesburg) |
| Owner | NasTech Research (nastechresearch) |

## For users (verifying an install)

The installed app carries the signing certificate. To check:

```bash
apksigner verify --print-certs path/to/app-release.apk
```

Compare the SHA-256 fingerprint below with the published one. If they differ,
**do not install** — it is not from us.

| Fingerprint | Value |
|---|---|
| SHA-1 | `B8:51:CB:1D:26:F7:E0:18:BC:77:23:56:12:95:B4:EC:8D:18:73:8E` |
| SHA-256 | `BC:7A:9E:9C:37:D8:E1:B8:13:6D:47:6F:1A:BC:5E:EC:96:F3:FD:C5:D5:D3:48:29:7C:CF:C6:E8:15:68:F4:CE` |

## For maintainers (signing a new release)

`android/app/build.gradle.kts` needs all four of these, or `hasReleaseSigning`
is false and `assembleRelease` silently produces an **unsigned** APK:

| Variable | Value |
|---|---|
| `JAFTA_KEYSTORE_PATH` | path to the decoded `.keystore` (set by the workflow) |
| `JAFTA_KEYSTORE_PASSWORD` | keystore (store) password |
| `JAFTA_KEY_ALIAS` | `jafta` |
| `JAFTA_KEY_PASSWORD` | private key password |

`JAFTA_KEY_PASSWORD` equals `JAFTA_KEYSTORE_PASSWORD`: a PKCS12 keystore cannot
hold a key password distinct from the store password. They are separate secrets
only because `build.gradle.kts` reads four independent variables.

The keystore itself travels as a fifth secret, `JAFTA_KEYSTORE_BASE64`, because
GitHub Actions secrets are string-valued and a binary file cannot be one.

To publish all of them:

```bash
python3 scripts/encode_keystore_for_secret.py --set-secrets
```

That verifies the key first (alias, fingerprints, and a round-trip that proves
the password opens the *private key*, not just the store), then uploads through
`gh secret set` with the value on stdin. An earlier version of the script
printed the password and the whole base64 blob for a human to copy, which put
the signing key into terminal scrollback and the clipboard.

To verify without uploading anything:

```bash
python3 scripts/encode_keystore_for_secret.py
```

### Building locally

`keystore.properties` in this directory is read by `build.gradle.kts` and is
gitignored. Without it a local `assembleRelease` is unsigned:

```properties
storeFile=/absolute/path/to/keystore/jafta-release.keystore
storePassword=...
keyAlias=jafta
keyPassword=...
```

## Backup

A copy of the keystore is stored encrypted in the NasTech Research 1Password
vault under **"Jafta Release Signing Key"**. Loss of the keystore = loss of the
ability to update the app for existing users.

**The vault entry is the only backup.** It is not in this repository, not in
CI, and not reproducible: `keygen` would produce a different key, and a
different key means every existing install can never be updated again. If you
are reading this because a release build failed to sign, check the vault before
doing anything else.

## Rotation policy

- **Don't rotate without migration.** Each release must be signed with the
  same key or users cannot upgrade in place.
- If rotation is required (compromise), publish a fresh app under a new
  package id (`com.nastechresearch.jafta.v2`) and migrate users.
