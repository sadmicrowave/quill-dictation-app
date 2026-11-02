# 📗 Your spreadsheet

Quill works with the spreadsheet app **you already use**. You don't pick one or change any setting.

## 🧩 Supported apps

| App | How Quill works with it | You do |
|---|---|---|
| **Excel** (Mac, Windows) | Live: rows appear as you speak | Nothing |
| **Numbers** | Works on the Excel file (`.xlsx`) open in Numbers, then asks Numbers to reload it | Open an `.xlsx` (for a `.numbers` sheet: **File > Export To > Excel** once) |
| **LibreOffice Calc** | Works on the open `.xlsx` file | **File > Reload** now and then |
| **Others, Google Drive copies** | Works on the `.xlsx` file | Reopen the file to see new rows |

> 💡 Quill looks for an open sheet every few seconds. Open one at any time and Quill finds it.

## 📁 Using a file directly

No spreadsheet app open? Quill can fill a file by itself.

1. Press the **folder** icon in the title bar, left of the turn and Settings icons. The **side panel** eases in on the right (press the folder again to ease it away). The icon is grey and closed while no file is open, and solid and open once one is; hover it to see the file's name and the open sheet.
2. The panel's **Active File** section is one button: it reads **Open File** (with a folder) until a file is active, then shows the file's name. Press it for the standard file window, which opens where the active file is (or use **File > Open Spreadsheet File…**), and pick an `.xlsx` or a `.csv` file. Under it, in quiet text: the sheet, the file's path (one line), what it is open in (Excel, LibreOffice, CSV ...), its size and when it was modified and created.
   Pressing **Start** with no file open opens this window for you.
3. Dictate. Quill remembers the file next time.

A file you pick this way that no program has open yet is **started in its own program** as well (in the background, so Quill stays in front).

![The side panel's file page](images/side-panel-file.png)

### Where the data starts

Also on this page: **Starting Row** (where a turn may begin writing; **Automatic** is the first empty row under the headings), **Sheet Layout** (Columns Across or Rows Down) and **Headings Row** (**Automatic** finds the headings; type a number to choose). With Rows Down these read *Column*.

### When another program holds the file

If Excel has the file you chose, Quill works through Excel itself (no file to fight over). If a program refuses the save (Excel on Windows), Quill keeps your rows, tries again every few seconds, says so in the **Log**, and after a few tries saves them to *name (Quill copy)* beside the file.

### Spreadsheets that are already open

Under a muted line, the **Files** section lists, in a scrolling list, the other spreadsheets open in programs on this computer (Excel, Numbers, LibreOffice Calc ...). Click one and it moves up into the **Active File** section; its name leaves the list. Type in the **Filter files** box to narrow the list. With nothing open it says *No open spreadsheet files have been detected.* The list refreshes by itself while the panel is open. The first time, macOS may ask whether Quill may control Excel: that is only so Quill can see which workbooks are open.

**File > Use the Open Workbook** goes back to the workbook open in your spreadsheet program.

## 📄 Working on a .csv file

A `.csv` file is plain text with no drop-down lists, so Quill learns from the file itself:

- Each column whose entries **repeat** (not numbers, not dates, not long sentences) becomes a list. Its different entries, with duplicates removed, are what Quill matches your words against.
- In a **brand new** file, with only a heading row, every word you say for a text column goes to the **Term Helper** to be sorted. That is how its lists begin.
- **Search is not available** (a `.csv` file cannot be filtered). Saying "search for…" tells you so in the **Log**.
- Rows are added to the end of the file. What was already there is left exactly as it was.

## 📑 Which sheet gets the row

Always the sheet that is **open** (the active tab). Quill never tries another sheet for you. If that sheet doesn't have the columns you filled (a dashboard is in front, say), the row isn't saved: you'll see a red **Error** in the **Log**, which opens by itself. Open the sheet you mean and say **"next row"** again. Your words stay in the grid until the row is saved.

## 🪟 What the window shows

![Not connected](images/not-connected.png)

- **File stream not connected**: shown inside the **Start** button, beside the play icon, while no sheet is found. Hover it for what to do.
- **The box that says "Words you say appear here…"**: the words Quill hears, as you say them. Words it already knows light up as coloured pills.
- **The row grid** under it: each known word, placed in its column as it is heard. Check it before saying "next row", and remove any line that is wrong with its round **x** (shown when you hover it).
- **Last Saved**: the row written last, on the right of the **Log** line. It only appears after the first save.
- **Log**: click to open a record of what happened. Each line starts with its time; a long message wraps back to where the message starts, not under the time.

The window opens at the smallest size it can be (and never gets smaller). The mini view remembers its own size; if you close Quill in the mini view, it opens in the mini view again.

## 🔘 The title bar

| Icon | Where | Does |
|---|---|---|
| Question mark | left, beside the window buttons | Opens this help, on the page for where you are |
| Curved arrow | left, next to the question mark | **Undo** the last answer |
| Sliders | right | **Settings** |
| Arrows | far right | **Mini view** |

## 🔔 Menu bar icon

A rounded square: **outline** = idle, **solid** = listening. Open it to start, stop, show the window or quit. While listening it names the sheet being written.
