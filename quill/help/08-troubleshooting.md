# 🛟 Troubleshooting

## Stopping and quitting

- **Say "stop listening"** (or press **Stop**) to pause. You can start again any time.
- Closing the window doesn't quit Quill; it keeps running in the menu bar / tray. To quit, use **Quit** in the icon's menu.
- If you close the spreadsheet, Quill lets go of it and stops listening, and starts again (waiting for your "start listening") when you open one.

## Tips

- Speak at a normal pace with a short pause before "next row".
- A headset microphone helps. Quill mutes itself while it speaks so it doesn't hear its own voice.
- Keep your drop-down lists in a **Config** sheet with a few spare empty cells at the bottom, so Quill can add new choices.
- If you add a new drop-down or column in Excel, just **save** the file: Quill notices within a few seconds and reads it again by itself.
- Say the column name when two lists share a word ("medium" as a size vs. a light level).

## Troubleshooting

| Problem | What to do |
|---------|-----------|
| "No speech model found" | The model that ships with Quill (the `model` folder) has been removed or moved. Press **Download speech model** to fetch it again. |
| I talk and nothing happens | Check the light is green; if not, say "start listening". Make sure Quill is allowed to use the microphone in your computer's privacy settings. |
| "I can't find an open spreadsheet" | Open your spreadsheet in Excel. Quill connects by itself within a few seconds. Then say "start listening". |
| Mac asks whether Quill can control Excel | Choose OK. If you said no, turn it back on under System Settings › Privacy & Security › Automation. |
| Quill doesn't know my drop-down lists | Save the spreadsheet (Quill re-reads it by itself a few seconds later). Make sure each list is a normal Excel drop-down (Data › Data Validation › List) pointing at one column. |
| "The … list is full" | Add empty cells to the bottom of that list's range in your spreadsheet. |
| Words go to the wrong column | Say the column name first ("color black"). |
| A word keeps appearing in Term Helper | Pick **Add** or **Same as…** once; Quill remembers. |
| Voice sorting says "Which column is ‘…’?" | That item has no suggested column; say a column name, e.g. "Color". |
| Voice sorting says "I don't have ‘…’" | The value after "same as" isn't in that list; say it again, or say "ignore". |
| I can't hear any sounds | Open Settings and check *Confirm with* isn't Off; use *Play sample*; check your computer's volume. |
| "Undo" does nothing | Say it while Quill is listening, or press the Undo icon. There's nothing to undo after you connect to a different spreadsheet. |
| Nothing I say is being typed | You may still be in voice sorting; say "done". |
| Search says "nothing to filter on" | Use words that are in your lists, e.g. "search for fern under 20". |
| Quill answers itself or gets confused by its own voice | Turn off "Read questions aloud" in Settings, or use headphones. |
| Search filters don't appear in Excel | Tell your helper; this part has not yet been tested against every version of Excel. |

## Good to know

- Quill works with desktop Excel on Mac and Windows. Google Sheets and Excel for the web aren't supported; to review a result in Google Sheets, save the Excel file to Google Drive and open it there.
- Quill never overwrites something you typed. If a cell it wants to fill already has content, it leaves it alone.
- If you say the same column twice while describing one item ("size medium… size large"), the last one wins. To start over, say "cancel".
