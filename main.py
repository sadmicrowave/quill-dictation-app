#!/usr/bin/env python3
"""Quill — hands-free spreadsheet dictation utility.

Entry point: python main.py  (or double-click the packaged .app / .exe)
"""
from __future__ import annotations
import sys


def main() -> int:
    # 1. Settings
    from quill.config.settings import Settings
    settings = Settings.load()

    # 2. Workbook bridge
    from quill.bridge.factory import get_bridge
    try:
        bridge = get_bridge()
    except NotImplementedError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # 3. Qt application
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Quill")
    app.setQuitOnLastWindowClosed(False)  # lives in tray after window closes

    # 4. UI
    from quill.ui.main_window import MainWindow
    from quill.ui.tray import TrayIcon

    window = MainWindow()
    window.setup()

    def on_start() -> None:
        window.set_listening_indicator(True)
        window.append_log("Listening started")
        tray.set_listening(True)

    def on_stop() -> None:
        window.set_listening_indicator(False)
        window.append_log("Listening stopped")
        tray.set_listening(False)

    tray = TrayIcon(app, window, on_start=on_start, on_stop=on_stop)
    tray.setup()
    window.show()

    # 5. Connect bridge + listener (Phase 4+)
    # TODO: bridge.connect(); vocab.load(bridge.get_lists())
    # TODO: wire listener -> session -> UI callbacks

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
