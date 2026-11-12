# Running tests in the Windows VM from the Mac

The Windows test VM (see `windows-vm.md`) runs a small **job runner**. The Mac leaves a job in the shared folder; the runner does it, and writes the answer
and any screenshots next to it. Nobody has to touch the VM.

```
Mac:  python tools/windows-vm/send_job.py looks        ->  ~/Developer/QuillShare/jobs/<id>.json
VM :  jobrunner.py picks it up, runs it                ->  ~/Developer/QuillShare/out/<id>/result.json, log.txt, *.png
```

## One-time setup (in the VM)

1. Run **Run Quill from source.bat** once (it makes `C:\QuillTest\venv`, the Python environment the runner uses).
2. Double-click **Install job runner.bat** (in `QuillShare\src\tools\windows-vm`). It starts the runner now and at every sign-in (a hidden launcher in the
   Startup folder). `python jobrunner.py --uninstall` removes it.

From then on, on the Mac: `python tools/windows-vm/send_job.py ping` answers when the runner is up. The runner writes `out/runner-alive.txt` every few seconds;
`send_job.py` warns when it has not been seen for 30 s.

## The jobs

| Command | What it does in the VM |
|---|---|
| `send_job.py ping` | Answers with the machine and Python version |
| `send_job.py sync` | Copies the code the last `sync-to-share.sh` left (`QuillShare/src`) to `C:\QuillTest\src` and installs the requirements when they changed |
| `send_job.py pytest [--k expr] [--path file] [--full] [--native]` | The test suite on Windows; `--native` uses the real display plugin instead of the headless one. Result: the summary line, `junit.xml`, `log.txt` |
| `send_job.py looks` | How Quill looks on the real screen (below) |
| `send_job.py dictation` | Dictating through the whole app with a stand-in microphone (below) |
| `send_job.py libreoffice` | Quill and a real LibreOffice (below) |

The usual round: edit on the Mac, `tools/windows-vm/sync-to-share.sh`, `send_job.py sync`, then the job you want. A job that runs longer than its limit
(15 minutes; an hour for pytest) is stopped and reported. Jobs run one at a time, oldest first.

## What the journeys check

The scripts are in `tools/vm_journeys/` and write `checks.json` (name, ok, detail) and screenshots to `out/<id>/`. Each also runs on any machine with `--offscreen`
(`python tools/vm_journeys/looks.py --out /tmp/x --offscreen`; checks that need a real screen then say they were skipped), and `tests/test_vm_jobs.py` runs them
that way.

- **looks**: text size default for the system; menu bar text size; the toolbar (above Start, help and undo at the left, no border until hover, six icons in
  the mini view); Start whole in the mini view; **pop-up corners on the real screen** (a menu, the file-settings overlay, a tool tip card: a corner that is
  black against the desktop fails); the Settings window opens without another window appearing and without jumping; screenshots of the main window and mini view
  in both themes, every Settings page and four help pages.
- **dictation**: a row (Start, say, next row, written to the workbook, grid reset, stop), a note across pauses, an ID counted for you, a word Quill does not know
  (it waits in the Term Helper, the window shows), the mini view while listening. The recogniser itself is not tested: a stand-in microphone feeds the phrases.
- **libreoffice** (Windows only; needs `winget install TheDocumentFoundation.LibreOffice`): Quill finds a file LibreOffice has open from the real process's command
  line (the file name has accents, an en dash, spaces and brackets), a row is written while LibreOffice holds the file, and LibreOffice is still running. Not covered:
  reading the open document back to prove the live link wrote the cells.

## What it cannot do

Judge taste (a person looks at the screenshots), hear a real voice, answer an operating-system permission prompt, or test Excel without a licence. A hung VM needs a
revert from you (Fusion: Virtual Machine > Snapshots).

## Finding a flicker

`Trace windows.bat` runs Quill with `QUILL_TRACE_WINDOWS` set: it writes every window shown, hidden or moved, every tool tip request and mouse press, and for each
shown window the Python code that showed it, to `out\windows-trace.txt`. That is how the Settings flicker was found: three tiny windows were the speech models' cost
lines, made visible before they had a parent.
