# On-screen journeys

The part of a full test that needs a real screen: the packaged app, a real Numbers, real windows. The headless journeys in
`tests/journeys/` cannot see looks, animation, real Numbers behaviour or permissions; these can. **A full test is both**: `pytest --full`
and this pass (see [Testing](testing.md#what-a-full-test-is)).

They are run by Claude with computer control (or by a person following the same steps), because screen control is not something a
test runner can call. Nothing here can run in CI.

## Before you start

```
sh tools/onscreen_setup.sh
```

builds `dist/Quill.app` if the code is newer, starts Quill in **demo mode** (settings in a throw-away folder: your own words, theme
and layouts are never touched), writes a sample workbook with a third, empty sheet called **Blank**, and opens that workbook once in
Numbers. `sh tools/onscreen_setup.sh status` shows what is open; `stop` quits that Quill.

Check first, and stop if it is not true:

- Numbers has **one** document, `Demo Inventory`. A document left over from an earlier run (the status line lists them) is closed
  by hand with its own window button or Cmd+W first. The script never closes a document, so nothing unsaved is lost.
- The Numbers that opened is the one Quill talks to (Quill's Files panel lists `Demo Inventory.xlsx` under Open Spreadsheets within a
  few seconds; press its refresh icon if not).

Driving the screen: use the Quill window's own controls; the **Demo** menu in the menu bar feeds text through the same path as speech.
Switching Numbers sheets, closing its window and pressing Settings controls need real clicks (full-screen control). Bring one app
forward at a time: a Quill window over a Numbers window takes your click.

## The journeys

| # | Journey | How | Pass when | Needs |
|---|---|---|---|---|
| S1 | Dictate a row | Demo > A Row Being Dictated (or Clip: Dictate) | Columns ease in muted; the heard column un-mutes and slides to the top; the value pill appears as words arrive, not at the end; the grid resets after the row is saved | Demo menu |
| S2 | Term Helper, file stays open once | Demo > Terms To Sort; answer both terms; close the Term Helper; run `sh tools/onscreen_setup.sh status` | **One** `Demo Inventory` document in Numbers; the grid shows the answered values; heard words and grid agree | Demo menu |
| S3 | A sheet with no columns | Numbers: select the Blank tab; bring Quill forward | Within about 15 s Quill shows "This sheet has no column headings...", with the two links; Headings Row opens the File Settings overlay (Headings Row, Starting Row, Sheet Layout) | Real clicks |
| S4 | Close the file | Close the document window in Numbers | "File not connected", gear muted, grid hint back, one log line "'...' was closed" (and "Row discarded" if a row was pending) | Real clicks |
| S5 | Layouts per sheet | On Blank set Headings Row 3; select Inventory; open the gear; select Blank; open the gear | Inventory shows Automatic, Blank shows 3 | Real clicks |
| S6 | Looks | Settings > Appearance: Light, then Dark, then System; opacity and blur at both ends; Mini View | Muted and normal text clearly different; nothing cut off; no control is left opaque or sharp at low opacity | Settings controls |
| S7 | Words To Skip | Settings > Words To Skip: add a word, search for it, select it, remove it | The list behaves like Learned Words; with no words the message says so | Real clicks |
| S8 | First launch of a fresh download | Release build, fresh machine or user | The first-run warnings match the README | A person; not run from here |

S1 and S2 are the spoken steps: demo mode stands in for the microphone, so they check the screen's side of a phrase, not the
recogniser. A real voice test stays a person's job.

Gotchas when driving it:

- The **Demo** menu is in the menu bar only while the Quill window is the front window: click the Quill window first. (After the
  Term Helper has opened, the menu was seen missing; if it is, that is a finding, see the 2026-11-10 report.)
- **A Row Being Dictated** opens the real microphone. Run it in a quiet room: room sound becomes junk words and Term Helper terms.
- The demo workbook must open in Numbers with **no warnings** (View > Show Warnings says "There aren't any warnings for this spreadsheet") and **no blue triangles** in the cells. If "Unsupported formulas were replaced by the last calculated value" shows, or every cell of a drop-down column has a blue triangle, that is a finding: it means a drop-down rule was written with a leading "=" (Excel stores the range without one). It was the case until 2026-11-10.
- Each run leaves a `Demo Inventory N.numbers` in the iCloud Numbers folder (Numbers saves the imported workbook there): list it
  under "left over" and leave it for the person to delete.

Things that went wrong in earlier runs and are worth checking each time:

- A second copy of the file in Numbers (Window menu lists each document; `status` too).
- More than one Numbers installed: the log must show it followed the sheet change; if it does not, check which Numbers holds the document.
- Settings changed by a run: demo mode should leave `~/Library/Application Support/Quill/keywords.toml` untouched (compare its
  modified time before and after).
- Anything left open afterwards that was not open before (Desktop files, extra Numbers documents).

## Report

Write `docs/test-runs/onscreen-YYYY-MM-DD.md` for every run (one file per day; a second run the same day adds a section). One row
per journey: **passed**, **failed** (what you saw, and the screenshot name if one was kept) or **not run** (and why, for example
"needs a microphone"). Never leave a row out and never call a journey passed that was not looked at. Start the file with the build
(`dist/Quill.app` modified time and `git rev-parse --short HEAD`), the macOS and Numbers versions, and what was left over.

```
# On-screen run, YYYY-MM-DD
Build: dist/Quill.app <time>, commit <hash>. macOS <v>, Numbers <v>.

| # | Result | Notes |
|---|---|---|
| S1 | passed | ... |
...
Left over: ...
```

A failed row is a bug: reproduce it as a headless journey or invariant first (see [Testing](testing.md#when-a-bug-is-found)),
then fix it, then repeat the journey here.
