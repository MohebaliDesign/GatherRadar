# GatherRadar Data Contracts

This document defines the records used by the MVP pipeline. Collectors may change, but these boundaries should remain stable unless the product contract changes.

```text
Source → RawItem → EventCandidate | PlaceCandidate → Event
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
| `image_url` | A thumbnail URL when available; collection does not download media. The separate explicit evidence command may capture displayed media locally below `data/` |
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

## EvidenceFragment, EvidenceBundle, and DiscoveryUnit

`RawItem.raw_text` remains the original collected caption or website text. Media OCR never
overwrites it. One raw observation instead owns an `EvidenceBundle` containing immutable,
deterministically identified `EvidenceFragment` records.

`EvidenceKind` is source-neutral: `caption`, `image_ocr`, `carousel_slide_ocr`,
`reel_frame_ocr`, and `website_text`. A fragment preserves its raw item id, observed text,
source URL, optional local artifact path and SHA-256, optional slide index or frame timestamp,
OCR engine/version/configuration, exact raw OCR output, and an optional failure reason. Empty
and failed OCR observations are auditable evidence records, not semantic facts.

Fragments are ordered deterministically: caption first, then media position. Stable identity
uses the raw item, kind, position, captured asset hash, OCR engine/configuration, OCR output,
and failure state; temporary Instagram CDN URLs are provenance only and never the identity.

A `DiscoveryUnit` is an explicit group of one or more fragments believed to describe one
potential event or place. A bundle may produce zero, one, or many units. The current strategy
creates only one unit from the original caption and passes that exact text to the existing rule
engine. It does not concatenate OCR slides. Future segmentation may deliberately group slides
1-3 separately from slides 5-6 without changing the evidence contract.

### MediaArtifact

A media artifact is a local OCR input with a stable kind (`image`, `carousel_slide`, or
`reel_frame`), raw item id, content-addressed local path, SHA-256, source URL, and the relevant
slide index or frame timestamp. Files live only below `data/media/`; same bytes at the same
position reuse the same file, while changed bytes create a new auditable artifact.

OCR evidence is append-only JSONL below `data/evidence/`. Repeating the same artifact and OCR
result does not append another line. Engine/configuration or output changes produce a new
fragment instead of mutating history. Malformed lines are isolated and reported.

## EventCandidate and PlaceCandidate

The result of discovery before deterministic normalization and final persistence. Either may be incomplete or uncertain.

`EventCandidate` preserves source wording such as `source_date_text` and `price_text`, plus extracted fields and `extraction_confidence`.

`PlaceCandidate` is the separate record for a venue worth visiting: `candidate_id`, `raw_item_id`, `title`, `summary`, `category`, `address`, `city`, `opening_hours_text`, `price_text`, `language`, and `evidence_url`. It exists so place content is never forced into an event record — a gallery that exists has no date, occurrence, or registration, and inventing those is exactly what GatherRadar must not do.

### Discovery boundary

```text
RawItem → DiscoveryService → DiscoveryProvider → DiscoveryFacts → EventCandidate | PlaceCandidate | Other
```

The service now reaches this unchanged provider through the conservative caption route:

```text
RawItem -> caption EvidenceFragment -> EvidenceBundle -> one DiscoveryUnit -> DiscoveryService
```

The API also accepts zero or many explicit discovery units for future segmentation. Media OCR
is persisted and inspectable in this milestone but is not automatically grouped or sent to the
provider.

Classification and field extraction are separate responsibilities but one provider
operation: `DiscoveryProvider.discover(ExtractionInput) -> DiscoveryFacts` decides
`discovery_type` — does this raw item announce a concrete attendable event, describe a place
worth visiting, or neither? — and returns the source-supported facts together.

`DiscoveryType` is a typed enum with exactly three values: `event`, `place`, `other`.
`other` means meaningful content was analyzed and found unrelated; content that was never
analyzed is a skipped outcome, not an `other`.

The interface is provider-neutral, and the shipped implementation is
`RuleBasedDiscoveryProvider` (`rule-based/1`): deterministic rules only — no model, no API
key, no network access, no cost. See "Rule-based discovery" below.

`ExtractionInput` is the only evidence a provider sees: `raw_item_id`, `source_id`,
`source_type`, `raw_text`, `content_url`, `content_type`, `published_at`, `author`, and, when
source configuration is supplied, `locale`, `timezone`, and `city_hint`. Adapter
`raw_metadata` is not passed.

`DiscoveryFacts` carries `discovery_type`, `title`, `summary`, `category`, `source_date_text`,
`venue_name`, `address`, `city`, `event_format`, `price_text`, `opening_hours_text`,
`registration_url`, `language`, `extraction_confidence`, and optional `evidence`. Unknown
values are null, and a clear event may have no title.

`DiscoveryEvidence` is debugging and review material, never a fact: `event_score`,
`place_score`, `negative_score`, `matched_signals`, `negative_signals`, and `reason`. It
belongs to the run outcome, never to a candidate, and is never persisted.

`DiscoveryService` owns the deterministic behavior:

| Rule | Behavior |
| --- | --- |
| Empty or whitespace-only `raw_text` | Skipped without calling the provider (`empty_text`); not classified as `other` |
| Text with no content words, e.g. `"and"` | Skipped without calling the provider (`insufficient_text`). The guard is token-based, not a character count, so a short real title such as `کنسرت` is still analyzed |
| Provider output | Validated: `discovery_type` is a `DiscoveryType`; text fields are text or null, with blank text becoming null; `extraction_confidence` is a number from 0 to 1; `registration_url` is an http(s) URL; `event_format` is `in_person`, `online`, `hybrid`, or null; `other` carries no facts; an event carries no `opening_hours_text` and a place carries no `source_date_text`, `event_format`, or `registration_url`. Other invalid output is rejected, not corrected |
| Result mapping | `event` becomes an `EventCandidate`, `place` a `PlaceCandidate`, `other` no candidate at all |
| Provenance | `raw_item_id` and `evidence_url` always come from the `RawItem`, never from the provider |
| `candidate_id` | `candidate:` plus the SHA-256 of the raw item `id` and `content_hash`: the same observation always yields the same id, an edited observation a new id, and the provider never affects it |
| Normalization-owned fields | `starts_at`, `ends_at`, `price_amount`, and `currency` stay null; source wording stays in `source_date_text` and `price_text`, and `city_hint` is never copied into `city` |
| Failures | Provider errors and invalid output become per-item outcomes (`provider_failed`, `invalid_output`). Provider adapters translate library errors into `ProviderExtractionError` or `InvalidExtractionOutputError` |

`orchestration.discovery_run.run_discovery` processes raw items independently and reports
`observed`, `discovered`, `events`, `places`, `other`, `skipped`, and `failed`. Candidates are
returned in memory and are not persisted. Normalization is a separate, later step.

### Rule-based discovery

The default provider lives in `extraction/` and is deliberately split so the vocabulary can
be reviewed without reading the logic:

| Module | Responsibility |
| --- | --- |
| `text.py` | Text mechanics only. `normalize` is length preserving, so an offset in the folded form is the same offset in the original — that is how extracted values stay the operator's exact wording, نیم‌فاصله and Persian digits included |
| `rules.py` | All vocabulary and every weight and threshold. No keyword list lives anywhere else |
| `signals.py` | Recognizes signals as whole-token phrase matches, so `رویدادهای` is not `رویداد` and `کلاسیک` is not `کلاس` |
| `fields.py` | Reads source-supported field values, never rewriting or normalizing them |
| `rule_based.py` | Scores the signals and decides event / place / other, then reports why |

**Classification.** No single keyword decides anything. An event needs a path through the
evidence:

* **Path A** — event terminology together with date, time, or registration evidence.
* **Path B** — strong event terminology, or a validated named event, together with an
  invitation to attend, plus venue or location context when the terminology alone is not
  specific enough.

Path B exists because requiring a date made the first version of this engine too strict for a
real and common shape: a post that says where to come and that they are waiting for you,
without ever printing a date. An attendance invitation alone still never creates an event,
and neither does a date alone, an address alone, or an event word alone.

A place needs place vocabulary plus descriptive or visit context, and is only considered
after no event path was satisfied — so a gallery announcing an opening on a date is an event,
while a gallery introducing itself is a place.

Retrospective wording (`برگزار شد`, `هفته گذشته`, `گزارش تصویری`, `behind the scenes`) is a
penalty, never a veto: a post that recaps the last occurrence and announces the next can
still be an event.

**Named events and titles are conservative.** A title comes only from a validated
`<head term> <name>` construction or an explicitly quoted name — otherwise it stays null,
because an unknown title is better than an invented one. A construction is valid only when
the head term is that exact word, opens its line, and is followed by words that are not
grammatical continuations (a centralized stopword list), dates, or numbers. So
`رویداد سرام` and `نمایشگاه «نام نمایشگاه»` are names, while `رویداد میتونید`,
`رویداد جزو`, `رویدادهای تهران`, and `اینجا فقط ایونت نیست` are not. A rejected construction
adds nothing to the event score.

**Temporal wording is detected, never converted.** Persian weekdays and months, relative
dates, Persian and Latin digits, times, and time ranges are recognized as signals and kept
verbatim in `source_date_text`. Jalali-to-Gregorian conversion is a later step.

**Everything else stays explicit.** `city` is only read when the text names a city — a
neighborhood never implies one. `event_format` is only set on explicit wording; an address is
never taken as proof that an event is in person. `price_text` keeps the source wording and no
numeric amount is produced.

## Event

The normalized canonical record used for filtering, deduplication, review, and later Google Sheets export.

It stores normalized event facts, review/status fields, provenance (`canonical_source_url`, `source_item_ids`), first/last seen timestamps, and human review notes.

## Storage boundary

```text
RawItem                         → JSONL
EventCandidate / PlaceCandidate → transient / processing boundary
Event                           → SQLite (planned)
Google Sheets                   → review/output surface, not source of truth
```

Media artifacts live below `data/media/` and source-neutral evidence fragments use append-only
JSONL below `data/evidence/`. Neither store contains candidates. Both are local runtime data,
and both preserve OCR/media changes as history rather than overwriting prior evidence.

The raw JSONL store is append-only and never overwrites or deletes a stored observation.
A rerun classifies each incoming item against the most recently stored observation with
the same `id`:

| Comparison | Outcome |
| --- | --- |
| new `id` | `New` — appended |
| same `id`, same `content_hash` | `Existing` — not appended |
| same `id`, different `content_hash` | `Changed` — appended as a new line, preserving the prior observation |

This keeps the raw capture history auditable: both the original and the edited wording
of an Instagram post remain on record, in the order they were observed.

### Reading the raw store

`JsonlRawItemStore.read_latest_items()` is the read-only side of that boundary. Because the
file is append-only, an edited caption is on record more than once; analysis must look at
what the source says now, so only the **most recently stored observation of each `id`** is
returned. Nothing is rewritten, reordered, or deleted, and items come back in the order their
ids first appeared.

A line that is not valid JSON, is not an object, or does not satisfy the `RawItem` contract is
isolated and reported in `malformed` rather than raised, so one corrupt observation does not
cost the caller every valid one. Reported reasons name the line number only, never its
content.

Choosing which of those observations to work on belongs to orchestration, not storage.
`select_latest` takes the newest by `published_at`, puts undated items after dated ones, and
breaks every tie with storage order, so the same file and the same `--limit` always select the
same items.

Unknown values remain null. GatherRadar must not invent missing dates, venues, prices, or registration details. Every material event fact must remain traceable to source evidence.
