# GatherRadar Data Contracts

This document defines the four records used by the MVP pipeline. Collectors may change, but these boundaries should remain stable unless the product contract changes.

```text
Source → RawItem → EventCandidate → Event
```

## Source

A configured place GatherRadar is allowed to inspect. A website and Instagram account for the same publisher are separate sources and share a `publisher_key`.

Key fields: stable `id`, `publisher_key`, `source_type`, canonical `url`, optional Instagram `username`, `enabled`, locale/timezone, and optional `city_hint`.

## RawItem

A source observation before semantic interpretation. Website collectors and Instagram collectors must both produce this same shape.

Key fields: source identity, source-native `external_id`, `content_type`, direct `content_url`, untouched `raw_text`, publication/capture timestamps, author, optional image URL, a `content_hash` fingerprint, and adapter-specific `raw_metadata`.

Raw items are intended for append-friendly JSONL storage during the MVP. They are evidence and debugging material, not the final event list.

### `content_hash`

A deterministic SHA-256 fingerprint over the source-supported fields that matter to
event interpretation: `raw_text`, `published_at`, `content_type`, and `content_url`.
It deliberately excludes `captured_at`, which changes on every run. Any collector can
compute one with `gatherradar.domain.compute_content_hash`; the field and its meaning
are source-neutral, not Instagram-specific.

The content hash lets a rerun tell an unchanged observation (same `id`, same hash) apart
from an edited one (same `id`, different hash) even though the source-native identity
did not change — for example, an organizer editing an Instagram caption after the fact.
See "Storage boundary" below for how the JSONL store uses it.

### Instagram raw items

The Instagram collector writes to `data/raw/instagram/<username>.jsonl` and fills the contract as follows:

| Field | Value |
| --- | --- |
| `id` | `instagram:<username>:<shortcode>` — stable across reruns, and the key used to detect an existing vs. changed observation |
| `external_id` | The Instagram shortcode |
| `content_url` | `https://www.instagram.com/p/<shortcode>/`, valid for every post type |
| `raw_text` | The caption exactly as published, never rewritten or summarized |
| `published_at` | Post creation time, normalized to UTC and always timezone-aware |
| `content_type` | `image`, `video`, `carousel`, `reel`, or `unknown` |

The collector reads both a profile's regular posts (`get_posts()`) and its Reels
(`get_reels()`), merges them into one recency-ordered, deduplicated sequence bounded by
the requested limit, and never returns the same shortcode twice even when Instagram
exposes it through both feeds. An item fetched through the Reels feed is labeled
`reel` on trusted collection-path context, since the anonymous web timeline's legacy
`__typename` alone carries no clips marker and can't be used to guess it. A plain video
post fetched through the regular posts feed still maps `GraphVideo` to `video`.
Adapter-specific values (`typename`, `media_id`, `is_video`, caption hashtags and
mentions, `origin` — `post` or `reel` — and `collector_version`) stay inside `raw_metadata`.

## EventCandidate

The result of event detection and extraction before deterministic normalization and final persistence. It may be incomplete or uncertain.

It preserves source wording such as `source_date_text` and `price_text`, plus extracted fields and `extraction_confidence`. A candidate can explicitly be `is_event = false`.

## Event

The normalized canonical record used for filtering, deduplication, review, and later Google Sheets export.

It stores normalized event facts, review/status fields, provenance (`canonical_source_url`, `source_item_ids`), first/last seen timestamps, and human review notes.

## Storage boundary

```text
RawItem        → JSONL (planned)
EventCandidate → transient / processing boundary
Event          → SQLite (planned)
Google Sheets  → review/output surface, not source of truth
```

The JSONL store is append-only and never overwrites or deletes a stored observation.
A rerun classifies each incoming item against the most recently stored observation with
the same `id`:

| Comparison | Outcome |
| --- | --- |
| new `id` | `New` — appended |
| same `id`, same `content_hash` | `Existing` — not appended |
| same `id`, different `content_hash` | `Changed` — appended as a new line, preserving the prior observation |

This keeps the raw capture history auditable: both the original and the edited wording
of an Instagram post remain on record, in the order they were observed.

Unknown values remain null. GatherRadar must not invent missing dates, venues, prices, or registration details. Every material event fact must remain traceable to source evidence.
