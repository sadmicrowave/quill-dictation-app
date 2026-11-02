# ⚙️ Settings

Press the ** sliders icon** in the title bar. Type in **Search** to jump to a setting (try *blur* or *voice*).

![Appearance settings](images/settings-appearance.png)

> 💡 Changes show **live**. **OK** keeps them, **Cancel** puts everything back. Settings reopens on the page you left it on, at the size you left it.

## 🧭 Groups

| Group | What's in it |
|---|---|
| **General** | Spoken Term Helper prompts (off by default), automatic voice sorting, microphone, **stop when quiet**, Dock icon, Undo memory |
| **Appearance** | Theme, accent colour, spacing, text size, opacity, blur |
| **Sounds** | Sound set, spoken word, sample |
| **Keywords** | The phrases you say and what they do |

## 🎨 Look

- **Theme:** Auto, Light or Dark
- **Accent:** Violet (default), Terracotta, Ocean, Forest, Rose
- **Spacing:** Compact or Comfortable
- **Text size:** 9–20 pt
- **Term Helper Follows Window Opacity** (off by default): the Term Helper stays solid so it is easy to read; turn this on to make it see-through like the main window
- **Opacity & blur:** drag a slider, or click anywhere along it to jump there. **Opacity** thins the window's background (text and controls stay crisp); **Blur** then blurs what shows through it (0 keeps it sharp). At opacity 100 the window is solid whatever the blur

## 🗝️ Keywords

![Keywords](images/settings-keywords.png)

Edit, add or remove phrases. Quill won't let a phrase clash with *yes* or *no*, and always keeps one for **Start** and **Stop**.

## 🎙️ Microphone

- **Stop Listening When Quiet** (on by default): if nothing is said for **10 seconds**, listening stops by itself, so the microphone is never left open by accident. While it counts down, the seconds left (for example **7s**) show to the right of the **Stop Listening** pill (and in the Term Helper's voice button). Say anything and it starts again from the full time. Change the seconds (3 to 3600) or turn it off in **General**. It also ends voice sorting and a wait for a spoken answer; the questions stay on the **Term Helper** list for later.

- **Off** until you press Start, and off again when you stop.
- Want to say **"start listening"**? Turn on **Keep the Microphone Open When Not Listening**. Your Mac's orange mic dot will show.

## 🧠 Speech model

A small English model ships inside Quill (about 41 MB). It runs **on your computer**: nothing is sent online. **Settings > Speech Model** (under *Voice and Commands*) lists the models with a radio button each; only one can be chosen. **Standard** (40 MB, ships with Quill) is quick and fine for clear speech and everyday words. **Better** (130 MB) has a much bigger vocabulary, so unusual words, names and numbers are heard correctly far more often. **Best** (145 MB) adds a second listen: after each pause a Whisper model re-reads the phrase using the words around each one, and the corrected words replace the live ones a moment later. A model that is on this computer shows an **Installed** pill; one that is not has a **Download** button with progress (downloaded once, over https, and checked against a fingerprint). Until it is downloaded Quill keeps using Standard. Switching takes effect straight away.

## 🖥️ Dock and menu bar

Quill lives in both. Hide the Dock icon in **General**, then use the menu bar icon > **Open Quill**. Closing the window never quits Quill: use **Quit** in the menu bar menu.
