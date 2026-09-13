# GatherRadar

> AI-assisted event discovery for small communities.

GatherRadar collects event information from a curated set of public websites and Instagram pages, turns it into consistent event records, and sends review-ready results to Google Sheets. The first version is a private MVP for planning activities with a community of roughly 20–40 people.

## MVP

- Collect public event content from approved sources.
- Extract and normalize dates, locations, categories, prices, and links.
- Keep every event traceable to its source.
- Detect likely duplicates and flag uncertain data for human review.
- Publish a clean, filterable event list to Google Sheets.

```text
Curated sources → collection → extraction → normalization → deduplication → review → Google Sheets
```

Automated Telegram publishing, recommendations, a public dashboard, and a multi-user product are intentionally deferred until the discovery workflow has been validated.

## Current foundation

The repository now defines the initial source registry and the shared data contracts used by future website and Instagram collectors:

```text
Source → RawItem → EventCandidate → Event
```

The first curated registry lives in `config/sources.yaml`. The Instagram collector is the
only live path so far, and it runs only when invoked explicitly.

## Development

Requires Python 3.11+ (developed on Python 3.13). Live Instagram collection also requires
Google Chrome installed on the machine.

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests
```

On Windows, activate the environment with `.venv\Scripts\activate`; on macOS and Linux use
`source .venv/bin/activate`.

`pip install -e .` installs the Playwright Python package. GatherRadar drives your installed
Google Chrome through Playwright (`channel="chrome"`), so Playwright's bundled browsers are not
needed and `playwright install` is not required. If Google Chrome is not installed, install it
normally, or run `python -m playwright install chrome`.

The test suite is offline. It never launches Chrome, never contacts Instagram, and no test needs
credentials.

## Instagram browser profile

Instagram collection runs in a real, visible Chrome window that uses a dedicated GatherRadar
browser profile:

```text
data/browser/instagram-profile/
```

This profile is separate from your normal Chrome profile, so your personal browser is never
touched or locked. The profile itself holds the Instagram login; GatherRadar does not store
passwords or cookies anywhere else.

### Log in once

```bash
python -m gatherradar auth instagram
```

This opens Chrome on Instagram with the GatherRadar profile. Log in manually in that window if
needed — GatherRadar never asks for your password — then return to the terminal:

```text
GatherRadar Instagram authentication

Opening Chrome with the GatherRadar browser profile:
data/browser/instagram-profile

Log in to Instagram in the opened Chrome window.
When the Instagram home page is visible, return here and press Enter.

Verifying session...

Instagram browser session verified.
Persistent profile saved.
```

GatherRadar checks that the window has left Instagram's login flow and that the profile holds
an Instagram login (it never prints cookie values), then closes Chrome.

The login usually persists between runs. If Instagram expires it, collection stops with:

```text
Instagram browser session is not authenticated.
Run:

python -m gatherradar auth instagram
```

Rerun `python -m gatherradar auth instagram` to log in again. If Instagram shows a
verification or checkpoint page, complete it manually in that Chrome window; GatherRadar does
not bypass it.

## Collecting from Instagram

Collection is always explicit — nothing runs on a schedule. Pass a source id from
`config/sources.yaml`:

```bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
```

Chrome does not need to be open. GatherRadar launches its own Chrome window on the GatherRadar
profile, then:

1. confirms the profile is still logged in to Instagram;
2. opens the source profile, e.g. `https://www.instagram.com/davvvat/`;
3. finds posts and reels from their `/p/` and `/reel/` links, taking a small candidate pool
   of up to three more than `--limit` (at most 12 in total unless `--limit` itself is
   larger), scrolling a few times at most and only while fewer candidates are visible;
4. opens each candidate page to read its caption and publish time, then keeps the `--limit`
   newest by publish date, so older pinned posts at the top of the grid do not take recent
   slots (items without a publish date sort last);
5. maps them onto the `RawItem` contract and appends new or changed items to
   `data/raw/instagram/<username>.jsonl`;
6. closes Chrome, including when the run fails.

Captions are read from the rendered post — the caption heading, the author's first caption
item, or the author's caption text — with Open Graph and page description metadata only as a
fallback. Author usernames, comments, timestamps, like counts, and interface labels are left
out, and a post without a caption keeps empty text. `raw_metadata.caption_source` records
which source was used.

Close any Chrome window that GatherRadar left open before collecting; a browser profile can be
used by only one Chrome instance at a time.

Items are keyed by a stable id (`instagram:<username>:<shortcode>`); rerunning the command with
unchanged content appends nothing, and an edited caption is recorded as a new, auditable
observation rather than silently ignored:

```text
Observed: 5
New: 0
Changed: 0
Existing: 5
```

Useful flags: `--limit` (default 5), `--config` (default `config/sources.yaml`),
`--data-dir` (default `data`), and `--transport` (default `browser`).

### Legacy Instaloader transport

The earlier Instaloader transport is kept only as a fallback reference, since its profile
lookup is refused with HTTP 429. The browser transport above is the validated default, and
GatherRadar never falls back to Instaloader automatically. It runs only when requested
explicitly:

```bash
python -m gatherradar auth instagram --legacy-cookie
python -m gatherradar collect instagram davvvat_instagram --transport instaloader
```

### Local data and privacy

Everything under `data/` — the browser profile, raw captures, and legacy session files — is
local runtime data and is ignored by Git. Passwords, cookies, and browser profile files are
never committed. GatherRadar collects only public profiles listed in `config/sources.yaml`.

## Project docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product scope, data contract, and MVP architecture
- [AGENTS.md](AGENTS.md) — working rules for coding agents and contributors
- [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) — source and event record boundaries

## Status

Early MVP. The Instagram Collector milestone is complete: browser-backed collection has been
validated live against `@davvvat` — authentication through the persistent Chrome profile,
real Persian caption extraction, published timestamps and image URLs, recent-item selection
that is not displaced by pinned posts, and New/Changed/Existing behavior across repeated
runs all work as intended.
Next milestone: event detection and structured extraction over collected raw items.

## License

Licensed under the [MIT License](LICENSE).
