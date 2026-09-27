# GatherRadar Data Contracts

This document defines the records used by the MVP pipeline. Collectors may change, but these boundaries should remain stable unless the product contract changes.

```text
Source → RawItem / Evidence → DiscoveryUnit → DiscoveryService
       → EventCandidate | PlaceCandidate → NormalizationOutcome
       → conservative canonicalization → review window → SQLite → XLSX / CSV / JSON
       → optional manual Gemini bundle / Google Sheets API adapter
```

## Source

A configured place GatherRadar is allowed to inspect. A website and Instagram account for the same publisher are separate sources and share a `publisher_key`.

Key fields: stable `id`, `publisher_key`, `source_type`, canonical `url`, optional Instagram `username`, `enabled`, locale/timezone, and optional `city_hint`.

`website` is an optional immutable `WebsiteConfig`, required to collect a website. Existing
Instagram configuration is unchanged. It contains an adapter key, required detail path
prefixes, one content selector (default `article`), exclude selectors, and explicitly safe
query keys to drop. Selectors are tag/`.class`/`#id` only. Invalid option shapes, unsafe source
IDs, credential-bearing URLs, duplicate IDs, and unknown source types are rejected. Adapter
keys resolve in the collector factory; an unregistered key fails before network access.

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

### Website raw items (Stage 6)

`data/raw/website/<source_id>.jsonl` uses the same append-only store. One permitted detail
page is one RawItem. The listing page discovers URLs **and** contributes each item's own
listing card: exactly the visible text of the anchor that links to that detail URL, never
the concatenated directory, day headers, filters or neighbouring cards. A URL linked by
differing card texts, or by an oversized wrapper, gets no card. The adapter protocol owns
URL discovery, cards, detail text selection, structural fields and external identity;
transport owns public HTTP, robots, request limits, and redirect checks. Shared
orchestration has no source-ID switches.

| Field | Website value |
| --- | --- |
| `id` | `website:<source_id>:<external_id>` |
| `external_id` | Current specialized adapters: native final path key when no meaningful query remains; otherwise SHA-256 of the canonical URL. Generic adapter: URL SHA-256. |
| `content_url` | Approved same-origin detail URL; fragment and verified tracking/navigation parameters removed, meaningful query bytes retained |
| `content_type` | `webpage` |
| `raw_text` | Relevant source content in document order, HTML entities decoded and whitespace separated; no invented labels, summaries, normalization, hidden href text, or structured-data field injection |
| `published_at` | `null`: the current adapters do not have a verified publication timestamp |
| `captured_at` | Aware UTC collection timestamp; excluded from the hash |
| `author`, `image_url` | `null`; current adapters do not infer these |
| `raw_metadata` | Adapter/version, listing/detail URLs, source title, optional native ID, structured-data presence, transport, retained content links (including registration hrefs when present), `listing_card_text` (this run's own card or null), `source_fields` (adapter-verified `{name, value, origin}` facts) |

`source_fields` are facts an adapter reads from explicit page structure — a dedicated
price/status badge, a fixed header slot, a labelled card field, a labelled description or
organizer section. `origin` is `detail` or `listing`; names are limited to
`source_date_text`, `area_text`, `duration_text`, `organizer_name`, `availability_text`,
`price_text`, `description_text` and `source_category_text` (for example the Vadoostan
card genre chip `بازی`/`ورزش`). Every value must be an exact slice of the detail
text or card text it came from; anything else is dropped at collection and again at the
discovery boundary. The detail text, a verified heading, the card text and these fields
all join the content hash, so a changed card (for example newly sold out) appends a
Changed revision and an unchanged rerun stays Existing.

Other metadata is provenance, not rule-engine input. Full HTML and review/profile text are not
stored in RawItems. A metadata-only change does not alter the existing content hash and
therefore does not append a new observation; this Stage 6 limitation preserves the shared
storage contract. CSS visibility beyond known exclusions, inline hidden/display attributes,
and Davvvat's mobile duplicate is not generally evaluated by the static parser.
Utility-class flex containers with a gap class (`flex`/`inline-flex` plus `gap-*`) are
rendered with a separating space, as inline-style gaps already were, so visually separate
spans never become fabricated words (`هیلان۲`).
The Davvvat adapter explicitly selects its known streamed detail panel even when the server
places it in a hidden staging wrapper for later relocation. The generic adapter rejects
content beneath hidden/excluded ancestors. Jabama only attaches price from one sibling
booking aside with the purchase control and exactly one price paragraph; ambiguity omits it.

Collection takes up to N valid details in source listing order (1–30, up to `min(3*N,30)`
attempts, one listing, no pagination). Offline discovery instead takes latest observations
in first-seen storage order; no capture-run manifest reconstructs later live list order.
Missing/deleted events are not tombstoned. Recurring/multi-session pages are not split into
individual occurrences. Related content must be excluded structurally by the adapter;
arbitrary page segmentation and cross-page event merging are not implemented.
See [source field coverage](SOURCE_FIELD_COVERAGE.md) for the per-adapter fact inventory.

## EvidenceFragment, EvidenceBundle, and DiscoveryUnit

`RawItem.raw_text` remains the original collected caption or website text. Media OCR never
overwrites it. One raw observation instead owns an `EvidenceBundle` containing immutable,
deterministically identified `EvidenceFragment` records.

`EvidenceKind` is source-neutral: `caption`, `image_ocr`, `carousel_slide_ocr`,
`reel_frame_ocr`, `website_text` and `website_listing`. A `website_listing` fragment is
built only from the current observation's `listing_card_text` (source URL = the listing
page); stored history never supplies a listing card, so a price absent from the current
listing is never borrowed from an older one. `conservative/1` joins it to the item's
single website-text unit unconditionally — the card was selected by the exact detail
link — and never decides field disagreements; discovery does. A unit containing website
text or its listing card keeps the `primary` identity slot. A fragment preserves its raw item id, observed text,
source URL, optional local artifact path and SHA-256, optional slide index or frame timestamp,
OCR engine/version/configuration, exact raw OCR output, and an optional failure reason. Empty
and failed OCR observations are auditable evidence records, not semantic facts.

Carousel OCR requires a non-negative integer `slide_index`; reel OCR requires a
non-negative integer `frame_timestamp_ms`. Each position field is valid only for its
corresponding kind; captions, image OCR, and website text carry neither. Zero is valid,
and booleans are not positions. Existing correctly positioned fragments keep their IDs
and serialized shape. Invalid stored records are reported without rewriting history.

Fragments are ordered deterministically: caption first, then media position. Stable identity
uses the raw item, kind, position, captured asset hash, OCR engine/configuration, OCR output,
and failure state; temporary Instagram CDN URLs are provenance only and never the identity.

A `DiscoveryUnit` is an explicit group of one or more fragments believed to describe one
potential event or place. A bundle may produce zero, one, or many units. `primary_fragment`
maps Instagram raw text to `CAPTION` and website raw text to `WEBSITE_TEXT`.
`EvidenceBundle.from_raw_item` uses that boundary. Default Instagram discovery still creates
only the original caption unit with unchanged identity. The website CLI uses the Stage 5
grouping path over its fresh primary text, without separate evidence persistence.

`DiscoveryUnit.from_fragments(..., strategy='conservative/1')` sorts fragments by their
domain sort key, retains their exact wording joined by a newline, and hashes an unambiguous
JSON encoding of raw item id, strategy/version, and ordered fragment ids. Mixed raw item ids,
duplicate fragment ids, empty groups, and empty strategy names are rejected. Changed OCR
fragment identity or strategy version changes unit identity. `from_fragment` and the legacy
caption route retain their existing behavior.

### Semantic selection and grouping (Stage 5)

`grouping.select_semantic_evidence` accepts a current RawItem and evidence in storage append
order. It excludes other raw item ids and stored captions, rebuilding the caption directly
from the current RawItem. Latest stored observations win by `(kind, position)`: one image
slot, each carousel `slide_index`, and each Reel `frame_timestamp_ms`. A latest failed or
empty observation wins too; older successes are never semantic fallback. Website text is
accepted per source URL as a separate page-text slot. For a website RawItem, stored text for
the current primary page URL is excluded in favor of fresh `RawItem.raw_text`; page-section
identities are not inferred. The website CLI supplies no extra page history. Selected
fragments remain auditable, including failures; semantic eligibility belongs to grouping.

Selection is read-only and means **latest known stored slots**, not a complete media run.
The contract contains no capture-run membership, observed-at timestamp, total slide count,
or removed-slot tombstone. Slots absent from later runs can remain stale. Image/carousel
kind changes cannot be reconciled reliably. Stage 4 deduplicates fragment ids globally, so
an A → B → A observation sequence stores only A and B; selection must still return B.
Likewise, a repeated failed version may not append after a different success. A capture
failure without an OCR fragment cannot invalidate a slot. Malformed records are isolated
and cannot reliably identify a slot to invalidate. These limitations require a future
acquisition/persistence decision; Stage 5 does not rewrite history or infer missing runs.

`GroupingStrategy.group(EvidenceBundle)` is the source-neutral boundary.
`ConservativeGrouping` (`conservative/1`) uses existing signal analysis on each fragment
independently. Grouping never classifies concatenations to decide whether to merge:

- A validated named event/place or independent Event/Place classification is an anchor.
  Multiple distinct line-level named events/places or independent event lines mark a
  fragment ambiguous for attachment. The fragment itself remains one unit; internal layout
  segmentation is not available.
- A new anchor normally starts a group. A supporting fragment can attach only after an
  anchor, within the same media kind, and with no ambiguous/failed/empty intervening slot.
  Carousel indices must be consecutive; Reel adjacency means consecutive stored samples,
  not continuous visual evidence. Every nonblank support line must have recognized
  structure: a nonempty leading field label, a compact date/time expression, leading
  supported price/opening-hours wording, or leading registration wording with its URL and
  no remaining content prose. Event/place terminology, retrospective wording, and attendance
  prose disqualify support-only fragments. This deliberately misses some valid continuations.
- Conflicting recognized date/time, address, venue, city, price, registration URL, or opening
  hours wording prevents attachment. Comparisons use folded source wording, not semantic
  normalization. Even complementary date/time wording may be split when both fragments
  already carry temporal evidence. Conflicts are checked against every member of the group.
- Consecutive Reel samples with identical whole text after existing script/digit/case folding
  and whitespace collapse share a unit, keeping **all** participating fragment provenance
  and wording. No token-overlap threshold, fuzzy matching, or cross-unit deduplication is
  used; small word/digit changes and nonconsecutive repeated scenes may remain separate.
- Caption stands alone with multiple media groups. With one group, caption joins only if
  one side is an anchor and the other entirely supporting facts, with no recognized
  conflicts/ambiguity, or all complete texts are equivalent. A single image is one group,
  but competing anchors or unrelated generic caption text still remain separate.
- Failed/empty fragments and text rejected by the existing meaningful-content guard never
  supply unit text. They are not removed from storage. Unrecognized content words remain
  separate and may classify as Other; noise is not reliably detectable. No eligible text
  produces zero units.

Adjacency plus structured support is a heuristic, not verified co-reference. Missed OCR
names, several occurrences on one line or poster, implicit venue references, and semantic
contradictions remain unsolved. Precision is preferred over recall, but perfect separation
is not claimed.

### MediaArtifact

A media artifact is a local OCR input with a stable kind (`image`, `carousel_slide`, or
`reel_frame`), raw item id, content-addressed local path, SHA-256, source URL, and the relevant
slide index or frame timestamp. Files live only below `data/media/`; same bytes at the same
position reuse the same file, while changed bytes create a new auditable artifact.
Instagram image screenshots use stable geometry and inward-rounded pixel bounds to avoid
capturing neighboring carousel edges. Reel frames are captured with playback paused after
the requested seek completes; a seek timeout produces a capture failure, not a timestamped
artifact. These are rendered media screenshots and may include overlaid media controls.

OCR evidence is append-only JSONL below `data/evidence/`. Repeating the same artifact and OCR
result does not append another line. Engine/configuration or output changes produce a new
fragment instead of mutating history. Malformed lines are isolated and reported.
Unknown-kind diagnostics do not echo the invalid value. Unexpected browser and OCR
exceptions report the failed operation and exception type without copying exception
payloads into summaries or evidence.

## EventCandidate and PlaceCandidate

The result of discovery, optionally copied by deterministic normalization before later persistence. Either may be incomplete or uncertain.

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

The API also accepts zero or many explicit discovery units. `extract --evidence` reads local
raw/evidence JSONL, selects semantic evidence, groups it, and invokes `discover_units`.
Default `extract instagram` remains caption-only, with unchanged output and identities. Both paths
remain offline, deterministic, and write-free; the evidence-aware path does not run OCR or
require Tesseract. The explicit acquisition command is separate.

`extract website` uses the same `run_evidence_discovery` and `discover_units` boundaries,
with `WEBSITE_TEXT` primary fragments. The compatibility `DiscoveryService.discover` API
also accepts website primary text; it retains its legacy single-observation identity policy.

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
`raw_metadata` is not passed. Stage 9 adds optional `source_title`: only an explicitly
verified website heading validated against the raw text, as detailed below.

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

For explicit units, `discover_unit` hashes the current raw content hash with `unit_id`
before deriving candidate identity. Different units therefore have different candidate
IDs, independent of provider/model. Evidence-aware caption units also have unit-specific
IDs; equality with legacy caption-only candidate IDs is not promised.

`orchestration.evidence_discovery_run` retains each RawItem's units and aligned outcomes in
`EvidenceItemDiscovery`; an outcome's `discovery_unit_id` links its candidate to the unit's
exact `fragments`. Candidate domain records are unchanged. This is group-level provenance,
not field-level fragment attribution. Candidates alone must not be detached from these
outcomes if an audit needs contributing fragments; future persistence must retain that link.
`EvidenceDiscoveryRunSummary.observed` counts RawItems, `unit_count` counts units, classification
and skipped counters count unit outcomes, and `failed` includes grouping failures and unit
failures. A zero-unit item has `no_meaningful_evidence`, not an Other outcome. Malformed input
reports store/line only, grouping and unexpected unit exceptions report operation/type only,
and later items/units continue. No candidate, unit, or modified evidence is persisted.

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
* **Structured occurrence** — only when Paths A/B and the place path fail: the item's own
  detail page has exactly one adapter-verified `source_date_text` slot (origin `detail`)
  containing both a date and a clock time, the text or structure carries price,
  registration or attendance evidence, and net event evidence stays positive. A card-only
  date, a date without a clock, a trusted listing alone, or free-text dates never qualify,
  so an Experiences listing is never promoted wholesale. Reason:
  `event: verified detail date/time slot with attendance or price evidence`.

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

### Source-supported review facts

`DiscoveryFacts`, `EventCandidate` and `Event` carry six optional, source-worded facts.
Each is exact source text or null; none is generated, summarized or inferred.

| Field | Meaning | Never |
| --- | --- | --- |
| `description_text` | The source's own description section, whitespace-normalized per line | a generated summary; `summary` stays reserved for a future summary contract |
| `area_text` | Neighborhood/district/approximate locality (`ایرانشهر - سمیه`) | a venue, a precise address, a city, or geocoded |
| `duration_text` | An explicitly stated length (`۳ ساعت`, `۹۰ دقیقه`) | derived from start/end clocks, or read as a clock time |
| `organizer_name` | A name behind an explicit organizer/host label or caption | an author, publisher, account or arbitrary person name |
| `availability_text` | Explicit capacity/registration-state wording (`تکمیل ظرفیت`, `ظرفیت: ۲۰ نفر`) | inferred from a missing price or booking control; no invented capacity |
| `source_schedule_text` | Exact multi-session/recurring/daily-window sentences (≤3, deduplicated) | expanded into occurrences or a continuous range |
| `source_category_text` | An explicit source category label (adapter-verified structural field) | inferred from prose; mapped to a category the taxonomy lacks |

**Category precedence.** When `source_category_text` exists it outranks free-text keyword
inference: `category` is its exact supported mapping in the controlled vocabulary
(`کارگاه` → `workshop`) or null (`بازی`, `ورزش`, `موسیقی`, `آشپزی` have no entry). A word
in a description (`کلاس‌های جادو`) can then never set `کارگاه`. Without a source label,
text inference is unchanged. The workbook category cell shows the mapped category, else
the exact source label; no workbook schema change. Captures made before this field
existed keep their old inference until re-acquired.

Text rules are source-neutral and also apply to Instagram captions: labels `محله/منطقه/محدوده`,
`مدت/مدت زمان/مدت برگزاری/مدت زمان برنامه`, `برگزارکننده/میزبان/organizer` (colon, or a
standalone section heading for the organizer), `ظرفیت/capacity`, and availability only as
a whole standalone status line — prose such as «قبل از تکمیل ظرفیت ثبت‌نام کنید» is not.
A schedule sentence needs explicit wording (plural weekday, two or more weekdays, two or
more sessions, recurrence vocabulary, or a day list before a month such as `5،12،19 و 26 مهر`)
plus a clock, number or date other than the weekday itself; a title such as `(۴ جلسه)` and
prose such as «چهارشنبه‌ها تجریش شلوغ است» do not qualify. A number written before
`ساعت` with none after it (`۲ ساعت`, `یک ساعت و نیم`) is a length, never a time signal. A
labelled venue whose whole value is a known city (`محل برگزاری: تهران`) is reported as city only.

**Listing/detail precedence.** For price, venue, address, city, area, duration, organizer
and availability, discovery reads each fragment of a website unit separately. An
adapter-verified structural value outranks a text-derived reading, which may be a prose
mention (for example a breakfast cost inside a description). Values of the same tier from
the card and the page must agree up to spacing and digit script; one exact wording is kept,
detail first. Explicitly different values are never chosen between: the field stays null
and `field_conflicts` names it, which Stage 8 reports as `source_field_conflict` (data quality
`تعارض داده`). A fact only one place states — a list-only price or sold-out badge, a
detail-only description — is kept. A structural detail header date (`source_date_text`)
outranks a labelled recurrence phrase elsewhere on the page. Temporal wording otherwise uses
the existing ranking over the whole unit; card/detail clock disagreement is not separately
detected (documented limitation). No new field participates in classification.

## Event

The normalized canonical record used for filtering, deduplication, review, and later Google Sheets export.

It stores normalized event facts, review/status fields, provenance (`canonical_source_url`, `source_item_ids`), first/last seen timestamps, and human review notes.

Stage 8 reconciles the legacy model: title is nullable; timezone has no implicit Tehran
default; date/time components, `DatePrecision`, Decimal-compatible prices, canonical
field provenance and membership are explicit. Timestamps must be timezone-aware.
`source_item_ids` continues to mean raw-item IDs. Lifecycle status remains `unknown` and
review status defaults to `needs_review`; grouping never means verified. Stage 8 creates
this model in memory only. Tags and reviewer notes remain domain fields but are not
fabricated from candidates. Lifecycle status becomes `sold_out` only when the resolved
`availability_text` is explicit sold-out wording (`تکمیل ظرفیت`, `ظرفیت تکمیل شد`, `sold out`,
…); `ظرفیت محدود` or a missing price never does. Cancelled/postponed wording was not observed
in current sources and is not mapped. Availability is never an identity or matching input. Registration deadlines are still outside the implemented
candidate contract. Discovery keeps `candidate_id` and `evidence_url` unchanged.

## Deterministic normalization (Stage 7)

`NormalizationService.normalize(candidate, raw_item, source, evidence_text=...)` returns
an immutable `NormalizationOutcome`. `orchestration.normalization_run.run_normalization`
handles discovery outcomes item by item, skips outcomes without candidates, and isolates
missing context/unexpected failures with fixed, secret-safe diagnostics. It validates
candidate/raw/source identity. Discovery summaries retain the exact RawItems used in the
run, avoiding a second store read or reference-date race. Unit text is passed separately
for relative-word context validation; the original RawItem is never overwritten.

The outcome carries the candidate, optional `TemporalResult`, reusable `PriceResult`, and
diagnostics. Event candidates are copied; place candidates remain unchanged and carry
numeric price in `PriceResult` only. No location, category, confidence, identity, provenance,
title, summary, `source_date_text`, or `price_text` is rewritten. Normalization does not
collect, run OCR, use AI, persist, deduplicate, or calculate event lifecycle status.

### Temporal values and precision

The pre-Stage-7 Python candidate lacked the brief's precision/timezone fields. Backward
compatible defaulted fields are now appended to `EventCandidate`:

| Field | Meaning |
| --- | --- |
| `start_date`, `end_date` | Gregorian `date` values; null when unresolved. End date requires explicit bounded range wording |
| `start_time`, `end_time` | Local 24-hour `time` values, separate from dates |
| `timezone` | Validated configured `Source.timezone`; null on invalid/unavailable configuration |
| `starts_at`, `ends_at` | Aware datetimes only for a supported single date plus clock, and an unambiguous same-day time range |
| `date_precision` | Typed `DatePrecision`: `exact`, `day`, `range`, `inferred`, `unknown` |

`exact` means a resolved single date and clock; `day` a resolved date without an accepted
datetime; `range` bounded calendar dates (not necessarily continuous attendance). `inferred`
distinguishes a single date with an inferred year, with clock resolution visible in the
separate time fields. It prevents a year estimate being labelled `exact`. Yearless ranges
retain `range` and the `inferred_year` review diagnostic. `unknown` also covers time-only
results; time fields make an additional time-only precision unnecessary. Precision describes
the interpretation's shape, not certainty or verification; always retain diagnostics.

There is no fake midnight. Multi-day bounds plus hours never create `starts_at`/`ends_at`.
Recurring/visiting schedules retain safely parsed calendar bounds but are not expanded.
Discrete dates are not collapsed into a range. Reversed/equal time endpoints are retained
as clocks for review, without inferred overnight dates or composed timestamps.

`persiantools>=6.2,<7.0` validates Jalali month-name dates and converts them to Gregorian.
Persian/Arabic digits, Arabic character variants and whitespace are folded on a parsing
copy only. Invalid explicit dates and weekday contradictions remain invalid/unresolved;
the parser never moves a date to agree with a weekday. Explicit range endpoint weekdays
are checked individually. Gregorian support is limited to `YYYY-MM-DD` with year >=1700;
ambiguous numeric dates and other calendars remain unresolved regardless of locale. No
locale-based day/month guessing is currently implemented.

Explicit Persian day ordinals (`اول`/`یکم` through `سی و یکم`) share the numeric
date grammar. Safe whitespace/ZWNJ/harakat variants are parsing-only changes. Month
names accept attached or separate `ماه`. Clear same-month ranges such as
`یکم تا سوم مهرماه` resolve through the existing reference policy. `۱ و ۲ مهر` and
textual discrete sessions remain unresolved. Calendar validation rejects impossible
month days. For `یکم تا سوم مهرماه از ساعت ۱۰ تا ۲۲`, date and time components are
retained with range precision and `multi_day_hours`; `starts_at`/`ends_at` remain null
because daily attendance hours do not establish a continuous multi-day interval.

The reference is `RawItem.published_at`, else `captured_at`, converted to the source timezone
before obtaining the local reference date. `reference_at` and `reference_basis` are exposed.
No wall clock is consulted. `امروز`/`فردا` and `today`/`tomorrow` can resolve against it.
At the service boundary a **bare relative word** additionally requires a standalone or
labelled temporal line in the corresponding discovery-unit text (or raw text for legacy
caption discovery). This avoids normalizing a word extracted from a publisher name or
ordinary prose. Missing unit context does not fall back to an unrelated caption.
Broad weeks/weekends remain unresolved; there is no assumed Iran weekend rule.

For clear yearless day/month wording, enumerate the reference Jalali year and its adjacent
years. Accept only one valid date within **45 days before or after** the stored local
reference. This symmetric bound handles near-Nowruz announcements without rolling old
events into the future. Yearless ranges must fit in one Jalali year, have their start in
that window, and span at most 90 days. Cross-Nowruz yearless ranges are unresolved. Every
accepted year inference emits `inferred_year` and remains partially normalized. The bound
is a conservative product policy, not proof of the intended year. Explicit years are never
replaced by inferred ones. Captured-at fallback is deterministic, but cannot prove when
an undated page was published.

`ZoneInfo` validates IANA names; invalid names never fall back to Tehran/UTC. Local DST
gaps and folds are invalid rather than choosing an arbitrary offset. Parsing has a
4096-character per-field bound. Unconsumed temporal wording is reported and prevents
datetime composition, even when safe calendar components remain available for review.

### Money

`PriceResult.price_amount` is `Decimal` in the **stated major currency unit**. The candidate
annotation accepts `int | Decimal | None` for backward compatibility; normalization emits
Decimal. `TOMAN` means تومان/تومن; `IRR` means ریال. No conversion or equivalence is implied.
Explicit USD/EUR/GBP codes and unambiguous supported words/symbols are accepted. Generic
`$`/دلار/dollars remain ambiguous. `هزار`/`میلیون` and English thousand/million multiply
exactly; comma and Arabic thousands separators must have groups of three. Monetary
arithmetic uses a local Decimal context; amounts over 18 significant digits are unresolved.

Explicit unconditional free wording yields Decimal zero with null currency, because none
was stated. Missing price never means free. Full-field grammar (with a small set of price
labels) prevents picking one tier, discount, range, minimum, or amount out of prose. This
deliberately leaves some clear-looking prices embedded in long sentences unresolved.

### Review statuses

`NormalizationStatus` is `normalized`, `partially_normalized`, `unresolved`, or `invalid`.
Each diagnostic has a stable code, field, fixed message, and `info`/`review`/`error` severity.
An error makes the outcome invalid; no values means unresolved; retained values with review
diagnostics means partial; otherwise it is normalized. Missing date/price are review
diagnostics, not invalid facts. Temporal and price statuses are also exposed independently.
`normalized` does not mean the source is true or the event has been human-verified.

`extract website ... --normalize` and `extract instagram ... [--evidence] --normalize`
append review output to unchanged discovery output. All results stay in memory and can be
used by the separate Stage 9 local persistence/export service. Normalization itself remains write-free.

## Conservative canonicalization (Stage 8)

`deduplication.canonicalize(contexts)` is the source-neutral in-memory batch boundary.
Each `CandidateContext` carries the `NormalizationOutcome`, original candidate, exact
RawItem/Source, historical `first_seen_at` and stable evidence slot. No provenance metadata
is added to `EventCandidate`. The result retains **all input contexts**, including rejected
inputs, plus canonical Events, automatic multi-member groups, all pair decisions, possible
relationships, singleton Events, unchanged Place candidates and structured diagnostics.
Events and Places are never compared or merged. No raw observation or candidate is deleted.

### Pair decisions

| Kind | Meaning |
| --- | --- |
| `same_event` | Sufficient deterministic evidence for automatic grouping, subject to all-member compatibility |
| `possible_duplicate` | Review suggestion only; Events stay separate |
| `distinct` | A conservative conflict veto; no automatic grouping |
| `insufficient` | No sufficiently specific relationship established |

Every decision contains sorted candidate IDs and sorted reason codes, without a numerical
probability. Comparison keys use Unicode NFKC, Arabic/Persian letter and digit folding,
case folding, punctuation and whitespace normalization. Stored wording is never rewritten.
Exact titles require at least one nongeneric, nonnumeric token. Approximate titles need
at least two shared distinctive tokens and token Jaccard overlap >=0.85. Differing numeric
tokens prevent approximate matching. Generic event words alone are not a positive signal.
Partial shared wording alone is insufficient; disjoint distinctive titles veto grouping.

The v1 automatic policy requires a strong distinctive title, the same explicit single
start date, the same known timezone and no recognized conflict. With a shared publisher,
date-only agreement can suffice; the publisher alone never does. Across publishers, the
pair additionally needs equal start clocks and either matching venue/address or an exact
non-homepage registration key. Same city alone is insufficient across publishers.

One narrow same-page rule (`same_source_page`): two candidates from **different sources of
the same publisher**, both in the `primary` identity slot, whose RawItems have the identical
canonical detail URL, are the same public page listed twice (for example Jabama's Events and
Experiences listings). With a strong/exact title and no recognized conflict they group even
when the page has no single reliable date. Media slots of one post never qualify.

Explicit unequal dates, reliable unequal clocks, and differing populated city, venue,
address or timezone veto automatic grouping. Location comparison is literal folded text,
not geocoding: aliases/translations can cause conservative false negatives. Missing values
are neutral. Prices do not determine event identity. Different registration vendors are
reported but are not assumed to identify different occurrences: there is no verified
source-neutral URL schema for that claim. Registration keys remove only the listed common
UTM/click tracking parameters; unknown query bytes/order, fragments, schemes and path/slash
semantics remain intact. Root URLs and either configured publisher homepage are weak.

Both candidates need `exact` or `day` precision, no end date and no temporal diagnostics
to auto-group. Price-only diagnostics do not block it. Inferred years (including ranges
carrying `inferred_year`), relative dates, multi-day ranges, recurrences and unparsed or
multiple-session schedules stay review-only. Stage 8 does not expand occurrences. A
distinctive title alone, registration agreement, or date plus location can suggest review.
Differences in uncertain dates/clocks remain reasons, not automatically reliable vetoes.

### Grouping and failure handling

Candidate IDs define deterministic insertion order. A candidate joins the first group
only if **every** pair with existing members is `same_event`; otherwise it starts a
singleton. A~B and B~C cannot bridge an A/C conflict or insufficient pair. All inputs belong
to at most one automatic group. A strong pair blocked by the all-member constraint appears
as a separate review suggestion with `all_member_grouping_blocked`, retaining the original
pair decision as well.

`duplicate_group_id = duplicate:<SHA-256(sorted candidate IDs)>` describes current
composition, including singleton composition. Event/group/decision/member ordering is
explicit. This greedy complete-link policy is deterministic, not a maximum-clique search.
New members can affect future partitions. Stage 9 records stable anchors but does not
automatically reconcile split/merge aliases or transfer human state between IDs.

Context identity, dates, timestamps, precision, prices, URLs and normalization consistency
are checked at the batch boundary. Invalid contexts remain in `rejected`; duplicate IDs
or ambiguous repeated raw-item/slot inputs are quarantined rather than selected by input
order. Matching exceptions produce `insufficient` with `matching_failed`; canonicalization
exceptions retain affected contexts and report `canonicalization_failed`. Other pairs and
groups continue. Exceptions never echo source payloads. CLI exits nonzero for source,
context, matching or canonicalization failures; missing stores are a normal report outcome.

### Stable Event identity

The anchor is the minimum `(first_seen_at, raw_item_id, identity_slot, candidate_id)`.
`first_seen_at` comes from the earliest valid capture timestamp for that raw ID across
the append-only raw history, not publication date, current input order or wall clock.
`ReadOutcome.first_seen_at` supplies this metadata from the **same read** as latest items.
First/last seen refer to stored observations: unchanged collections are not appended and
therefore do not advance last seen.

`event_id = event:<SHA-256([anchor raw ID, anchor slot])>` is independent of group size
and candidate/content hashes. Primary website text and captions use `primary`; a separate
media unit uses its first stable kind/slide-index/frame-position slot. This prevents several
events in one carousel from sharing an Event ID. Adding a later supporting source or editing
content at the anchor slot normally preserves identity. Candidate ID only breaks otherwise
equal ties; it is not in the event hash. Canonical source URL is the anchor candidate's
evidence URL, falling back to that RawItem's content URL. No URL is constructed.

Importing an earlier observation, losing an anchor, moving slides, changing evidence
selection, or future group splits/merges may change identity. In-memory identity cannot
replace identity-evolution review. Stage 9 persists authoritative ID/anchor mappings
and rejects contradictory mappings; split/merge alias resolution remains deferred.

### Canonical fields and provenance

All populated, agreeing values corroborate one source-supported value; nulls do not
conflict. Title/location/category/language agreement uses folded text but selects the
earliest anchor-ordered **original** wording. Other text requires literal agreement.
Equally strong disagreements become null with `field_conflict` and supporting candidate
IDs. This includes different summaries or source wording; the complete originals remain
available through retained contexts. Missing title remains null, never a placeholder.
Extraction confidence is preserved on agreement, never averaged or recalibrated.

Price amount and stated currency resolve together. Decimal precision, `TOMAN` and `IRR`
remain distinct. A zero from one candidate cannot acquire another candidate's currency.
Temporal fields resolve as a source-supplied interpretation: an explicit safe tuple can
outweigh an inferred interpretation, but the disagreement is diagnosed. Otherwise, an
existing tuple must cover the populated compatible values of equally strong tuples.
Equal-strength contradictions or complementary tuples with no covering interpretation
stay unresolved. No timestamp, overnight date, range or recurrence is synthesized by
combining facts. Unselected partial interpretations are diagnosed and retained in context.
This deliberately favors coherence over filling every canonical cell.

`FieldProvenance(field, candidate_ids)` references selected facts and corroboration.
`CanonicalDiagnostic(code, field, candidate_ids)` records conflicts and upstream
normalization codes without large evidence payloads. Membership includes sorted unique
candidate IDs, raw IDs (`source_item_ids`), source IDs, publisher keys and evidence URLs.
Every Event defaults to `needs_review`. Domain records do not import scraping, normalization,
database or Google clients. `CandidateContext` belongs to the orchestration/matching layer.

`area_text`, `duration_text`, `organizer_name`, `availability_text` and
`source_schedule_text` resolve like other text facts (folded agreement, conflicts become
null with `field_conflict`). `description_text` is narrative context, not an occurrence fact:
the earliest-anchored source description is kept exactly, with provenance listing the
candidates that supplied the same text, and differing descriptions from several sources
are not a conflict. Descriptions, areas and availability never feed title similarity or
matching. Candidate-level `field_conflicts` become `source_field_conflict` diagnostics.

### Offline review and limitations

`canonicalize --source <id> --source <id>` or `canonicalize --all-enabled` reads local
stored data only. `--instagram-evidence` explicitly selects stored Stage 5 media grouping
with caption fallback; without it Instagram uses captions only. Source reports identify
the chosen mode, missing data and failures. The existing `extract` commands are unchanged.
Raw/evidence snapshots are not rewritten, and the command does not collect, open a browser,
run OCR, contact a network, or persist canonical state. Per-source limits are 1–30 raw items.

Unrecognized title aliases, multilingual names, location variants, multi-location events,
missing titles, recurring/session ambiguity, inferred dates, contradictions and future
source updates remain limitations. Places pass through; Place deduplication is deferred.
Pair enumeration is quadratic and intended for bounded private-source review. Stage 9
uses these results for SQLite persistence and local review snapshots; matching remains independent of persistence.
See [Stage 8 validation](STAGE8_VALIDATION.md) for measured results and coverage gaps.

## Storage boundary

```text
RawItem                         → JSONL
EventCandidate / PlaceCandidate → transient / processing boundary
Event                           → in-memory canonical draft → SQLite current/history state
SQLite                          → canonical/review history, human decisions and notes
XLSX / CSV / JSON                → local review workspace / portable exports
Gemini / Google Sheets          → optional publishing adapters
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

## Local review and persistence (Stage 9)

JSONL is source/evidence audit. SQLite is durable canonical/review state. XLSX is the
default human interface. CSV is portable tabular export; JSON is structured interchange.
Gemini bundles are manual one-way publishing; Google Sheets API is an optional adapter.
Neither cloud account nor Office is required for default persistence/export.
Human edits never modify source facts, normalization, matching or raw/evidence stores.

### Application and run membership

`RunSummary.observed_items` contains the exact immutable RawItems returned by a
collector, including New, Changed and Existing unchanged observations. Its sorted
`observed_item_ids` is the deterministic membership set. No extra unchanged rows
are appended to raw storage. Current capture timestamps are retained in memory,
so refresh Event `last_seen_at` advances even when an unchanged observation is not
appended; `first_seen_at` still comes from stored history.

`run_canonical_review(..., observed_items={source_id: tuple[RawItem, ...]})` bypasses
historical selection only for explicit current-run input. Source/type/unique-ID/limit
checks apply; an omitted source in that map contributes no items. Legacy offline
selection remains unchanged. `SourceReview.observed_item_ids` exposes the exact
selection for stored-data sync as well.

`RefreshService.run` is reusable outside the CLI. It validates persistence and imports local XLSX human edits first, selects
approved enabled sources, isolates source failures, optionally acquires evidence for
exact current Instagram members, and invokes the existing discovery → normalization
→ canonicalization path. Stored-data sync uses the same application service with
`collect=False`: no collector, source browser, OCR, or raw/evidence writes.

A lightweight ignored `RunManifest` stores run ID, aware start/finish timestamps,
selected sources, exact observed IDs, per-source New/Changed/Existing counts and safe
failure codes, limits, review horizon/timezone, evidence mode and completion state.
It contains no canonical fields, raw text, credentials or browser state. Retry reuses
the original run start; a different option set requires a different run ID. Failed
or ambiguous persistence is marked `failed_or_unconfirmed` in the manifest; SQLite
is the local completion authority. A completed retry skips collection and retries exports.
Exporter failures do not roll back canonical state.

Stage 9 adds OCR reuse for matching artifact hash, raw ID, semantic position, engine,
validated version and configuration when prior OCR succeeded or was empty. Failed
OCR retries. Providers without an explicit version do not use the cache. Existing
append-only evidence identity and Stage 5 latest-known-slot limitations remain:
stale removed media slots and A → B → A fragment recency are not solved here.

### Review window and display

Window: run-start date in `--review-timezone` (default Asia/Tehran) through that date
plus `--days` (default 14; 1–90), inclusive. Normalized dates/ranges are retained on
overlap, including known ongoing ranges. Dated Events outside the window are excluded
only from the new snapshot. Inferred dates use their normalized interpretation and
retain review diagnostics. Missing dates/unknown precision are included after dated
Events. Sorting uses date, known time first, time, title, stable Event ID. Review
reference timezone does not overwrite event timezone or source interpretation.

Visible dates are explicit Persian Jalali text using `persiantools`; weekdays come
from the normalized Gregorian date. Hidden ISO components remain machine-safe.
Source `price_text` takes precedence; fallback Decimal text preserves stated TOMAN,
IRR or other currency without conversion. Explicit zero may display `رایگان`;
missing price is blank. Canonical status is translated without inventing cancellation,
sold-out or postponement. Quality labels reflect missing data/diagnostics, not ranking.

### SQLite schema version 1 (records schema 2)

`CanonicalRepository` extends the reusable snapshot persistence seam;
`SqliteCanonicalRepository` implements it using standard-library sqlite3. SQL is
isolated in storage modules. `RefreshService` injects repository, collectors/evidence,
analysis and import/export callbacks; CLI owns argument routing and reporting only.

Default DB: `data/state/gatherradar.sqlite3`, configurable with `--db`/`--data-dir`.
`PRAGMA user_version=1`; empty DB initializes via a transactional migration list,
current version does nothing, unsupported newer/unversioned nonempty DB is refused.
Foreign keys, busy timeout 5000 ms, WAL and FULL synchronous writes are enabled.
`BEGIN IMMEDIATE` commits a complete run or rolls it back. Constraints protect identity,
run/snapshot membership and duplicate pair uniqueness. No delete/recreate migration.

| Table | Responsibility / key |
| --- | --- |
| `runs` | `run_id`; aware timestamps/status plus versioned metadata JSON containing selected sources, exact observed IDs, horizon/timezone, failures, counts, diagnostics |
| `events` | Stage 8 `event_id`, latest run and structured current canonical payload |
| `event_identity_map` | exact Event ID/anchor raw ID/slot, first/last run; conflicting anchor rejected |
| `event_snapshots` | `(run_id,event_id)`, immutable facts, visibility and review sort ordinal; filtered facts retained |
| `event_review` | Event ID, Persian decision, notes, update timestamp; separate from facts |
| `place_snapshots` | `(run_id,candidate_id)` and source-supported Place payload; no fake canonical Place ID |
| `place_review` | same run/candidate key, decision/notes/update timestamp; no cross-run carry-forward |
| `duplicate_review` | stable sorted Event-ID pair key; decisions/notes, first/last run, Event FKs |
| `duplicate_snapshots` | `(run_id,pair_key)` and run-specific context/reasons |
| `review_exports` | opaque token binding kind/ID/run to exported human baseline for safe import |

No full raw captions, OCR content, contexts, browser profiles, tokens or credentials
are serialized into SQLite. Facts retain original source date/price wording, structured
field provenance, membership, source URLs and diagnostics. Raw audit history supplies
the underlying evidence. Stage 8 Event IDs remain authoritative; no title-based alias,
merge/split repair or cross-ID review inheritance is introduced. New runs can contain the
same Event; repeating a committed run ID creates no new rows. Exact run timestamps
are stored in ISO form; no OS-specific provenance paths are required.

The source-completeness pass required no DDL change: Event payloads are versioned JSON
records (records/export schema 2 adds the six source-supported facts). A Stage 9 database
written before them opens unchanged (`user_version` stays 1, reopen is a no-op, newer
versions are still refused) and older payloads load with those fields null. No database is
recreated.

Keep SQLite local with one active writer. The workflow lock is an exclusive local file,
not a distributed lock. Network/synced-folder multi-writer databases are unsupported.
Exports may live in synced folders. See [recovery and backup policy](LOCAL_REVIEW.md).

### Workbook schema version 3

Default: `data/review/GatherRadar.xlsx`. Permanent sheets: `راهنما`, `تاریخچه اجراها`,
`بررسی تکراری‌ها`; hidden `_meta` contains schema version, latest generated run,
and generation timestamp. Database tables are not exposed as tabs.

Event visible columns in order (shared with the optional Sheets row serializer):

`تصمیم من`, `عنوان`, `دسته‌بندی`, `وضعیت رویداد`, `تاریخ شمسی شروع`, `روز`, `ساعت شروع`,
`تاریخ شمسی پایان`, `ساعت پایان`, `زمان‌بندی اعلام‌شده`, `مکان`, `منطقه / محله`, `شهر`,
`آدرس`, `مدت`, `هزینه`, `ظرفیت / وضعیت ثبت‌نام`, `فرمت`, `توضیحات / معرفی`, `برگزارکننده`,
`ثبت‌نام / خرید`, `منبع اصلی`, `همه منابع`, `تعداد منابع`, `کیفیت داده`, `یادداشت من`.

`خلاصه` is no longer shown: `summary` is a reserved, normally empty machine field.
`زمان‌بندی اعلام‌شده` shows `source_schedule_text` when present; otherwise it shows
`source_date_text` only when the normalized date is missing, unknown/inferred or diagnosed,
so a fully modelled single date is not repeated. `ظرفیت / وضعیت ثبت‌نام` uses the badge
treatment and stays separate from `وضعیت رویداد`. `توضیحات / معرفی` holds the complete
source description, wrapped, in a bounded-width column with the usual 60-point row cap;
open the cell to read it all. Only a description over the 32,767-character XLSX cell limit
is cut, with an explicit `… [متن کامل در review.json و events.csv]` marker; SQLite, JSON and
CSV keep it whole. Only link columns become hyperlinks, so text starting with a URL stays text.

Where several supporting URLs exist, extra `پیوند منبع N` columns make each URL
clickable with ordinary hyperlinks. No generated hyperlink formulas or macros.

Hidden Event columns:

`event_id`, `run_id`, `start_date_iso`, `end_date_iso`, `timezone`, `date_precision`,
`starts_at_iso`, `ends_at_iso`, `price_amount`, `currency`, `source_date_text`,
`source_schedule_text`, `source_ids`, `publisher_keys`, `candidate_ids`, `source_item_ids`, `evidence_urls`,
`canonical_source_url`, `diagnostics`, `first_seen_at`, `last_seen_at`,
`duplicate_group_id`, `field_provenance`, `extraction_confidence`, `category`,
`event_format`, `status`, `registration_url`, `review_token`.

Place visible columns: `تصمیم من`, `نام مکان`, `دسته‌بندی`, `شهر`, `آدرس`,
`ساعات فعالیت`, `هزینه`, `خلاصه`, `منبع`, `یادداشت من`. Hidden: `candidate_id`,
`raw_item_id`, `source_id`, `run_id`, `evidence_url`, `review_token`.

Snapshot names use `رویدادها <Jalali-date> <HHMM>` and optional
`مکان‌ها <Jalali-date> <HHMM>`, shortened with deterministic suffixes on collision.
RTL, freeze panes, filters, wrapped cells, useful widths and Persian dropdowns support
review. Technical columns are hidden, not security-protected. No full raw/OCR columns.
Historical sheets remain untouched; permanent navigation/duplicate queue is rebuildable.

The newest Event tab is active and first; latest Place, history, duplicate queue,
older snapshots, guide, then hidden metadata follow. Every review table freezes `A2`.
`exports/excel_design.py` owns semantic bounded dimensions, 30-point bold dark headers,
24–60 point body rows, calm banding/separators and semantic text badges. Editable decisions
have conditional formatting and dropdown validation. Persian/mixed content uses Vazir;
English/technical content uses Poppins. Fonts are not bundled; install them for best
appearance or accept client-specific fallback. Hyperlink labels do not alter targets.
Known category keys are translated only for presentation; unknown keys fall back unchanged.
Duplicate rows link to a primary source and retain both complete URL lists hidden;
Event snapshots provide individually clickable cells for supporting URLs.

Prerelease XLSX schema 1 is refused intact. Schema 2 workbooks (earlier Stage 9) differ
only in new snapshot columns and are accepted: imports read by header name, historical
snapshots are never rewritten, and the next export upgrades `_meta` to 3. Schemas newer
than 3 are refused intact. The optional Google layout keeps its permanent-tab schema 1
(new Event snapshot columns only; human state is read by header name).

### Supported-field extraction hardening

An optional `ExtractionInput.source_title` carries only an adapter-verified retained
heading (`raw_metadata.title_origin = heading`), length 1–500, occurring exactly in
the raw text. Generic/Davvvat/Jabama use a retained h1; Vadoostan owns its explicit
`.font-black` heading selection. First-line fallbacks and arbitrary raw metadata are
excluded. The rule provider uses the heading only after existing Event classification.
The verified heading participates in website content hashing, causing one Changed
revision for an unchanged older capture lacking this context, then stable reruns.
Existing raw JSONL is never rewritten. Recollect to add heading context to old captures.

Standalone exact address/venue section labels now work without a colon; prose mentions
do not become labels. The Persian `ها` connector preserves a recurring weekday and clock
as one source temporal fragment. Normalization still flags unsupported recurrence rather
than inventing a date. Original date/price text and field provenance remain intact.
Event summary generation is not implemented; descriptions are not turned into prose.
Metadata-only content links/JSON-LD remain outside semantic extraction. Explicit supported
registration URLs in text retain the existing path; no page URL is invented as a booking
URL. Unlabelled venue/neighborhood strings do not become inferred locations.
An unlabelled venue can be retained only when a separate short name, explicit
event-at-that-name wording and a labelled street address all corroborate the same
complete name. Organizer identity, prose alone and the last address token are
insufficient. The full source address remains separate and unchanged.
Attendance format requires direct participation/holding wording or a standalone
format label. Ticket purchase, registration, historical mentions and an address
do not establish attendance mode. Both direct attendance modes support `hybrid`.
Explicit directional wording (`روبروی` / `روبه روی`) in an ambiguous location field is
address evidence, not a venue name; no venue is inferred from the remainder.

Event decision options: `بررسی نشده`, `علاقه‌مندم`, `می‌خوام برم`, `رفتم`, `رد شد`.
Duplicate options: `بررسی نشده`, `یکی هستند`, `جدا هستند`. Notes remain literal text.
Only these human fields import. Arbitrary fact edits stay visual. The newest workbook
snapshot per Event is eligible; Places use exact run/candidate identity. Baseline tokens
reject changed IDs and conflicting stale edits; invalid/formula/duplicate rows are
isolated with counts. Corrupt/incompatible schemas fail without replacement. A malformed
or conflicting automatic import holds XLSX export to preserve those edits while allowing
canonical persistence and portable exports. The source engine never consumes human review.

Save in memory to a temporary sibling, reopen/verify cells, then replace atomically.
A file lock/replacement failure leaves old bytes and committed SQLite intact. Unsupported
schemas are never reset. XLSX text limits fail visibly rather than truncate source values,
except the explicitly marked description cell above. Edits to area, description, duration,
organizer, availability or schedule cells are visual only and never imported.

### Portable export schema version 2

`ReviewExporter.export(document)` consumes persisted structured review data. Exporters
are isolated from collection, matching and SQL. `ExcelReviewExporter` additionally uses
the repository's review-token/queue methods; CSV/JSON do not import openpyxl.

JSON top level: `schema_version`, `run`, `events`, `places`, `possible_duplicates`.
Version 2 adds `description_text`, `area_text`, `duration_text`, `organizer_name`,
`availability_text` and `source_schedule_text` (appended CSV columns, stable English keys).
Event records contain canonical domain fields, Jalali dates/weekday/data-quality labels,
and separate `review_decision`, `review_notes`, `review_updated_at`. Place records contain
candidate fields, source ID and review state. Duplicate records contain stable pair and
Event IDs, source URLs, original reason-code arrays, Persian reason text and human state.
Lists remain structured, null stays null, dates/times/datetimes use ISO, enum keys remain
stable, Decimal is exact text. UTF-8 and sorted JSON keys make output deterministic.
Historical fact snapshots overlay current human review at export time.

CSV uses stable English keys from the same records, UTF-8 BOM, empty for null, compact
JSON for arrays/objects. Leading `= + - @`, whitespace-concealed formula prefixes and
leading tab/newline get an apostrophe. JSON keeps the original string. XLSX uses literal
string cell types for untrusted content. Empty CSV tables still include headers.

Default paths: `data/exports/{latest,runs/<run_id>}/{events.csv,places.csv,possible_duplicates.csv,review.json}`.
The `latest` directory is the last explicitly exported selection. Each file replaces
atomically; a multi-file export is not a filesystem transaction. SQLite is authoritative
and partial exports can be regenerated. Gemini manifests include checksums to detect
mixed files and are written last.

### Gemini bundle version 1

`data/exports/gemini/{latest,runs/<run_id>}/` reuses the identical CSV/JSON bytes and
adds `manifest.json` plus `GEMINI_INSTRUCTIONS.md`. Manifest: bundle/export versions,
run ID/timestamp/horizon/timezone, filenames, counts, file roles and SHA-256 digests.
No absolute private paths or authentication state. Instructions require Persian RTL,
exact values/IDs/URLs, unknowns left unknown, separate Event/Place/duplicate tables,
clickable sources, filters, frozen headers and the same human dropdowns. They forbid
fact invention, factual rewriting, silent row removal and automatic duplicate merges.
JSON owns structured IDs/arrays; CSV is a table convenience. Source text is untrusted data.
They also require: description kept whole as untrusted content (never instructions, never
shortened or moved into `summary`), area kept separate from venue/address and never turned
into an address, schedule wording kept visible and never expanded, availability kept as
source wording with no invented capacity, and duration/organizer never derived.

The bundle is generated locally by default and with `export gemini`. No API, upload,
Gemini browser automation, credentials or automatic reverse synchronization exists.
Local XLSX is the supported review round-trip; see [manual workflow](GEMINI_HANDOFF.md).

### Optional Google adapter

Google dependencies live in `.[google-sheets]` and import lazily only on explicit
Google commands. The retained `SheetRepository` keeps its atomic temporary-tab
publication, readback, run-ID reconciliation, remote human-state preservation and
identity map. Its schema remains separate from XLSX (`_event_map`/`_sync_state` remain
remote only). Shared Persian serializers/constants live in `review/`; old imports
remain compatibility shims. Mocked adapter coverage is retained.

`sheets export --run latest` publishes an existing SQLite run without collection or
analysis. Existing Google-owned review wins; local Event and duplicate decisions seed
new remote identities. Google edits do not flow back into SQLite. Legacy explicit
`sheets sync`/`sheets refresh` remain available as direct Google workflows, separate
from normal local refresh. Desktop OAuth and live validation remain optional/pending.
See [optional setup](GOOGLE_SHEETS_SETUP.md).
