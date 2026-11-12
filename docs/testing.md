# Testing

How Quill is tested, and how a bug found by hand becomes a test that keeps it from coming back. For running the tests see
[Development](development.md#setting-up-for-development).

## The layers

| Layer | Where | What it proves | When it runs |
|---|---|---|---|
| Unit tests | `tests/test_*.py` | One piece does what it says (the parser, the session, a widget) | Every run |
| **Journeys** | `tests/journeys/test_journeys.py` | Whole sessions a person has, through the real application, window and workbook file | `pytest --full` (and so the weekly CI run, pull requests and `main`) |
| **Random walks** | `tests/journeys/test_random_walks.py` | Hundreds of arbitrary sessions never reach a contradictory state | `pytest --full` |
| **Windows tests** | `tests/windows/` | The Windows provider: what `tasklist` and PowerShell say, Windows paths and names, files Excel holds, CSVs in cp1252. Most use a pretend runner and run anywhere; the `test_windows_system.py` ones, and the end of `test_windows_files.py`, ask a real Windows and run on the GitHub `windows-2025` runner | Every run (the real ones only on Windows) |
| On-screen journeys | below | What only a real screen shows (looks, animation, real Numbers, permissions) | By hand or with computer control, on the packaged app |

Unit tests are good at "this function is right". They cannot see a bug that only exists across a whole session, such as the
Numbers file being opened again every time the Term Helper saved. Journeys exist for those.

## Journeys and invariants

`tests/journeys/harness.py` builds a whole Quill (the real application object, windows, controller, bridge and workbook file) in
a stand-in world: a fake microphone, and `tests/fake_numbers.py`, a stand-in for Numbers that behaves like it (opening a file
always opens another document, an imported `.xlsx` reports no file, documents can have unsaved changes). A journey is a story told
with plain steps (`start()`, `say(...)`, `go_quiet()`, `answer(...)`, `close_file()`, `switch_sheet(...)`).

**After every step the harness checks every invariant** (the methods named `inv_*`): things that must be true at every moment,
whatever happened before. A few of them:

- the file is open at most once in the spreadsheet program;
- the grid agrees with the row being built, lists every column of the sheet exactly once, and mutes exactly the columns not heard;
- the File Settings gear works exactly while a file is connected;
- the Term Helper button counts exactly the terms waiting;
- a file that is not connected has no row, and a pending row is always visible in the grid;
- no warning is logged twice running, and nothing in the log is a crash.

A failure names the invariant, the step and the steps before it, so it reads like a bug report.

The random walks do the same with arbitrary sequences (start, say, go quiet, answer a term, close the file, switch sheets, change
the headings row, ...) from fixed seeds, so a failure is reproducible: run `QUILL_FULL=1 pytest tests/journeys -k test_seed_17`.
They have already found bugs nobody wrote a journey for (a row dictated for one file written into the next, the Term Helper button
counting terms a deleted row had taken with it, stale lines in the grid after the sheet changed).

## Windows long paths

A new Windows PC refuses a file whose whole path is 260 characters or more ("path not found", for a file that is there) until its **long paths** setting is on
(`LongPathsEnabled`, a registry value or a group policy). Quill's packaged program is built to use long paths when the setting is on (PyInstaller's manifest says
`longPathAware`; `tests/windows/test_windows_long_paths.py` guards it), the self-check reports whether a long path works on that PC, and when a file cannot be reached
the message gives the path's length and what to do. The GitHub runners have the setting on, the test VM does not: the long-path test runs only where Windows allows it.

## Mac and Windows

A test that fakes one system's output (`ps`, `lsof`, AppleScript, POSIX paths) says so and is skipped on the other. **Every such skip has
a counterpart**: Mac fakes in `tests/test_hosts.py` and `tests/macos/`, Windows ones in `tests/windows/`. A skip with no counterpart
is a gap, not a decision. When a Windows behaviour can only be seen on Windows (file sharing, a real PowerShell, the profile folder),
the test is written for it and skipped elsewhere with `skipUnless(sys.platform == "win32")`. Windows on Arm is not tested: Vosk
publishes no Arm64 wheel, so the Arm runner cannot install Quill; the x64 build is what Arm PCs run.

## Trying a build on a real Windows PC

No merge, tag or release is needed to try what is on `develop`:

1. Every push to `develop` runs the **dev build** workflow (`.github/workflows/dev-build.yml`): it builds the app folder and
   `Quill-Setup.exe` on a Windows runner, installs the installer silently, runs the *installed* `Quill.exe --selftest` (a broken
   installer or program fails the build), uninstalls it and checks nothing is left. It attaches `Quill-Setup.exe` and
   `Quill-windows-dev.zip` (the portable folder) to the run. Open the run in the Actions tab, then Artifacts, and download it (GitHub
   sign-in needed; kept 14 days). It can also be started by hand, for any branch.
2. On the PC, run `Quill-Setup.exe` (or unzip the portable copy), then `Quill.exe --selftest` (a Command Prompt or PowerShell in its folder). It writes **Quill self-check.txt** on the
   Desktop and opens it: versions, microphone, the speech model, the folders, which spreadsheet programs are running and how fast
   they answer, a row written into a workbook with accents in its name, a CSV in Excel's ANSI encoding, a file held the way Excel holds
   one, and the Windows look. Nothing is changed or recorded, and the report holds no file names, words or sheet names.
3. To send it, run **`Send Quill self-check.bat`** from the portable zip's folder (or `Quill.exe --selftest --send`). It runs the check and sends the
   report through the support relay, which opens an issue in the private `quill-support` repository (titled "[problem] Self-check: ...", no
   token is in the exe). A message box says "sent as issue #N". Find them with `gh issue list --repo sadmicrowave/quill-support --search "Self-check"`,
   then close them. Each line says ok, warn, FAIL or skip.

The same check runs in every release build against the packaged exe, and `tests/test_selfcheck.py` runs it on every system.

## When a bug is found

1. Reproduce it as a **journey** (the steps the person took) or add the **invariant** it breaks. If the bug is a state that must
   never occur, an invariant protects every route to it, not only the one found.
2. Check that it **fails on the old code** (temporarily put the bug back).
3. Fix it, run `pytest --full`.
4. If the outside world was involved (a program, a file, a window), model it in a stand-in with state, not a canned reply, and
   assert what is left behind afterwards.

## What a full test is

**A full test is two parts, and a release is not tested until both have run:**

1. `pytest --full`: the unit tests, the headless journeys and the random walks.
2. The **on-screen journeys**: [docs/onscreen-journeys.md](onscreen-journeys.md). They need a real screen, the packaged app and a
   real Numbers, so Claude runs them with computer control (the first run of a session asks you for access to Quill and
   Numbers, and for full-screen control for the clicks). `sh tools/onscreen_setup.sh` prepares the machine; the result is written to
   `docs/test-runs/onscreen-YYYY-MM-DD.md`, one row per journey: passed, failed, or not run with the reason.

`pytest` cannot start part 2: screen control is a tool of the Claude session, not something a test runner or CI can call. So part 2
runs when a person asks Claude for a "full test" (the project skill `full-test` does both parts in order), and never in CI.
What the on-screen pass cannot do (speak into a microphone, download a fresh release) is listed in the report as *not run*,
never as passed.

## On-screen journeys

Nine journeys, S1 to S9, with how each is driven and what counts as a pass, are in [onscreen-journeys.md](onscreen-journeys.md).
