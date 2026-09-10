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

## Collecting from Instagram

Collection is always explicit — nothing runs on a schedule. Pass a source id from
`config/sources.yaml`:

```bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
```

This reads a bounded number of recent public posts and Reels anonymously, maps them onto the
`RawItem` contract, and appends new or changed items to `data/raw/instagram/<username>.jsonl`.
Items are keyed by a stable id (`instagram:<username>:<shortcode>`); rerunning the command with
unchanged content appends nothing, and an edited caption is recorded as a new, auditable
observation rather than silently ignored:

```text
Observed: 5
New: 0
Changed: 0
Existing: 5
```

Useful flags: `--limit` (default 5), `--config` (default `config/sources.yaml`), and
`--data-dir` (default `data`).

Everything under `data/` is runtime output and stays out of Git. GatherRadar collects public
content only; it does not log in, and it does not store cookies or sessions.

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
