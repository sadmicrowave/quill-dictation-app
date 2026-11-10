# Development

For people running or changing the code. For using Quill, see the [README](../README.md).

## Running from source

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python main.py                       # drives the Excel workbook that is open
    python main.py --workbook file.xlsx  # edits a file directly (no Excel needed)

1. Nothing to download: the speech model ships in the repo as a zip (`quill/model/`, about 41 MB) and is unpacked once, on first launch. If it is ever missing, press **Download speech model**.
2. Open a workbook in Excel (before or after Quill; Quill notices).
3. Say **"start listening"**, or press **Start** in the window / menu bar icon.
4. Speak a row, then say **"next row"**. Say **"stop listening"** when done.

To try it without a workbook of your own, build the demo:

    python examples/make_demo_workbook.py "Quill Demo Inventory.xlsx"

then say, for example: *"this item is a black t-shirt in good condition, appraisal thirty five dollars, next row"*. Say something Quill doesn't know ("a large one", "from the nineties") and it lands in the Needs-sorting window, where *Same as 1990s* teaches it.

## Running as a packaged app (no terminal)

Real users double-click an app; nothing is run from a command line. So: a log file replaces the console (`quill/diagnostics.py`: `quill.log` in the per-user log folder, rotating, with every log line and any uncaught error from the main or a background thread; **Settings > General > Open Log Folder** shows it); first launch unpacks the speech model by itself; settings, aliases and the model live in per-user folders (`platformdirs`); and the macOS `Info.plist` carries the microphone and Apple Events (Excel) usage descriptions that the permission prompts need.

## Development workflow

- **Day to day: run from source** (`python main.py`) with the test suite: instant feedback, no rebuild.
- **Build the packaged app now, once, as a smoke test, then at milestones** (`sh tools/build_mac.sh`, `tools\build_win.bat`). Packaging fails in ways source runs never show: missing hidden imports (PyObjC, Vosk's native libraries), data files not found inside the bundle (`sys._MEIPASS`: model zip, sounds, assets, `defaults.json`), per-user folders, and **permissions**. When run from a terminal, macOS attributes the microphone and Excel-automation prompts to Terminal / Python; the packaged app has its own identity and must be tested getting them itself (reset with `tccutil reset Microphone com.quill.app` and `tccutil reset AppleEvents com.quill.app`).
- **First build results (2026-10-30)**: the app bundle is about 196 MB; launching it exposed two defects that source runs hide (spec paths relative to the wrong folder; `xlwings` not installed in the dev environment so the bundle had no Excel bridge), both fixed. Check `~/Library/Logs/Quill/quill.log` after any test launch.
- **Rebuild when something packaging-related changes** (a new dependency, data file, `Info.plist` key, icon, entitlement) and before anyone else tries it. Not after every code edit.
- **Always test the packaged app by double-clicking it**, never from a terminal, because that is what a user does.
- **Before release**: a clean build, then sign with a Developer ID certificate and notarise (macOS) or sign the `.exe` (Windows); otherwise Gatekeeper / SmartScreen warn. Expect an app of roughly 300 MB (Qt, Vosk, the 68 MB unpacked model).
- Optional: on macOS, `py2app -A` ("alias mode") builds a real `.app` that points back at the source files, so code edits take effect without rebuilding while still giving the app its own bundle identity for permissions. Not set up yet.

## Setting up for development

    pip install -r requirements-dev.txt
    python -m pytest          # ~400 tests, headless, a few seconds

Tests need no Excel, microphone or speech model (Qt runs `offscreen`; a fake
xlwings, fake recogniser and file bridge stand in). Two tests skip on the
offscreen platform (system tray, colour scheme).

## Status and limits

Built and unit-tested: introspection, parser, keywords and settings, window, tray, sorting window (clicks and voice), search, workbook watcher.
**Not yet verified**: against real Excel on macOS or Windows (including the AutoFilter calls and bring-to-front), with a real microphone and Vosk model, the tray on a real desktop, and PyInstaller builds. See `$ To Do.md`.
Not built: Linux, free-text "contains" search, date comparisons in search, a file picker for non-Excel users.

## Testing

- `pytest` runs the **quick** suite (about a minute and a half): the ~320 tests that take 0.25 s or more (listed in `tests/slow_tests.txt`) are left out. `pytest --full` (or `QUILL_FULL=1`) runs everything (about 4.5 minutes); do that before a commit or a build, or when something broad changed. A test named on the command line is always run. `python tools/make_slow_list.py` rewrites the list.
- On a real screen: `tools/verify_window_effects.py` (opacity and blur basics) and `tools/verify_control_opacity.py` (every control, window, theme, spacing; about 25 minutes, leave the screen alone), both macOS only.

## Troubleshooting for developers

| Symptom | Try |
|---------|-----|
| "No speech model found" | `quill/model/` was removed. Restore it from git, press **Download speech model**, or set `model_path` to a Vosk model folder |
| Nothing happens when I speak | Is the light green? Say "start listening". Check the OS microphone permission for Quill (macOS: Privacy & Security > Microphone) |
| "Can't find an open spreadsheet" | Open a workbook in desktop Excel; Quill attaches within a few seconds |
| macOS asks to control Excel | Choose OK (Privacy & Security > Automation). If you declined, re-enable it there |
| My drop-downs aren't picked up | Save the workbook (Quill re-reads it by itself within a few seconds); check the validation is a list pointing at a single column |
| "list is full" | Extend the list's range in the workbook (leave spare empty cells) |
| A column word is ignored | It must match the header text; say it just before the value |
| Search says nothing to filter on | Use values that exist in your lists, e.g. `search for fern under 20` |
| Quill hears itself | Turn off *Read questions aloud* in Settings, or use headphones |
