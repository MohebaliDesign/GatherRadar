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

The repository defines the source registry and shared data contracts used by website and Instagram collectors:

```text
Source → RawItem → EventCandidate → Event
```

The evidence-aware path is:

```text
Source -> RawItem -> evidence acquisition -> EvidenceBundle -> 0..N DiscoveryUnits -> discovery -> candidates
```

The original caption becomes one `CAPTION` fragment without changing `RawItem.raw_text`.
Image OCR, ordered carousel-slide OCR, and timestamped reel-frame OCR are separate fragments
with local artifact and OCR provenance. Default extraction still creates only the original
caption unit. Explicit `extract --evidence` selects locally stored evidence and applies
`conservative/1` grouping before discovery; unrelated slides are never blindly concatenated.

The curated registry lives in `config/sources.yaml`. Instagram and public website collection
run only when explicitly invoked. Website primary text uses `WEBSITE_TEXT` through the same
evidence/grouping/discovery boundary.

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

### Public websites (Stage 6)

```bash
python -m gatherradar collect website davvvat_website --limit 5
python -m gatherradar extract website davvvat_website --limit 5
```

The same commands accept `vadoostan_website` and `jabama_events_website`. Collection uses
public static HTTP, with no browser, login, Instagram cookies, OCR, or paid service.
It respects robots rules, checks every redirect against the approved origin and detail
layout, and refuses account paths, downloads, access restrictions, and non-HTML responses.
Robots failures stop collection; missing robots (404/410) permits public pages. Requests
have a 15-second timeout, a 3 MB response bound, at least a one-second interval (or the
robots crawl delay), and at most three redirects. There are no automatic retries.
Access/rate-limit refusals stop that source while retaining earlier successful items.

`WebsiteCollector` delegates URL discovery and content selection to `WebsiteAdapter`;
`HttpTransport` is replaceable independently. One detail page becomes one RawItem.
The listing itself never becomes semantic evidence. A broken detail is reported and
does not discard successful items. `--limit` accepts 1–30 and means the first N valid
details in listing order, with at most `min(3*N, 30)` detail attempts and no pagination.
These are not necessarily the newest or upcoming events. Dynamic listings can select
different items on successive runs.

Raw history is append-only at `data/raw/website/<source_id>.jsonl`, with the existing
New/Changed/Existing semantics. Source wording, Persian digits, and date/price expressions
are preserved; HTML entities and whitespace are rendered into text with neutral separators.
No labels or hidden URLs are injected to strengthen classification. Publication time is
unknown (`null`), not copied from the event date. Metadata holds adapter/version, listing
and detail URLs, title, native ID, transport, structured-data presence, and retained content
hrefs. Metadata does not enter semantic extraction.

`extract website` is always offline and write-free. It reads the latest stored observation
of each identity in **first-seen storage order**, up to the limit. It does not reconstruct
the current live listing. Each item's fresh primary `WEBSITE_TEXT` flows through unchanged
`conservative/1` and `DiscoveryService`, retaining unit/fragment provenance and deterministic
candidate IDs. No separate website evidence file is required. Instagram's default
caption-only command and its optional `--evidence` behavior remain unchanged.

Current adapters and bounded live validation on 2026-09-24:

| Source | Supported detail layout | Collection / offline discovery |
| --- | --- | --- |
| Davvvat | `/event/<id>`; known streamed desktop detail panel without mobile duplicate, account prompts, or comments | Initial five records, five Events. A changing homepage selected different records on a normal rerun; with one actual listing snapshot held fixed, the live-detail rerun returned five Existing and unchanged storage. |
| Vadoostan | `/app/experiences/<id>`; title/details/description before FAQ; organizer biography excluded | Five records, four Events and one Other; normal rerun returned five Existing and no appended lines. |
| Jabama Events | `/events/<id>`; event article plus price from its single sibling booking panel, without reviews/profile/loading UI | Five records, five Events; normal rerun returned five Existing and no appended lines. `/theaters/` and other layouts are not supported. |

Each examined item yielded one primary-text unit. Repeated offline runs preserved unit and
candidate identities and raw files. These are small live samples, not a claim of full site
coverage. The rule engine can leave titles/addresses unset or partially read dates despite
complete raw wording; it was not tuned for these samples. Recurring series or several sessions
within one detail page remain one source observation, without occurrence expansion.

### Adding an approved website

For a straightforward list/detail site, inspect public access, robots, and the detail layout,
then add a source with a small `website` configuration:

```yaml
- id: community_website
  publisher_key: community
  name: Community Website
  type: website
  url: https://community.example/events
  enabled: true
  website:
    adapter: generic
    detail_path_prefixes: [/events/]
    content_selector: '#event'
    exclude_selectors: [.related, '#comments']
    drop_query_params: [campaign]
```

Only drop a query key after verifying it is navigation/tracking, never item identity.
Known `utm_*`, `fbclid`, and `gclid` tracking keys and URL fragments are removed by default;
other query bytes/order are preserved. Detail prefixes match exactly one following opaque
alphanumeric/hyphen/underscore key, optionally ending in `/`. Generic IDs hash the canonical
URL. Current specialized adapters use the path-native ID when no meaningful query remains,
otherwise the URL hash. The source ID namespaces every RawItem identity.

Selectors intentionally support only a tag, `.class`, or `#id`, not arbitrary CSS. Generic
extraction requires exactly one configured region and at most one retained `h1`; it excludes
common navigation, footer, hidden, comment, review, FAQ, aside, and recommendation regions.
The owner must configure exclusions for unusual related-content containers. No whole-body
fallback, rendering of external stylesheets, or automatic full-page segmentation is provided.
The sanitized `tests/fixtures/websites/generic-*.html` integration test demonstrates adding
a future source through configuration alone, using unchanged orchestration/storage/CLI.

An unusual site needs a small class implementing `WebsiteAdapter` and one factory entry
in `collectors/websites/adapters.py:ADAPTERS`, plus sanitized fixtures and live validation.
Keep selectors/layout handling there; do not change orchestration or the semantic engine.
JavaScript-only, authenticated, non-UTF-8, paginated-only, and roundup/card-only sites are
unsupported by this first static transport. **Arbitrary websites cannot be guaranteed to
work from URL alone.** Layout changes should be investigated when collection fails or text
changes; passing selectors alone cannot prove that all irrelevant content was excluded.

### Instagram captions

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

### Discovering from stored evidence (opt-in)

```bash
python -m gatherradar extract instagram davvvat_instagram --limit 5 --evidence
```

This reads local raw and evidence JSONL only. It never opens Chrome, contacts Instagram,
runs OCR, requires Tesseract, or persists candidates. Without `--evidence`, caption-only
behavior, output, and candidate identities remain unchanged.

`conservative/1` selects the current RawItem caption and the latest **stored** media version
per image slot, carousel slide index, or Reel frame timestamp. A latest empty or failed OCR
version suppresses earlier text in that slot. History remains untouched.

Grouping precedes classification and never tries combinations to raise an Event score:

- Named events/places and independent Event/Place paths are anchors. A new anchor starts
  a separate group. Multiple recognizable occurrences within one fragment prevent it from
  anchoring additional text; image-layout segmentation is not implemented.
- Adjacent supporting slides/frames may attach to an anchor only when every line has
  recognizable supporting structure (date/time, labelled location, price, opening hours,
  or registration with a URL), no competing topic, and no conflicting recognized facts.
  Ambiguous text, failed/empty positions, and missing carousel indices break attachment.
- Consecutive Reel frames with identical text after case, script/digit folding, and
  whitespace folding share a unit. Source wording from every contributing frame stays
  intact; changed words or digits remain separate. There is no fuzzy scene matching.
- Caption is never copied across groups. With exactly one media group, it joins only
  when one side is an anchor and the other consists of supporting facts without conflicts,
  or their complete texts are equivalent. Competing anchors and generic captions stay
  separate even with one image. Caption-only evidence remains useful.
- Failed, empty, punctuation-only, and function-word-only fragments supply no semantic
  text. Other unrecognized text stays separate and may classify as Other. No meaningful
  evidence means zero units.

The report shows each RawItem, unit count, shortened stable unit IDs, contributing kinds
and positions (slides are zero-based), classifications, fields, and skip/failure reasons.
Each unit retains the exact fragments; its ID includes the strategy version and ordered
fragment identities. Evidence-aware candidate IDs are unit-specific, including caption
units, and intentionally differ from the legacy caption-only candidate IDs.

This is conservative heuristic grouping, not proof that fragments describe one event.
OCR can miss names or turn unrelated wording into signals. A single poster/caption may
already contain multiple events. Similar-looking text is not automatically deduplicated.
The store has no full-run manifest or removal markers; absent slots and reverted, already
deduplicated observations cannot be reconstructed reliably. See the
[evidence contract](docs/DATA_CONTRACTS.md#semantic-selection-and-grouping-stage-5).

Bounded read-only validation of existing Stage 4 samples produced seven Davvvat units
(caption Event + six noisy frame Others) and six Vadoostan units (caption + five individual
slide Others). No media-derived candidates or blind five-slide merge resulted. These
samples validate separation under poor OCR, not general segmentation accuracy.

A follow-up positive-grouping check inspected five stored RawItems from each of Vadoostan,
Davvvat, Jabama Events, and Emrooz Events (20 items total). Only the carousel and Reel above
had stored media evidence; Jabama and Emrooz had no evidence files. None of the 11 selected
media fragments supplied a clear event/place anchor, so **no suitable real positive grouping
example was found**. No media was recollected and no OCR was rerun.

Positive grouping is instead validated with a
[synthetic Persian poster carousel](tests/fixtures/evidence_grouping/persian_workshop_carousel.json):
slide 0 names a pottery workshop; adjacent slide 1 supplies labelled date/time, address,
price, and registration details without a competing anchor. The unchanged `conservative/1`
policy produces one two-fragment Event unit. Tests check exact extracted wording, fragment
provenance, stable rerun/unit/candidate identities, and separation when a competing anchor,
ambiguous heading, or slide gap is introduced. This validates the capability offline;
positive multi-fragment grouping on real captured evidence remains unvalidated.

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

`extract` remains offline and caption-only by default. `extract --evidence` reads this
already-stored OCR through conservative grouping; acquisition remains a separate command.

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
reads source-supported fields out of them. Stage 6 adds the shared Website Collector and
configured adapters, validated on bounded public Davvvat, Vadoostan, and Jabama Event samples
as described above. It does not change classification thresholds or vocabulary.

Visual evidence acquisition is implemented behind a separate explicit command: images,
bounded carousel slides, and bounded reel frames are stored locally, OCRed with local
Tesseract, and persisted as source-neutral evidence. Stage 5 adds conservative grouping and
explicit offline evidence-aware discovery. Audio transcription is not implemented.
Normalization (Jalali conversion and numeric prices), canonical persistence, deduplication,
and Google Sheets remain later steps. Candidates remain transient.

Bounded live validation captured six frames from one Davvvat Reel and five slides from
one Vadoostan carousel. After capture fixes, unchanged reruns appended no evidence for
either sample. Persian OCR on the carousel was partly recognizable but error-prone;
nonempty OCR is not proof of useful text. Standalone images, ordinary videos, repeated
carousel visuals, and wider source/layout coverage still require separate validation.

## License

Licensed under the [MIT License](LICENSE).
