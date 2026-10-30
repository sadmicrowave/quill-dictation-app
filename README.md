# Quill

A hands-free dictation utility for Excel. Open any workbook, open Quill, say
"start listening", then speak rows in. Quill learns its vocabulary from the
workbook's own drop-down lists, so it works with any domain.

Speech recognition is offline (Vosk); nothing leaves your machine.

## How speaking works

| You say | What happens |
|---------|--------------|
| `start listening` / `stop listening` | Opens / closes the gate. Nothing is written while closed. |
| a list value (`fern`, `bright`) | Fills the column whose drop-down list contains it |
| a column name + value (`pot size large`, `price twelve fifty`, `acquired today`, `notes needs water`) | Fills that column: list value, amount, date, or free text |
| `next row` (or `new record`) | Writes the row to the next empty row of the active sheet |
| `cancel` / `delete row` | Discards the row being built |
| a value that isn't on a list | At the end of the row Quill asks "…isn't in the Color list. Add it?" Say `yes` to add it to the workbook |

Keywords are editable in **Settings**. Dates understand `today`, `yesterday`
and `october 30 [2026]`; amounts understand `twelve dollars and fifty cents`.

## Running

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python main.py                       # drives the Excel workbook that is open
    python main.py --workbook file.xlsx  # edits a file directly (no Excel needed)

On first run, press **Download speech model** (about 40 MB).

Drop-down lists are read from the workbook *file*, so save after adding a
validation rule and press **Refresh**. Values and rows are written live.
A list typed straight into a validation rule (`"A,B,C"`) can't be extended in
live Excel; put it on a Config sheet range instead.

## Development

    pip install -r requirements-dev.txt
    python -m pytest

Tests run headless (Qt offscreen) and need no Excel, microphone or model.

| Package | Role |
|---------|------|
| `quill/bridge/` | Workbook access: introspection, live Excel (xlwings), file (openpyxl) |
| `quill/parser/` | Tokens, numbers/dates, vocabulary, phrase parser, keyword matcher |
| `quill/session.py` | Pure state machine: gate, row building, new-value question |
| `quill/controller.py` | Carries Session events out to the bridge and speaker |
| `quill/listener/`, `quill/speaker/` | Vosk microphone input, text-to-speech |
| `quill/ui/`, `quill/app.py` | PySide6 window, tray icon, settings, wiring |
| `quill/config/` | Shipped defaults and user settings (TOML) |

Packaging: see `packaging/README.md`.
