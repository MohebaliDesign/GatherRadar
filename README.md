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

The first curated registry lives in `config/sources.yaml`. No live crawling is enabled yet.

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests
```

## Project docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product scope, data contract, and MVP architecture
- [AGENTS.md](AGENTS.md) — working rules for coding agents and contributors
- [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) — source and event record boundaries

## Status

Early MVP foundation. Next milestone: one real Instagram source through an isolated Instaloader adapter.

## License

Licensed under the [MIT License](LICENSE).
