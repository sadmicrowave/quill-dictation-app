---
name: full-test
description: Run Quill's full test: pytest --full, then the on-screen journeys with computer control, then write the report. Use when the user asks for a full test, a release check, or "run all the tests".
---

A full test for Quill is **two parts**; do both, in this order, and say which part a result comes from.

1. **Headless.** From the repository root with the venv: `.venv/bin/python -m pytest --full -q --tb=short` (about 8 minutes; run it in
   the background and read the end of its output). Fix nothing silently: a failure is reported with its test name.
2. **On screen.** Follow `docs/onscreen-journeys.md` exactly:
   - `sh tools/onscreen_setup.sh` (builds if the code is newer; add the venv to PATH first, the build script needs `python`).
   - Request access to Quill and Numbers (`com.quill.app`, `com.apple.Numbers`), then full-screen control for the clicks; say which
     step needs it. Do not quit apps or close documents with scripts: close Numbers windows with the window or Cmd+W.
   - Run S1 to S8 as that document says. S1 and S2 use the Demo menu (the app_menu tool).
   - Write `docs/test-runs/onscreen-YYYY-MM-DD.md` (passed / failed / not run with the reason, plus anything left open).
   - Release full-screen control when done.

Report both parts to the user, with what was not run and why. A journey that was not looked at is "not run", never "passed".
Do not commit the report unless asked. Do not merge, tag or push because a test passed.
