# Changelog

What changed in each release of Jafta, written for the person holding the phone. The
version numbers follow [Semantic Versioning](https://semver.org/): from 1.0 on, a change that
breaks something you rely on gets a new major number.

Releases before 1.0 are described only on their
[GitHub release pages](https://github.com/nastechresearch/Jafta/releases).

> **Jafta note:** Jafta is a rebrand and continuation of [Jafta 1.0.0](https://github.com/nastechresearch/jafta-android-ai-agent)
> (released 2026-10-02). All Jafta 1.0.0 entries below describe behavior that ships
> unmodified in Jafta. New Jafta-specific entries appear at the top of each version block.

## [0.1.0] — 2026-10-05

The first Jafta release. Mechanical rebrand of Jafta 1.0.0 — no behavior changes.

### Rebrand
- Package renamed: `jafta` → `jafta` (Python module + WebUI)
- WebUI files renamed: `home-jafta.js` → `home-jafta.js`, `jafta-sdk.js` → `jafta-sdk.js`, etc.
- Repository URL updated to `nastechresearch/Jafta`
- Build and release infrastructure added (see below)
- Brand audit script (`scripts/brand_audit.py`) added for CI
- Android package id, Kotlin namespace, and asset strings still carry the original
  `com.nastechresearch.jafta` values — this is intentional, those land in the next PR cluster
  so this PR stays mechanical and reviewable.

### Build
- New: `.github/workflows/android.yml` — Android build + signed release APK on `main`
- New: `.github/workflows/release.yml` — tag-triggered release with verified signature + SHA-256 manifest
- New: `.github/workflows/pages.yml` — GitHub Pages deployment for docs
- New: `keystore/jafta-release.keystore` — permanent RSA-4096 release key, alias `jafta`,
  30-year validity, signed by `CN=Nsamba (NasTech Research), O=NasTech Research, C=ZA`.
  Keystore is gitignored; stored as `JAFTA_KEYSTORE_BASE64` + `JAFTA_KEYSTORE_PASSWORD`
  GitHub secrets. See `keystore/README.md`.
- New: `scripts/brand_audit.py` — fails CI on any `jafta` / `nastechresearch` / `nanobot` /
  `HKUDS` reference in source. Will be wired into CI in a follow-up PR after the rest
  of the rebrand lands.

## [1.0.0] — 2026-10-02

The first stable release. Over 800 changes since 0.11.0. The biggest one is a new home
screen built around the conversation, and the old interface becomes the workshop behind it.

### Highlights

- **A new home.** Jafta opens on a home of swipeable pages: Apps, Jafta (the chat),
  Notebooks and Settings. A row of page names at the top replaces the drawer button and the
  dots. You can pin a Jafta App or a notebook as a page of its own, from where it lives.
- **The workshop.** The previous interface lives on behind Settings, regrouped into four
  drawers: Console, Brain, Hands and Memory.
- **Jafta outside the app.** She can float above other apps and you can talk to her there,
  in a short conversation with rendered Markdown. You can also reply to her straight from the
  notification shade, and the shade shows the exchange as one conversation.
- **Notebooks in the home.** A notebook opens on its own chat, its pages and its map. From
  the reader you can edit a page and report a passage, and the report lands in that
  notebook's chat.

### Home and chat

- Chat text can be selected and copied, and a Copy button sits under every reply.
- Formulas and diagrams render in both shells.
- Older history loads page by page in both shells, and a reply that is streaming stays
  below the history that loads above it.
- A message the gateway refuses comes back to the composer, with the reason in your
  language, instead of disappearing.
- Videos are recognised as videos before they are sent.
- The minichat opens wherever the chat is not on screen, in both shells.
- The status bar and the working line wear Jafta's flower, and the working line stays lit
  through tool runs and subagent waits.
- Jafta's mood comes from the emoji in her reply. The model is not asked for it.
- The assistant carries the name you gave her. The app itself stays Jafta.

### Themes and look

- Synthwave '84 is now near-black and the default theme. Its own bubble is solid pink with
  white text.
- The loading screen and the system splash wear the last theme you chose.
- The theme is picked on Settings, where you can see it.

### Notebooks and wiki

- Creating a notebook asks for its name and then for one line on what it is about. A wrong
  name keeps the dialog open and says the rule first.
- A notebook can be renamed or deleted from its sheet. Both are refused while Jafta is
  still working in it, and the refusal says so in your language.
- The map keeps a dot where you drag it, follows a notebook's rename and leaves with its
  deletion.
- The audit format drops its severity field, in the skill too.

### Workshop

- **Brain** holds the providers as brands with their models. One tap on a model makes it
  answer.
- **Hands** shows what Jafta does for you: skills, scheduled jobs, Telegram and SSH. A
  scheduled job of yours can be paused, resumed or removed from there.
- **Memory** holds the file manager. Delete, rename and copy run as WebSocket commands and
  never overwrite.
- The first-run wizard is now a page of its own.

### Providers and models

- OpenCode Go is supported.
- A provider's base URL is checked before it is saved.
- A provider key or a Telegram token saved from Settings takes effect at once, without a
  restart.
- Streams are more robust:
  - a dropped keep-alive or a reset connection is retried;
  - an interrupted or error-ending stream is reported as an error, not as a complete reply;
  - a retry does not repeat the thinking and tool output already shown;
  - the wait announced by a provider's Retry-After is capped and shown to you.
- The configured temperature reaches the models that accept it. The Anthropic thinking
  budget fits inside the configured max tokens.

### Memory, Dream and the agent

- Dream reads every diary entry whole, keeps up when the chat and a notebook take turns,
  and no longer loses the conversation when a consolidation call fails.
- After `/stop` or a crash the history keeps the whole turn.
- Rules you give Jafta survive the night. Dream no longer erases them or counts them
  against its budget.
- Each conversation has its own `python_exec` globals, and waiting on a `python_exec`
  session no longer freezes the gateway.
- Subagent and consolidation calls count in the token usage.

### Telegram, SSH and the browser

- Attachments sent on Telegram reach Jafta.
- Telegram pairs only from a private chat, and after pairing it listens only to that
  person. Unpairing asks first.
- SSH works with ECDSA and large RSA host keys. Downloads stop at the byte limit and never
  overwrite a partial file.
- The agent's browser blocks the same private and local addresses as the Python network
  guard, including WebSocket, WebRTC and service-worker traffic.

### Backup, updates and settings

- A large backup exports without the 10-second cut and without holding the whole file in
  memory.
- Back closes the backup passphrase dialog instead of the screen beneath it.
- Updates says you have the latest version only after a check that actually worked.
- `config.json` is private from the moment it exists. A value this version does not know
  costs only its own field, and a settings save resolves `${VAR}` references like a start
  does.
- Onboarding sends the first API key over the WebSocket, never in a URL.

### Accessibility

- Every word in every theme reaches a contrast of 4.5:1, and keyboard focus shows in every
  theme.
- Buttons have real accessible names, and small close buttons answer on 24 px or more.
- The workshop dock can be reached from a physical keyboard.

### Changed in ways you may notice

- **The WebUI follows the phone's language.** An old saved language choice is no longer
  remembered.
- **Built-in skills cannot be switched off.** Skills now say whether they ship with the
  app.
- **Cron expressions are evaluated by Jafta itself.** The `croniter` dependency is gone. An
  expression that would never fire is refused when the job is added, and an interval of zero
  or less is refused too.
- **The all-notebooks graph is gone.** The `/api/graph` route now needs a notebook name.
- **Skills can no longer be deleted over HTTP.**
- **Saved home pages and preferences are migrated.** The interface's vocabulary was renamed
  to English, and saved pages, theme ids, mascot keys and workshop drawers carry over
  automatically.
