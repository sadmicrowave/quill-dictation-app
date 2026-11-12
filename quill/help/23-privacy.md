# Privacy and your data

Your voice and your spreadsheets stay on your computer. This page says exactly what that means and the two things that can ever leave it.

## What stays on your computer

| What | Where it lives |
|---|---|
| **Your voice** | Turned into text by a model on your computer. No audio is saved or sent. |
| **Your spreadsheets** | Quill reads and writes only the files you open. Contents, file names and sheet names are never sent. |
| **Settings and learned words** | In your own user folders. **Settings > Learned Words** lets you forget any of it. |
| **The log** | A small record of what Quill did, in the log folder (**Help > Open the Log Folder**). It can hold file names and words, so it is never sent. |

Quill's link to LibreOffice (a small script inside it) works only on your computer, is protected by a secret only Quill's folder holds, and answers only a short list of fixed requests.

## When Quill uses the internet

| When | What is sent |
|---|---|
| You **install a speech model** | A normal download (your network address, as with any download). |
| Quill **checks for a newer version**, at each start and when you press the button in **Settings > About** | Only Quill's name and version. Nothing about you, your files or your voice. Nothing is installed by itself. |

Nothing else. Quill has no accounts, no analytics, no tracking and no automatic uploads. Turn the version check off in **Settings > About > Check for Updates at Start**.

## Report a problem

**1. Choose Help > Report a Problem.**

**2. Write what happened.** You can read exactly what will be sent first.

**3. Click Send Report.** You don't need a GitHub account.

![The Report a Problem form](images/support.png)

A report holds only your message, an e-mail address if you type one, the Quill version and your system, and (if you leave the box ticked) the **SYS** lines of the log: fixed wording, counts, program names and error kinds. It never holds file names, sheet names, column names, spoken words, cell values or folder paths. **Copy Diagnostics** gives you the same text to send yourself.

A report becomes a support request the developer reads. Ask in the request, or write to the address on the project page, and it is deleted.

## Your controls

| I want to | Do this |
|---|---|
| See what Quill stored | **Settings > Learned Words**, and **Help > Open the Log Folder** |
| Remove the log | Quit Quill and delete the log folder |
| Remove learned words | **Settings > Learned Words > Forget All Shown** |
| Remove speech models | **Settings > Speech Model** > Uninstall |
| Stop microphone use | Click **Stop**: the microphone is closed whenever Quill isn't listening |

**Next:** [Troubleshooting](help:troubleshooting)
