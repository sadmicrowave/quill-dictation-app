# Architecture

How the code is organised. For running and building it, see [Development](development.md).

## Packages and data flow

| Package | Role |
|---------|------|
| `quill/bridge/` | Workbook access: `introspect.py` (finds lists), `grid.py` (cell-level read/write/filter over openpyxl or xlwings), `grid_bridge.py` (shared logic), `xlsx_bridge.py` (file), `xlwings_bridge.py` + `win_bridge.py`/`mac_bridge.py` (live Excel), `filters.py` |
| `quill/parser/` | `tokens`, `numbers` (numbers, money, dates), `vocab` (values, field words, aliases), `phrase_parser`, `commands` (keyword matcher) |
| `quill/sorting_voice.py` | Voice sorting: chained spoken commands applied to the top pending term |
| `quill/bridge/hosts.py` | Which spreadsheet program is in use (Excel live; Numbers / LibreOffice / WPS through the `.xlsx` file): detects running programs and their open files, asks Numbers to reload after a save |
| `quill/licensing.py` | Account / subscription back end (not exposed yet): `[account]` settings, `LicenseService`, token store and transport interfaces, HTTPS-only addresses |
| `quill/session.py` | Pure state machine: gate, row building, terms to sort and their decisions |
| `quill/search.py` | Spoken search → per-column filters |
| `quill/controller.py` | Carries Session events out to the bridge and speaker; back-fills cells, saves synonyms |
| `quill/listener/`, `quill/speaker/` | Vosk microphone loop and model download; text-to-speech |
| `quill/ui/`, `quill/app.py` | PySide6: main window, tray, settings, Needs-sorting window; app wiring and the workbook watcher |
| `quill/config/` | Shipped defaults and user settings (TOML) |
| `examples/` | `make_demo_workbook.py` |

Data flow: microphone → `Listener` (thread) → Qt signal → `Controller.handle_transcript` → `Session.feed` → events → bridge writes / speech / window updates.
The Session never does I/O, so the dictation logic is tested without Excel, audio or Qt. Packaging notes: [`packaging/README.md`](../packaging/README.md).

## Background noise (listener)

`quill/listener/noise.py` keeps the room out of the recogniser: a one-pole **high-pass** filter (about 100 Hz) and a **noise gate** that learns the room's quiet level (the quietest 5% of the last eight seconds), opens only for sound at least 2.5 times that (never below an RMS of 350) and for 0.4 s after, and otherwise hands Vosk *silence* of the same length (so a phrase still ends when the speaker stops). The voice lines on the Start button read the gated audio, so they stay flat for the room. `Listener._clean` also drops words Vosk reports below 0.55 confidence (it is asked for word details) and a phrase of two words or fewer whose average is below 0.75. `Settings > Speech Model > Reduce Background Noise` (`noise_filter`, on by default) turns it off; the Listener itself has it off unless `set_noise_filter(True)` is called, so tests that push fake bytes are unaffected. A room that is noisy after two seconds is reported once through `Relay.notice` into the Log. A lone filler word in a partial phrase no longer restarts the quiet timer.

## Listening only for answers

While voice sorting is on, `QuillApp._focus_listener` gives the Listener `set_grammar(expected_words(vocab, aliases))` (`quill/sorting_voice.py`): the commands, the little words, the column names, every list value and its letters, number words and the user's synonyms. The Listener builds a Vosk grammar from them (plus `[unk]`, which is stripped from results and partials) and makes a new recogniser at once; the Whisper second pass is skipped while a grammar is set. `set_grammar(None)` when sorting ends restores open dictation. `Settings > Speech Model > Focus On Answers While Sorting` (`sorting_grammar`, on by default) turns it off. A recogniser factory that takes no grammar argument still works (it is called without it).

## Update check and an older relay

`quill/updates.py` asks the relay's `GET /latest`. A relay that has not been redeployed since `/latest` was added answers 405 (its old code only knows `POST`), which used to show *"The update service answered with an error (405)"*. On a 404 or 405 from the relay the check now asks GitHub's public releases API directly (`GITHUB_LATEST_URL`; the repository is public) and carries on; GitHub's own 404 means nothing is released yet, which counts as up to date. Redeploying the relay (`cd relay && npx wrangler@4 deploy`, or a push to `main` that touches `relay/`, which runs the workflow) makes the app use it again.
