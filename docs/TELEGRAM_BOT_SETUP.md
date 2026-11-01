# GatherRadar Telegram Bot

`@GatherRadar_Bot` runs on the owner's Windows computer with long polling. No public server,
webhook, tunnel, domain or hosting is needed.

- **Phase 1:** a Persian menu, help, `/whoami`, and a read-only list of the configured sources.
- **Phase 2:**
  - crawl all enabled sources («🔄 کرال همه منابع»);
  - crawl a chosen set of sources («🎯 انتخاب منابع»);
  - receive the Persian Excel workbook («📊 دریافت خروجی»);
  - browse the extracted events as Persian messages;
  - open earlier runs and their outputs («🕘 آخرین اجراها»).

The bot never adds, edits, enables or deletes sources. «📋 مدیریت منابع» and «⚙️ تنظیمات» stay
marked «به‌زودی».

## Architecture

```text
python -m gatherradar telegram run
  └─ telegram_bot/runner.py      settings → single-instance lock → getMe check → long polling
       ├─ settings.py           env vars only; token never printed or logged
       ├─ auth.py               OwnerPolicy: exact numeric owner ID, private chat only
       ├─ handlers.py           global guard (group -1) + per-handler re-check; thin rendering
       ├─ presentation.py       Persian text, inline keyboards, versioned allowlisted callback data
       ├─ services.py           SourceCatalog (read-only) + GatherRadarOperations protocol
       ├─ operations.py         LocalOperations: crawl scope, runs, events, workbook checks
       └─ jobs.py               JobManager: one crawl at a time in a worker thread, persisted status
                                 └─ orchestration.refresh.application_refresh_service → RefreshService
```

- **Same pipeline as the CLI.** A crawl calls the same `RefreshService` wiring as `gatherradar refresh`:
  - the same database (`data/state/gatherradar.sqlite3`), workbook (`data/review/GatherRadar.xlsx`) and exports;
  - defaults of `--limit 5 --days 14`;
  - Instagram media evidence included.

  Bot runs therefore appear in the normal history, keep review decisions, and use the existing XLSX exporter.
- **Read-only browsing.** Events, runs and workbook checks only read:
  - the persisted SQLite review projection;
  - the run index (`تاریخچه اجراها`) of the existing workbook.

  Nothing is rediscovered or renormalized, and a read action never creates a database.
- **Collection runs off the event loop.** Browser capture, OCR, collection, persistence and export run in one non-daemon worker thread; the event loop is never blocked.
- **One job at a time.** A second request is refused and shown the current job's status.
- **Persisted job status.**
  - The job ID equals the GatherRadar run ID.
  - Status is saved atomically to `data/telegram/jobs.json` (last 30 jobs).
  - After a restart, a job that was running is shown as «قطع‌شده» (interrupted), never as finished.
- **Progress hooks.** `RefreshService.run` gained optional `progress` and `should_stop` hooks:
  - progress reports source started/finished, analysis, persistence and export, with no percentages;
  - stopping is checked only before each source and before analysis.
- **Cancellation.**
  - A source in progress (Chrome capture, OCR) and the database/export writes are never interrupted.
  - A cancelled run records manifest status `cancelled` and persists no snapshot. Raw observations already collected stay in the append-only raw store.
  - Stopping the bot (Ctrl+C) asks a running crawl to stop at the next safe boundary and waits for it.

## Security boundary

- **Secrets.**
  - Credentials come only from `GATHERRADAR_TELEGRAM_BOT_TOKEN` and `GATHERRADAR_TELEGRAM_OWNER_ID`.
  - GatherRadar does not read `.env` files. `.env.example` documents the names only, and `.env` is ignored by Git.
  - The token is redacted from every log record.
  - `httpx` and `httpcore` request logging, which contains the token in the URL, is raised to WARNING.
- **Bot identity.** Start-up checks `getMe`; a token for any bot other than `@GatherRadar_Bot` is refused.
- **Owner check.**
  - Every update passes a global guard before any handler. Each handler re-checks the owner, and so does every callback.
  - Callback data is versioned (`gr1:`), limited to 64 bytes and parsed against an allowlist.
  - Source IDs in callbacks are checked against the registry, so forged or stale callbacks return "invalid" and no data.
- **Bootstrap mode.**
  - Until `GATHERRADAR_TELEGRAM_OWNER_ID` is set, the bot answers only `/whoami`, with the sender's numeric ID, in private chats.
  - Every other request gets a short "owner not configured" note.
  - The first `/start` sender never becomes the owner.
- **Strangers and groups.**
  - Other users get "this bot is private" and nothing else: no menus, sources, paths or logs.
  - In groups the bot stays silent, even for the owner.
- **Command menus.** Commands are published per scope: the default menu shows only `/whoami`, and the owner's private chat shows the full list.
- **One instance.**
  - A lock file (`data/telegram/bot.lock`) allows a single local bot process.
  - If another computer is polling the same bot, Telegram reports a `Conflict`; the bot stops and says so.
- **Errors.** The owner sees a short Persian error message; details go only to the local log.

Adding a source in a later phase never implies that an arbitrary website is supported:
- unsupported layouts need an adapter;
- `robots.txt` and access policy always apply (the Davvvat website stays disabled);
- disabling a source is reversible and is preferred over deletion.

## Windows setup (PowerShell, in the repository folder)

1. Install the dependency into the existing virtual environment:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .
   ```

2. Store the token as a user environment variable. You type it into a hidden prompt; it never
   appears on screen, in history, in GitHub or in chat:

   ```powershell
   $secure = Read-Host 'GatherRadar bot token from BotFather' -AsSecureString
   $plain = [System.Net.NetworkCredential]::new('', $secure).Password
   [Environment]::SetEnvironmentVariable('GATHERRADAR_TELEGRAM_BOT_TOKEN', $plain, 'User')
   Remove-Variable plain, secure
   ```

   Close this PowerShell window and open a new one so the variable is loaded.

   > Windows stores user environment variables in your profile, readable by programs you run.
   > Revoke the token in BotFather (`/revoke`) if this computer is ever compromised.

3. Start the bot in bootstrap mode and get your numeric ID:

   ```powershell
   .\.venv\Scripts\python.exe -m gatherradar telegram run
   ```

   In Telegram, open `@GatherRadar_Bot` and send `/whoami`. Note the number it returns.
   Stop the bot with `Ctrl+C`.

4. Set the owner ID (replace the digits with your own) and open a new PowerShell window:

   ```powershell
   [Environment]::SetEnvironmentVariable('GATHERRADAR_TELEGRAM_OWNER_ID', '123456789', 'User')
   ```

5. Start the bot:

   ```powershell
   .\.venv\Scripts\python.exe -m gatherradar telegram run
   ```

6. In `@GatherRadar_Bot`, test `/start`, `/menu` and `/sources`.

7. Stop safely with `Ctrl+C`. The bot finishes the current update, stops polling and releases the lock.

## Manual acceptance checklist

- [ ] Start-up logs `telegram_bot_starting username=@GatherRadar_Bot mode=owner configured`, and no token appears anywhere.
- [ ] `/start` and `/menu` show the Persian main menu:
  - «📚 فهرست منابع» works;
  - only «📋 مدیریت منابع» and «⚙️ تنظیمات» carry «· به‌زودی» and answer «این قابلیت در مرحله بعد فعال می‌شود.»
- [ ] `/sources` lists Instagram and Website sources separately, with active/inactive state. Davvvat Website shows as inactive (robots).
- [ ] Tapping a source shows its ID, type, state and public URL. «↩️» returns to the list and to the menu.
- [ ] Tapping the same button twice causes no error message.
- [ ] From another Telegram account, `/start`, `/sources` and `/whoami` return only «این ربات خصوصی است…».
- [ ] Adding the bot to a group produces no replies.
- [ ] Starting a second bot in another window fails with "already running".
- [ ] Nothing under `data/raw`, `data/state` or `data/review` changes during the session.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `GATHERRADAR_TELEGRAM_BOT_TOKEN is not set` | Repeat step 2, then open a new PowerShell window. |
| `Telegram rejected the bot token` | The token was revoked or mistyped. Get it from BotFather and repeat step 2. |
| `This token belongs to @X, not @GatherRadar_Bot` | Use the GatherRadar bot's token. |
| `Telegram is unreachable (network error)` | No internet, a firewall, or Telegram is blocked on this network. Check access to `api.telegram.org` (a system VPN or proxy may be required). The bot retries three times, then exits. |
| `Another GatherRadar Telegram bot is already running` | Another window is running it. Close that window (`Ctrl+C`). |
| `Another process is already polling this bot` | The same token runs on another computer or service. Stop it; only one poller per token is possible. |
| The bot answers «مالک ربات هنوز تنظیم نشده است» | `GATHERRADAR_TELEGRAM_OWNER_ID` is not visible to this window. Repeat step 4 and open a new window. |

## Phase 2 usage

- **Crawl all enabled sources («🔄 کرال همه منابع»).**
  1. The bot shows a summary: enabled sources, 5 items per source, a 14-day horizon, and the outputs.
  2. Tap «✅ شروع کرال» to start. One status message is edited in place: stage, current source, completed/total, and each source's ✅/⚠️/❌.
  3. «⏹ توقف پس از منبع فعلی» stops at the next safe boundary.
- **Crawl selected sources («🎯 انتخاب منابع»).**
  - Pages of enabled sources only, with ☑️/⬜️ checkboxes. The selection is kept across pages.
  - Options: «همه فعال‌ها», «پاک کردن انتخاب», «✅ تأیید انتخاب».
  - Each channel is separate, e.g. Jabama Events website, Jabama Experiences website and Jabama Instagram.
  - The Davvvat website (disabled by robots) is never offered and is refused if forged.
- **After a crawl.** The summary separates:
  - successful, partial and failed sources;
  - event candidates discovered vs. those excluded for a missing title;
  - unique canonical Events, split into upcoming/current, Schedule Review and expired;
  - Excel success or failure.

  It then offers «📥 دریافت Excel», «📋 نمایش رویدادها», «🗓 بررسی زمان‌بندی» and «↩️ منوی اصلی».
- **«📊 دریافت خروجی».** Opens the latest run whose snapshot is in the workbook, without crawling.
- **Excel delivery.**
  - The workbook file is sent only if it exists, is readable, is under 45 MB, and its run index contains that run's sheet.
  - The caption names the run time, the sources and that run's sheet.
  - A failed or missing export is reported; an older file is never sent instead.
  - The workbook is the existing cumulative GatherRadar workbook, so it also contains earlier runs' sheets (append-only history).
- **Event browsing.**
  - Five events per page, grouped by date, showing:
    - title;
    - Jalali date and the time when stored, or the next session;
    - venue, area and city;
    - the first line of the source's own description.
  - «مشاهده جزئیات» opens one event by editing the same message. It also shows the source's schedule wording, address, price and capacity wording, the review note and up to 900 characters of description, plus «🔗 مشاهده منبع».
  - «بستن جزئیات» returns to the page.
  - Schedule Review items are a separate list with their source wording.
  - Missing facts are omitted, never invented. Expired Events are not listed as upcoming.
- **«🕘 آخرین اجراها».** Lists recent runs labelled as:
  - live crawl (کرال زنده);
  - stored replay (بازپخش);
  - incomplete (ناتمام, i.e. interrupted, cancelled or failed before persistence).

  Open a run to get its Excel or event lists.

Callback data holds only short tokens: a 12-character run-ID prefix, a page, an index, or a one-time confirmation nonce. Everything else is looked up on the server:
- confirmations expire after ten minutes and work once;
- replayed or forged callbacks are refused.

## Phase 2 local acceptance (Windows PowerShell, repository folder)

1. Update the branch (your data and `config/sources.yaml` are untouched):

   ```powershell
   git fetch origin feat/telegram-bot-mvp
   git checkout feat/telegram-bot-mvp
   git pull origin feat/telegram-bot-mvp
   ```

2. Install (no new dependency since Phase 1; this refreshes the editable install):

   ```powershell
   .\.venv\Scripts\python.exe -m pip install -e .
   ```

3. Start the bot:

   ```powershell
   .\.venv\Scripts\python.exe -m gatherradar telegram run
   ```

4. Run a single-source test.
   1. In `@GatherRadar_Bot`: `/menu` → «🎯 انتخاب منابع». Tick one small website source, e.g. «Vadoostan Website».
   2. Tap «✅ تأیید انتخاب» → «✅ شروع کرال». Watch the single status message update until the summary appears.
5. Tap «📥 دریافت Excel». Open the document, then the sheet named in the caption.
6. Tap «📋 نمایش رویدادها». Page through, open «مشاهده جزئیات», «🔗 مشاهده منبع» and «بستن جزئیات».
7. Only after steps 4–6 pass: `/menu` → «🔄 کرال همه منابع» → «✅ شروع کرال». Chrome opens for Instagram as in a normal refresh.
8. Stop the bot with `Ctrl+C`. If a crawl is running, it finishes the current source first.

## Phase 2 acceptance checklist

- [ ] Confirmation appears before every crawl; menu navigation alone never starts one.
- [ ] Tapping «✅ شروع کرال» twice, or tapping an old confirmation, starts nothing more.
- [ ] While a crawl runs, a second crawl request shows «یک اجرا در جریان است…».
- [ ] Progress shows the current source and completed counts (no percentages).
- [ ] The summary distinguishes candidates, canonical, upcoming, review, expired and missing-title.
- [ ] The Excel document belongs to that run (caption sheet name and time), and the file opens.
- [ ] The event list pages, details expand and collapse, and source links open.
- [ ] «🕘 آخرین اجراها» shows this run and earlier CLI runs, and an old run's Excel can be requested.
- [ ] «⏹ توقف پس از منبع فعلی» ends as «لغو شد» after the current source.
- [ ] Another Telegram account still gets only «این ربات خصوصی است…».

## Known limitations

- **Cancellation is coarse.** It takes effect between sources. One Instagram source with media can take several minutes, and CLI runs cannot be cancelled from the bot.
- **The workbook is cumulative.** Telegram receives the whole workbook, and the caption names the sheet for the run.
- **CLI and bot runs block each other.** A crawl started from the command line holds the database lock, so a bot crawl at the same time fails with a clear message (and vice versa).
- **Job status is persisted, but the job itself is not resumed.** After an unexpected exit, an interrupted crawl must be started again.
- **The selection is in memory.** It resets when the bot restarts. Only the owner can use the bot, so selection state is single-user by design.

## Future phases

**Phase 3** adds source management:
- validate a URL (robots and adapter support) before registering it;
- disable or enable a source reversibly, with a registry backup and an audit line;
- never delete sources and never re-enable sources disabled by policy.

Adding a source never implies arbitrary website support: unsupported layouts need an adapter, and `robots.txt` and access policy always apply.
