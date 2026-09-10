# GatherRadar — Phase 2: First Real Instagram Collection

Act as a **Senior Python Backend Engineer, Data Pipeline Engineer, and Repository Maintainer**.

You are working locally inside the existing `GatherRadar` repository.

Your task is to implement the **first real Instagram collection slice** using **Instaloader**, while strictly preserving the architecture, product scope, and data contracts already defined in the repository.

---

## 1. Read the repository before changing anything

Before writing code:

1. Inspect the entire current repository structure.
2. Read these files completely:
   - `AGENTS.md`
   - `PROJECT_CONTEXT.md`
   - `README.md`
   - `docs/DATA_CONTRACTS.md`
   - `config/sources.yaml`
   - existing Python models, loaders, fixtures, and tests
3. Check:
   - current Git status
   - current Python project configuration
   - existing tests
   - existing dependencies
4. Treat `PROJECT_CONTEXT.md` and `AGENTS.md` as the source of truth.

Do not redesign the existing architecture unless there is a concrete technical reason.

If something already exists, reuse it instead of creating a parallel implementation.

---

# 2. Goal of this phase

The goal is intentionally narrow:

> GatherRadar should be able to fetch a small number of recent public Instagram posts/reels from the configured `davvvat` Instagram source, convert them into the existing `RawItem` data contract, and store them locally as JSONL.

Target flow:

```text
config/sources.yaml
        ↓
davvvat_instagram
        ↓
Instaloader
        ↓
Recent public posts / reels
        ↓
RawItem
        ↓
JSONL
```

This is the first real external data ingestion test.

---

# 3. Important scope boundary

Implement ONLY the collection layer required for this milestone.

## In scope

- Python environment verification
- Existing tests verification
- Adding Instaloader as a dependency
- Instagram collector abstraction if required
- Instaloader-based implementation
- Loading `davvvat_instagram` from `config/sources.yaml`
- Fetching a small number of recent public posts/reels
- Mapping Instagram metadata into the existing `RawItem` model
- Writing collected RawItems to local JSONL
- Basic idempotency / duplicate protection
- Clear console/run summary
- Unit tests using synthetic fixtures/mocks
- One explicit opt-in live collection command

## Out of scope

Do NOT implement:

- AI event detection
- LLM extraction
- `EventCandidate` generation
- final `Event` generation
- SQLite
- Google Sheets
- Telegram
- Website crawling
- all other Instagram accounts
- recommendations
- scheduling
- dashboard/UI
- proxies
- anti-detection systems
- CAPTCHA bypass
- private profiles
- follower/comment collection
- downloading full images/videos unless technically required

Do not expand the project scope.

---

# 4. Environment verification

First verify the local environment.

Check:

```bash
python --version
```

or on Windows if necessary:

```bash
py --version
```

The project currently expects Python 3.11+.

Then create/use a local virtual environment if one does not already exist.

Preferred:

```bash
python -m venv .venv
```

Activate it appropriately for the current shell.

Then install the existing project in editable mode:

```bash
python -m pip install -e .
```

Run the current tests before modifying code:

```bash
python -m unittest discover -s tests
```

Record the baseline result.

If the existing test suite fails before your changes, investigate and report the existing failure before proceeding.

---

# 5. Add Instaloader properly

Add Instaloader as a normal Python dependency.

Do NOT copy the Instaloader repository into GatherRadar.

Do NOT use a Git submodule.

GatherRadar should depend on Instaloader through its Python package configuration.

The architecture must remain:

```text
GatherRadar
    ↓
Instagram collector interface
    ↓
Instaloader implementation
```

Instaloader must be replaceable later without changing domain models or the rest of the pipeline.

---

# 6. Collector architecture

Follow the existing repository architecture.

Create the minimum necessary modules under the current collector/package structure.

The conceptual contract should remain close to:

```python
collect(source) -> list[RawItem]
```

The collector should:

1. Receive a configured Instagram `Source`.
2. Verify that it is an Instagram source.
3. Use the configured username.
4. Request only recent content.
5. Convert each returned Instagram item into the shared `RawItem` contract.
6. Return domain objects rather than exposing Instaloader-specific objects outside the adapter.

Keep all Instaloader-specific behavior isolated inside the Instagram adapter.

---

# 7. First real source

For this milestone, process ONLY:

```text
source id:
davvvat_instagram

username:
davvvat

canonical URL:
https://www.instagram.com/davvvat/
```

Load this information from:

```text
config/sources.yaml
```

Do not hardcode the username into the collection logic.

---

# 8. Limit the live crawl

This is an MVP validation test.

By default, fetch only a very small bounded number of recent items.

Recommended default:

```text
5 recent posts/reels
```

Make this configurable through a command argument or function parameter.

Example concept:

```bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
```

You may choose a cleaner CLI structure if the existing repository architecture suggests one.

Do not crawl the entire profile history.

---

# 9. RawItem mapping

Convert each collected Instagram item to the existing `RawItem` model.

Map source-supported values such as:

```text
id
source_id
source_type
external_id
content_type
content_url
raw_text
captured_at
published_at
author
image_url
raw_metadata
```

Use:

```text
raw_text = original Instagram caption
```

Do not rewrite or summarize the caption at this stage.

Possible `content_type` values may include:

```text
post
reel
carousel
video
image
unknown
```

Use values that can be derived reliably from Instaloader metadata.

Keep adapter-specific metadata inside:

```python
raw_metadata
```

Avoid polluting the shared domain contract with Instaloader-only fields.

---

# 10. Stable IDs and reruns

The same Instagram post must not become a completely new logical RawItem every time the command runs.

Use a stable identifier based on source identity + Instagram-native identifier/shortcode.

Example concept:

```text
instagram:davvvat:<shortcode>
```

Do not use timestamps or random UUIDs as the only identity for source observations.

---

# 11. JSONL raw storage

For this phase, RawItems should be written to append-friendly JSONL.

Preferred directory:

```text
data/raw/instagram/
```

Example:

```text
data/raw/instagram/davvvat.jsonl
```

Each line must represent one complete RawItem record.

Example shape:

```json
{"id":"...","source_id":"davvvat_instagram","source_type":"instagram","external_id":"...","content_type":"reel","content_url":"...","raw_text":"...","captured_at":"...","published_at":"...","author":"davvvat","image_url":"...","raw_metadata":{}}
```

Important:

- `data/` runtime output must remain Git-ignored.
- Do not commit real scraped Instagram content.
- Do not commit session data.
- Do not commit cookies.
- Do not commit authentication credentials.

---

# 12. Idempotent JSONL behavior

Repeated runs should not endlessly append duplicate copies of the exact same Instagram item.

Implement a simple MVP-safe strategy.

For example:

1. Read existing RawItem IDs from the destination JSONL file.
2. Skip already stored IDs.
3. Append only unseen items.

Report:

```text
observed
new
already_existing
failed
```

Keep this simple.

Do not build SQLite yet.

---

# 13. Authentication and Instagram restrictions

Start with public/anonymous access only if Instaloader supports it reliably.

Do not automatically request account credentials from the user.

Do not implement:

- CAPTCHA bypass
- proxy rotation
- stealth tooling
- anti-bot bypasses
- scraping of private content
- bypassing Instagram access controls

If Instagram blocks anonymous access or Instaloader returns a rate/access restriction:

1. Stop the live crawl safely.
2. Keep the collector implementation intact.
3. Report the exact error.
4. Explain whether an optional authenticated Instaloader session would be the next legitimate test.
5. Do not commit credentials or session files.

Failure of the live request should not cause architecture changes.

---

# 14. CLI / runnable entry point

Provide one simple developer-facing way to run the test.

The final experience should be approximately:

```bash
python -m gatherradar collect instagram davvvat_instagram --limit 5
```

or a similarly clear command.

A successful run should print a concise summary such as:

```text
GatherRadar collection run

Source: Davvvat Instagram
Username: @davvvat

Observed: 5
New: 5
Existing: 0
Failed: 0

Saved:
data/raw/instagram/davvvat.jsonl
```

On a second run:

```text
Observed: 5
New: 0
Existing: 5
```

Keep console output understandable for a non-backend developer.

---

# 15. Error handling

Handle at least:

- invalid source id
- disabled source
- non-Instagram source passed to Instagram collector
- missing Instagram username
- unavailable public profile
- network failure
- Instagram/Instaloader access restriction
- malformed post metadata
- JSONL write failure

One malformed item should not necessarily invalidate all successfully collected items.

Errors should be concise and actionable.

Do not expose secrets or session information in logs.

---

# 16. Testing

Default tests must NOT require live Instagram access.

Add tests using fixtures or mocked Instaloader objects for:

- Source → collector validation
- Instagram item → RawItem mapping
- stable ID creation
- timezone-aware timestamps
- empty captions
- reel/post content type handling
- JSONL serialization
- duplicate prevention
- invalid source behavior

Keep live Instagram testing explicit and opt-in.

After implementation run:

```bash
python -m unittest discover -s tests
```

All existing and new tests must pass.

---

# 17. Documentation

Keep documentation changes minimal.

Update README only if necessary to add the exact local install/run commands.

Update `docs/DATA_CONTRACTS.md` only if the actual contract changes.

Do not expand README into a long architecture document.

Do not rewrite `PROJECT_CONTEXT.md` or `AGENTS.md` unless the implementation introduces a real architectural decision that must be recorded.

---

# 18. Git rules

Do not push anything.

Do not merge anything.

Do not force-push.

Do not rewrite history.

Keep all changes local for now.

Do not commit unless explicitly instructed after I review the result.

Before finishing, show:

```bash
git status
```

and summarize the changed files.

---

# 19. Definition of Done

This phase is complete when:

- Instaloader is installed as a proper project dependency.
- `davvvat_instagram` is loaded from the existing source registry.
- A real Instagram collector exists behind a clean project-owned adapter.
- The collector can request a bounded number of recent public items.
- Instagram objects are converted into the existing `RawItem` contract.
- RawItems can be written to JSONL.
- Re-running does not duplicate already stored items.
- No real scraped data, credentials, cookies, or sessions are committed.
- Unit tests do not require Instagram.
- Existing + new tests pass.
- One explicit live command is available for the first real Davvvat test.
- No Event Detection, AI Extraction, SQLite, Google Sheets, Telegram, or unrelated features were added.

---

# 20. Final report

When finished, do NOT immediately start the next milestone.

Return a structured report containing:

## Baseline
- Python version
- initial test status

## Implementation
- files created
- files modified
- dependency changes
- collector architecture

## Verification
- test command
- test count
- pass/fail result

## Live Davvvat test
- command used
- whether Instagram access succeeded
- number of items observed
- number saved
- number skipped as existing
- output JSONL path
- any access/rate-limit errors

## Git
- final `git status`
- confirm that nothing was pushed

## Next recommended milestone

Do not implement it yet.

The expected next milestone is:

```text
RawItem
   ↓
Event Detection
   ↓
Is this actually an event?
```