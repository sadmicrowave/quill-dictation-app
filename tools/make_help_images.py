"""Regenerate the pictures the help pages use (``quill/help/images/``).

Run from the repository root with the project's Python:  ``.venv/bin/python tools/make_help_images.py``
The windows are drawn offscreen with sample data, so nothing needs Excel or a microphone.
"""
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer                                  # noqa: E402
from PySide6.QtWidgets import QApplication                              # noqa: E402

from quill.config.settings import Settings                              # noqa: E402
from quill.parser.vocab import Vocabulary                               # noqa: E402
from quill.ui.main_window import MainWindow                             # noqa: E402
from quill.ui.settings_dialog import SettingsDialog                     # noqa: E402
from quill.ui.sorting_window import SortingWindow                       # noqa: E402
from quill.ui.theme import apply_spacing, apply_theme, colors_for                   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "quill" / "help" / "images"
WIDTH = 560                                                              # pictures are shown at most this wide


def save(widget, name: str, crop_top: int = 0) -> None:
    pixmap = widget.grab()
    if crop_top:                                   # the in-window menu bar (macOS has it at the top of the screen)
        pixmap = pixmap.copy(0, crop_top, pixmap.width(), pixmap.height() - crop_top)
    if pixmap.width() > WIDTH:
        pixmap = pixmap.scaledToWidth(WIDTH, Qt.TransformationMode.SmoothTransformation)
    pixmap.save(str(OUT / name))
    print("wrote", name, pixmap.width(), "x", pixmap.height())


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, "dark", "violet", "compact")
    row = {"Type": "T-Shirt", "Color": "Black", "Size": "L", "Condition": "Good", "Appraisal": 35}

    def as_native(window: MainWindow) -> MainWindow:
        """Hide the in-window icon buttons, as on macOS where they sit in the title bar."""
        window.set_native_help_button(True)
        window.set_native_undo_button(True)
        window.set_native_settings_button(True)
        window.set_native_mini_button(True)
        return window

    main_window = as_native(MainWindow())
    main_window.setup()
    main_window.update_workbooks(["Apparel Inventory.xlsx"], "Apparel Inventory.xlsx")
    main_window.update_sheet("Inventory")
    main_window.set_listening_indicator(True)
    colors = colors_for(True, "violet")
    main_window.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
    main_window.set_stream_classifier(lambda words: [w in ('black', 't-shirt', 'large', 'good', 'appraisal', 'thirty', 'five') for w in words])
    main_window.add_stream_text('this next one is a black t-shirt large good appraisal thirty five')
    main_window.update_current_row(row)
    main_window.set_last_saved("Row 6", {"Type": "Blouse", "Color": "Navy", "Size": "M"})
    main_window.widget.resize(380, 590)
    main_window.widget.show()

    mini = as_native(MainWindow())
    mini.setup()
    mini.set_mini(True)
    mini.set_listening_indicator(True)
    mini.update_current_row(row)
    mini.set_sorting_count(2)
    mini.widget.resize(340, 190)
    mini.widget.show()

    waiting = as_native(MainWindow())
    waiting.setup()
    waiting.set_not_connected(True)
    waiting.widget.resize(380, 200)
    waiting.widget.show()

    vocab = Vocabulary()
    vocab.load({"Era": ["1980s"], "Color": ["Black"], "Type": ["T-Shirt"]}, [])
    helper = SortingWindow(vocab, lambda *a: None)
    helper.setup(parent=main_window.widget)
    helper.set_items([(None, "teal"), ("Era", "90s")])
    helper.set_voice_active(True)
    apply_spacing(helper.widget, "compact")
    helper.widget.resize(620, 330)
    helper.show()

    dialogs = {}
    for shown in ("Appearance", "Sounds", "Keywords"):
        dialog = SettingsDialog(Settings.defaults())
        widget = dialog.build()
        dialog.nav.setCurrentRow(dialog._nav_row(shown))
        widget.resize(820, 520)
        widget.show()
        dialogs[shown] = (dialog, widget)

    def grab() -> None:
        save(main_window.widget, "main-window.png", 24)
        save(mini.widget, "mini-view.png", 24)
        save(waiting.widget, "not-connected.png", 24)
        save(helper.widget, "term-helper.png")
        for shown, (dialog, widget) in dialogs.items():
            save(widget, f"settings-{shown.lower()}.png")
        app.quit()

    QTimer.singleShot(1200, grab)
    app.exec()


if __name__ == "__main__":
    main()
