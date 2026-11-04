# 🎤 Talking to Quill

Speak naturally. Quill picks out the words it knows.

## 🗣️ The basics

| Say | Quill |
|---|---|
| **"Start listening"** | starts taking notes |
| *describe the item* | fills the columns |
| **"Next row"** | saves the row, starts a new one. Ending with just **"next"**, **"next item"** or **"stop"** does the same |
| **"Stop listening"** | stops |

> 💡 Prefer buttons? While listening, the **next** button (a skip-forward icon, the height of the Start button) beside it does what saying **"next row"** does: it saves what was understood, clears the heard words and the grid, and is ready for the next row. Say **"open term helper"** (or **"term helper"**) to open that window by voice. You can also press the wide **Start / Stop** button, or use the menu bar icon. It shows a **Start Listening** (or **Stop Listening**) pill, and its sound lines are grey and still when Quill is not listening, and turn green and move while it is.

## ✍️ Describing an item

> "Black t-shirt, large, good condition, appraisal thirty five dollars. Next row."

- **List words** go to their column by themselves: *"black"* Color
- **Column name first** when it's ambiguous: *"size medium"*
- **Amounts:** *"appraisal thirty five"*, *"twelve dollars fifty"*
- **Dates:** *"acquired today"*, *"date march 3"*
- **Notes:** *"notes needs a new button"*
- Filler like *"this next one is a…"* is ignored

## 👂 What Quill heard

Everything you say shows up, word by word and in italics, in the box under the Start button.

- Words Quill understood become **coloured pills** and appear in the grid below, in their column.
- Words still being spoken are shown in the normal text colour; once the phrase is done, words that were **not understood** turn grey.
- Spoken commands (*next row*, *next item*) are taken out of the box once recognised, so the box shows only what describes the item.
- Everyday words (*got*, *really*) are skipped, so Quill won't ask about them.
- A word that sounds like one of your column names or list values is taken as that word. *"Waste"* becomes *Waist* if your sheet has a Waist column. The Log notes it.
- A word Quill doesn't know goes straight onto the **Term Helper** button as soon as the phrase ends.
- Disagree with a match? Hover its line in the grid: a round **x** appears at the right (it turns red under the pointer). Click it and the line is removed and will not be written.

## 📅 Dates

Say a date any way you like and Quill writes the **real date** into the sheet.

- *"yesterday"*, *"tomorrow"*, *"day before yesterday"*
- *"three weeks ago"*, *"a month ago"*, *"a couple of days ago"*
- *"last friday"*, *"next monday"*, *"friday"*, *"last week"*
- *"march third"*, *"the third of march twenty twenty five"*, *"october thirty"*

Which date column? Quill reads your spreadsheet, not a word list. If a word you said is a form of a word in a date column's heading (*"departed"* near **Departure Date**), that column is used. Otherwise the first empty date column, left to right, is used and the Log says which (the second date you say goes to the second date column). You can always name the column: *"departure date yesterday"*. Words you have taught Quill come first: see **Teaching Quill your words** below.

## 🧑‍🏫 Teaching Quill your words

Only you know that, in your sheet, *"spotted"* means **Observation Date** and *"left"* means **Departure Date**. Quill never ships a word list; it learns yours.

- **Change a line's column.** In the row being built, click a line's column name (dates and amounts) (a small arrow shows when the pointer is over it) and pick another column under **Change this to**. A value already in that column swaps places, so two dates in the wrong order are fixed by one click.
- **Or delete and say it again.** Delete the wrong line (the round **x**) and say the value again *with its column's name*: *"departure date yesterday"*. Quill sees the correction and offers the same question. It only counts when the new column is one you named (not one Quill guessed), the value is the same sort (a date for a date, an amount for an amount), and it comes in the next two phrases of the same row.
- **Amounts too.** A bare amount (*"paid thirty dollars"*) goes to the first money column, or to the column a learned word says; change it the same way.
- **Quill asks once:** *"Remember that 'spotted' means Observation Date?"* with **Yes** and **No** (or say *yes* or *no*). It goes away by itself after a few seconds, and nothing is learned then.
- **After enough corrections** (2 by default) Quill uses the word by itself, and the Log says so: *'spotted' used for Observation Date (learned)*.
- **Teach a word at once:** while listening, say the word, then *means*, then the column's name: *"spotted means observation date"*. It is learned the moment you say it.
- Quill never learns numbers, small everyday words, or words that are already in your sheet (a heading or a list value), and a column you name always wins.
- **See and undo it** in **Settings > Learned Words**, or from the **Learned Words** link under the active file in the Files panel.

A month and day with no year mean this year, or last year if that day is more than a month ahead.

## 🛠️ Fixing mistakes

| Say | Quill |
|---|---|
| **"Cancel"** / **"Delete row"** | drops the row you're still describing |
| **"Undo"** | takes back the last Term Helper answer |
| *(saved rows)* | fix them in your spreadsheet as usual |

## 🔍 Search

| Say | Quill |
|---|---|
| **"Search for black blouses under 50"** | filters the sheet |
| **"Clear search"** | shows every row again |

Understands *under, over, at least, at most, exactly* and *"black **or** navy"*.

## 🧩 Other phrases

| Say | Quill |
|---|---|
| **"Sort terms"** | starts [voice sorting](help:term-helper) |

You can change every phrase in [Settings](help:settings).

> 💡 Two values for one column ("jeans and other stuff" when both fit **Category**)? Both are kept: the second goes under the first in the same cell, one per line (in the grid and in the spreadsheet). Say the column name ("category other") to *replace* the value instead.

> How each turn is written (to a new row, or added to one row) and which way your sheet runs is chosen with the **turn** icon: see [Turns](help:turns).
