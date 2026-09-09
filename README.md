# GatherRadar

> AI-assisted event discovery for small communities.

GatherRadar collects event information from a curated set of public websites and
Instagram pages, turns it into consistent event records, and sends review-ready
results to Google Sheets. The first version is a private MVP for planning
activities with a community of roughly 20–40 people.

## MVP

- Collect public event content from approved sources.
- Extract and normalize dates, locations, categories, prices, and links.
- Keep every event traceable to its source.
- Detect likely duplicates and flag uncertain data for human review.
- Publish a clean, filterable event list to Google Sheets.

```text
Curated sources → collection → extraction → normalization → deduplication → review → Google Sheets
```

Automated Telegram publishing, recommendations, a public dashboard, and a
multi-user product are intentionally deferred until the discovery workflow has
been validated.

## Project docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product scope, data contract, and MVP architecture
- [AGENTS.md](AGENTS.md) — working rules for coding agents and contributors

## Status

Early MVP planning and foundation.

## License

Licensed under the [MIT License](LICENSE).
