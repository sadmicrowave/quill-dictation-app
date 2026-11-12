"""How Quill looks on this machine's real screen: the toolbar, the mini view, the text size, pop-up corners, the Settings window opening, and
screenshots of every window in both themes. Run by the VM job runner (``looks`` job); ``--offscreen`` tries it anywhere.

What it can say for sure (checks): sizes, positions and pixels of the windows. What it cannot (a person looks at the screenshots): taste.
"""
from __future__ import annotations

import sys

from common import Report, corners_are_clear, parse, screen_image, scratch_folder, start_qt, wait


def main(argv=None) -> int:
    args = parse(__doc__, argv)
    app = start_qt(args.offscreen)
    report = Report(args.out, args.offscreen)
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtTest import QTest

    from quill import platforms
    from quill.ui.main_window import MainWindow
    from quill.ui.theme import apply_theme, colors_for

    real_screen = not args.offscreen
    MainWindow.animation_ms = 0

    def build(theme: str, size=None, width=520, height=600):
        apply_theme(app, theme, font_size=size or platforms.default_font_size())
        window = MainWindow()
        window.setup()
        window.update_workbooks(["Stock.xlsx"], "Stock.xlsx")
        window.set_columns(["ID", "Species", "Price", "Notes"])
        window.set_column_tips({"Notes": "Say “notes” or “start note”, speak your note, then “end note” or “next row”."})
        colors = colors_for(theme == "dark", "violet")
        window.refresh_icons(colors["text"], colors["on_accent"], colors["accent"])
        window.widget.resize(width, height)
        window.widget.show()
        wait(1300)
        return window

    def where(window, widget) -> QPoint:
        return widget.mapTo(window.widget, QPoint(0, 0))

    def pixel(window, point):
        return window.widget.grab().toImage().pixelColor(point)

    # -- text size ---------------------------------------------------------------------------------------------------------------------------
    window = build("light")
    report.check("the text size setting is the default for this system", int(app.property("quillFontSize")) == platforms.default_font_size(),
                 f"{app.property('quillFontSize')} (default {platforms.default_font_size()})")
    title = QFontDatabase.systemFont(QFontDatabase.SystemFont.TitleFont).pointSizeF()
    bar = window.widget.menuBar()
    report.check("the menu bar text is the title bar's size", abs(bar.font().pointSizeF() - title) <= 0.6, f"{bar.font().pointSizeF()} against {title}")

    # -- the toolbar --------------------------------------------------------------------------------------------------------------------------
    icons = [window.help_button, window.undo_button, window.open_file_button, window.turn_button, window.settings_button, window.mini_button]
    start_y = where(window, window.toggle_button).y()
    report.check("every toolbar icon is above Start", all(where(window, b).y() + b.height() <= start_y for b in icons))
    half = window.widget.width() / 2
    report.check("help and undo are at the left, the other four at the right",
                 all(where(window, b).x() + b.width() < half for b in icons[:2]) and all(where(window, b).x() > half for b in icons[2:]))
    report.check("Start keeps most of the width", window.toggle_button.width() >= window.widget.width() * 0.7, str(window.toggle_button.width()))
    edges_clear = []
    for button in icons:
        origin = where(window, button)
        outside = pixel(window, QPoint(origin.x() - 4, origin.y() + button.height() // 2))
        inside = pixel(window, QPoint(origin.x() + 1, origin.y() + button.height() // 2))
        if max(abs(inside.red() - outside.red()), abs(inside.green() - outside.green()), abs(inside.blue() - outside.blue())) > 8:
            edges_clear.append(button.toolTip())
    report.check("no icon has a border until the pointer is on it", not edges_clear, ", ".join(edges_clear))
    report.check("the grid has info icons for the notes column", "Notes" in window.row_table._tips)
    shot = report.widget_shot(window.widget, "main-light")
    report.check("screenshot: main window, light", True, shot=shot)

    # -- the mini view ------------------------------------------------------------------------------------------------------------------------
    window.set_mini(True)
    wait(400)
    start_y = where(window, window.toggle_button).y()
    report.check("the mini view keeps the toolbar and all six icons", window.ribbon.isVisible() and all(b.isVisible() for b in icons) and
                 all(where(window, b).y() + b.height() <= start_y for b in icons))
    central = window.widget.centralWidget()
    corner = window.toggle_button.mapTo(central, QPoint(window.toggle_button.width() - 1, window.toggle_button.height() - 1))
    report.check("Start is whole and inside the mini window", corner.y() <= central.height() and window.toggle_button.height() >= window.toggle_button.minimumSizeHint().height(),
                 f"window {window.widget.width()}x{window.widget.height()}")
    report.check("screenshot: mini view, light", True, shot=report.widget_shot(window.widget, "mini-light"))
    window.set_mini(False)
    wait(400)
    window.widget.close()

    # -- dark ---------------------------------------------------------------------------------------------------------------------------------
    window = build("dark")
    report.check("screenshot: main window, dark", True, shot=report.widget_shot(window.widget, "main-dark"))
    window.set_mini(True)
    wait(400)
    report.check("screenshot: mini view, dark", True, shot=report.widget_shot(window.widget, "mini-dark"))
    window.set_mini(False)
    wait(300)

    # -- pop-up corners (the real screen) ------------------------------------------------------------------------------------------------------
    def popup_corners() -> None:
        from PySide6.QtWidgets import QApplication
        menu_action = window.widget.menuBar().actions()[0]
        menu = menu_action.menu()
        menu.popup(window.widget.mapToGlobal(QPoint(10, 40)))
        wait(500)
        image = screen_image()
        ok, detail = corners_are_clear(image, menu.geometry())
        report.check("a menu's corners are rounded, with nothing dark behind them", ok, detail,
                     shot=report.screen_shot("menu-open", menu.geometry().adjusted(-30, -30, 30, 30)))
        menu.close()
        wait(200)
        # the file settings overlay
        from PySide6.QtCore import QPoint as P
        window.panel.show_settings(window.widget.mapToGlobal(P(window.widget.width() - 40, 120)))
        wait(500)
        overlay = window.panel.settings
        ok, detail = corners_are_clear(screen_image(), overlay.geometry())
        report.check("the file-settings overlay's corners are rounded, with nothing dark behind them", ok, detail,
                     shot=report.screen_shot("file-settings-overlay", overlay.geometry().adjusted(-30, -30, 30, 30)))
        overlay.close()
        wait(200)
        # Quill's tool tip card, as the system asks for it over a toolbar icon
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QHelpEvent
        from quill.ui.widgets import CenteredToolTips
        tips = CenteredToolTips(app)
        app.installEventFilter(tips)
        button = window.settings_button
        point = QPoint(button.width() // 2, button.height() // 2)
        QTest.mouseMove(button, point)
        app.sendEvent(button, QHelpEvent(QEvent.Type.ToolTip, point, button.mapToGlobal(point)))
        wait(400)
        card = tips.window.geometry()
        ok, detail = corners_are_clear(screen_image(), card, margin=3)
        report.check("a tool tip card has rounded corners with nothing dark behind them", ok, detail,
                     shot=report.screen_shot("tooltip-card", card.adjusted(-30, -30, 30, 30)))
        tips.window.hide()
        app.removeEventFilter(tips)

    if real_screen:
        report.attempt("pop-up corners", popup_corners)
    else:
        report.skip("pop-up corners", "needs the real screen")

    # -- the Settings window opening ----------------------------------------------------------------------------------------------------------
    def settings_opening() -> None:
        import tempfile, pathlib
        from PySide6.QtCore import QEvent, QObject
        from PySide6.QtWidgets import QWidget
        from quill.config.settings import Settings
        from quill.ui.settings_dialog import SettingsDialog

        class Watch(QObject):
            def __init__(self):
                super().__init__()
                self.shown, self.positions = [], []

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Show and isinstance(obj, QWidget) and obj.isWindow():
                    self.shown.append(obj.metaObject().className() + ":" + (obj.windowTitle() or obj.objectName() or "-"))
                    self.positions.append((obj.windowTitle(), obj.x(), obj.y()))
                return False

        watch = Watch()
        app.installEventFilter(watch)
        folder = pathlib.Path(tempfile.mkdtemp(prefix="quill-vm-settings-"))
        dialog = SettingsDialog(Settings.load(folder), window.widget)
        dialog.open()
        wait(700)
        app.removeEventFilter(watch)
        extra = [name for name in watch.shown if "Settings" not in name]
        report.check("no other window appears while Settings opens", not extra, ", ".join(extra))
        spots = [(x, y) for title, x, y in watch.positions if title == "Quill Settings"]
        final = (dialog._dialog.x(), dialog._dialog.y())
        report.check("the Settings window opens where it stays (it does not jump after it appears)",
                     bool(spots) and abs(spots[0][0] - final[0]) <= 3 and abs(spots[0][1] - final[1]) <= 3,
                     f"first shown at {spots[0] if spots else None}, now at {final}")
        report.check("screenshot: Settings", True, shot=report.widget_shot(dialog._dialog, "settings-appearance"))
        pages = []
        for row in range(dialog.nav.count() if hasattr(dialog.nav, "count") else 0):
            dialog.nav.setCurrentRow(row)
            wait(150)
            name = f"settings-page-{row + 1:02d}"
            pages.append(report.widget_shot(dialog._dialog, name))
        report.check("screenshots: every Settings page", bool(pages), f"{len(pages)} pages")
        dialog.close_now()

    report.attempt("the Settings window opening", settings_opening)

    # -- the help window ------------------------------------------------------------------------------------------------------------------------
    def help_pages() -> None:
        from quill.ui.help_window import HelpWindow
        from quill import helpdocs
        help_window = HelpWindow()
        widget = help_window.setup()
        widget.resize(1000, 900)
        for topic in ("welcome", "notes", "icons", "troubleshooting"):
            help_window.show(topic)
            wait(300)
            report.widget_shot(widget, f"help-{topic}")
        groups = getattr(helpdocs, "GROUPS", None)
        if groups is None:
            report.skip("the help sidebar shows group headings", "this build's help has no groups")
        else:
            report.check("the help sidebar shows group headings", help_window.nav.topLevelItemCount() > len(groups))
        report.check("screenshots: four help pages", True, shot="help-welcome.png")
        widget.close()

    report.attempt("the help window", help_pages)
    window.widget.close()
    failed = [c for c in report.checks if not c["ok"]]
    print(f"{len(report.checks) - len(failed)} of {len(report.checks)} checks held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
