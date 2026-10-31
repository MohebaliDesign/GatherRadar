# GatherRadar Telegram Bot — Phase 1

`@GatherRadar_Bot` runs on the owner's Windows computer with long polling. No public server,
webhook, tunnel, domain or hosting is needed. Phase 1 provides the bot foundation:

- a Persian menu;
- help;
- `/whoami`;
- a read-only list of the configured sources.

It never crawls, exports or changes the source registry.

## Architecture

```text
python -m gatherradar telegram run
  └─ telegram_bot/runner.py      settings → single-instance lock → getMe check → long polling
       ├─ settings.py           env vars only; token never printed or logged
       ├─ auth.py               OwnerPolicy: exact numeric owner ID, private chat only
       ├─ handlers.py           global guard (group -1) + per-handler re-check
       ├─ presentation.py       Persian text, inline keyboards, versioned callback data
       └─ services.py           application boundary
            ├─ SourceCatalog    read-only view over config.load_sources (Phase 1)
            └─ GatherRadarOperations   Phase 2+ protocol
```

- **Handlers stay thin.** They never import collectors, OCR, the repository or exporters.
- **`GatherRadarOperations` is the only route for future work.** Its implementations must reuse:
  - `RefreshService`;
  - the existing source validation and robots policy;
  - the SQLite repository;
  - the existing XLSX, CSV and JSON exporters.
- **Nothing is duplicated.** There is no second database, event model, OCR pipeline or export path.

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
  - the six future items carry «· به‌زودی» and answer «این قابلیت در مرحله بعد فعال می‌شود.»
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

## Future phases

**Phase 2** delivers crawl, export and run history through the bot, each owner-only:

- **Job runner:** a `GatherRadarOperations` implementation with one job at a time, in a worker thread.
  - It calls the existing `RefreshService` with `all_enabled` or selected source IDs.
  - It uses the same `--limit 5 --days 14` defaults and an isolated or the default database, as the owner chooses.
- **Crawl actions:**
  - «🔄 کرال همه منابع»;
  - «🎯 انتخاب منابع» (a multi-select keyboard over enabled sources);
  - a confirmation step, progress messages and a cancel button that sets a cooperative stop flag checked between sources.
- **Exports:** «📊 دریافت خروجی» sends the workbook already written by the existing XLSX exporter, as a document. It is not regenerated, and an export failure is reported with the offline recovery command.
- **Event list:** a Persian text list of current Events from the existing review JSON projection (title, Jalali date and time, venue, source link), paginated under Telegram's 4,096-character limit.
- **Run history:** «🕘 آخرین اجراها» reads run summaries from the repository and manifests (status, counts, failures).

**Phase 3** adds source management:

- validate a URL (robots and adapter support) before registering it;
- disable or enable a source reversibly, with a registry backup and an audit line;
- never delete sources and never re-enable sources disabled by policy.
