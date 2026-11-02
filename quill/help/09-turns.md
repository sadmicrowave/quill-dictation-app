# 🔁 Turns

A **turn** is one round of you speaking and Quill answering: the words you say, Quill's match to your columns, the Term Helper if a word needs sorting, and the writing of those matches. **Next** (the button, or saying "next row") ends the turn and starts the next.

Press the **turn** icon (two speech bubbles) in the title bar. The **side panel** eases in with the turn settings; press the icon again to ease it away. The folder icon opens the same panel on its file page. The panel is titled **Turn Options** here; a link opens **Settings > Keywords**, where each turn setting can be given a spoken phrase.

![The side panel's turn page](images/side-panel-turn.png)

## Each turn: Next Row or Append To

- **Next Row** (the default): every turn is written to a new row.
- **Append To**: every turn adds to the **same row**. A cell that already holds a value keeps it and gets the new one after a comma, so a *Fruit* column can end up as `Apple, Banana, Cherry`. Several values heard in one turn are separated by commas too.
  - Press **Next** in the panel (a skip-forward icon; enabled only in this mode) when you want the next turn to begin a fresh row.
  - Changing the mode, the file or the sheet also starts a fresh row.
  - A cell that holds a formula is left alone.

## Starting Row

Quill starts a record at the **first empty row under the headings** (the first row whose cells are all empty or computed, so a gap in the middle gets filled). **Starting Row** in the panel changes that: type a row number and turns begin there (never above the headings). **Auto** (0) is the default. With **Rows Down** it reads **Starting Column**.

## By voice

Say these while listening (change them in Settings > Keywords); a rising sound means *on*, a lower one with the word "off" means *off*:

| Say | Does |
|---|---|
| **"Append on"** / **"Append mode"** | Append To |
| **"Append off"** / **"Row mode"** | Next Row |
| **"Rows down"** | Rows Down |
| **"Columns across"** | Columns Across |

The panel's choice follows what you say.

The **Log** and the **Last Saved** line say *Row 4 (added to)* for these turns.

Starting Row, Sheet Layout (**By Columns** or **By Rows**) and Headings Row are in the file settings (the gear on the Files page; see [the spreadsheet page](help:spreadsheet)). Every text in the panel follows the layout: with **By Rows** it says *column* where it said *row*, and the Log says *Column C*. **Searching** needs the headings across the top.

**Next** in the panel moves the spreadsheet's cursor to the next row (column). After a turn in **Next Row** mode the cursor moves on to the next row; in **Append To** mode it stays on the row that was written.

## By voice

Say these while listening (change them in Settings > Keywords); a rising sound means *on*, a lower one with the word "off" means *off*:

| Say | Does |
|---|---|
| **"Append on"** / **"Append mode"** | Append To |
| **"Append off"** / **"Row mode"** | Next Row |
| **"Rows down"** | Rows Down |
| **"Columns across"** | Columns Across |

The panel's choice follows what you say.

The **Log** and the **Last Saved** line say *Row 4 (added to)* for these turns.

Starting Row, Sheet Layout and Headings Row are on the **Files** page, near the file's details (see [the spreadsheet page](help:spreadsheet)). With **Rows Down** the headings run down the first column and each turn fills the next column; the Log says *Column C*. **Searching** needs the headings across the top.

## By voice

Say these while listening (change them in Settings > Keywords); a rising sound means *on*, a lower one with the word "off" means *off*:

| Say | Does |
|---|---|
| **"Append on"** / **"Append mode"** | Append To |
| **"Append off"** / **"Row mode"** | Next Row |
| **"Rows down"** | Rows Down |
| **"Columns across"** | Columns Across |

The panel's choice follows what you say.

The **Log** and the **Last Saved** line say *Row 4 (added to)* for these turns.

## Sheet Layout: Columns Across or Rows Down

- **Columns Across** (the default): the headings run across the first row and every record is a row.
- **Rows Down**: your sheet is turned the other way. The headings run down the **first column** and every record is a **column** (B, C, D ...). The drop-down lists are read from the heading in each row, and each turn fills the next empty column; the Log says *Column C*.

You can switch whenever you like; the choice is remembered. **Searching** needs the headings across the top, so it says so while **Rows Down** is on.

## Sizes and sounds

Drag the edge of the side panel to make it wider or narrower (the window keeps its size; the content never gets smaller than it can work at). Drag the dots under the matched-words box, or on the bottom edge of the **Log**, to change their heights. Quill remembers all of them.

Confirmation sounds play only for things you **say**. A click confirms itself on screen and stays silent.
