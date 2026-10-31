# Quill

A hands-free dictation utility for Excel. Open any workbook, open Quill, say
"start listening", then speak rows in. Quill learns its vocabulary from the
workbook's own drop-down lists and column headers, so it works with any kind
of catalog: clothing, plants, parts, coins.

Speech recognition is offline ([Vosk](https://alphacephei.com/vosk/)); nothing leaves your machine.

> New to Quill? The plain-language guide is `$ Overview.md` in the parent
> folder. This README is the reference for people running or changing the code.

## Contents

- [Quick start](#quick-start) · [Speaking to Quill](#speaking-to-quill) · [Search](#search)
- [Terms Quill doesn't recognise](#terms-quill-doesnt-recognise-the-needs-sorting-window)
- [The window, the tray icon and settings](#the-window-the-tray-icon-and-settings)
- [Working with workbooks](#working-with-workbooks) · [Troubleshooting](#troubleshooting)
- [Development](#development) · [Architecture](#architecture) · [Status and limits](#status-and-limits)

## Quick start

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

## Speaking to Quill

Speech is ignored until the gate is open ("start listening"), so conversation
nearby never reaches your sheet.

| You say | What happens |
|---------|--------------|
| a list value: `fern`, `bright` | Fills the column whose drop-down list holds it. A leading "the" is optional; close spellings are accepted |
| column + value: `size large`, `color navy blue` | Fills that column (also settles values that are in several lists) |
| column + amount: `appraisal thirty five`, `price twelve dollars and fifty cents` | Number |
| amount with money words, no column: `thirty five dollars` | Goes to the sheet's money-like number column; the log says which |
| column + date: `acquired today`, `date october thirty`, `march 3 2025` | Date (`today`, `yesterday`, or `<month> <day> [year]`) |
| column + text: `notes needs repotting` | Text up to the next column word. Columns named note/notes/comment(s)/description/remarks/details are always text |
| `next row` (or `new record`) | Writes the row to the next empty row of the active sheet |
| `cancel` / `delete row` | Discards the row being built |
| `stop listening` | Closes the gate |

Details worth knowing:

- Whole sentences are fine. Filler words (`this`, `next`, `item`, `is`, `an`, `made`, `mainly`, `could`, …) are skipped.
- A header word right after "this/the/a/next…" is treated as an ordinary word, so *"this next item is…"* doesn't mean "set the Item column". A column with a list, or a notes-style column, is never skipped.
- Several values can follow one another. A value found in more than one list goes to the earlier column and the log shows an "Assumed:" line; say the column name first to choose.
- Computed (formula) columns and stray cells beside the table never block a row; the row goes to the first row whose own columns are empty.
- `search for`, `clear search` and the other keywords can be renamed in **Settings**. A keyword can't be a bare yes/no answer word, duplicates are rejected, and Start and Stop must keep at least one phrase each.

### Default keywords

| Say | Action |
|-----|--------|
| start listening | Open the gate |
| stop listening | Close the gate |
| next row · new record | Commit the row |
| delete row · cancel | Discard the row |
| search for … | Filter the sheet (see below) |
| clear search · reset filters | Remove the filter |
| sort terms | Start answering the Needs-sorting list by voice |

If you saved keywords before a default existed, add it in Settings or press *Restore defaults*.

## Search

`search for black blouses under 50` turns on AutoFilter on the active sheet's
header row: `black` → Color, `blouses` → Type (plurals work), `under 50` →
a number column `< 50`. Words not in your lists are reported in the log, never
guessed. `clear search` shows every row again and returns you to the cell you
were on before the first search.

- Different columns are AND; several values in one column are OR (`black or navy skirts`).
- Comparisons: `under / below / less than` (<), `at most / up to / no more than` (≤), `over / above / more than` (>), `at least` (≥), `exactly` (=). Two on one column work (`price over 20 under 50`).
- A number applies to a column you name just before it (`sale price under 20`). Otherwise it uses the first money-like number column (header contains price, cost, amount, total, paid, value, fee, msrp, appraisal, worth or estimate, or numeric data) and says which in the log.
- Matching is exact (case-insensitive) against list values, not "contains"; dates aren't compared.

## Terms Quill doesn't recognise: the Needs-sorting window

Anything that matches no list value, header or keyword is collected while you
build the row. When the row ends (`next row`) or you stop listening, the
**Needs sorting** window opens: small, resizable, scrollable, one line per term.

    You said ‘90s’ — is that an Era?
    [ 90s ] [ Era ▾ ] [Add] [Same as… ▾] [Ignore]

    You said ‘teal’ — which column is that?
    [ teal ] [ Choose column… ▾ ] [Add] [Same as… ▾] [Ignore]

- **Suggested column** appears when Quill can tell: you said the column name (`color teal`), the term looks like the values of exactly one list (a pattern like `1990s`), or only one list column is still empty in this row. Otherwise it asks "which column is that?" and never guesses.
- **Add** puts the term (capitalised) in the chosen column's drop-down list.
- **Same as…** says the term is another name for an existing value ("extra large" means whichever value of that list you pick, say XL in a clothing sheet). Saved in your settings, so it works next time.
- **Ignore** drops it.
- You can correct the words first (a run like "mainly teal" can be trimmed to "teal").
- If the term was heard in a row that's already saved, deciding **fills that row's empty cell** (never overwriting anything). Terms from an unsaved or discarded row aren't back-filled.
- **Add all with a column** / **Ignore all** act on every line.
- When every term has a suggestion Quill also asks aloud ("Gucci isn't in the Brand list. Add it? Say yes or no."): `yes` accepts the suggestions, `no` ignores them. If nobody answers, the terms stay in the window.
- A **Needs sorting (n)** button in the main window reopens the list.

### Sorting by voice

Click the first term (or **🎤 Sort by voice**, or say **"sort terms"**) and just talk. Everything
Quill hears is then read as sort commands applied to the **top** term; it leaves the list, the
next one moves up (the highlighted row), and the stream continues. Chain several in one breath:
*"same as <value>, color, same as <value>"*, where a value is anything from your own lists. The window shows `Heard ‘…’ → what happened` as it goes.

| Say | Does |
|-----|------|
| `yes` · `add` · `ok` | Add the term to its suggested column |
| a column name (`color`) · `add to color` | Add it to that column |
| `same as <value>` | It's another name for an existing value from your lists, whatever your sheet holds: "same as fern", "same as XL", "same as walnut" (the column is found from the value when only one list has it; spelled letters like "x l" work) |
| `same` … then the value in the next phrase | Same, in two steps |
| `<column> same as <value>` | Alias, naming the column ("size same as XL") |
| `undo` · `oops` | Take back the last answer; `undo three` steps back three |
| `ignore` · `no` · `drop` · `forget it` | Forget the term |
| `later` · `skip` · `pass` · `next` | Keep it; move it to the end |
| `add all` · `ignore all` | Every term (add all: only those with a column) |
| `done` · `stop` | Leave voice sorting (the rest stay listed) |

While voice sorting is on, speech goes only to the list (nothing is dictated into the sheet). It ends by itself when the list is empty.
If "yes" is said for a term with no suggested column Quill answers "Which column is ‘teal’? Say a column name." and keeps the term. If a *same as* value isn't found it says so and keeps the term.
"`color same as 1990s`" means *add to Color, then the next term is the same as 1990s* unless 1990s is a Color value.
Turn on **Start voice sorting automatically when terms need sorting** in Settings to skip the click.

Example, speaking: *"this next item is an extra large t-shirt made in the 90s, mainly teal, could sell for thirty five dollars"* → Type = T-Shirt and Appraisal = 35 are written at once; "90s", "teal" and "extra large" are listed. Choosing *Era → Same as 1990s*, *Color → Add*, *Size → Same as XL* fills the row's other three cells.

### Undo

Every answer you give (add, same as, ignore, later; the bulk buttons and "add all" / "ignore all" count as one) goes into a running history of the **last 100 actions**; the oldest quietly drops off, so it never grows without end. Step backwards through it with:

- the **↶ Undo (n)** button in the Needs-sorting window or the main window (press repeatedly to keep going back),
- the spoken keyword **`undo`** while dictating (a default keyword; add it under Settings if your keywords were saved earlier), or `undo` / `oops` / `undo three` while voice sorting. Undo is also understood in the same breath as the answers: *"ignore ignore oops"*.

An undo puts the term back where it was in the list and reverses everything the answer did: the value is removed from the workbook list (unless it was already there), the synonym is forgotten, and the cell that was back-filled is emptied again, but only if it still holds what Quill wrote (if you've changed it since, it is left alone and the log says so). The history is cleared when you connect to a different workbook. Only sorting answers are undoable; a saved row is an ordinary Excel row (use Excel's own undo or edit it).

### Sounds and spoken confirmations

Quill confirms what it did without you looking at the screen. **Settings → Confirm with** picks one of:

- **Short sounds** (default). Choose a **Sound set**: Chime, Marimba, Glass, Digital or Walkie-talkie.
- **Spoken word**. Quill says a word instead. Choose what it says for success: *Okay*, *Done* or *Got it*. Other cues say "Ignored" / "Undone" / "Deleted", "Please sort" and "Problem".
- **Off**.

| Cue | When |
|-----|------|
| **success** (rising) | A row saved with nothing left to sort; a term added or aliased; a search run or cleared |
| **sort** (three rising notes) | Terms need sorting. The Needs-sorting window also comes to the front |
| **dismiss** (falling) | Ignore, undo, delete row |
| **error** (low, buzzy) | Something failed or wasn't understood, including an unclear voice-sort command |

When one breath triggers several (a voice-sort chain answering five terms), only the most important cue plays, so you hear one sound, not a burst. The microphone is muted while a cue plays so Quill never hears itself. A spoken sorting question waits for the sort cue to finish. **Play sample** in Settings previews the unsaved choice. Sounds are generated by `tools/make_sounds.py` into `quill/sounds/<pack>/<cue>.wav`; to add a sound set, add a pack to that script, then to `feedback.PACKS`.

### Look

A custom theme (`quill/ui/theme.py`): Qt's cross-platform Fusion style plus a palette and style sheet built from one colour table, in warm light and dark variants with rounded controls and an accent colour. *Auto* follows the OS and restyles live. Two more choices in **Settings**: an **accent colour** (Terracotta, Ocean, Forest, Violet or Rose, each tuned for light and dark with readable text on it) and **spacing**: *Compact* (the original, packed look) or *Comfortable* (roomier padding, margins and gaps). Both apply as soon as you press OK. Colours and spacing live in the tables `ACCENTS` and `DENSITIES` in `ui/theme.py`; layout margins can't be set from a style sheet, so `apply_spacing()` sets them on each window's layouts (new Needs-sorting rows pick up the current choice). Cost: about 25 ms at startup and under 1 ms per repaint, measured. Third-party packages were considered and not used: `qt-material` (Material Design look), `pyqtdarktheme` (unmaintained), `qdarkstyle` (dark only), `PyQt-Fluent-Widgets` (GPL or paid licence). Screenshots are in the project's `Screenshots/` folder.

### Window frame, log, last-saved line, text size and drop-downs

- **Native window chrome** (`ui/chrome.py`). "Chrome" is the frame around a window: title bar, buttons, border. Quill keeps the OS's own frame (dragging, snapping, accessibility) and tints it to the theme. *macOS*: transparent title bar in the window colour plus the matching light/dark appearance (PyObjC; verified against a real Cocoa window). *Windows 11*: dark title bar in dark mode, title bar and border in the theme colours, rounded corners (DWM calls through `ctypes`; **not yet run on Windows**). Best effort: a missing PyObjC or an older Windows build leaves the normal frame, and under the headless `offscreen` plugin nothing is applied (a fake window id would crash PyObjC). Translucent vibrancy (macOS) and the Mica backdrop (Windows) are not used because Quill's windows are opaque.
- **Collapsible log.** Click **Log ▴** to hide it (the arrow turns to ▾ and points the way it will open). It keeps collecting while hidden, and the choice is remembered.
- **Last saved** is always one line: `Last saved: Row 6 · 12 fields · Type: T-Shirt, Appraisal: 35.0, Notes: ve…`, shortened to the window width. The tooltip lists every field (up to 40, then "…and n more"). The live row above it scrolls on its own.
- **Text size** in Settings (9 to 20 pt, default 12). The "You said ‘teal’ — which column is that?" question is shown 3 pt larger than body text.
- **Drop-downs and number boxes** use custom chevrons drawn in the theme's colours (generated SVGs, light/dark and disabled variants), padding for the arrow, and a list that opens below the box with roomy, rounded items.

### Count badges, icon buttons and see-through windows

- **Menu bar / tray badge.** While terms wait, the icon carries a round badge with the count ("9+" past nine) in the **accent colour**, like the unread count on other menu bar apps. The tray menu also gets a **Needs sorting (n)…** line that opens the list. Both vanish at zero.
- **Needs sorting button.** Filled with the accent colour (like Start/Stop) while terms wait, with the count as an inline **pill** in the sentence: `Needs sorting (3)`. The pill is painted by hand (`ui/widgets.Pill`) because a style-sheet radius was square on macOS.
- **Icons.** Start/Stop show a play or stop glyph; Settings is an icon-only (sliders) button with a tooltip and accessible name. The icons are SVG redrawn in the theme's colours (`ui/icons.py`).
- **Last saved** is a smaller italic supporting note (2 pt under the text size, muted colour).
- **Window opacity** (Settings, 55 to 100 %, default 100) fades the *whole* window (`setWindowOpacity`): text, inputs, buttons, selection boxes and text areas all follow it together.
- **Blur behind windows** (Settings checkbox, on by default). The windows are created translucent (`WA_TranslucentBackground`). With blur on, the window background becomes a light tint (72 % opaque, cards 86 %) over a blur of whatever is behind it. *macOS*: an `NSVisualEffectView` (Sidebar material, always active) is added behind Qt's view and removed again when you turn blur off; checked against a real window's view hierarchy. *Windows 11*: the acrylic backdrop (`DWMWA_SYSTEMBACKDROP_TYPE`) plus `DwmExtendFrameIntoClientArea`; needs 22H2 or later, **never run on Windows**. Turning blur off gives solid windows.
- **Hover and selection** in drop-down lists and menus is a soft accent tint with the normal text colour, never the white-on-light combination (a test checks the contrast for every accent in light and dark).
- **Checkboxes** are rounded boxes that fill with the accent and show a tick (generated SVG, `on_accent` colour). **Headings** ("Current row", "Log") are regular weight in the muted colour.
- **Tray icon clicks** only ever open the menu; they never start or stop listening (a left click pops the menu up on Windows, where it otherwise shows only on right click).
- **Play sample** plays only the selected sound set's chime (or says only the selected word); choosing a sound set or word also plays it once.
- **Collapsing the log** shrinks the window to fit (the empty footer is hidden too) and reopening restores the earlier height.

### Settings window

A sidebar of groups (**General**, **Appearance**, **Sounds**, **Keywords**) with a **search box** at the top, and rows of *name, muted help text, control*, in the style of Claude's own settings. Search filters the rows of every group (it matches names, help text and extra keywords, and a keyword phrase finds the Keywords page) and hides groups with no match. Controls: toggle switches, a three-icon **Theme** selector (Auto / Light / Dark), plain-text drop-downs with a chevron (no box), sliders with a live percentage, and the keyword table on its own page, which takes all the spare height. Built from `ui/settings_widgets.py` (`SettingRow`, `ToggleSwitch`, `SegmentedControl`, `FlatCombo`) and `ui/settings_dialog.py`. The Settings window itself always stays solid, so it can be read even when the main window is made very transparent.

- **Window opacity**: 10 to 100 %. **100 % is completely solid**, whatever the blur. Lower values fade the whole window (background, controls and text together) so what is behind it shows through.
- **Window blur**: 0 to 100 %. Frosts what shows through the window; at 100 % opacity there is nothing to see through, so blur only matters once opacity is lowered (macOS: the `NSVisualEffectView`'s alpha; Windows 11: acrylic on/off, since its strength cannot be set).
- **Current row** can be collapsed like the log (arrow beside the heading; remembered). The window gives back the height of whatever you collapse and takes it again when you reopen it.

- **Live updates.** Every control applies as you change it (theme, accent, spacing, text size, opacity, blur, sounds, undo cap and so on) so you can see the result before deciding; **Cancel** (or closing the window) restores the settings exactly as they were, and **OK** saves. Nothing is written to disk until OK; keyword edits take effect only on OK.
- **Scrolling is safe.** Drop-downs, number boxes and sliders ignore the mouse wheel until clicked into, so scrolling a page cannot change a setting by accident (this once silently changed a saved keyword's action while scrolling the table). All clickable controls show a pointing hand.
- The Settings window follows the opacity setting but never goes below 70 % so it stays readable.

### Sounds

The five sets now differ in instrument *and* melody, not just pitch: **Chime** (bells, rising fifth), **Marimba** (wooden mallet knocks, a roll for sorting, one low knock to dismiss), **Glass** (high long-ringing pings, an octave pair, a falling cascade), **Digital** (8-bit square waves: a fast arpeggio, a siren, a pitch dive, a buzz), **Walkie-talkie** (radio beeps in a puff of static). A test checks that every pair of sets differs for every cue.

### App icon ideas

`tools/make_icon_ideas.py` draws twenty concepts (`--more` for ideas 11 to 20, `--new` for 21 to 40, `--mix` for 41 to 50: the parts that were liked, recombined; `--ring` for 51 to 56: the record ring with vertical sound lines in purples; `--clip` for 57 to 59: idea 47 (the clipboard) on purples; `--sheet` for 60 to 63: the Excel-style tiled sheet in purples with white sound lines on top; `--offset` for 64 to 67: the Excel layout, an offset sheet behind a small front box that holds the sound lines; `--all` for one sheet of the first forty) in the modern macOS manner: a flat colour with only a hint of depth (a faint light-to-dark shift, a hairline top highlight, a faint shade on the bottom edge, a flat white glyph at 72 % of the box with a very soft shadow), like the Mail or Arduino icons in the Dock. An earlier, heavily embossed version was too much. They are written into `assets/icon-ideas/` (a full-colour app icon and a one-colour menu bar glyph for each, as SVG) and an optional contact sheet. They are ideas, not final art.

### Auto-refresh

There is no Refresh button. Every 3 seconds Quill compares the workbook file's modification time with the last one it saw and, if you have saved a change in Excel (a new column, a new drop-down value), re-reads the lists and columns. Quill's own writes (rows, taught values, filters) record the new time straight away so they are never mistaken for outside changes, and a file caught mid-save is simply retried on the next tick. The log says "Workbook changed: lists and columns re-read".

### App icon

The chosen design (idea 66: a violet icon, a pale tiled sheet set to the right, a deep small box on the left holding the white sound lines, centred vertically) is built by `tools/make_app_icon.py` into `quill/assets/`: `icon.svg`, `icon-small.svg`, `icon-16` to `icon-1024.png`, `Quill.icns` (macOS, through `iconutil`) and `Quill.ico` (Windows, seven PNG sizes written directly). At 48 px and below the sound lines are drawn as five bold lines instead of seven thin ones, which would blur into a smudge. `QuillApp` sets it as the application icon (this is the Dock icon on macOS, verified on a real run) and both PyInstaller specs use it and ship `quill/assets`. The menu bar icon is separate: the small box on its own (see above). The packaged macOS app shows in both the Dock and the menu bar (no `LSUIElement`).

### Dock icon

macOS shows Quill in the Dock and the menu bar. **Settings > General > Hide the Dock Icon** (off by default, remembered) turns Quill into a menu bar app, live, without restarting (`NSApp.setActivationPolicy_`: regular or accessory; verified on a real run). With the Dock icon hidden you open Quill from the menu bar icon (**Open Quill**), or by opening the app again: clicking its Dock icon or reopening it from Finder with no window showing brings the window back (`QuillApp._app_state_changed`). Closing the window never quits Quill.

### Running as a packaged app (no terminal)

Real users double-click an app; nothing is run from a command line. So: a log file replaces the console (`quill/diagnostics.py`: `quill.log` in the per-user log folder, rotating, with every log line and any uncaught error from the main or a background thread; **Settings > General > Open Log Folder** shows it); first launch unpacks the speech model by itself; settings, aliases and the model live in per-user folders (`platformdirs`); and the macOS `Info.plist` carries the microphone and Apple Events (Excel) usage descriptions that the permission prompts need.

### Development workflow

- **Day to day: run from source** (`python main.py`) with the test suite: instant feedback, no rebuild.
- **Build the packaged app now, once, as a smoke test, then at milestones** (`sh tools/build_mac.sh`, `tools\build_win.bat`). Packaging fails in ways source runs never show: missing hidden imports (PyObjC, Vosk's native libraries), data files not found inside the bundle (`sys._MEIPASS`: model zip, sounds, assets, `defaults.json`), per-user folders, and **permissions**. When run from a terminal, macOS attributes the microphone and Excel-automation prompts to Terminal / Python; the packaged app has its own identity and must be tested getting them itself (reset with `tccutil reset Microphone com.quill.app` and `tccutil reset AppleEvents com.quill.app`).
- **Rebuild when something packaging-related changes** (a new dependency, data file, `Info.plist` key, icon, entitlement) and before anyone else tries it. Not after every code edit.
- **Always test the packaged app by double-clicking it**, never from a terminal, because that is what a user does.
- **Before release**: a clean build, then sign with a Developer ID certificate and notarise (macOS) or sign the `.exe` (Windows); otherwise Gatekeeper / SmartScreen warn. Expect an app of roughly 300 MB (Qt, Vosk, the 68 MB unpacked model).
- Optional: on macOS, `py2app -A` ("alias mode") builds a real `.app` that points back at the source files, so code edits take effect without rebuilding while still giving the app its own bundle identity for permissions. Not set up yet.

Titles, labels, buttons, menu items, setting names and the like use Title Case throughout: two-word titles have both words capitalised (**Last Saved**, **Current Row**, **Not Listening**, **Needs Sorting**, **Sound Set**), and longer ones capitalise every word except small joining words (**Sort by Voice Automatically**, **Keep the Mini View on Top**). Descriptions, tooltips and log sentences stay sentence case.

### Mini view

Press the resize icon in the title bar (on the right) to shrink Quill to a small overlay: a status row (light, the **Listening / Not Listening** text, the **Needs Sorting** count and an icon-only **Start / Stop**); the resize icon sits in the **title bar** itself, on the right, opposite the red / yellow / green buttons (macOS; elsewhere a bare icon inside the window) and the **row being built** in a small box beneath. The log, the saved-row line, the workbook picker, the sheet name, Undo, the footer and Settings are hidden. The window **animates** (about 0.25 s, eased; `MainWindow.animation_ms`; the size moves first and the contents swap at the end when shrinking or at the start's end when growing, so it visibly shrinks and grows instead of snapping) to 340 px wide and about 120 px tall and **floats above other windows** (Settings has a switch, *Keep the mini view on top*) so it can sit beside or over a spreadsheet. The arrows button turns into the way back and restores the previous size, and which view you left it in is remembered. Collapsed sections keep their state across a round trip. Dictation, the microphone and the tray all work from the mini view. The stay-on-top level is changed in place with the OS (`NSWindow.setLevel_` on macOS, `SetWindowPos` on Windows) because changing Qt's window flag destroys and recreates the native window, which is what made the first version jump; Qt's flag is only a fallback.

### Speech model

The Vosk small US-English model (`vosk-model-small-en-us-0.15`, Apache 2.0) ships **compressed** as `quill/model/vosk-model-small-en-us-0.15.zip` (41 MB; 68 MB unpacked), so a fresh clone works with no download and the repository stays smaller. `ensure_model` (in `quill/listener/model.py`) uses a model you configured or one already unpacked, and otherwise unpacks the zip once into the per-user data folder (`.../Quill/model`). An unpacked copy beside the zip is also used and is git-ignored. Plain git is enough (the zip is under GitHub's 100 MB limit); move it to Git LFS if the repository should stay small.

### Microphone

The microphone is **only open while Quill is listening** (plus while a spoken answer is expected: a yes / no question or voice sorting). At launch the speech model loads in the background but the microphone stays off until you press Start, so the macOS microphone indicator is off whenever Quill is idle. The log says "Microphone on" / "Microphone off". Because a closed microphone cannot hear "start listening", there is a setting, **Keep the microphone open when not listening** (off by default), for people who want to start by voice. Implementation: `Listener.preload()` loads the model without opening a stream; `QuillApp.mic_wanted()` / `_sync_mic()` start and stop the stream after every event.

## The window, the tray icon and settings

- **Main window**: status light, Start/Stop, Settings, workbook picker, current sheet, the row being built, last saved row, a log, and a footer for status messages (such as the model download).
- **Tray / menu bar icon**: the small rounded square of the app icon with its sound lines: an **outline when idle, solid with the lines cut out when listening** (a template image, so the system tints it for light and dark menu bars; with a Needs Sorting count it becomes a coloured image with the count badge). There is no Mini View item in this menu; the mini view is toggled from the window. Menu: Start/Stop Listening, Open Quill, Quit. While listening it begins with `Editing: <workbook>` and the workbook's folder (`~` for home, long paths shortened); click either line to bring the workbook to the front. On Windows a left click toggles listening; on macOS use the menu.
- **Settings**: editable keyword table (add, remove, restore defaults), appearance (auto / light / dark), accent colour, spacing (compact / comfortable), text size, window opacity and blur, "read questions aloud", automatic voice sorting, **Undo remembers** (5 to 500 actions, default 100), and the **feedback** choices below. Stored in the OS config folder as `keywords.toml` (also holds your synonyms and the last-used workbook).

Quill mutes the microphone while it speaks so it can't hear itself.

## Working with workbooks

- **Which lists it finds**: validation lists typed inline (`"A,B,C"`), pointing at a range (`Config!$A$2:$A$20`, quoted sheet names fine), or a defined name; plus any column on a sheet named Config or Settings whose header ends `_list`. Header row: the first Excel table, otherwise the text-richest of the first 10 rows.
- **Live Excel** reads cell values live but reads list *structure* from the saved file: save after adding a validation rule and Quill re-reads it within a few seconds (the file's modification time is checked every 3 seconds; Quill's own writes are not mistaken for outside changes).
- **Lists can grow** only if their range has spare empty slots (or is a `*_list` column). A full fixed range reports an error; an inline `"A,B,C"` list can't be extended in live Excel (it can in file mode) — keep lists on a Config sheet.
- **No workbook open?** Quill says so (window, notification, spoken) and keeps watching every 3 seconds: when a workbook opens it attaches by itself (it doesn't start listening — you still say "start listening"); when it closes Quill lets go and stops listening.
- **Several workbooks**: use the picker; the last one used is re-selected on launch.
- **File mode** (`--workbook`) is for testing and for sheets not open in Excel. It saves after each change, so don't use it on a file that is open and unsaved elsewhere.

## Troubleshooting

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

## Development

    pip install -r requirements-dev.txt
    python -m pytest          # ~400 tests, headless, a few seconds

Tests need no Excel, microphone or speech model (Qt runs `offscreen`; a fake
xlwings, fake recogniser and file bridge stand in). Two tests skip on the
offscreen platform (system tray, colour scheme).

### Architecture

| Package | Role |
|---------|------|
| `quill/bridge/` | Workbook access: `introspect.py` (finds lists), `grid.py` (cell-level read/write/filter over openpyxl or xlwings), `grid_bridge.py` (shared logic), `xlsx_bridge.py` (file), `xlwings_bridge.py` + `win_bridge.py`/`mac_bridge.py` (live Excel), `filters.py` |
| `quill/parser/` | `tokens`, `numbers` (numbers, money, dates), `vocab` (values, field words, aliases), `phrase_parser`, `commands` (keyword matcher) |
| `quill/sorting_voice.py` | Voice sorting: chained spoken commands applied to the top pending term |
| `quill/session.py` | Pure state machine: gate, row building, terms to sort and their decisions |
| `quill/search.py` | Spoken search → per-column filters |
| `quill/controller.py` | Carries Session events out to the bridge and speaker; back-fills cells, saves synonyms |
| `quill/listener/`, `quill/speaker/` | Vosk microphone loop and model download; text-to-speech |
| `quill/ui/`, `quill/app.py` | PySide6: main window, tray, settings, Needs-sorting window; app wiring and the workbook watcher |
| `quill/config/` | Shipped defaults and user settings (TOML) |
| `examples/` | `make_demo_workbook.py` |

Data flow: microphone → `Listener` (thread) → Qt signal → `Controller.handle_transcript` → `Session.feed` → events → bridge writes / speech / window updates.
The Session never does I/O, so the dictation logic is tested without Excel, audio or Qt. Packaging notes: `packaging/README.md`.

## Status and limits

Built and unit-tested: introspection, parser, keywords and settings, window, tray, sorting window (clicks and voice), search, workbook watcher.
**Not yet verified**: against real Excel on macOS or Windows (including the AutoFilter calls and bring-to-front), with a real microphone and Vosk model, the tray on a real desktop, and PyInstaller builds. See `$ To Do.md`.
Not built: Linux, free-text "contains" search, date comparisons in search, a file picker for non-Excel users.
