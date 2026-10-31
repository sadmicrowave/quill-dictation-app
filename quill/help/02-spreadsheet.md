# 📗 Your spreadsheet

Quill works with the spreadsheet app **you already use**. You don't pick one or change any setting.

## 🧩 Supported apps

| App | How Quill works with it | You do |
|---|---|---|
| 📗 **Excel** (Mac, Windows) | Live: rows appear as you speak | Nothing |
| 🔢 **Numbers** | Works on the Excel file (`.xlsx`) open in Numbers, then asks Numbers to reload it | Open an `.xlsx` (for a `.numbers` sheet: **File > Export To > Excel** once) |
| 📘 **LibreOffice Calc** | Works on the open `.xlsx` file | **File > Reload** now and then |
| 📄 **Others, Google Drive copies** | Works on the `.xlsx` file | Reopen the file to see new rows |

> 💡 Quill looks for an open sheet every few seconds. Open one at any time and Quill finds it.

## 📁 Using a file directly

No spreadsheet app open? Quill can fill a file by itself.

1. Press the **📁 folder** button (or **File > Open Spreadsheet File…**).
2. Pick an `.xlsx` file.
3. Dictate. Quill remembers the file next time.

**File > Use Open Excel Workbook** goes back to live Excel.

## 🪟 What the window shows

![Not connected](images/not-connected.png)

- 🟠 **File stream not connected**: no sheet found yet. Hover it for what to do.
- 📄 **Current Row**: what Quill has understood so far. Check it before saying "next row".
- 🕘 **Last Saved**: the row written last. It only appears after the first save.
- 📜 **Log**: click to open a record of what happened.

## 🔘 The title bar

| Icon | Does |
|---|---|
| ❓ | Opens this help, on the page for where you are |
| ↩️ | **Undo** the last answer |
| 🎚️ | **Settings** |
| ↘️ | **Mini view** |

## 🔔 Menu bar icon

A rounded square: **outline** = idle, **solid** = listening. Open it to start, stop, show the window or quit. While listening it names the sheet being written.
