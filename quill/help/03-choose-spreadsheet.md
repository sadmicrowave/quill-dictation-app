# Choose your spreadsheet

Quill works with the spreadsheet app you already use. You don't pick one or change a setting.

## What Quill does in each app

| App | What happens | You do |
|---|---|---|
| **Excel** (Mac, Windows) | Rows appear live as you speak. | Nothing. |
| **Numbers** | Rows appear in the open document as you speak. | Open an `.xlsx` (for a `.numbers` sheet: **File > Export To > Excel** once). The first time, allow Quill to control Numbers. |
| **LibreOffice Calc** | Rows appear live and stay unsaved until you save. | Open an `.xlsx`. Quill adds a small script to LibreOffice the first time. |
| **Anything else**, or a Google Drive copy | Quill writes to the `.xlsx` file. | Reopen the file to see new rows. |

Quill looks for an open sheet every few seconds, so you can open one at any time.

## Good to know

You can have Excel, Numbers and LibreOffice open with different files. Quill writes only to the file you chose as **Active File**, in whichever app has it.

Writing always goes to the sheet that is **open** (the active tab). If that sheet doesn't have the columns you filled, Quill keeps your words, shows a red error in the Log, and waits: open the right sheet and say **"next row"** again.

## A `.csv` file

A `.csv` has no drop-down lists, so Quill makes lists from the entries that repeat in each column. In a brand new file, every word you say for a text column goes to the Term Helper first, which is how its lists begin. Search is not available for `.csv`. Quill adds rows at the end and leaves everything else as it was.

**Next:** [Use a file directly](help:use-a-file-directly)
