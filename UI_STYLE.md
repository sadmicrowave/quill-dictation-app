# Quill UI style: one style per element type

Every kind of element has **one** decided look, used in every window and page. When something is added, find the
existing widget for its type and use it; never hand-style a one-off. `tests/test_side_panel_and_turns.py`
(`TestControlsFollowTheirStyle`, `TestOneStyleForTooltipsEverywhere`, `TestEverythingClickableHasHoverText`) enforces
what can be checked; this page is what cannot.

| Element | The one style | Where it lives |
|---|---|---|
| **Button** | accent-coloured 1 px border, no fill until hovered; icon-only buttons grey-bordered; a button that is not usable *looks* disabled (grey border and text) | `theme.py` (`QPushButton`, `[outline]`, `:disabled`) |
| **Link** | accent colour, underlined; the pointer is a hand only while over the link itself; it has hover text | `QLabel` with `href`, `linkHovered` |
| **Input / search box** | boxed field, rounded 8 px, accent border on focus, placeholder text muted | `QLineEdit` rule in `theme.py` |
| **Number field with "Automatic"** | boxed, empty means Automatic, shown as muted placeholder | `side_panel.NumberField` |
| **Drop-down** | the flat one with a chevron, always `FlatCombo` (a letter list is `LetterBox`, a `FlatCombo`) | `settings_widgets.FlatCombo` |
| **Switch / slider / spin box** | `ToggleSwitch`, `GuardedSlider`, `GuardedSpinBox` | `settings_widgets.py` |
| **Radio button** | accent-filled circle; its description is muted text under the name | `QRadioButton` rule |
| **Pill (spoken word or phrase)** | `PILL_BG` violet with white text, square-cornered; editable ones are `PillField` | `theme.PILL_BG/PILL_FG`, `widgets.pill`, `PillField` |
| **Status pill** | no fill, accent border and text (`Installed`) | `QLabel[installedPill]` |
| **Placeholder / hint text** | muted, italic | `QLabel[placeholder]`, `[note]` |
| **Section title in the side panel** | bold; muted small text under it | `QLabel[panelHeading]`, `[panelNote]` |
| **Chrome icon** | 36 x 30 box, 16 pt symbol, rounded muted fill on hover and while its panel is open | `chrome.py` |
| **Tool tip** | the rounded lighter-grey card, centred on the pointer, plain text only (no markup, no emoji or symbols), on screen | `widgets.TipWindow`, `CenteredToolTips` |
| **Hover text** | every clickable element has some (`hints.fill_missing_tips` is the safety net) | `hints.py` |
| **Confirming blink** | one blink for the whole app: green for it worked, grey for a deliberate no, red for it could not | `theme.FLASH_STYLES` |
| **Sounds** | only for what the user *said*, never for a click | `Event.spoken`, `Controller` |

Rules of thumb: a control that works the same way gets the same widget; wording that depends on the sheet's layout
follows it (rows or columns); never ship a window the pixel checks have not seen (`tools/verify_window_effects.py`
for opacity and blur).
