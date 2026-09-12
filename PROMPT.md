You are working on the existing GatherRadar repository on branch:

feat/instagram-collector

Do not modify main.

The Instagram collector is already implemented, but anonymous Instagram access returns HTTP 429.

Your task is ONLY to add authenticated Instaloader session support.

Current CLI supports:

python -m gatherradar collect instagram <source_id>

It does NOT currently support authentication.

Implement a new command:

python -m gatherradar auth instagram

Requirements:

1. Add an `auth instagram` CLI command.

2. The command must securely create and verify a reusable Instaloader session for the project owner's Instagram account.

3. Do NOT store the Instagram password in source code, config files, Git, or logs.

4. Do NOT ask the user to paste credentials into committed files.

5. Prefer Instaloader's official session APIs:
   - update_cookies / session handling where appropriate
   - test_login()
   - save_session_to_file()
   - load_session_from_file()

6. Store the session locally under:

data/sessions/

For example:

data/sessions/instagram-<username>.session

7. The data directory and session files must remain Git-ignored.

8. Update the Instagram collector so that:
   - if a valid local session exists, it loads and uses it;
   - otherwise it behaves clearly and reports that authenticated access is not configured;
   - it must not silently fall back to repeated anonymous requests after an authenticated session was requested.

9. Keep all authentication/session handling isolated from domain models.

10. Do not implement proxies, CAPTCHA bypasses, stealth techniques, or private-profile crawling.

11. Add offline tests for:
   - auth CLI parsing
   - session path generation
   - session loading
   - missing session behavior
   - invalid session behavior
   - collector using an injected authenticated Instaloader context

12. Do not contact Instagram from automated tests.

13. Run the full test suite after implementation.

14. Do NOT implement Event Detection, Google Sheets, SQLite, website crawling, Telegram, or any unrelated feature.

15. Do not commit, push, or merge anything.

At the end, report:

- files changed
- exact auth command to run
- exact collection command to run afterward
- test count and result
- git status

Stop after implementation. Do not attempt repeated live Instagram requests.