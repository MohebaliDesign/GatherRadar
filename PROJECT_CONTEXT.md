# GatherRadar Project Context

**Status:** Living product and architecture brief

**Stage:** Early MVP

**Primary audience:** The project owner and a private community of approximately 20–40 people

## 1. Product summary

GatherRadar helps its owner answer a practical question: **What worthwhile
events can our community attend next?**

The product replaces repeated browsing across selected websites and Instagram
pages with a reviewable event-discovery pipeline. It collects public event
content, preserves the source, extracts structured facts, normalizes them,
groups likely duplicates, and publishes useful candidates to Google Sheets.

This is a small, private validation project. Optimize for trustworthy output,
fast learning, and easy changes rather than public scale or feature breadth.

## 2. Product boundaries

### Current MVP outcome

A repeatable run produces a clean Google Sheet containing current event
candidates that the owner can filter, verify, compare, and shortlist.

### In scope

- A manually curated registry of public event sources.
- Website and Instagram source adapters where access is permitted and reliable.
- Raw source capture with timestamps and provenance.
- Deterministic, free discovery: classifying source content as an event, a place,
  or neither, and extracting structured fields from it. No paid AI or API key is
  required to run the core MVP.
- Persian and English text handling.
- Date, time, timezone, location, category, and price normalization.
- Duplicate detection without destructive deletion.
- Confidence and review states for uncertain records.
- Local persistence and Google Sheets export or synchronization.
- Manual or scheduled local execution with understandable run summaries.

### Deferred

- Selecting events through a dedicated dashboard.
- Telegram publishing, polls, or community voting.
- Personalized ranking and recommendation models.
- Automated booking or registration.
- A public SaaS product, accounts, roles, payments, or multi-tenant infrastructure.
- Broad, unsupervised crawling of the web or Instagram.

## 3. Primary workflow

1. The owner maintains a small list of approved sources.
2. A collection run checks each enabled source and records what was observed.
3. The pipeline identifies event-like content and extracts candidate facts.
4. Deterministic rules normalize and validate those facts.
5. Exact and probable duplicates are grouped.
6. Candidates are written to a review-friendly Google Sheet.
7. The owner verifies uncertain fields and chooses what is worth sharing.

Human review is a product feature in this phase, not an exception. The system
must expose uncertainty rather than silently inventing missing information.

## 4. MVP architecture

```text
Source registry
      ↓
Source adapters (website / Instagram)
      ↓
Raw capture store
      ↓
Evidence selection and conservative grouping (explicit opt-in for media)
      ↓
Discovery (event / place / other) and extraction
      ↓
Normalization and validation
      ↓
Deduplication
      ↓
Canonical local repository
      ↓
Google Sheets review view
```

### Architectural responsibilities

- **Source registry:** Declarative source name, type, URL, locale, timezone,
  enabled state, collection interval, and adapter configuration.
- **Source adapters:** Fetch content only. Source-specific behavior remains
  isolated behind a shared interface.
- **Raw capture store:** Retains enough source material, hashes, and timestamps
  to reproduce or audit an extraction.
- **Discovery:** Classifies source content as an event, a place, or neither, and
  converts it into candidate facts. The default engine is deterministic, rule-based,
  and free; any other implementation must sit behind the same provider-neutral
  interface.
- **Normalization and validation:** Applies deterministic conversions and flags
  incomplete or contradictory data.
- **Deduplication:** Groups probable matches using source identifiers first, then
  normalized title, date/time, venue, and location signals.
- **Canonical repository:** A local SQLite database is the recommended MVP
  source of truth. It supports idempotent reruns and history without operating a
  server.
- **Google Sheets:** A review and collaboration surface. It must not be the only
  copy of raw or canonical data.

Keep the pipeline modular. A change to one website, extraction provider, or
output destination should not require rewriting the rest of the system.

## 5. Data contract

Use two related records: an immutable-enough source observation and a canonical
event candidate. Exact implementation types may change, but the separation and
meaning of the fields should remain stable.

Discovery also recognizes a third outcome. Content that describes a venue worth
visiting rather than an occurrence becomes a **place candidate** — name, summary,
category, address, city, opening-hours text, price text, language, and evidence URL —
kept separate so place content is never forced into an event record. Content that is
neither becomes no candidate at all. See `docs/DATA_CONTRACTS.md` for the full shape.

### Source observation

| Field | Meaning |
| --- | --- |
| `source_record_id` | Stable internal identifier for the observation |
| `source_type` | Adapter family, such as `website` or `instagram` |
| `source_name` | Human-readable configured source name |
| `source_url` | Root page or account URL |
| `content_url` | Direct URL of the observed page or post |
| `captured_at` | Time the collector observed the content |
| `content_hash` | Hash used to recognize unchanged content |
| `raw_text` | Extracted source text without semantic rewriting |
| `raw_metadata` | Adapter-specific metadata stored as structured data |
| `collector_version` | Version or identifier of the collection logic |

### Canonical event candidate

| Field | Meaning |
| --- | --- |
| `event_id` | Stable internal event identifier |
| `title` | Best source-supported event title |
| `summary` | Short factual summary grounded in the source |
| `category` / `tags` | Controlled category plus optional discovery tags |
| `source_date_text` | Original date wording for audit and review |
| `starts_at` / `ends_at` | Timezone-aware normalized timestamps when known |
| `date_precision` | `exact`, `day`, `range`, or `unknown` |
| `timezone` | IANA timezone used for interpretation |
| `venue_name` / `address` / `city` | Structured location fields when known |
| `event_format` | `in_person`, `online`, `hybrid`, or `unknown` |
| `price_text` | Source wording for price; never discard it after normalization |
| `price_amount` / `currency` | Parsed price fields when unambiguous |
| `registration_url` / `registration_deadline` | Registration facts when present |
| `canonical_source_url` | Best direct evidence URL for the event |
| `language` | Detected source language |
| `extraction_confidence` | Calibrated score or level, not a truth guarantee |
| `review_status` | `needs_review`, `verified`, or `rejected` |
| `duplicate_group_id` | Optional link between probable duplicates |
| `first_seen_at` / `last_seen_at` | Discovery history |
| `reviewer_notes` | Human corrections or decisions |

Unknown fields remain null or explicitly unknown. Never infer a venue, price,
date, or registration detail merely to make a row look complete.

### Google Sheets view

Use one row per canonical candidate. The initial ordered columns are:

```text
review_status, event_id, title, category, start_date, start_time, end_date,
end_time, timezone, venue_name, city, event_format, price_text,
registration_deadline, registration_url, source_name, source_type,
canonical_source_url, summary, tags, extraction_confidence, first_seen_at,
last_seen_at, reviewer_notes
```

Do not place full raw payloads or credentials in the sheet. Sync by `event_id`
so reruns update existing rows instead of appending endless copies. Preserve
human-owned review fields during automated updates.

## 6. Data and language rules

- Store normalized timestamps as timezone-aware values. Preserve the source
  timezone and render review dates consistently.
- Use `Asia/Tehran` only when the source configuration or event evidence makes
  that interpretation valid; do not assume every event is in Tehran.
- Support Persian digits, Persian month names, and Jalali dates. Convert them to
  Gregorian ISO values while retaining `source_date_text`.
- Keep a controlled top-level category vocabulary; keep free-form labels as tags.
- Prefer exact source IDs, URLs, and hashes for deduplication. Fuzzy matches must
  be reviewable and must not delete records automatically.
- Mark expired, cancelled, postponed, or sold-out events when the source says so.
- Every canonical fact must be traceable to at least one source observation.

## 7. Collection and safety policy

- Collect only public event information from sources approved by the owner.
- Follow applicable terms, robots directives, rate limits, and platform rules.
- Prefer official feeds, APIs, exports, or permitted access methods when they are
  available.
- Never bypass authentication, CAPTCHAs, access controls, or anti-bot measures.
- Do not collect followers, comments, private profiles, direct messages, or
  unrelated personal data.
- Never commit cookies, tokens, credentials, raw session data, or private exports.
- Isolate a failing source, use bounded retries, and report the failure without
  blocking the remaining sources.
- Make retention of raw captures configurable and keep only what is needed for
  debugging, provenance, and reprocessing.

## 8. Quality and observability

Each run should have a `run_id`, start and finish timestamps, per-source status,
counts for observed/extracted/new/updated/duplicate/rejected records, and concise
errors. Logs must be useful without exposing secrets.

The pilot should measure:

- source coverage against a small manual sample;
- required-field completeness;
- false-positive and missed-event rates;
- duplicate rate after grouping;
- time needed for owner review;
- percentage of records requiring correction.

Set numeric acceptance thresholds only after a baseline run. Avoid inventing
precision targets before real source samples exist.

## 9. Proposed repository shape

Create this structure incrementally as implementation begins:

```text
src/gatherradar/
  domain/           # records, enums, and validation contracts
  collectors/       # source adapter interface and implementations
  ocr/              # provider boundary and local Tesseract implementation
  grouping/         # semantic snapshot selection and conservative discovery units
  extraction/       # discovery: classification, rule engine, and field extraction
  normalization/    # dates, text, locations, categories, and prices
  deduplication/    # exact and fuzzy grouping
  storage/          # raw/evidence JSONL and media now; SQLite repositories later
  exports/          # Google Sheets integration
  orchestration/    # run coordination and summaries
tests/
  fixtures/         # sanitized, stable source samples
  unit/
  integration/
config/
  sources.example.*
data/               # local runtime data; add to .gitignore before use
```

Python 3.11+ with `pip`, a local `.venv`, and setuptools via `pyproject.toml` is the
chosen toolchain. Tests run on `unittest` from the standard library. No formatter or
linter is final yet. Discovery uses the standard library only and adds no AI dependency;
`openai`, `anthropic`, LangChain, and any other paid or cloud AI service are deliberately
out of the core MVP. See the README for exact setup and run commands.

Instagram access runs through [Playwright](https://playwright.dev/python/) driving the
installed Google Chrome with a dedicated, persistent GatherRadar profile under
`data/browser/instagram-profile/`. The owner logs in manually once in that profile; it is
the persisted session. Responsibilities stay separate: `collectors/instagram_browser.py`
owns the profile, launch, and login checks and navigates pages;
`collectors/instagram_dom.py` extracts media links, captions, and timestamps from page
HTML using URL patterns and semantic elements; `collectors/instagram.py` maps the result
into `RawItem`; storage is unchanged. The browser runs visibly and unmodified — no stealth,
fingerprint changes, proxies, or checkpoint bypasses.

Visual evidence acquisition is a separate explicit run over already-stored `RawItem` records.
`collectors/instagram_evidence.py` revisits only those approved media URLs through the same
authenticated Chrome profile, captures the displayed image or bounded ordered carousel slides,
and samples a small deterministic set of reel frames. It stores content-addressed PNG artifacts
below `data/media/`; one artifact failure is isolated from other items. Audio is out of scope.

`OcrProvider` keeps evidence independent of one OCR engine. The first implementation invokes
the local Tesseract executable with `fas+eng`, a bounded timeout, and no `shell=True`; it never
downloads an executable or language pack. Raw and lightly cleaned OCR output, engine/version/
configuration, artifact provenance, empty results, and failures are represented explicitly.
No cloud OCR, paid AI, API key, or new Python dependency is required.

The earlier [Instaloader](https://instaloader.github.io/) transport remains as a legacy
fallback reference in `collectors/instagram_instaloader.py`, since its profile lookup is
refused with HTTP 429. It is used only when explicitly selected, never as an automatic
fallback.

Discovery lives in `extraction/`. `DiscoveryProvider` is a provider-neutral protocol whose
single `discover` call both classifies a raw item and returns source-supported facts
(`DiscoveryFacts`) from a deliberate `ExtractionInput` that excludes adapter `raw_metadata`.
The classification is a typed `DiscoveryType` — `EVENT`, `PLACE`, or `OTHER` — never a free
string. `DiscoveryService` validates that output, maps it onto `EventCandidate`,
`PlaceCandidate`, or no candidate at all, sets provenance (`raw_item_id`, `evidence_url`) from
the `RawItem` itself, and derives the candidate id from the raw item id and content hash so it
never depends on the provider. `orchestration/discovery_run.py` analyzes a batch item by item
and keeps candidates in memory. Normalization-owned fields (`starts_at`, `ends_at`,
`price_amount`, `currency`) stay null until the normalization step exists.

The source-neutral evidence boundary is `RawItem -> EvidenceBundle -> 0..N DiscoveryUnits ->
DiscoveryService`. The original caption is a `CAPTION` fragment and still reaches the rule
engine unchanged. Media OCR is stored as separate `IMAGE_OCR`, `CAROUSEL_SLIDE_OCR`, and
`REEL_FRAME_OCR` fragments; future website adapters use `WEBSITE_TEXT` through the same layer.
`RawItem.raw_text` is never replaced with OCR. Default extraction still creates only the
caption unit. Stage 5 adds explicit `extract --evidence`: `grouping/` selects the current
caption plus the latest stored fragment per semantic media position, then `conservative/1`
builds zero or more units. Failed/empty latest versions suppress older OCR without changing
storage. Unit identity includes raw item id, strategy version, and ordered fragment ids;
unit text joins only deliberately grouped source fragments, unchanged, with newlines.

Grouping reuses existing signals without changing classification rules. New anchors split
groups; only adjacent, structured supporting facts without recognized conflicts may attach.
Ambiguous or unavailable fragments break attachment. Consecutive Reel samples with fully
equivalent folded text group together; changed wording/digits stay separate. Captions are
never copied to multiple groups, and a single media group joins a caption only when their
roles are complementary and nonconflicting, or their complete texts are equivalent.
Uncertain relationships remain separate. This does not reliably segment multiple events
inside one image or resolve noisy OCR, implicit references, or semantic contradictions.

`orchestration/evidence_discovery_run.py` reads local raw/evidence stores, selects items with
the existing recency policy, isolates malformed records and per-item/unit failures, and
returns transient candidates plus units for provenance review. It invokes no collector or
OCR engine. Evidence-aware candidate IDs are unit-specific; default caption-only IDs and
output remain unchanged. No database-specific logic or candidate persistence is introduced.

The append-only evidence contract lacks run manifests, removed-slot markers, and observation
timestamps. Selection means latest stored version per slot, not a full capture snapshot:
missing positions can remain stale, and returning to an already-stored fragment is not
recorded by Stage 4 deduplication. This limitation is documented rather than changing
persistence in Stage 5. SQLite remains the recommended canonical MVP store; choosing a
future Sheets-first workflow is a separate decision.

`storage/evidence_jsonl.py` persists evidence append-only and idempotently below
`data/evidence/`. Artifact hash plus media position avoids identity based on signed CDN URLs;
OCR engine/configuration and output changes remain auditable. Candidates remain transient.
Carousel and reel OCR fragments require their respective non-negative integer position;
other fragment kinds reject media positions. Valid persisted identities remain unchanged.

**GatherRadar's core MVP runs completely free.** The default and only implementation of that
protocol is `RuleBasedDiscoveryProvider` (`rule-based/1`): deterministic rules with no model,
no API key, no paid service, and no network access. The engine is split so its judgement is
reviewable — `text.py` (length-preserving folding and whole-token matching), `rules.py` (all
vocabulary, weights, and thresholds in one place), `signals.py` (explainable signal detection),
`fields.py` (source-supported field reading), `rule_based.py` (scoring and the decision). It is
source-neutral: it reads `ExtractionInput`, so website observations and later source families
use the same engine unchanged. Every decision carries `DiscoveryEvidence` — scores, matched
signals, negative signals, and a reason — which belongs to the run outcome and is never
persisted.

`storage/jsonl.py` gained a read-only side, `read_latest_items()`, which returns the most
recently stored observation of each id and isolates malformed lines instead of raising.
`python -m gatherradar extract instagram <source_id> --limit 5` runs discovery over stored
items only: it never collects, never opens a browser, and persists nothing.

## 10. Delivery sequence

The project intentionally became Instagram-first for initial source validation: an
Instagram collector was easier to stand up before a website adapter and gives an early
read on whether anonymous access is viable at all, which the rest of the pipeline
depends on knowing.

1. Define schemas, source registry format, and one sanitized fixture. **Done.**
2. Implement the Instagram collector end to end into local raw JSONL storage. **Done.**
3. Complete live Instagram validation. **Done** — the browser-backed collector has been
   validated live against `@davvvat`: authentication, profile and media discovery, real
   Persian caption extraction, published timestamps and image URLs, recency-based
   selection that pinned posts do not displace, and New/Changed/Existing behavior across
   repeated runs. This closes the Instagram Collector MVP milestone.
4. Add detection and structured extraction over collected raw items. **Done** — the
   provider-neutral boundary (`RawItem` → `DiscoveryService` → `DiscoveryProvider` →
   transient `EventCandidate` | `PlaceCandidate` | none) plus a deterministic, free rule
   engine behind it, reachable through `python -m gatherradar extract`. Tested offline with
   fake providers for the architecture and synthetic Persian and English captions for the
   rules. No AI is used and none is required.
5. Add source-neutral visual evidence, bounded Instagram image/carousel/reel capture, local
   OCR, and evidence persistence. **Implemented and validated on bounded live samples:** one
   Davvvat Reel (six frames) and one Vadoostan carousel (five slides), local `fas+eng` OCR,
   artifact/provenance inspection, and unchanged reruns with zero new evidence. Persian OCR
   quality remains variable; standalone images and broader media/layout coverage are not yet
   validated. The existing caption candidate semantics remain unchanged.
6. Add conservative evidence grouping and explicit offline evidence-aware discovery
   (**Stage 5**). Implemented with synthetic offline tests and bounded read-only inspection
   of the existing Stage 4 evidence: Davvvat produced a caption Event and six noisy frame
   Others; Vadoostan produced a caption Other and five independent slide Others. No blind
   carousel concatenation or new media candidates occurred. Broader segmentation accuracy
   remains unvalidated; owner review is required before starting the next milestone.
7. Add website adapters and broader source coverage. **The next major source family** after
   grouping review. Website text uses the same evidence/discovery-unit boundary; no website
   collector is implemented in Stage 5.
8. Add deterministic normalization and validation: Jalali-to-Gregorian conversion, normalized
   timestamps, and numeric prices.
9. Add canonical local storage with deduplication and repeatable reruns.
10. Export candidates to a test Google Sheet without overwriting review fields.
11. Pilot with a small curated source set and refine from measured errors.
12. Evaluate Telegram and recommendations only after the discovery loop works.

## 11. Open decisions

- Initial source list and source priority.
- Google authentication and ownership model for the review sheet.
- Raw capture retention period.
- Category taxonomy and Persian/English display conventions. The rule engine ships a small
  provisional vocabulary in `rules.py`; the final taxonomy is still open.
- Scheduling mechanism for local runs.
- Whether anything beyond the rule engine is ever needed. **Resolved for now:** discovery is
  deterministic and free, and no paid AI or API key is part of the core MVP. `DiscoveryProvider`
  stays provider-neutral so that decision remains reversible, and measured rule-engine error
  rates from the pilot are what should reopen it.

Resolve these through small end-to-end experiments. Update this document when a
decision changes the product boundary, data contract, or architecture.
