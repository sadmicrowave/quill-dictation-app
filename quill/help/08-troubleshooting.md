# 🛟 Troubleshooting

## 🚦 Quick checks

1. 🟢 Is the button showing **Listening**?
2. 📗 Is a spreadsheet open? (no orange *File stream not connected*)
3. 🎤 Is Quill allowed to use the **microphone**?
4. 🔊 Is your volume up?

## 🔧 Problems and fixes

| Problem | Try |
|---|---|
| 🙊 Nothing happens when I talk | Say **"start listening"**; check microphone permission in your computer's privacy settings |
| 🟠 *File stream not connected* | Open your spreadsheet. Quill finds it in a few seconds |
| 🍎 Mac asks about controlling Excel | Choose **OK**. To undo: *System Settings > Privacy & Security > Automation* |
| 📋 Quill doesn't know my lists | **Save** the sheet; Quill re-reads it. Lists must be real drop-downs (*Data > Data Validation > List*) |
| 📥 *"The … list is full"* | Add empty cells below that list in your sheet |
| 🏷️ Word goes to the wrong column | Say the **column name first**: *"color black"* |
| 🧩 A word keeps showing in Term Helper | Choose **Add** or **Same As…** once; Quill remembers |
| ❓ *"Which column is …?"* | Say a column name, e.g. **"Color"** |
| ❌ *"I don't have …"* | That value isn't in the list: say it again, or **"ignore"** |
| 🔇 No sounds | **Settings > Sounds**: check it isn't *Off*; press **Play Sample** |
| ↩️ Undo does nothing | Nothing left to undo, or you changed sheets |
| ⌨️ Nothing is typed | You may still be voice sorting: say **"done"** |
| 🗣️ Quill hears itself | Turn off spoken questions in Settings, or wear headphones |
| 🔁 Rows don't show in my app | See [Your spreadsheet](help:spreadsheet): some apps need a reload |

## 🙌 Good to know

- ✋ Quill **never overwrites** a cell that already has content.
- 🔁 Say the same column twice and the **last one wins**; say **"cancel"** to start over.
- 🌐 Google Sheets and Excel for the web aren't driven live. Save the file to Google Drive and open it there to review.
- 🎧 A headset and a short pause before "next row" help.
- 🗂️ Keep drop-down lists on a **Config** sheet with spare empty cells.
