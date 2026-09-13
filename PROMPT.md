You are finishing the already validated Instagram Collector milestone in GatherRadar.

Current branch:
feat/instagram-collector

Do NOT modify runtime code.
Do NOT change tests.
Do NOT commit, push, merge, or create a PR.

Inspect the current README.md and PROJECT_CONTEXT.md and make only the minimum documentation updates required to reflect the real current state:

- Browser-backed Instagram collection has now been successfully validated live.
- Authentication through the persistent Chrome profile works.
- Live collection from @davvvat works.
- Real Persian captions are extracted correctly.
- Published timestamps and image URLs are extracted correctly.
- Old pinned posts no longer displace newer content in the final recent-item selection.
- New / Changed / Existing behavior has been validated through repeated runs.
- The Instagram Collector MVP milestone is complete.
- Event detection and structured extraction is now the next milestone.

In PROJECT_CONTEXT.md:
- update the delivery-sequence status where appropriate;
- resolve/remove the open decision that says browser-profile reliability is still awaiting live validation;
- keep Instaloader documented only as the legacy transport.

Do not change architecture or product scope.

Run:
git diff --check
git status

Then stop and report the exact documentation changes.
Do not commit or push.