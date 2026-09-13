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
- Event detection and structured field extraction.
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
Event detection and extraction
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
- **Extraction:** Converts source content into candidate event facts. AI-assisted
  extraction must sit behind a provider-neutral interface.
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
  extraction/       # event detection and structured extraction
  normalization/    # dates, text, locations, categories, and prices
  deduplication/    # exact and fuzzy grouping
  storage/          # SQLite repositories and migrations
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
chosen toolchain. Tests run on `unittest` from the standard library. No formatter,
linter, or AI provider is final yet. See the README for exact setup and run commands.

Instagram access runs through [Playwright](https://playwright.dev/python/) driving the
installed Google Chrome with a dedicated, persistent GatherRadar profile under
`data/browser/instagram-profile/`. The owner logs in manually once in that profile; it is
the persisted session. Responsibilities stay separate: `collectors/instagram_browser.py`
owns the profile, launch, and login checks and navigates pages;
`collectors/instagram_dom.py` extracts media links, captions, and timestamps from page
HTML using URL patterns and semantic elements; `collectors/instagram.py` maps the result
into `RawItem`; storage is unchanged. The browser runs visibly and unmodified — no stealth,
fingerprint changes, proxies, or checkpoint bypasses.

The earlier [Instaloader](https://instaloader.github.io/) transport remains temporarily in
`collectors/instagram_instaloader.py` while the browser transport is validated. It is used
only when explicitly selected, never as an automatic fallback.

## 10. Delivery sequence

The project intentionally became Instagram-first for initial source validation: an
Instagram collector was easier to stand up before a website adapter and gives an early
read on whether anonymous access is viable at all, which the rest of the pipeline
depends on knowing.

1. Define schemas, source registry format, and one sanitized fixture.
2. Implement the Instagram collector end to end into local raw JSONL storage.
3. Complete live Instagram validation (see the open decision below).
4. Add event detection and structured extraction over collected raw items.
5. Add deterministic normalization and validation.
6. Add canonical local storage with deduplication and repeatable reruns.
7. Export candidates to a test Google Sheet without overwriting review fields.
8. Add website adapters and broader source coverage.
9. Pilot with a small curated source set and refine from measured errors.
10. Evaluate Telegram and recommendations only after the discovery loop works.

## 11. Open decisions

- Initial source list and source priority.
- Whether browser-profile Instagram collection is reliable. Anonymous Instaloader runs
  were refused with HTTP 429 (2026-09-10), and so were authenticated Instaloader runs:
  `Profile.from_username()` hits `/api/v1/users/web_profile_info/` even with a valid
  session, while the same account browses `davvvat` normally in Chrome. The
  Playwright + persistent Chrome profile transport is now the default and awaits
  live validation.
- Extraction approach: rules, LLM, or a hybrid, and its cost/privacy constraints.
- Google authentication and ownership model for the review sheet.
- Raw capture retention period.
- Category taxonomy and Persian/English display conventions.
- Scheduling mechanism for local runs.

Resolve these through small end-to-end experiments. Update this document when a
decision changes the product boundary, data contract, or architecture.
