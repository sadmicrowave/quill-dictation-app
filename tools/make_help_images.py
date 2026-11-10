"""Regenerate the pictures the help pages use (``quill/help/images/``).

Run from the repository root with the project's Python:  ``.venv/bin/python tools/make_help_images.py``
The windows are drawn offscreen with sample data, so nothing needs Excel or a microphone.
"""
import os
import pathlib
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt                                          # noqa: E402
from PySide6.QtTest import QTest                                       # noqa: E402
from PySide6.QtWidgets import QApplication                              # noqa: E402

from quill.config.settings import Settings                              # noqa: E402
from quill.parser.vocab import Vocabulary                               # noqa: E402
from quill.stream import WordMatch                                      # noqa: E402
from quill.ui.main_window import MainWindow                             # noqa: E402
from quill.ui.settings_dialog import SettingsDialog                     # noqa: E402
from quill.ui.sorting_window import SortingWindow                       # noqa: E402
from quill.ui.theme import apply_spacing, apply_theme, colors_for                   # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "quill" / "help" / "images"
WIDTH = 560                                                              # pictures are shown at most this wide


def save(widget, name: str, crop_top: int = 0, theme: str = "dark") -> None:
    pixmap = widget.grab()
    if crop_top:                                   # the in-window menu bar (macOS has it at the top of the screen)
        pixmap = pixmap.copy(0, crop_top, pixmap.width(), pixmap.height() - crop_top)
    if pixmap.width() > WIDTH:
        pixmap = pixmap.scaledToWidth(WIDTH, Qt.TransformationMode.SmoothTransformation)
    name = f"{pathlib.Path(name).stem}-{theme}.png"            # one picture per theme: the help shows the one that matches
    pixmap.save(str(OUT / name))
    print("wrote", name, pixmap.width(), "x", pixmap.height())


def main() -> None:
    app = QApplication(sys.argv)
    for old in OUT.glob("*.png"):
        old.unlink()
    for theme in ("light", "dark"):
        shoot(app, theme)


def support_form():
    """The Report a Problem form with a sample message and the preview open (a log of SYS lines only)."""
    import logging
    import tempfile
    from quill import diagnostics
    from quill.ui.support_dialog import SupportDialog
    folder = pathlib.Path(tempfile.mkdtemp())
    diagnostics.setup_logging(folder)
    logging.getLogger("quill").info("Connected to a file the report never shows")
    diagnostics.syslog().info("Connected to a spreadsheet: %d lists, %d values", 5, 25)
    dialog = SupportDialog(None, lambda payload: None, lambda: None, log_folder=folder, configured=True)
    dialog.message.setPlainText("After I said next row the line was saved twice.")
    dialog.toggle_preview()
    dialog.resize(560, dialog.sizeHint().height())
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    return dialog


def shoot(app: QApplication, theme: str) -> None:
    dark = theme == "dark"
    apply_theme(app, theme, "violet", "compact")
    row = {"Type": "T-Shirt", "Color": "Black", "Size": "L", "Condition": "Good", "Appraisal": 35}

    def as_native(window: MainWindow) -> MainWindow:
        """Hide the in-window icon buttons, as on macOS where they sit in the title bar."""
        window.set_native_help_button(True)
        window.set_native_undo_button(True)
        window.set_native_settings_button(True)
        window.set_native_mini_button(True)
        window.set_native_file_button(True)
        window.set_native_turn_button(True)
        return window

    main_window = as_native(MainWindow())
    main_window.setup()
    main_window.update_workbooks(["Apparel Inventory.xlsx"], "Apparel Inventory.xlsx")
    main_window.set_listening_indicator(True)
    colors = colors_for(dark, "violet")
    main_window.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
    heard_in = {"black": "Color", "t-shirt": "Type", "large": "Size", "good": "Condition", "appraisal": "Appraisal", "thirty": "Appraisal", "five": "Appraisal"}
    main_window.set_columns(["Type", "Color", "Size", "Era", "Condition", "Appraisal", "Notes"])        # (the sheet's columns, listed from the start)
    main_window.set_stream_classifier(lambda words: [WordMatch(w in heard_in, heard_in.get(w), span=list(heard_in).index(w) if w in heard_in else None) for w in words])
    main_window.add_stream_text('this next one is a black t-shirt large good appraisal thirty five')
    main_window.update_current_row(row)
    main_window.set_last_saved("Row 6", {"Type": "Blouse", "Color": "Navy", "Size": "M"})
    main_window.widget.resize(380, 590)
    main_window.widget.show()

    mini = as_native(MainWindow())
    mini.setup()
    mini.set_mini(True)
    mini.set_listening_indicator(True)
    mini.set_columns(["Type", "Color", "Size", "Era", "Condition", "Appraisal", "Notes"])
    mini.update_current_row(row)
    mini.set_sorting_count(2)
    mini.widget.resize(340, 190)
    mini.widget.show()

    waiting = as_native(MainWindow())
    waiting.setup()
    waiting.set_not_connected(True)
    waiting.widget.resize(380, 200)
    waiting.widget.show()

    panels = {}
    MainWindow.animation_ms = 0                                   # the panel is drawn open, not mid-slide
    for page in ("file", "turn"):
        side = as_native(MainWindow())
        side.setup()
        side.update_workbooks(["Apparel Inventory.xlsx"], "Apparel Inventory.xlsx")
        side.set_workbook_path("/Users/you/Documents/Apparel Inventory.xlsx")
        side.set_active_sheet("Inventory")
        side.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
        side.panel.set_available([("Orders 2026.xlsx", "Open in Numbers", None), ("Birds.csv", "Open in Numbers", None),
                                  ("Budget.xlsx", "Open in Excel", None), ("Notes.xlsx", "Open in LibreOffice Calc", None)])
        side.panel.set_turn("append", False)
        side.widget.resize(453, 430)
        side.widget.show()
        side.open_panel(page)
        panels[page] = side
    MainWindow.animation_ms = 240

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
    newer = {"available": True, "checking": False, "message": "Version 0.2.0 is available."}
    for shown in ("Appearance", "Sounds", "Keywords", "About", "Update"):
        dialog = SettingsDialog(Settings.defaults(), update_state=lambda: newer)
        widget = dialog.build()
        if shown == "Update":                                  # the red dot on About, seen from another page
            dialog.nav.setCurrentRow(dialog._nav_row("General"))
            dialog.set_about_badge(True)
        else:
            dialog.nav.setCurrentRow(dialog._nav_row(shown))
        widget.resize(820, 520)
        widget.show()
        dialogs[shown] = (dialog, widget)

    QTest.qWait(1200)
    save(main_window.widget, "main-window.png", 24, theme)
    save(mini.widget, "mini-view.png", 24, theme)
    save(waiting.widget, "not-connected.png", 24, theme)
    save(helper.widget, "term-helper.png", 0, theme)
    save(support_form(), "support.png", 0, theme)
    for page, side in panels.items():
        save(side.widget, f"side-panel-{page}.png", 24, theme)
    for shown, (dialog, widget) in dialogs.items():
        save(widget, f"settings-{shown.lower()}.png", 0, theme)
    for window in (main_window.widget, mini.widget, waiting.widget, helper.widget, *(p.widget for p in panels.values()), *(w for _, w in dialogs.values())):
        window.close()


if __name__ == "__main__":
    main()
