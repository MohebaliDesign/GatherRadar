# ROLE

Act as a Senior Full-Stack Engineer, Senior Python Engineer, and Software Architect.

You are working inside the existing GatherRadar repository on:

feat/instagram-collector

Do NOT modify main.
Do NOT commit, push, merge, or create a PR.

This is a targeted live-validation fix.

Do NOT redesign the Instagram collector architecture.

---

# FIRST: INSPECT THE EXISTING IMPLEMENTATION

Before changing anything:

1. Read:
   - AGENTS.md
   - PROJECT_CONTEXT.md
   - README.md
   - docs/DATA_CONTRACTS.md

2. Inspect the current implementation, especially:
   - src/gatherradar/collectors/instagram.py
   - src/gatherradar/collectors/instagram_browser.py
   - src/gatherradar/collectors/instagram_dom.py
   - src/gatherradar/collectors/instagram_instaloader.py
   - src/gatherradar/cli.py
   - existing Instagram tests and fixtures

3. Understand the current flow before editing anything.

Preserve the architecture that already works.

---

# CURRENT STATUS

The browser-backed Instagram collector has now been validated against LIVE Instagram.

Authentication works.

The dedicated persistent Chrome profile works.

The collector successfully opened:

https://www.instagram.com/davvvat/

It successfully discovered and collected 5 real media items.

The live run returned:

Observed: 5
New: 5
Changed: 0
Existing: 0
Failed: 0

A second identical run successfully produced Existing items, so:

- browser login works
- profile discovery works
- media discovery works
- JSONL storage works
- stable IDs work
- deduplication works
- New / Changed / Existing works

DO NOT break these working behaviors.

---

# LIVE DATA PROBLEM

The real JSONL output revealed a data-quality issue.

For real Instagram media, GatherRadar successfully extracted:

- shortcode
- source username
- reel/post origin
- published_at
- image_url
- final URL

But captions were NOT extracted.

Example real output:

raw_text: ""

raw_metadata:
{
  "transport": "browser",
  "caption_source": "none",
  "published_at_source": "time[datetime]:media-link"
}

Hashtags and mentions were therefore also empty.

This means the current synthetic HTML fixtures do not accurately cover Instagram's current rendered caption structure.

The current caption logic is too narrow.

---

# SECOND LIVE PROBLEM: PINNED POSTS

The live collection also included an old post dated:

2026-06-12

among the first 5 collected items, while other collected media were from September 2026.

This strongly indicates that a pinned post from the top of the Instagram profile grid consumed one of the requested `--limit 5` slots.

The user wants:

"recent 5 posts/reels"

not:

"first 5 grid positions"

Pinned posts must therefore NOT displace genuinely newer media.

---

# GOAL

Fix ONLY these two issues:

1. Real Instagram caption extraction
2. Recent-media selection when pinned posts exist

Keep everything else working exactly as it does now.

Target flow:

Instagram profile
→ discover a small bounded candidate pool
→ open media pages
→ extract real caption + publish date
→ sort by actual published_at
→ select the newest requested N items
→ existing RawItem mapping
→ existing JSONL storage

---

# PART 1 — CAPTION EXTRACTION

The current caption extraction must become more robust against the CURRENT rendered Instagram DOM.

Do NOT rely on generated Instagram CSS class names.

Generated class names are unstable and must not become part of the extraction contract.

Prefer semantic DOM structure and stable attributes.

---

## REQUIRED EXTRACTION STRATEGY

Use multiple bounded caption strategies in priority order.

The exact implementation may differ if inspection reveals a cleaner solution, but conceptually use:

### Strategy A — rendered article caption

Prefer caption text from the media's rendered `<article>`.

Support structures where the caption is rendered inside semantic descendants such as:

- h1
- first caption/list item in the article
- text containers such as `span[dir="auto"]`
- other semantic descendants that clearly belong to the media author's caption

Instagram may not use an `<h1>` for every post/reel.

Do NOT assume h1 is always present.

---

### Strategy B — author-associated caption

When possible, identify the caption by its relationship to the source author.

Example source:

davvvat

If the first media-author block contains:

davvvat
<caption text>

extract the caption text without including the username itself.

Do not include:

- comments
- comment authors
- timestamps
- Like counts
- UI buttons
- "Reply"
- "See translation"
- accessibility/navigation text

Do NOT simply store the entire article.inner_text() as the caption.

---

### Strategy C — metadata fallback

Keep Open Graph fallback, but make it more tolerant.

Support common Instagram metadata shapes where caption text may appear inside:

- og:description
- og:title
- meta[name="description"]

Do not require one overly-specific quoted format.

Support patterns such as:

123 likes, 4 comments - davvvat on September 10, 2026: "caption"

and reasonable variations.

HTML entities must decode normally.

Do not accidentally save the likes/comments prefix as the caption.

---

# CAPTION QUALITY REQUIREMENTS

Preserve caption wording.

Do not summarize or normalize the actual content.

Preserve:

- Persian text
- emojis
- hashtags
- mentions
- meaningful line breaks where reasonably possible

Trim only obvious surrounding whitespace/UI noise.

Example:

raw_text should become something like:

"جمعه ۲۱ شهریور دورهمی دعوت داریم 🎉
برای ثبت‌نام..."

not:

"davvvat
120 likes
View all comments
..."

---

# CAPTION SOURCE METADATA

Continue recording:

raw_metadata["caption_source"]

Use clear source labels, for example:

article:h1
article:author-block
article:caption-item
article:dir-auto
og:description
meta:description
none

Do not silently pretend a fallback succeeded.

---

# HASHTAGS AND MENTIONS

Once caption extraction works, the existing caption hashtag/mention extraction should operate on the real caption.

Verify Persian hashtags still work.

Example:

#رویداد
#تهران

and mentions such as:

@venue

must remain supported.

---

# LEGITIMATE EMPTY CAPTIONS

Some Instagram posts genuinely have no caption.

Do not invent text.

`raw_text=""` is still allowed when a post truly has no caption.

However, the extractor should make a strong effort to find the rendered caption before concluding `caption_source="none"`.

---

# PART 2 — PINNED POSTS / TRUE RECENCY

Current behavior appears to select the first `limit` grid links BEFORE enough media pages have been opened to compare their publication dates.

That means an old pinned post can consume a recent-media slot.

Fix this.

---

# REQUIRED RECENCY APPROACH

Do not attempt to depend on a fragile "pinned" CSS icon.

Instead use actual `published_at`.

For a requested limit such as:

--limit 5

discover a SMALL bounded candidate pool larger than the final limit.

For example conceptually:

candidate_limit = limit + 3

because pinned content may occupy several top grid positions.

You may choose a similarly small bounded value if the code architecture suggests something cleaner.

Also apply a hard upper bound so this does not become bulk crawling.

For example:

maximum candidate pool around 10–12 items.

Do not crawl dozens of posts.

---

# IMPORTANT EXISTING BEHAVIOR

InstagramCollector already has recency sorting and final bounding logic.

Inspect it carefully before implementing new sorting.

Reuse or improve the existing sorting boundary rather than implementing conflicting duplicate sorting logic.

The desired conceptual behavior is:

BrowserMediaFetcher
→ fetch enough bounded candidates
→ return media with published_at
→ InstagramCollector sorts newest-first
→ final `_dedupe_and_bound(..., limit)`
→ final N recent items

If this can be achieved cleanly by allowing the browser fetcher to return a small bounded overflow of candidates, prefer that over duplicating final-selection logic.

---

# RECENCY RULES

Items with a valid published_at:

newest first.

Items with no published_at:

sort after items with known timestamps.

Do not invent publication times.

Do not use capture time as publication time.

Preserve deterministic ordering when dates are equal or missing.

---

# EXAMPLE

Suppose profile grid order is:

Pinned A — June 12
Pinned B — August 10
Post C — September 13
Post D — September 12
Post E — September 11
Post F — September 10
Post G — September 9

For:

--limit 5

final results should be:

C
D
E
F
G

The pinned June/August items must not consume recent slots merely because they appear at the top of the grid.

---

# REQUEST BOUNDARIES

This is still a very small private MVP.

Keep collection bounded.

For `--limit 5`:

do NOT inspect 50 posts.

Use the minimum small candidate buffer necessary to handle pinned posts safely.

Keep existing scroll limits / safety limits.

No infinite scrolling.

---

# EXISTING RAW ITEM CONTRACT

Do NOT change the RawItem contract.

Keep:

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
content_hash
raw_metadata

Do NOT reintroduce `content_type` into content_hash.

Preserve stable identity:

instagram:<username>:<shortcode>

---

# EXISTING BAD JSONL RECORDS

Do NOT delete or rewrite existing JSONL data.

The existing raw store is intentionally append-only.

After this fix, the same previously collected shortcode may now have:

old observation:
raw_text=""

new observation:
raw_text="<real caption>"

This should naturally be classified as:

Changed

because the content hash changes.

That is CORRECT.

Preserve this audit history.

Do not migrate/delete the old observation.

---

# POST / REEL CLASSIFICATION

Do not change the currently working classification behavior unless required for this fix.

Reels discovered through:

/reel/<shortcode>/

remain:

content_type = "reel"

Normal browser `/p/` posts may remain:

content_type = "unknown"

if their exact image/video/carousel type cannot be determined reliably.

This is NOT part of the current bug.

Do not spend time solving it.

---

# INSTALOADER

Do not modify the legacy Instaloader implementation unless required for an import/refactor caused by this targeted fix.

The default browser transport must remain unchanged.

No fallback to Instaloader.

---

# LIVE NETWORK RULE

Do NOT make live Instagram requests yourself while implementing this change.

Do not run live collection.

All automated tests remain offline.

The user will perform the final live validation manually.

---

# TESTS — CAPTION EXTRACTION

Add realistic offline fixtures/tests covering at minimum:

1. Caption inside article h1
2. Caption inside first semantic caption/list item
3. Caption inside an author-associated block
4. Caption inside `span[dir="auto"]`
5. Reel caption extraction
6. Persian caption
7. Multiline caption
8. Emoji caption
9. Persian hashtags
10. Mentions
11. Caption must not include source username prefix
12. Caption must not include comments
13. Caption must not include comment usernames
14. Caption must not include timestamps/UI labels
15. Open Graph caption fallback
16. meta[name="description"] fallback
17. legitimate no-caption media stays empty
18. published_at extraction still works
19. image_url extraction still works

Do not build tests around Instagram generated CSS class names.

---

# TESTS — RECENCY / PINNED CONTENT

Add tests proving:

1. Browser fetcher discovers more than final limit when using the recency candidate buffer.
2. Candidate pool is strictly bounded.
3. Existing scroll hard limit remains respected.
4. A June pinned item cannot displace a newer September item for --limit 5.
5. The final five are sorted by published_at newest-first.
6. Items without published_at sort after known dates.
7. Same shortcode is still deduplicated.
8. Reel preference remains intact.
9. Final number never exceeds requested limit.
10. Existing New / Changed / Existing storage behavior is unchanged.

---

# REGRESSION TESTS

Run the complete test suite:

python -m unittest discover -s tests

All previously passing tests should remain passing.

Current baseline before this change was:

231 passed
0 failed

Do not simply delete tests to make the suite pass.

If existing tests need adjustment because they encode the old first-N-grid behavior, update them and explain why.

---

# OPTIONAL INTERNAL REFACTOR

If required, you may introduce small pure helper functions such as:

extract_caption(...)
select_candidate_pool(...)
candidate_limit_for(...)
sort_by_recency(...)

Only if they improve testability.

Do not introduce unnecessary frameworks or abstractions.

---

# DOCUMENTATION

Update README.md and docs/DATA_CONTRACTS.md only where necessary.

Document that:

- Browser collection uses a small bounded candidate pool.
- Final results are selected by publication date so old pinned posts do not consume recent slots.
- Caption extraction uses rendered semantic DOM with metadata fallback.

Do not add another Prompt.md.

---

# SECURITY

Continue to keep:

data/

Git-ignored.

Do not commit:

- browser profile
- cookies
- sessions
- captured Instagram HTML
- real captions from private/local runtime data
- credentials

Tests must use synthetic fixture content only.

---

# DO NOT DO

Do NOT implement:

- Event Detection
- AI extraction
- Google Sheets
- SQLite
- scheduling
- website collectors
- proxy rotation
- stealth automation
- CAPTCHA bypass
- fingerprint spoofing
- bulk Instagram crawling
- private-profile crawling

Stay focused on:

CAPTION EXTRACTION + TRUE RECENCY.

---

# VALIDATION BEFORE STOPPING

Run:

python -m unittest discover -s tests

Then:

python -m gatherradar --help

python -m gatherradar collect instagram --help

Then inspect:

git diff
git diff --check
git status

Verify no runtime data is staged.

---

# FINAL REPORT

When complete, STOP.

Do not commit or push.

Report:

1. Root cause of the missing-caption bug
2. Caption extraction strategy implemented
3. How comments/UI text are prevented from leaking into raw_text
4. Pinned/recency strategy implemented
5. Candidate pool size/bound
6. Files changed
7. Tests added/changed
8. Total tests / passed / failed
9. Whether any existing data contract changed
10. Expected behavior on the next live run
11. git status
12. Confirmation that:
   - no live Instagram request was made
   - no local browser/session data was staged
   - nothing was committed
   - nothing was pushed
   - nothing was merged

Also explicitly state what the user should expect on the FIRST live collection after this fix.

Because existing JSONL observations have empty captions, corrected observations for the same shortcodes may legitimately appear as:

Changed

rather than Existing.

A SECOND identical run after the corrected observations are stored should then become Existing.