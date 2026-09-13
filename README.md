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

Requires Python 3.11+.

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests
```

On Windows, activate the environment with `.venv\Scripts\activate`; on macOS and Linux use
`source .venv/bin/activate`.

The test suite is offline. It never contacts Instagram, and no test needs credentials.

## Authenticating with Instagram

Anonymous Instagram access is blocked (HTTP 429) for this project's sources, so collection
requires one authenticated local session. Authentication is a separate concept from the
public sources being collected: you log in once as your own Instagram account (for example
`instaloader.crawler`), and that single session is reused to crawl every approved public
source (`davvvat`, `vadoostan`, `jabama.events`, ...). The collector never needs to know the
login account's username in advance, and the login account is never treated as a source to
crawl.

```bash
python -m gatherradar auth instagram
```

This does not take a username or password argument. It interactively prompts for an
Instagram `Cookie` request-header string, copied from an already logged-in browser session
(e.g. from your browser's devtools on instagram.com), and reads it with `getpass` so it is
never echoed to the terminal:

```text
GatherRadar Instagram authentication
Paste Instagram Cookie header: [hidden]

Verifying session...

Authenticated as @instaloader.crawler
Session saved successfully.
```

The pasted cookie is parsed, handed to Instaloader (`update_cookies` + `test_login`), and
never printed, logged, or stored — only the resulting Instaloader session is saved locally
under `data/sessions/`, alongside non-secret metadata recording which account is active:

```text
data/sessions/instagram-active.json
data/sessions/instagram-instaloader.crawler.session
```

Session files remain purely local and are Git-ignored; no passwords or cookies are ever
committed. If no session has been configured yet, collection fails with an actionable error
telling you to run `auth instagram` first.

## Collecting from Instagram

Collection is always explicit — nothing runs on a schedule. Pass a source id from
`config/sources.yaml`:

```bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
```

This loads the active authenticated session, then reads a bounded number of recent public
posts and Reels from the target source, maps them onto the `RawItem` contract, and appends
new or changed items to `data/raw/instagram/<username>.jsonl`. Items are keyed by a stable id
(`instagram:<username>:<shortcode>`); rerunning the command with unchanged content appends
nothing, and an edited caption is recorded as a new, auditable observation rather than
silently ignored:

```text
Observed: 5
New: 0
Changed: 0
Existing: 5
```

Useful flags: `--limit` (default 5), `--config` (default `config/sources.yaml`), and
`--data-dir` (default `data`).

Everything under `data/` is runtime output and stays out of Git. GatherRadar collects public
content only, targeted at accounts the owner has explicitly approved in `config/sources.yaml`.

## Project docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product scope, data contract, and MVP architecture
- [AGENTS.md](AGENTS.md) — working rules for coding agents and contributors
- [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) — source and event record boundaries

## Status

Early MVP. The Instagram collection pipeline is implemented and verified with offline tests.
Live Instagram access is currently being validated.
Next milestone: event detection over collected raw items.

## License

Licensed under the [MIT License](LICENSE).
