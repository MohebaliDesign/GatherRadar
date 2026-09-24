# GatherRadar

> A provenance-first event discovery pipeline for curated websites and Instagram sources.

GatherRadar is an early-stage Python project for answering a practical question: **what worthwhile events can a small community attend next?** It replaces repeated browsing across selected public sources with a reviewable pipeline that collects source content, preserves provenance, extracts structured facts, and classifies each observation as an **event**, a **place**, or **other**.

The current implementation includes source collection, append-only raw storage, optional visual evidence and OCR, conservative evidence grouping, deterministic rule-based discovery, date/time/price normalization, and conservative in-memory event canonicalization. Canonical persistence and Google Sheets synchronization remain future stages.

## Why GatherRadar

- **Curated, not broad crawling.** Sources are explicitly approved in `config/sources.yaml`.
- **Deterministic discovery.** The default engine is rule-based, local, explainable, and requires no paid AI API.
- **Provenance first.** Raw source wording and direct evidence URLs are preserved so extracted facts can be audited.
- **Persian + English aware.** The discovery layer recognizes Persian and English event signals, dates, times, prices, locations, and related wording.
- **Human review by design.** Unknown or ambiguous facts stay unknown instead of being invented.
- **Offline reprocessing.** Stored observations can be re-run through discovery without contacting the original source.

## Project status

| Capability | Status |
| --- | --- |
| Curated source registry | ✅ Implemented |
| Public website collection | ✅ Implemented |
| Instagram collection through a dedicated Chrome profile | ✅ Implemented |
| Append-only raw JSONL storage | ✅ Implemented |
| Optional Instagram media capture + local OCR | ✅ Implemented |
| Conservative evidence grouping | ✅ Implemented |
| Event / place / other discovery | ✅ Implemented |
| Explainable deterministic rule engine | ✅ Implemented |
| Date / time / price normalization | ✅ Implemented; conservative offline review |
| Duplicate grouping / canonical event drafts | ✅ Implemented; conservative offline review |
| Canonical persistence (Sheets-first / SQLite decision pending) | 🧭 Planned |
| Google Sheets review synchronization | 🧭 Planned |
| Scheduling, Telegram publishing, recommendations, public dashboard | ⏸ Deferred |

## How it works

~~~text
Curated source registry
        ↓
Website / Instagram collectors
        ↓
RawItem observations
        ↓
Optional media evidence + OCR
        ↓
EvidenceBundle
        ↓
0..N DiscoveryUnits
        ↓
DiscoveryService + RuleBasedDiscoveryProvider
        ↓
EventCandidate | PlaceCandidate | Other
        ↓
Deterministic normalization (opt-in, transient results)
        ↓
Conservative deduplication → canonical Event drafts (in memory)
        ↓
[planned] persistence / Google Sheets
~~~

The important boundary is that **collection and discovery are separate operations**. Collection talks to a source and stores observations. Extraction/discovery reads stored data and classifies it. For Instagram, media evidence is also an explicit, separate step.

By default, Instagram extraction analyzes the stored caption only. Passing `--evidence` selects already-stored caption/OCR fragments and groups only evidence that can be joined conservatively; unrelated carousel slides or reel frames are not blindly concatenated.

## Requirements

- Python **3.11+**
- `pip` and a local virtual environment
- Google Chrome for Instagram collection/authentication
- Tesseract with `fas` and `eng` language data only when running media OCR

The Python dependencies are declared in `pyproject.toml`. Tesseract is an external executable, not a Python package. If it is not on `PATH`, set `GATHERRADAR_TESSERACT_PATH` to the executable path.

## Quick start

~~~bash
git clone https://github.com/MohebaliDesign/GatherRadar.git
cd GatherRadar

python -m venv .venv
python -m pip install -e .
~~~

Activate the environment with `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on macOS/Linux.

Run the test suite:

~~~bash
python -m unittest discover -s tests
~~~

The tests are designed to run offline with fixtures and fakes; they do not require Instagram credentials, Chrome, Tesseract, a cloud AI provider, or live network access.

## Usage

### 1. Collect from a public website

Use a source ID from `config/sources.yaml`:

~~~bash
python -m gatherradar collect website davvvat_website --limit 5
~~~

Website collection uses bounded static HTTP through source adapters. It respects robots rules, validates redirects/origins, and stores one `RawItem` per supported detail page.

Then classify the stored observations offline:

~~~bash
python -m gatherradar extract website davvvat_website --limit 5
~~~

### 2. Authenticate Instagram once

~~~bash
python -m gatherradar auth instagram
~~~

GatherRadar opens a visible Chrome window using a dedicated profile under `data/browser/instagram-profile/`. Log in manually in that window. GatherRadar does not ask for or store your Instagram password.

### 3. Collect Instagram posts

~~~bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
~~~

The browser transport is the default. The older Instaloader transport remains available only when explicitly selected with `--transport instaloader`; it is not an automatic fallback.

### 4. Discover events and places from stored captions

~~~bash
python -m gatherradar extract instagram davvvat_instagram --limit 5
~~~

This command is offline and write-free. It reads the latest stored observations, runs deterministic discovery, and prints the classification, evidence signals, scores, and source-supported fields.

### 5. Optional: capture visual evidence and OCR

~~~bash
python -m gatherradar evidence instagram davvvat_instagram --limit 5
~~~

This revisits already-known Instagram media through the authenticated browser profile, captures bounded image/carousel/reel evidence, and runs local Tesseract OCR.

Then run evidence-aware discovery:

~~~bash
python -m gatherradar extract instagram davvvat_instagram --limit 5 --evidence
~~~

Evidence-aware extraction still does not persist semantic candidates. It reads stored raw/evidence data, builds conservative discovery units, and reports the transient results.

### 6. Review normalized values offline

~~~bash
python -m gatherradar extract website davvvat_website --limit 5 --normalize
python -m gatherradar extract instagram davvvat_instagram --limit 5 --evidence --normalize
~~~

`--normalize` appends source wording beside dates, times, aware timestamps, price, currency,
reference basis and diagnostics. It reads the same local snapshot as discovery: no collection,
browser, OCR, network or data writes. Without the flag, extract output is unchanged.

Normalization uses `persiantools>=6.2,<7.0` for Jalali conversion, parsing copies for digit
folding, and the configured source's `ZoneInfo` timezone. The package supplies `tzdata` on
Windows. Source date and price text, candidate IDs and provenance remain unchanged.
Date-only values stay dates, never midnight timestamps. Relative dates use stored publication
time, or capture time as fallback. Nearby yearless dates may infer a year within a documented
45-day window; they carry review diagnostics and `inferred` precision, not `exact`.

Prices use Decimal in their stated units: `TOMAN`, `IRR`, or explicit supported foreign
currency codes. Explicit free means zero with no invented currency. Unknown prices stay null.
Multi-day hours, recurring schedules, multiple sessions, broad relative dates, price ranges,
tiers and conditional prices remain partial/unresolved. A bare relative token also needs
clear temporal context, so a publisher named “Today” cannot invent a date.
See [the normalization contract](docs/DATA_CONTRACTS.md#deterministic-normalization-stage-7)
for exact policies and [the validation report](docs/STAGE7_VALIDATION.md) for measured results.

### 7. Review canonical events across sources (Stage 8)

~~~bash
python -m gatherradar canonicalize --source davvvat_website --source davvvat_instagram --limit 5
python -m gatherradar canonicalize --all-enabled --instagram-evidence --limit 5
~~~

This is offline analysis of existing local stores: no collection, browser, OCR, network,
or data writes. `--source` is repeatable; `--all-enabled` analyzes only enabled sources
with local data and reports missing stores. `--limit` is 1–30 raw items **per source**.
Website selection uses storage order; Instagram uses stored publication recency.
Explicit selection can inspect disabled sources offline. `--config` and `--data-dir`
work as on other commands.

Instagram defaults to caption-only discovery. `--instagram-evidence` opts into Stage 5
grouping of stored evidence with a current-caption fallback for items without usable
media. The report identifies each source's path. Legacy `extract instagram` is unchanged.

Only strong `same_event` pairs auto-group, and every member must match every other
member. Possible duplicates remain separate review suggestions. Inferred dates,
recurring schedules, missing titles and unresolved sessions cannot auto-group.
Canonical drafts preserve unknown fields, membership, field provenance and conflicts;
all default to `needs_review`.

Event IDs use the earliest observed raw-item anchor (plus an evidence slot for separate
media events), so later corroborating sources and content edits normally preserve them.
Composition-based duplicate-group IDs are separate. Persistent split/merge identity is
deferred to Stage 9. No canonical state is saved.

See [the Stage 8 contract](docs/DATA_CONTRACTS.md#conservative-canonicalization-stage-8)
and [actual validation](docs/STAGE8_VALIDATION.md). The bounded local sample contained
no sufficiently strong duplicate pair; positive grouping is covered by synthetic fixtures.

## Discovery model

The discovery layer is provider-neutral:

~~~text
RawItem / DiscoveryUnit
        ↓
ExtractionInput
        ↓
DiscoveryProvider
        ↓
DiscoveryFacts
        ↓
DiscoveryService
        ↓
EventCandidate | PlaceCandidate | Other
~~~

The shipped provider is `RuleBasedDiscoveryProvider` (`rule-based/1`). It combines explicit signals rather than relying on a single keyword. For example, event terminology normally needs supporting date, time, registration, invitation, or venue context before content is classified as an event.

The service layer owns deterministic validation, provenance, candidate mapping, and stable candidate IDs. The provider only decides the semantic type and source-supported facts. This keeps the architecture open to future discovery providers without coupling the rest of the pipeline to a model or vendor.

Current candidate fields can include titles, categories, source date text, venue/address/city, event format, price text, registration URL, summary, language, and the direct evidence URL. Discovery leaves normalized values unset; the separate opt-in normalization layer produces a copy with supported structured values and diagnostics.

For the full record shapes and evidence/grouping rules, see [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md).

## Evidence and grouping

GatherRadar keeps original source text separate from visual evidence:

- `CAPTION` — original Instagram caption
- `WEBSITE_TEXT` — primary text selected from a supported website detail page
- `IMAGE_OCR` — OCR from a single image
- `CAROUSEL_SLIDE_OCR` — OCR from an ordered carousel slide
- `REEL_FRAME_OCR` — OCR from a timestamped reel frame

`RawItem.raw_text` is never replaced with OCR output. Evidence is stored separately with artifact and OCR provenance.

The current grouping strategy, `conservative/1`, prefers false negatives over unsafe merges. New anchors split groups; only adjacent structured supporting evidence can attach when there is no competing topic or recognized conflict. Ambiguous fragments remain separate.

## Source registry

All approved sources live in [`config/sources.yaml`](config/sources.yaml). The registry currently contains website and Instagram sources and can carry per-source hints such as timezone, locale, city, username, website adapter, content selector, and supported detail-path prefixes.

For ordinary list/detail websites, the generic website adapter can often be configured without changing orchestration or discovery. Sites with unusual layouts should get a small dedicated `WebsiteAdapter` plus sanitized fixtures and tests.

GatherRadar is intentionally **not** a general-purpose web crawler. JavaScript-only, authenticated, unsupported, or structurally incompatible websites may require a new adapter or may remain out of scope.

## Repository structure

~~~text
GatherRadar/
├── config/
│   └── sources.yaml              # curated source registry
├── docs/
│   └── DATA_CONTRACTS.md         # record, evidence, grouping, and provenance contracts
├── src/gatherradar/
│   ├── collectors/               # website + Instagram acquisition boundaries
│   ├── domain/                   # Source, RawItem, evidence, and candidate models
│   ├── extraction/               # provider interface, signals, rules, fields, service
│   ├── grouping/                 # evidence selection + conservative grouping
│   ├── normalization/            # deterministic dates, times, prices and diagnostics
│   ├── deduplication/            # pair decisions, complete-link groups, canonical drafts
│   ├── ocr/                      # OCR provider boundary + Tesseract implementation
│   ├── orchestration/            # collection/evidence/discovery run coordination
│   ├── storage/                  # append-only JSONL and media storage
│   ├── config.py                 # source registry loading/validation
│   └── cli.py                    # command-line interface
├── tests/
│   └── fixtures/                 # sanitized offline fixtures
├── PROJECT_CONTEXT.md            # product direction and architecture brief
├── pyproject.toml
└── README.md
~~~

### Runtime data

Local runtime state is written below `data/` and is ignored by Git:

~~~text
data/
├── raw/                          # append-only collected observations
├── evidence/                     # append-only evidence/OCR records
├── media/                        # content-addressed captured artifacts
└── browser/instagram-profile/    # dedicated persistent Chrome profile
~~~

Do not commit browser profiles, cookies, sessions, raw private exports, or credentials.

## Design principles

1. **Source-supported facts only.** Missing facts stay unknown.
2. **Traceability over convenience.** Every semantic result should remain connected to the source observation/evidence that produced it.
3. **Explicit side effects.** Collection, evidence acquisition, and offline discovery are separate commands.
4. **Deterministic core.** The current discovery engine is reviewable, local, free, and has no AI SDK dependency.
5. **Adapter isolation.** Source-specific layout logic stays behind collector/adapter boundaries.
6. **Human review is part of the MVP.** The goal is trustworthy shortlisting, not autonomous publishing.

## Roadmap

The intended MVP continuation is:

1. Review Stage 7 date/time/price normalization; category/location normalization remains deferred.
2. Review Stage 8 conservative event groups and possible-duplicate suggestions; Place deduplication remains deferred.
3. Evaluate Sheets-first versus a canonical local SQLite repository for stable history and idempotent reruns. In-memory canonicalization supports either future choice.
4. Synchronize review-ready canonical candidates to Google Sheets while preserving human review fields.
5. Add scheduling and broader delivery only after the discovery workflow is validated.

Telegram publishing, recommendations, community voting, automated booking, a public dashboard, and a multi-user SaaS product are intentionally outside the current implementation.

## Safety and collection boundaries

GatherRadar is built around approved public sources. The project should not bypass authentication, CAPTCHAs, access controls, anti-bot protections, or platform restrictions. Website collection follows robots directives and bounded request behavior; Instagram uses an ordinary visible browser session authenticated manually by the owner.

The project does not need followers, comments, direct messages, private profiles, or unrelated personal data to discover events.

## Documentation

- [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) — product goals, boundaries, and longer-term MVP architecture
- [`docs/DATA_CONTRACTS.md`](docs/DATA_CONTRACTS.md) — detailed data, evidence, storage, grouping, and provenance contracts
- [`config/sources.yaml`](config/sources.yaml) — currently approved sources and adapter configuration

## License

GatherRadar is licensed under the [MIT License](LICENSE).
