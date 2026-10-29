# Live-Run QA and OCR Fallback (2026-10-29)

Follow-up on branch `fix/gatherradar-source-field-hardening` (draft PR #11, base
`feat/data-quality-occurrences`). Neither PR #11 nor anything else was merged; `main` is
unchanged. Contract details: [data contracts](DATA_CONTRACTS.md#live-run-qa-fixes-2026-10-29).

**Inputs actually available in Cloud:** the owner's live-run `review.json`, workbook
`GatherRadar.xlsx` and manifest for run `e3ddedf31d5248808f78e5586b58d703` (started
2026-10-29T12:54:35Z, 9 sources, 26 canonical Events: 12 actionable, 10 schedule review,
4 expired). The referenced "targeted QA and OCR fallback master prompt" was **not** among
the attachments; this work follows the priorities stated in the owner's message. Raw
JSONL, HTML, media and SQLite from the run were not available; live sources remain
unreachable from Cloud.

## What the live run confirms about PR #11

- Jabama program sections reached `description_text` on five live pages (`89740631`,
  `86400491`, `48751310`, `01519540`, `08945247`): `چه برنامه‌ای داریم؟` and its text are
  present. The other two audit pages were not described this run (see open items).
- Mana's range shows a blank remaining-session count in the live workbook.
- The new session diagnostics fired on **every** Jabama website page
  (`embedded_session_drift_new_properties`), so no embedded sessions were read at all.

## Defects confirmed in this run and fixed

| Live item | Symptom | Cause | Fix | Tests |
| --- | --- | --- | --- | --- |
| Jabama `08945247` | `source_date_text` = `۲ ساعت` | `مدت زمان:` also matched the date label `زمان:` | nested labels belong to the longer label | `test_live_run_temporal.py` |
| Jabama `95037796` | `۸ آبان · ۱۸:۰۰` lost its clock → schedule review | `·` not a date/clock separator | `·`/`•` accepted as separators | same |
| Salovini `De98iwhkf3A` | `جمعه ۸ آبان / ساعت ۵` published as **05:00**, actionable | bare 12-hour clock read as 24-hour; extraction also dropped `عصر/شب` (so `ساعت ۸ شب` became 08:00) | day-part words kept and applied within fixed bounds; bare 1–6 without minutes = `ambiguous_meridiem` → schedule review | same |
| Salovini `De98iwhkf3A` | `جمعه و شنبه ۸ و ۹ آبان` unresolved | weekday-list prefix unsupported | expanded when weekdays match dates in order | same |
| Davvvat `DfCnNueOwV6` | no venue (`در عمارت زیرخاکی` under the title) | generic head without holding wording | standalone line under the title + repeated name | `test_live_run_fields.py` |
| Davvvat `DfCdYpmtECt` | no venue (`ایونت «چیزمیز» در کافه‌کتاب مدیا`) | no prose/address agreement for this form | quoted event name + exact address tail | same |
| All Jabama pages | zero sessions read | strict parser refused any new session property | bounded tolerant mode (below) | `test_jabama_sessions.py`, `test_jabama_program_sessions.py` |

Before/after on identical live wording (PR #11 head `0d4cc39` vs current head):

| Input | Before | After |
| --- | --- | --- |
| Hiilan description `source_date_text` | `۲ ساعت` | none from the duration label |
| `۸ آبان · ۱۸:۰۰` | 30 Oct, no clock, `unparsed_temporal` | 30 Oct 18:00 |
| `جمعه ۸ آبان / ساعت ۵` | 30 Oct **05:00** | 30 Oct, no clock, `ambiguous_meridiem` |
| `جمعه و شنبه ۸ و ۹ آبان` | no session, `ambiguous_date_context` | 30 and 31 Oct |
| venue سکانس چهارم / چیزمیز | null / null | `عمارت زیرخاکی` / `کافه‌کتاب مدیا` |

Policy change to note: a test previously pinned `ساعت ۸ شب` as unreadable. Combined with
extraction dropping `شب`, real 20:00 events became 08:00. `شب` is now applied to 6–11 only;
`ساعت ۲ شب` / `ساعت ۱۲ شب` remain unchosen.

## Jabama sessions with unknown properties

The new property **names** are recorded locally in raw metadata
`source_session_drift_keys` but were not in the uploaded files, so no new shape could be
documented. Bounded tolerant mode: a session whose only drift is extra, safely named
properties keeps its own id, start and duration (`schema_status = unverified_properties`);
price, discount, seats and enabled are not read. Its occurrence is reviewable but never
actionable, unless its date and clock equal exactly one schedule the page states in
visible text (then `embedded_session_corroborated_by_page_text`). Non-empty `timeslots`
and unsafe key names stay refused. Expected effect on the next live run: pottery,
perfume, tour and stand-up pages should show session dates in schedule review instead of
"unreadable"; the Hiilan workshop should stay actionable if its sessions match its visible 15:00 schedule.

## OCR fallback

`FallbackOcrProvider` with engines from `GATHERRADAR_OCR_ENGINES`
(default `tesseract,easyocr,windows`). Unavailable engines are skipped; a later engine runs
only after a failed or empty result; each attempt is stored separately and the chosen one
last. `python -m gatherradar ocr check [--image PATH]` validates engines read-only.

| Engine | Verified in Cloud |
| --- | --- |
| Tesseract 5.3.4 + `fas` | **Real**, through the chain, on a rendered Persian image (`RealTesseractTests`, skipped where Tesseract is absent) |
| EasyOCR 1.7.2 (optional extra) | **Real**, manual run in a scratch venv with Tesseract deliberately broken: read `کارگاه سفال / جمعه ٨ آبان` from a rendered image. Not part of the default suite (torch is large). |
| Windows.Media.Ocr (PowerShell) | **Not run** — Linux Cloud. Behaviour tested with a fake runner only. Persian (`fa`) OCR availability on Windows is not confirmed; if not installed, the engine reports unavailable rather than substituting another script. |

None of this proves OCR quality on the owner's Instagram media; the two OCR audit entries
(Evenza `DewenndDR2X`, Jabama `DewdAUCCnsq`) and this run's 9 `title_resolution_failed`
media candidates still need the original images.

## Open items (evidence needed)

1. **Jabama session key names:** run the snippet below and send the output.
2. **Jabama `69063962`** is now `non_event: retrospective_without_new_attendance` and
   **`legacy-941`** produced no Event (one unclassified item). Both were Events on 2026-10-23.
   The page text may have changed; need their latest raw JSONL lines.
3. **Media title failures:** 9 candidates excluded for missing titles (Jabama Instagram 6,
   Tehran by Tehran 2, Evenza 1); OCR images needed. Try `ocr check --image` on one slide.
4. **City from a hashtag:** `رویداد سکانس چهارم` gets city `تهران` from `#ایونت_تهران`. It is
   true here but not a stated location; not changed.
5. **Possible duplicate:** two Vadoostan `سفالگری با چرخ` pages at 10:00 and 13:00 on 8 Aban
   are suggested for review. They are distinct sessions; the suggestion is never merged.
6. **Venue not read:** `ایونت ویرا در تیدا سنتر` (address holds `مجتمع تجاری تیدا سنتر`).

## Validation

- Full suite: **1,403 tests, OK, 9 skipped** (optional google-sheets extra). The real
  Tesseract test runs where Tesseract is installed.
- New tests: `test_live_run_temporal.py`, `test_live_run_fields.py`, `test_ocr_fallback.py`,
  plus updated session tests.

## Owner local acceptance (Windows PowerShell)

Close the workbook first.

```powershell
git fetch origin
git switch fix/gatherradar-source-field-hardening
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m gatherradar ocr check
```

Optional EasyOCR fallback (large download; models fetched once):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ocr-easyocr]"
.\.venv\Scripts\python.exe -m gatherradar ocr check --image "data\media\<one slide>.png"
```

Fresh crawl:

```powershell
$env:GATHERRADAR_TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --limit 5 --days 14
```

Jabama session property names (names only, no values):

```powershell
@'
import json, pathlib
for path in sorted(pathlib.Path("data/raw/website").glob("jabama_*.jsonl")):
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        latest[item.get("id")] = item
    for item_id, item in latest.items():
        meta = item.get("raw_metadata") or {}
        if meta.get("source_session_diagnostics"):
            print(item_id, meta.get("source_session_diagnostics"), meta.get("source_session_drift_keys"))
'@ | .\.venv\Scripts\python.exe -
```
