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
- **Opacity & blur:** drag a slider, or click anywhere along it to jump there. With blur on, the window background turns frosted glass (text and controls stay crisp); with blur at 0 the whole window fades

## 🗝️ Keywords

![Keywords](images/settings-keywords.png)

Edit, add or remove phrases. Quill won't let a phrase clash with *yes* or *no*, and always keeps one for **Start** and **Stop**.

## 🎙️ Microphone

- **Stop Listening When Quiet** (on by default): if nothing is said for **10 seconds**, listening stops by itself, so the microphone is never left open by accident. While it counts down, a small italic **Stops in 7s** shows inside the Start / Stop button, beside the play / stop icon (and in the Term Helper's voice button). Say anything and it starts again from the full time. Change the seconds (3 to 3600) or turn it off in **General**. It also ends voice sorting and a wait for a spoken answer; the questions stay on the **Term Helper** list for later.

- **Off** until you press Start, and off again when you stop.
- Want to say **"start listening"**? Turn on **Keep the Microphone Open When Not Listening**. Your Mac's orange mic dot will show.

## 🧠 Speech model

A small English model ships inside Quill (about 41 MB). It runs **on your computer**: nothing is sent online. **Settings > General > Speech Model** lets you choose **Standard** (the one that ships) or **Better** (about 130 MB, downloaded once from the Vosk project and checked against a fingerprint before it is unpacked). Better mishears fewer words and uses more memory. If the one you chose isn't downloaded yet, the row says so and has a **Download** button with progress; until then Quill keeps using Standard. Switching takes effect straight away.

## 🖥️ Dock and menu bar

Quill lives in both. Hide the Dock icon in **General**, then use the menu bar icon > **Open Quill**. Closing the window never quits Quill: use **Quit** in the menu bar menu.
