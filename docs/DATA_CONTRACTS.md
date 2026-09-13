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
event interpretation: `raw_text`, `published_at`, and `content_url`. It deliberately
excludes `captured_at`, which changes on every run, and `content_type`, which is
GatherRadar's own classification of the content rather than a property of the
content itself — so a later fix to that classification cannot make unchanged source
content look edited. Any collector can compute one with
`gatherradar.domain.compute_content_hash`; the field and its meaning are
source-neutral, not Instagram-specific.

The content hash lets a rerun tell an unchanged observation (same `id`, same hash) apart
from an edited one (same `id`, different hash) even though the source-native identity
did not change — for example, an organizer editing an Instagram caption after the fact.
See "Storage boundary" below for how the JSONL store uses it.

### Instagram raw items

The Instagram collector writes to `data/raw/instagram/<username>.jsonl` and fills the contract as follows:

| Field | Value |
| --- | --- |
| `id` | `instagram:<username>:<shortcode>` — `<username>` is always the configured source account, never the logged-in account; stable across reruns, and the key used to detect an existing vs. changed observation |
| `external_id` | The Instagram shortcode |
| `content_url` | `https://www.instagram.com/p/<shortcode>/`, valid for posts and reels alike, so the content hash does not depend on which URL form the media was discovered through |
| `raw_text` | The caption exactly as published, never rewritten or summarized; empty when none was found |
| `published_at` | Post creation time, normalized to UTC and always timezone-aware; null when no timezone-aware timestamp is available |
| `author` | The configured source username |
| `image_url` | A thumbnail URL when available; media files are never downloaded |
| `content_type` | `reel`, `image`, `video`, `carousel`, or `unknown` (see below) |

Every collected shortcode appears at most once per run, preferring its reel form when
Instagram exposes the same media as both a post and a reel. Both transports share one
mapping, so the same media keeps the same `id` whichever transport observed it.

**Browser transport (default).** Playwright opens the source profile in the persistent
GatherRadar Chrome profile, discovers media from `/p/<shortcode>/` and
`/reel/<shortcode>/` link patterns, and opens a small candidate pool: up to three more media
pages than the requested limit, at most 12 unless the limit itself is larger. The collector
then keeps the requested number of newest items by `published_at` (items without one sort
last, ties keep grid order), so older pinned posts at the top of the grid do not displace
recent media. Media reached through a `/reel/` URL is `reel`; other posts are `unknown`,
because browser-visible pages do not reliably say whether a post is an image, video, or
carousel. The caption is read from the rendered page first — a caption `h1`, the author's
first caption list item, a block attributed to the author's profile link, or the author's
`dir="auto"` caption text — and only then from `og:description`, `description`, or
`og:title` metadata. Author usernames, comments, comment authors, timestamps, like counts,
and interface labels are excluded, and a post without a caption keeps an empty `raw_text`.
`raw_metadata.caption_source` names the scope and strategy used, for example `article:h1`,
`main:author-block`, `article:caption-item`, `article:dir-auto`, `og:description`,
`meta:description`, or `none`. The publish time comes from the `time[datetime]` element that
links to the post; comment timestamps are never used.

Because raw observations are append-only, a caption first stored as empty and later
extracted produces a new `Changed` observation for the same `id`; the earlier observation is
kept. `raw_metadata` records `transport` (`browser`), `media_url`,
`final_url`, `caption_source`, `published_at_source`, caption `hashtags` and `mentions`,
`origin`, and `collector_version` (`instagram-browser/1`); `typename`, `media_id`, and
`is_video` are null.

**Legacy Instaloader transport** (`--transport instaloader`, kept only while the browser
transport is validated). It reads `get_posts()` and `get_reels()` and merges them into one
recency-ordered sequence. Items from the Reels feed are labeled `reel`, since the legacy
`__typename` carries no clips marker; `GraphImage`, `GraphVideo`, and `GraphSidecar` map to
`image`, `video`, and `carousel`. Its `raw_metadata` carries `typename`, `media_id`,
`is_video`, `hashtags`, `mentions`, `origin`, and `collector_version`
(`instagram-instaloader/2`).

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
