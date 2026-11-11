# Using Quill

What to say, how to search, how Quill handles words it doesn't know, and how it finds the lists in your workbook. The in-app guide (**F1**) covers the same ground with pictures.

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
| column + text: `source garden center` | Text up to the next column word |
| a note: `notes needs repotting`, `description a tall fern…` | Columns named note/notes/comment(s)/description/remarks/details take **everything you say** (see *Long notes* below) |
| `end note` · `end notes` | Closes the note being dictated |
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
| end note · end notes | Close the note being dictated |
| next row · new record | Commit the row |
| delete row · cancel | Discard the row |
| search for … | Filter the sheet (see below) |
| clear search · reset filters | Remove the filter |
| sort terms | Start answering the Needs-sorting list by voice |

If you saved keywords before a default existed, add it in Settings or press *Restore defaults*.

## Long notes

A column named note, notes, comment(s), description, remarks or details (with no drop-down list) is dictated as a **note**:

- Everything after the column name is the note, **across pauses**: the recogniser ends a phrase at every pause, and the next phrase goes on with the same cell, one space between the pieces. Column names, list values, numbers and dates inside it are ordinary words (*"notes the price went up last spring"* is a note, nothing goes to Price or to the Needs-sorting window).
- It ends on **`end note`** (the words after it are read as usual: *"notes needs repotting, end note, color navy"*), on **`next row`** (or any other command, or *stop listening*), or when a phrase **begins with another column's name** (*"notes needs repotting"* … pause … *"color navy"*). Saying the note's own column name again goes on with it.
- Where the note goes last in the row, `next row` is all it needs.
- The saved note gets a capital letter and a full stop (the recogniser gives neither). A note that already ends in `.`, `!` or `?` keeps it.
- Trade-off: a continuation that happens to **begin with a column name** (*"size was hard to tell"*) is read as that column; and the words *end note* inside a note end it.
- Keywords saved before `end note` existed get it added once (**Settings > Keywords** shows it, and Restore defaults brings it back).

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

## Working with workbooks

- **Which lists it finds**: validation lists typed inline (`"A,B,C"`), pointing at a range (`Config!$A$2:$A$20`, quoted sheet names fine), or a defined name; plus any column on a sheet named Config or Settings whose header ends `_list`. Header row: the first Excel table, otherwise the text-richest of the first 10 rows.
- **Live Excel** reads cell values live but reads list *structure* from the saved file: save after adding a validation rule and Quill re-reads it within a few seconds (the file's modification time is checked every 3 seconds; Quill's own writes are not mistaken for outside changes).
- **Lists can grow** only if their range has spare empty slots (or is a `*_list` column). A full fixed range reports an error; an inline `"A,B,C"` list can't be extended in live Excel (it can in file mode) — keep lists on a Config sheet.
- **No workbook open?** Quill says so (window, notification, spoken) and keeps watching every 3 seconds: when a workbook opens it attaches by itself (it doesn't start listening — you still say "start listening"); when it closes Quill lets go and stops listening.
- **Several workbooks**: use the picker; the last one used is re-selected on launch.
- **File mode** (`--workbook`) is for testing and for sheets not open in Excel. It saves after each change, so don't use it on a file that is open and unsaved elsewhere.
