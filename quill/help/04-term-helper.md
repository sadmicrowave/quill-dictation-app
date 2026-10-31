# 🧩 Term Helper

Term Helper is the window that opens when Quill hears words it can't place.

![The Term Helper window with Sort by Voice on](images/term-helper.png)

## When Quill doesn't know a word

Say something that isn't in your lists, for example *"…made in the 90s, mainly teal…"*, and Quill saves everything it understood, then opens a small **Term Helper** window listing the rest, one line each. If you start **Sort by Voice** the first row lights up and shows what to say (and the list of columns opens when it needs one):

> You said ‘90s’ — is that an Era?  
> You said ‘teal’ — which column is that?

For each line you choose:

- **Add**: put it in that column's drop-down list as a new choice.
- **Same as…**: it's another name for something already there ("extra large" is the same as XL; the value comes from your own list, whatever your spreadsheet is about). Quill remembers it for next time.
- **Ignore**: forget it.

If you'd already saved the row, Quill fills in the empty cell for you as soon as you decide. The window is resizable and scrolls if there are many. If it's closed, press **Term Helper (n)** in the main window to reopen it.

### Changed your mind? Undo

Press the **Undo** icon (the curved arrow in the title bar of the main window, left of the settings icon; or in the Term Helper window)  or say **"undo"**. Each press takes back one answer, so you can keep stepping back. Quill remembers your last 100 answers. Undo puts the item back where it was in the list and takes back what it did: the new choice is removed from your drop-down list, the "same as" is forgotten, and the cell it filled is emptied again (unless you've typed in it since, in which case it's left alone). Saved rows themselves are normal Excel rows; use Excel's own undo for those.

### Or just say your answers

Tired of clicking? **Click the first item** in the window (or press **🎤 Sort by Voice**, or say **"sort terms"**) and talk. Quill answers the *top* item with the first thing you say, removes it, and moves the next one up, so you can keep going without touching the mouse:

| Say | What happens to the top item |
|-----|------------------------------|
| **"Yes"** or **"Add"** | Added to the column Quill suggested |
| **a column name**, e.g. **"Color"** | Added to that column |
| **"Same as …"** and then a value from your list, e.g. **"Same as XL"** | Becomes another name for that value |
| **"Undo"** or **"Oops"** | Takes back the last answer (**"Undo three"** takes back three) |
| **"Ignore"** or **"No"** | Forgotten |
| **"Later"** or **"Skip"** | Kept, moved to the bottom of the list |
| **"Add all"** / **"Ignore all"** | Everything at once |
| **"Done"** | Stop voice sorting |

You can chain them: **"Same as (a value)… color… same as (another value)… done."** The window shows what Quill heard and what it did. While you're sorting by voice, nothing you say is typed into the spreadsheet, and it stops by itself when the list is empty. (Settings has a switch to start voice sorting automatically.)

When Quill is fairly sure of the column for everything, it also asks out loud ("Teal isn't in the Color list. Add it?"); say **"yes"** to accept or **"no"** to skip.

## When something needs sorting

You'll know without looking at Quill's window: the **menu bar / tray icon** shows a coloured circle with the number of items waiting (in the accent colour you chose), and the **Term Helper** button in the window turns that colour with the number beside it. Click either to open the list. Both disappear when the list is empty.
