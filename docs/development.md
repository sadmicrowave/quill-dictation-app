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

To try it without a workbook of your own, start **demo mode** (a sample workbook, its settings kept in a throw-away folder so your own are never touched, and a **Demo** menu that fills the screens without speaking):

    python main.py --demo

then say, for example: *"this item is a black t-shirt in good condition, appraisal thirty five dollars, next row"*. Say something Quill doesn't know ("a large one", "from the nineties") and it lands in the Needs-sorting window, where *Same as 1990s* teaches it.

## Running as a packaged app (no terminal)

Real users double-click an app; nothing is run from a command line. So: a log file replaces the console (`quill/diagnostics.py`: `quill.log` in the per-user log folder, rotating, with every log line and any uncaught error from the main or a background thread; **Settings > General > Open Log Folder** shows it); first launch unpacks the speech model by itself; settings, aliases and the model live in per-user folders (`platformdirs`); and the macOS `Info.plist` carries the microphone and Apple Events (Excel) usage descriptions that the permission prompts need.

## Development workflow

- **Day to day: run from source** (`python main.py`) with the test suite: instant feedback, no rebuild.
- **Build the packaged app now, once, as a smoke test, then at milestones** (`sh tools/build_mac.sh`, `tools\build_win.bat`). Packaging fails in ways source runs never show: missing hidden imports (PyObjC, Vosk's native libraries), data files not found inside the bundle (`sys._MEIPASS`: model zip, sounds, assets, `defaults.json`), per-user folders, and **permissions**. When run from a terminal, macOS attributes the microphone and Excel-automation prompts to Terminal / Python; the packaged app has its own identity and must be tested getting them itself (reset with `tccutil reset Microphone com.quill.app` and `tccutil reset AppleEvents com.quill.app`).
- **A packaged build is about 440 MB** (Qt, Vosk and the 68 MB unpacked speech model). Packaging has caught defects that source runs hide (spec paths relative to the wrong folder; a dependency missing from the bundle), so launch the build and check `~/Library/Logs/Quill/quill.log` after any test launch.
- **Rebuild when something packaging-related changes** (a new dependency, data file, `Info.plist` key, icon, entitlement) and before anyone else tries it. Not after every code edit.
- **Always test the packaged app by double-clicking it**, never from a terminal, because that is what a user does.
- **Releasing**: bump `__version__` in `quill/__init__.py`, merge `develop` into `main`, and push a tag that equals the version (`git tag v0.1.0 && git push origin v0.1.0`). The **release** workflow builds the Windows zip and the two macOS disk images (Apple chip and Intel) on GitHub's runners, checks the tag against the version, and attaches them, with checksums, to a **draft** release; nothing is public until you publish it. The builds are not signed with a paid certificate (macOS: ad-hoc signed; Windows: unsigned), so people see the first-run warnings described in the [README](../README.md#get-quill) and in [`packaging/README.md`](../packaging/README.md). The minimum macOS (26.0) is set in `packaging/quill_mac.spec`; the Windows build carries a version resource.
- Optional: on macOS, `py2app -A` ("alias mode") builds a real `.app` that points back at the source files, so code edits take effect without rebuilding while still giving the app its own bundle identity for permissions. Not set up yet.

## Setting up for development

    pip install -r requirements-dev.txt
    python -m pytest          # the quick suite, headless
    python -m pytest --full   # every test (about 2,000 of them)

Tests need no Excel, microphone or speech model (Qt runs `offscreen`; a fake
xlwings, fake recogniser and file bridge stand in). A few tests skip where the platform
cannot run them (the system tray and colour scheme offscreen, file permissions on Windows).

## Status and limits

- **Automated**: the whole suite runs in GitHub Actions on macOS 26, macOS 15 and macOS 15 Intel, and Windows Server 2025 and 2022 (quick tests on every push; the full suite on pull requests, on `main` and every week). Windows 11 on Arm is tried as an experiment only.
- **By hand**: what needs a real screen, microphone and spreadsheet program (Excel, Numbers and LibreOffice live links, permissions, the look of the windows, the packaged builds) is checked with the End-to-End Test Checklist, which lives outside this repository with the other planning notes. The Windows build has had the least hands-on testing.
- **Not built**: Linux, a free-text "contains" search, and a file picker for people who do not use a spreadsheet program.
- **Known gaps** are tracked in the planning notes (`$ To Do.md`), not here.

## Testing

How the layers fit together (unit tests, journeys with invariants, random walks, on-screen journeys) is in [Testing](testing.md). Running them:

- `pytest` runs the **quick** suite: the ~320 tests that take 0.25 s or more (listed in `tests/slow_tests.txt`) are left out. `pytest --full` (or `QUILL_FULL=1`) runs everything (a little under 7 minutes); do that before a commit or a build, or when something broad changed. A test named on the command line is always run. `python tools/make_slow_list.py` rewrites the list.
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
