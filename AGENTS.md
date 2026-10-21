# Repository conventions

- This repository publishes one reusable skill in skills/impress-story/. README.md explains scope, setup, capabilities and limitations in Chinese.
- Keep the skill self-contained: generic scripts, references, local fonts and licenses, pinned impress.js and its license. Do not include user presentation sources, portraits, customer materials, credentials, local absolute paths or deployment accounts.
- tests use temporary fixtures and must not deploy, push or overwrite an installed skill. Run python3 skills/impress-story/scripts/test_fast_iteration.py after tool changes.
- Preserve font and runtime licenses. Root LICENSE covers original repository contributions only.
- Do not edit generated decks here. No build caches, screenshots of private content, archives, node_modules or installer output in Git.
- Only push when the user requests it. Do not force push, create tags or releases without authorization.
- docs/ holds user-authorized public demo cover images for README, compressed as WebP; no original screenshot intermediates.
