# Signing Key

Jafta is signed with a permanent RSA-4096 key for release builds. The keystore
lives at `keystore/jafta-release.keystore` (gitignored). The same keystore is
required to publish updates to an existing install — **rotating it means users
must uninstall and reinstall, losing all on-device memory**.

## Key identity

| Field | Value |
|---|---|
| Alias / Key ID | `jafta` |
| Algorithm | RSA 4096-bit |
| Signature | SHA384withRSA |
| Subject DN | `CN=Nsamba (NasTech Research), OU=Jafta, O=NasTech Research, L=Johannesburg, ST=Gauteng, C=ZA` |
| Validity | 30 years (2026-10-05 → 2056-09-27) |
| Created | 2026-10-05 (Africa/Johannesburg) |
| Owner | NasTech Research (nastechresearch) |

## For users (verifying an install)

The installed app carries the signing certificate. To check:

```bash
apksigner verify --print-certs path/to/app-release.apk
```

Compare the SHA-256 fingerprint below with the published one. If they differ,
**do not install** — it's not from us.

| Fingerprint | Value |
|---|---|
| SHA-1 | `B8:51:CB:1D:26:F7:E0:18:BC:77:23:56:12:95:B4:EC:8D:18:73:8E` |
| SHA-256 | `BC:7A:9E:9C:37:D8:E1:B8:13:6D:47:6F:1A:BC:5E:EC:96:F3:FD:C5:D5:D3:48:29:7C:CF:C6:E8:15:68:F4:CE` |

## For maintainers (signing a new release)

The keystore + password are stored as GitHub repository secrets:

- `JAFTA_KEYSTORE_BASE64` — base64 of `jafta-release.keystore`
- `JAFTA_KEYSTORE_PASSWORD` — the store password

To re-encode after rotation:

```bash
python3 scripts/encode_keystore_for_secret.py
```

Then paste the output into the GitHub repo secrets page.

## Backup

A copy of the keystore is stored encrypted in the NasTech Research 1Password
vault under **"Jafta Release Signing Key"**. Loss of the keystore = loss of the
ability to update the app for existing users.

## Rotation policy

- **Don't rotate without migration.** Each release must be signed with the
  same key or users cannot upgrade in place.
- If rotation is required (compromise), publish a fresh app under a new
  package id (`za.nastech.jafta.v2`) and migrate users.
