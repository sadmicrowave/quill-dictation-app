# 🔒 Privacy and Your Data

Quill is built so that your voice and your spreadsheets stay on your computer. This page says exactly what that means, what is stored here, and the one thing that can ever be sent.

## 🏠 What stays on your computer

- **Your voice.** Speech is turned into text by a model that runs on your computer. No audio is recorded to a file and none is sent anywhere.
- **Your spreadsheets.** Quill reads and writes only the files you open, using your spreadsheet program or the file itself. Their contents, names and sheet names are never sent. Quill's link to LibreOffice (a small script inside it) works only on your own computer, is protected by a secret that only Quill's own folder holds, and answers nothing but a short list of fixed requests.
- **What Quill remembers.** Your settings, the words Quill learned from you (*Settings > Learned Words*) and the speech models live in your own user folders. *Settings > Learned Words* lets you forget any of it.
- **The log.** Quill keeps a small log of what it did (*Help > Open the Log Folder*) so problems can be understood. It can contain file names and words, so **the log itself is never sent**. Each line is labelled **USR** (may contain your things, stays here) or **SYS** (fixed wording only: counts, program names, error kinds). Only SYS lines can be part of a report.

## 🌐 When Quill uses the internet

- **Downloading a speech model**, only when you choose to install one: the Quick model comes from alphacephei.com and the Careful one from huggingface.co. Nothing about you is sent with the request except what any download reveals (your network address).
- **Nothing else.** Quill has no accounts, no analytics, no tracking and no automatic uploads.

## 📨 Reporting a problem (the only thing that can be sent)

**Help > Report a Problem** opens a form. Nothing is sent until you press **Send Report**, and **Show exactly what will be sent** shows the full text first. A report holds:

- what you wrote in the box;
- an e-mail address, **only if you typed one** (so you can be answered);
- the Quill version and your system (for example *macOS 15, Apple Silicon*);
- if you leave the box ticked, the **SYS** lines of the log.

It never holds file names, sheet names, column names, spoken words, cell values or folder paths. Untick **Include the diagnostic log** to send only your message, or use **Copy Diagnostics** to read it and send it yourself.

A report becomes a support request that the Quill developer reads. Requests are kept only as long as needed to fix the problem, and anything you send can be deleted: ask in the request, or write to the address on the project page.

## 🧰 Your controls

| I want to… | Do this |
|---|---|
| See what Quill stored about me | *Settings > Learned Words*, and *Help > Open the Log Folder* |
| Remove the log | Quit Quill and delete the log folder |
| Remove learned words | *Settings > Learned Words > Forget All Shown* |
| Remove downloaded speech models | *Settings > Speech Model* |
| Stop microphone use | Press **Stop**; the microphone is closed whenever Quill isn't listening |

See also [Troubleshooting](help:troubleshooting).
