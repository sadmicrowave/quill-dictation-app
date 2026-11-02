# 🛟 Troubleshooting

## 🚦 Quick checks

1. Is the button filled and are its sound lines green and moving? (Still and grey means Quill is not listening.)
2. Is a spreadsheet open? (no *File not connected* pill)
3. Is Quill allowed to use the **microphone**?
4. Is your volume up?

## 🔧 Problems and fixes

| Problem | Try |
|---|---|
| Quill mishears many words | Choose **Settings > Speech Model > Careful** (installed once, about 145 MB), or Broad (about 130 MB). Also speak close to the microphone and pause between phrases |
| *Could not save the row…* in red in the **Log** (it opens by itself) | The row is **kept** (nothing is lost). Quill only writes to the open sheet, and it doesn't have your columns. Open the sheet you are filling in, then say **"next row"** again |
| Listening stopped by itself | Nothing was said for 10 seconds. Say **"start listening"** again, or change **Stop Listening When Quiet** in **Settings > General** |
| Nothing happens when I talk | Say **"start listening"**; check microphone permission in your computer's privacy settings |
| *File not connected* | Open your spreadsheet. Quill finds it in a few seconds |
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

## 🙌 Good to know

- Quill **never overwrites** a cell that already has content.
- Say the same column twice and the **last one wins**; say **"cancel"** to start over.
- Google Sheets and Excel for the web aren't driven live. Save the file to Google Drive and open it there to review.
- A headset and a short pause before "next row" help.
- Keep drop-down lists on a **Config** sheet with spare empty cells.
