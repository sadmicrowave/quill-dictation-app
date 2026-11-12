# Troubleshooting

Find what you see, then do what it says.

## Check these first

**1. Is the Start button dark purple with moving lines?** A flat line and the words *Start Listening* mean Quill isn't listening.

**2. Is a spreadsheet open?** The button doesn't say *File not connected*.

**3. Is the microphone allowed?** Check your computer's privacy settings.

**4. Is your volume up?**

## Nothing happens, or Quill stops

| You see | Do this |
|---|---|
| Nothing happens when you talk | Say **"start listening"**. Check microphone permission. |
| Listening stopped by itself | Nothing was said for 10 seconds. Click Start, or change **Stop Listening When Quiet** in **Settings > General**. |
| Start shakes while you talk | The file was closed, or a different sheet is open and not saved. Pick the file again. |
| Nothing is typed | You may still be sorting words by voice: say **"done"**. |
| No sounds | **Settings > Sounds**: check it isn't *Off*, then pick a sound to hear it. |

## Wrong words or columns

| You see | Do this |
|---|---|
| Many words misheard | Install **Careful** or **Broad** in **Settings > Speech Model**. Speak close to the microphone and pause between phrases. |
| A word goes to the wrong column | Say the column name first: *"color black"*. |
| A word keeps showing in the Term Helper | Click **Add** or **Same As…** once. Quill remembers. |
| **Which column is...?** | Say a column name, for example **"Color"**. |
| **I don't have...** | That value isn't in the list: say it again, or **"ignore"**. |
| Quill hears itself | Turn off **Speak Sort Term Prompts** in **Settings > General**, or wear headphones. |

## The row isn't saved, or isn't where you expect

| You see | Do this |
|---|---|
| **Could not save the row...** in red in the Log | Your words are kept. Open the sheet you are filling in, then say **"next row"** again. |
| **This sheet has no column headings Quill can find** | Set the **Headings Row** ([Where your data starts](help:data-starts)). **Start** is off until the sheet has headings. |
| **The ... list is full** | Add empty cells below that list in your sheet. |
| Quill doesn't know my lists | Save the sheet. Lists must be real drop-downs (**Data > Data Validation > List**). |
| A row is in LibreOffice but not in the file | Quill writes into the open document and leaves saving to you. Click **Save** in LibreOffice (keep `.xlsx`). |
| Rows don't show in my app | Some apps need the file reopened ([Choose your spreadsheet](help:choose-spreadsheet)). |

## File and sheet

| You see | Do this |
|---|---|
| **File not connected** | Open your spreadsheet (Quill finds it in a few seconds), or click Start to open the Files panel and pick one. |
| **... was closed** under Open File | You closed the spreadsheet window, so Quill stopped. Click **Reopen**, or pick another file. |
| A red dot on the folder icon, then one beside **Sheet** | You opened a sheet the saved file doesn't have. Save the file, then click the refresh icon beside **Sheet**. (LibreOffice needs no save.) |
| A red dot: *Now on sheet...* | You changed sheet and Quill followed. Opening the Files panel clears the dot. |
| The Mac asks about controlling your spreadsheet program | Choose **OK**. Undo it later in **System Settings > Privacy & Security > Automation**. |

## Is it already fixed?

Quill checks for a newer version at every start. If one is out, a red dot appears on the Settings icon and on **About**. Open **Settings > About** and click **Update**.

![The About page with the Update button](images/settings-about.png)

## Still stuck?

**1. Choose Help > Report a Problem.**

**2. Write what happened and click Send Report.** See [Privacy and your data](help:privacy) for exactly what is sent.

## Good to know

Quill never overwrites a cell that already has content. Say the same column twice and the last one wins; say **"cancel"** to start over. Google Sheets and Excel for the web aren't driven live: save the file to Google Drive and open it there. Keep drop-down lists on a **Config** sheet with spare empty cells.
