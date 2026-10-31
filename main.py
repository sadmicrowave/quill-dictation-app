#!/usr/bin/env python3
"""Quill — hands-free spreadsheet dictation utility.

Entry point: python main.py  (or double-click the packaged .app / .exe)

Options:
  --workbook PATH   Dictate into an .xlsx file directly (no Excel needed).
"""
from __future__ import annotations
import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quill dictation utility")
    parser.add_argument("--workbook", help="path to an .xlsx file to use instead of live Excel")
    args = parser.parse_args(argv)

    from quill.diagnostics import setup_logging
    setup_logging()                      # a packaged app has no console: keep a log file instead

    from quill.config.settings import Settings
    settings = Settings.load()

    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Quill")
    app.setQuitOnLastWindowClosed(False)  # lives in tray after window closes

    from quill.bridge.factory import startup_bridge
    try:
        bridge = startup_bridge(settings, args.workbook)
    except NotImplementedError as exc:
        QMessageBox.critical(None, "Quill", str(exc))
        return 1

    from quill.app import QuillApp
    quill = QuillApp(app, settings, bridge)
    quill.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
