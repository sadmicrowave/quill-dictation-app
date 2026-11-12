# Help redesign: the rules and the page list (written)

The current help is organised by feature, written as long bullet lists, and mostly without pictures. This replaced it (`quill/help/`, 24 pages) with pages organised by what
the user is trying to do, in the order they meet it.

## Rules every page follows

1. **One page, one goal**, titled as the goal ("Use a file directly", "Fix a mistake"), never as a feature name.
2. **Numbered steps, one action each**, a short sentence in bold. Under it, one muted line: *You'll see: ...* (what changes on screen).
3. **A picture for anything the reader must find**: a real screenshot for a screen, the real icon inline for a button ("Click the folder icon [icon]"). No description of an icon in words alone.
4. **At most seven steps.** Anything else goes to a short "Good to know" (two or three plain sentences, no bullets inside bullets) or to "If something looks off".
5. **"If something looks off"** is a two-column table: *You see* | *Do this*. One line each.
6. **Tables only for lookups** (*You say* | *Quill does*), never to carry an explanation.
7. **No emoji** in headings, in the sidebar or in the text, to match the app. Callouts are plain: **Tip**, **Careful**.
8. **Plain words, second person.** No internal terms (turn, vocabulary, stream); no sentence over about 20 words.
9. **Every page ends with "Next:"** and a link to the following step of the journey.
10. **Light and dark pictures** for every screenshot (the pipeline already makes both).

## Outline (the order a person meets it)

**Start here**
1. Welcome to Quill: what it does in 30 seconds, one annotated picture of the window.
2. Quick start: install to first saved row in five steps.

**Set up (once)**
3. Choose your spreadsheet: Excel, Numbers, LibreOffice, or a file.
4. Use a file directly *(drafted)*: pick a file when no spreadsheet app is open.
5. Tell Quill where your data starts: headings row, starting row, columns across or rows down.
6. Microphone and speech model: permissions, the model, what to do if nothing is heard.

**Dictate a row (the everyday loop)**
7. Say your first row: Start, speak, "next row"; the grid, the pills, the Log.
8. Numbers, money and dates.
9. Notes and long text: "notes" or "start note", then "end note" or "next row"; the *i* icon.
10. ID and record numbers: counted for you; the grey pill; say your own.
11. Fix a mistake: delete a line, change its column, cancel the row, undo.

**When Quill does not know a word**
12. Answer with the mouse (Term Helper).
13. Answer by voice.
14. Teach Quill your words (learned words and synonyms).

**Work the way you like**
15. Mini view.
16. Add to one row, or rows down (turn options).
17. Search by voice.
18. Sounds and spoken prompts.

**Reference**
19. Every spoken phrase: one table.
20. Every icon and button: a picture glossary (the missing pictures of each icon).
21. Settings, one screenshot per group.
22. Menus and keyboard shortcuts (Mac and Windows side by side).
23. Privacy and your data.
24. Troubleshooting: symptom, then fix.

## What changes in the app
- The sidebar groups the pages under the five headings above (small, non-clickable labels) and shows plain words.
- The "?" icons open the page for the place the user is in (as now).
- A "Next:" link at the end of each page and a "Back to" link at the top.

## Checks

`tests/test_help.py` (`TestThePagesFollowTheRules`) holds the rules to the pages: no emoji, every link goes to a page, every page ends with "Next:",
no nested or long bullet lists, task pages number their steps and say what you will see, every named icon has a light and dark picture, and
the pages sit in the groups above in order. The icons are drawn by `tools/make_help_images.py` (`write_icons`), the real icons of the app.
