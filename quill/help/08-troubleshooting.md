# 🛟 Troubleshooting

## 🚦 Quick checks

1. Is the button the darker purple, with a green edge on its screen and moving lines in it? (A flat line and the words *Start Listening* mean Quill is not listening.)
2. Is a spreadsheet open? (the button does not say *File not connected*)
3. Is Quill allowed to use the **microphone**?
4. Is your volume up?

## 🔧 Problems and fixes

| Problem | Try |
|---|---|
| Quill mishears many words | Choose **Settings > Speech Model > Careful** (installed once, about 145 MB), or Broad (about 130 MB). Also speak close to the microphone and pause between phrases |
| *Could not save the row…* in red in the **Log** (it opens by itself) | The row is **kept** (nothing is lost). Quill only writes to the open sheet, and it doesn't have your columns. Open the sheet you are filling in, then say **"next row"** again |
| Listening stopped by itself | Nothing was said for 10 seconds. Say **"start listening"** again, or change **Stop Listening When Quiet** in **Settings > General** |
| Nothing happens when I talk | Say **"start listening"**; check microphone permission in your computer's privacy settings |
| *… was closed* (an amber note under **Open File** in the Files panel) | You closed the spreadsheet window, so Quill stopped listening (nothing is lost) and the Start button shakes. Choose **Reopen** to open it again, or pick another file |
| A red dot on the folder icon, then one beside **Sheet** in the Files panel (hover it) | You opened a sheet that the saved file does not have (a new or renamed sheet). Quill will not listen (Start shakes) so nothing lands in the old sheet. **In LibreOffice Quill works in the open document, so a new sheet needs no save**; you only see this dot if the link to LibreOffice is down and the file does not have the sheet (save it there yourself). In other programs, save the file yourself, then press the refresh icon beside **Sheet**. Opening the Files panel puts the folder dot away |
| Start shakes while you are talking | Quill stopped listening because the file was closed or a different sheet is open and not saved. While you were listening by voice you also hear the error sound (or the word *Problem*), because you are not looking; a click on Start with nothing listening only shakes |
| A red dot on the folder icon: *Now on sheet …* | You moved to another sheet in your spreadsheet program and Quill followed. Opening the Files panel puts the dot away |
| *File not connected* | Open your spreadsheet. Quill finds it in a few seconds. Pressing **Start** with none open shakes the button and opens the Files panel so you can pick one |
| A row is in LibreOffice but not in the file | Quill writes into the **open LibreOffice document** and leaves saving to you, as with Excel. Press **Save** in LibreOffice (keep the `.xlsx` format) |
| Mac asks about controlling your spreadsheet program | Choose **OK**. To undo: *System Settings > Privacy & Security > Automation* |
| Quill doesn't know my lists | **Save** the sheet; Quill re-reads it. Lists must be real drop-downs (*Data > Data Validation > List*) |
| *"The … list is full"* | Add empty cells below that list in your sheet |
| Word goes to the wrong column | Say the **column name first**: *"color black"* |
| A word keeps showing in Term Helper | Choose **Add** or **Same As…** once; Quill remembers |
| *"Which column is …?"* | Say a column name, e.g. **"Color"** |
| *"I don't have …"* | That value isn't in the list: say it again, or **"ignore"** |
| No sounds | **Settings > Sounds**: check it isn't *Off*; pick another sound to hear it |
| Undo does nothing | Nothing left to undo, or you changed sheets |
| Nothing is typed | You may still be voice sorting: say **"done"** |
| Quill hears itself | Turn off **Speak Sort Term Prompts** (off by default) in **Settings > General**, or wear headphones |
| Rows don't show in my app | See [Your spreadsheet](help:spreadsheet): some apps need a reload |

## 🆕 Is it already fixed?

Quill checks at every start whether a newer version has been released. If one is out, a **red dot** appears on the Settings icon and on **About** in the Settings list; open **Settings > About** and press **Update** to read what changed and go to the download page. Press **Check for Updates** there at any time, and turn the start-up check off on the same page.

![The red dot on About in Settings](images/settings-update.png)

![The About page with the Update button](images/settings-about.png)

## 🛟 Still stuck?

![The Report a Problem form](images/support.png)

Choose **Help > Report a Problem**. Write what happened, look at exactly what will be sent if you like, and press **Send Report**: you don't need a GitHub account. **Copy Diagnostics** gives you the same text to send yourself. See [Privacy and Your Data](help:privacy) for what is and isn't included.

## 🙌 Good to know

- Quill **never overwrites** a cell that already has content.
- Say the same column twice and the **last one wins**; say **"cancel"** to start over.
- Google Sheets and Excel for the web aren't driven live. Save the file to Google Drive and open it there to review.
- A headset and a short pause before "next row" help.
- Keep drop-down lists on a **Config** sheet with spare empty cells.
