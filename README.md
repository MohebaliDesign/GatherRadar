# GatherRadar

> Event discovery for small communities.

GatherRadar collects event information from a curated set of public websites and Instagram pages, turns it into consistent event records, and sends review-ready results to Google Sheets. The first version is a private MVP for planning activities with a community of roughly 20–40 people.

Discovery is **deterministic and free**. The default engine is a rule-based classifier that runs locally: no paid AI, no API key, no cloud service, and no network access at the discovery step.

## MVP

- Collect public event content from approved sources.
- Classify what was collected as an **event**, a **place**, or **neither**.
- Extract and normalize dates, locations, categories, prices, and links.
- Keep every event traceable to its source.
- Detect likely duplicates and flag uncertain data for human review.
- Publish a clean, filterable event list to Google Sheets.

```text
Curated sources → collection → discovery → normalization → deduplication → review → Google Sheets
```

Automated Telegram publishing, recommendations, a public dashboard, and a multi-user product are intentionally deferred until the discovery workflow has been validated.

## Current foundation

The repository now defines the initial source registry and the shared data contracts used by future website and Instagram collectors:

```text
Source → RawItem → EventCandidate → Event
```

The evidence-aware path is:

```text
Source -> RawItem -> evidence acquisition -> EvidenceBundle -> 0..N DiscoveryUnits -> discovery -> candidates
```

The original caption becomes one `CAPTION` fragment without changing `RawItem.raw_text`.
Image OCR, ordered carousel-slide OCR, and timestamped reel-frame OCR are separate fragments
with local artifact and OCR provenance. The current production grouping strategy deliberately
creates only the original caption unit, so existing candidate semantics remain unchanged and
unrelated slides are never blindly concatenated.

The first curated registry lives in `config/sources.yaml`. The Instagram collector is the
only live collection path so far, and it runs only when invoked explicitly. Website collectors
are the next major source family.

Discovery sits after collection:

```text
RawItem → DiscoveryService → DiscoveryProvider → DiscoveryFacts → EventCandidate | PlaceCandidate | Other
```

A provider decides what a raw item is — an event, a place, or neither — and extracts its
source-supported facts in one operation. The service owns everything deterministic: skipping
observations with no meaningful content, validating provider output, mapping the result onto
the right candidate type, keeping provenance from the raw item, and assigning stable candidate
ids.

The interface is provider-neutral, and the shipped implementation is a **rule engine**, not a
model. Candidates are transient (not persisted), and date, price, and category normalization
is a separate, later step.

## Discovering events and places

```bash
python -m gatherradar extract instagram davvvat_instagram --limit 5
```

This reads only what collection already stored. It opens no browser, contacts no source, makes
no network call, needs no API key, costs nothing, and writes nothing.

It analyzes the newest stored observations for the source — the latest observation of each
item, newest by publish date, undated items last — and prints, for every item, what it was
classified as, the scores and signals behind that decision, and the fields read out of it:

```text
[1] instagram:davvvat:ABC123
    Result: Event
    Scores: event 7.5 / place 0.5 / negative 0.0
    Reason: event: terminology with date, time, or registration evidence
    Signals: event_strong:کارگاه, date:جمعه, date:شهریور, time:از ساعت, price:ورودی, location:address
    Negative: -
    Fields:
      title: کارگاه سفالگری
      category: workshop
      source_date_text: جمعه ۲۱ شهریور از ساعت ۱۶ تا ۲۲
      address: تهران، نیاوران، سه راه یاسر
      city: تهران
      price_text: ورودی ۳۵۰ هزار تومان
      language: fa
      evidence_url: https://www.instagram.com/p/ABC123/

Observed: 5
Events: 1
Places: 1
Other: 2
Skipped: 1
Failed: 0
```

`Skipped` means nothing was classified — the caption was empty, or carried no content words at
all. `Other` means the content *was* analyzed and found unrelated. The two are deliberately
different answers.

### How the rule engine decides

No single keyword decides anything. An event needs a path through the evidence: either event
terminology **with** date, time, or registration evidence, or strong event terminology **with**
an invitation to attend and venue context. An attendance invitation alone, a date alone, an
address alone, or an event word alone is never enough. Wording that says the occurrence
already happened (`برگزار شد`, `هفته گذشته`, `behind the scenes`) counts against it as a
penalty, not a veto.

A place needs place vocabulary plus descriptive or visit context, and is only considered when
no event path was satisfied — so a gallery announcing an opening on a date is an event, while a
gallery introducing itself is a place.

Titles are conservative: one is extracted only from a validated named construction
(`رویداد سرام`, `نمایشگاه «نام نمایشگاه»`) or an explicit quotation. A line that merely mentions
an event word gets no title, because an unknown title is better than an invented one.

Persian weekdays, months, relative dates, digits, and times are detected but **not converted**;
the source wording is kept exactly as published. Jalali-to-Gregorian conversion, numeric prices,
and canonical persistence belong to the later normalization step.

The vocabulary and every weight live in one reviewable place, `src/gatherradar/extraction/rules.py`.
Useful flags: `--limit` (default 5), `--config` (default `config/sources.yaml`), and
`--data-dir` (default `data`).

## Development

Requires Python 3.11+ (developed on Python 3.13). Live Instagram collection also requires
Google Chrome installed on the machine.

```bash
python -m venv .venv
python -m pip install -e .
python -m unittest discover -s tests
```

On Windows, activate the environment with `.venv\Scripts\activate`; on macOS and Linux use
`source .venv/bin/activate`.

`pip install -e .` installs the Playwright Python package. GatherRadar drives your installed
Google Chrome through Playwright (`channel="chrome"`), so Playwright's bundled browsers are not
needed and `playwright install` is not required. If Google Chrome is not installed, install it
normally, or run `python -m playwright install chrome`.

The test suite is offline. It never launches Chrome, never contacts Instagram, and no test needs
credentials, Tesseract, an API key, or an AI provider. Browser and OCR boundaries use fakes.
No AI SDK is a dependency.

## Instagram browser profile

Instagram collection runs in a real, visible Chrome window that uses a dedicated GatherRadar
browser profile:

```text
data/browser/instagram-profile/
```

This profile is separate from your normal Chrome profile, so your personal browser is never
touched or locked. The profile itself holds the Instagram login; GatherRadar does not store
passwords or cookies anywhere else.

### Log in once

```bash
python -m gatherradar auth instagram
```

This opens Chrome on Instagram with the GatherRadar profile. Log in manually in that window if
needed — GatherRadar never asks for your password — then return to the terminal:

```text
GatherRadar Instagram authentication

Opening Chrome with the GatherRadar browser profile:
data/browser/instagram-profile

Log in to Instagram in the opened Chrome window.
When the Instagram home page is visible, return here and press Enter.

Verifying session...

Instagram browser session verified.
Persistent profile saved.
```

GatherRadar checks that the window has left Instagram's login flow and that the profile holds
an Instagram login (it never prints cookie values), then closes Chrome.

The login usually persists between runs. If Instagram expires it, collection stops with:

```text
Instagram browser session is not authenticated.
Run:

python -m gatherradar auth instagram
```

Rerun `python -m gatherradar auth instagram` to log in again. If Instagram shows a
verification or checkpoint page, complete it manually in that Chrome window; GatherRadar does
not bypass it.

## Collecting from Instagram

Collection is always explicit — nothing runs on a schedule. Pass a source id from
`config/sources.yaml`:

```bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
```

Chrome does not need to be open. GatherRadar launches its own Chrome window on the GatherRadar
profile, then:

1. confirms the profile is still logged in to Instagram;
2. opens the source profile, e.g. `https://www.instagram.com/davvvat/`;
3. finds posts and reels from their `/p/` and `/reel/` links, taking a small candidate pool
   of up to three more than `--limit` (at most 12 in total unless `--limit` itself is
   larger), scrolling a few times at most and only while fewer candidates are visible;
4. opens each candidate page to read its caption and publish time, then keeps the `--limit`
   newest by publish date, so older pinned posts at the top of the grid do not take recent
   slots (items without a publish date sort last);
5. maps them onto the `RawItem` contract and appends new or changed items to
   `data/raw/instagram/<username>.jsonl`;
6. closes Chrome, including when the run fails.

Captions are read from the rendered post — the caption heading, the author's first caption
item, or the author's caption text — with Open Graph and page description metadata only as a
fallback. Author usernames, comments, timestamps, like counts, and interface labels are left
out, and a post without a caption keeps empty text. `raw_metadata.caption_source` records
which source was used.

Close any Chrome window that GatherRadar left open before collecting; a browser profile can be
used by only one Chrome instance at a time.

Items are keyed by a stable id (`instagram:<username>:<shortcode>`); rerunning the command with
unchanged content appends nothing, and an edited caption is recorded as a new, auditable
observation rather than silently ignored:

```text
Observed: 5
New: 0
Changed: 0
Existing: 5
```

Useful flags: `--limit` (default 5), `--config` (default `config/sources.yaml`),
`--data-dir` (default `data`), and `--transport` (default `browser`).

### Legacy Instaloader transport

The earlier Instaloader transport is kept only as a fallback reference, since its profile
lookup is refused with HTTP 429. The browser transport above is the validated default, and
GatherRadar never falls back to Instaloader automatically. It runs only when requested
explicitly:

```bash
python -m gatherradar auth instagram --legacy-cookie
python -m gatherradar collect instagram davvvat_instagram --transport instaloader
```

## Acquiring visual media evidence

Media acquisition is explicit and separate from offline discovery:

```bash
python -m gatherradar evidence instagram davvvat_instagram --limit 5
```

The command reads only already-collected `RawItem` records, reopens those exact public media
URLs with the existing authenticated GatherRadar Chrome profile, captures the displayed image
or ordered carousel slides, or samples at most six deterministic reel frames, then runs local
OCR. Carousel capture is capped at 20 slides by default. Use `--max-carousel-slides` and
`--max-reel-frames` to lower or explicitly adjust those bounds.

Artifacts are content-addressed below `data/media/instagram/<username>/<shortcode>/` and OCR
evidence is append-only JSONL below `data/evidence/instagram/<username>.jsonl`. Both locations
are runtime data covered by the repository's existing `data/` ignore rule. A repeated run with
the same artifact and OCR output records it as existing; changed pixels, OCR output, engine
version, or configuration remain separate auditable observations. A failed slide, frame, or OCR
operation is reported without discarding unrelated items.

`extract` remains offline and does not read or merge OCR fragments yet. This milestone captures
inspectable evidence and establishes the grouping boundary; semantic grouping of media into
zero or more event/place candidates is intentionally a later change.

### Local Tesseract prerequisite

Install Tesseract locally and install both the Persian (`fas`) and English (`eng`) language
data. GatherRadar never downloads the executable or language packs. Verify the installation:

```bash
tesseract --version
tesseract --list-langs
```

If `tesseract` is not on `PATH`, set `GATHERRADAR_TESSERACT_PATH` to the executable path. This is
especially useful on Windows; keep the value in the local environment and do not commit a
machine-specific path. The evidence command reports a clear error when the executable, `fas`,
or `eng` is unavailable.

Both languages must appear in `--list-langs` before attempting a live evidence run.
A failed prerequisite check remains failed on provider reuse; it cannot authorize OCR.
Install missing language data manually, then repeat the checks. GatherRadar does not
modify PATH or install missing components.

Unexpected capture/OCR exceptions are reported by operation and exception type without
echoing browser or provider exception payloads. A verification/checkpoint page stops
further media navigation for manual resolution and retains earlier captures from that run.

Media selection supports post layouts in either `article` or `main`, excludes linked
post thumbnails and small profile images, and accounts for carousel clipping. Image
captures wait for stable geometry and round their bounds inward to exclude unstable
neighboring pixels. Reel sampling pauses playback and requires a completed seek; a
seek timeout is a capture failure rather than a frame labeled with an unverified time.

Audio transcription and speech-to-text are not implemented. OCR is local and free; no cloud
OCR, paid AI, API key, or new Python dependency is used.

### Local data and privacy

Everything under `data/` — the browser profile, raw captures, and legacy session files — is
local runtime data and is ignored by Git. Passwords, cookies, and browser profile files are
never committed. GatherRadar collects only public profiles listed in `config/sources.yaml`.

## Project docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product scope, data contract, and MVP architecture
- [AGENTS.md](AGENTS.md) — working rules for coding agents and contributors
- [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) — source and event record boundaries

## Status

Early MVP. The Instagram Collector milestone is complete: browser-backed collection has been
validated live against `@davvvat` — authentication through the persistent Chrome profile,
real Persian caption extraction, published timestamps and image URLs, recent-item selection
that is not displaced by pinned posts, and New/Changed/Existing behavior across repeated
runs all work as intended.

Discovery is implemented and tested offline: the provider-neutral boundary plus a
deterministic, free rule engine that classifies stored items as event, place, or other and
reads source-supported fields out of them. Instagram is the first collector; website collectors
are the next major source family.

Visual evidence acquisition is implemented behind a separate explicit command: images,
bounded carousel slides, and bounded reel frames are stored locally, OCRed with local
Tesseract, and persisted as source-neutral evidence. Audio transcription is not implemented,
and OCR evidence is not yet grouped into semantic candidates. Normalization (Jalali conversion,
numeric prices, canonical
persistence, deduplication, and Google Sheets) is a separate, later step, and candidates remain
transient until it exists.

Bounded live validation captured six frames from one Davvvat Reel and five slides from
one Vadoostan carousel. After capture fixes, unchanged reruns appended no evidence for
either sample. Persian OCR on the carousel was partly recognizable but error-prone;
nonempty OCR is not proof of useful text. Standalone images, ordinary videos, repeated
carousel visuals, and wider source/layout coverage still require separate validation.

## License

Licensed under the [MIT License](LICENSE).
