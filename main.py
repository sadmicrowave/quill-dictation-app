#!/usr/bin/env python3
"""Quill — hands-free spreadsheet dictation utility.

Entry point: python main.py  (or double-click the packaged .app / .exe)

Options:
  --workbook PATH   Dictate into an .xlsx file directly (no Excel needed).
  --verbose, -v     Log debug detail to the log file and the terminal (same as QUILL_DEBUG=1).
  --demo            Open a sample workbook and add a Demo menu that fills the screens with data (QUILL_DEMO=1).
"""
from __future__ import annotations
import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    """Start Quill: read the settings, open the first workbook and run the window until the user quits."""
    parser = argparse.ArgumentParser(description="Quill dictation utility")
    parser.add_argument("--workbook", help="path to an .xlsx file to use instead of live Excel")
    parser.add_argument("--verbose", "-v", action="store_true", help="log debug detail (also QUILL_DEBUG=1)")
    parser.add_argument("--demo", action="store_true", help="sample workbook and a Demo menu (also QUILL_DEMO=1)")
    args = parser.parse_args(argv)

    from quill.diagnostics import setup_logging
    setup_logging(verbose=args.verbose)                      # a packaged app has no console: keep a log file instead

    from quill.config.settings import Settings
    from quill.demo import demo_requested
    demo = demo_requested(args.demo)
    if demo:
        # A demo must never change what a real user has taught Quill (words, synonyms, skipped words, the window's size), and a second
        # run must start as clean as the first: its settings live in a new throw-away folder every time.
        import pathlib
        import tempfile
        settings = Settings.load(pathlib.Path(tempfile.mkdtemp(prefix="quill-demo-settings-")))
    else:
        settings = Settings.load()

    from PySide6.QtWidgets import QMessageBox

    from quill.app import QuillApplication
    app = QuillApplication(sys.argv[:1])
    app.setApplicationName("Quill")
    app.setQuitOnLastWindowClosed(False)  # lives in tray after window closes

    from quill.bridge.factory import startup_bridge
    from quill.demo import make_demo_workbook
    if demo:
        args.workbook = str(make_demo_workbook(os.environ.get("QUILL_DEMO_DIR") or None))   # (a fixed folder lets a recording open the same file in a spreadsheet first)
    try:
        bridge = startup_bridge(settings, args.workbook)
    except NotImplementedError as exc:
        QMessageBox.critical(None, "Quill", str(exc))
        return 1

    from quill.app import QuillApp
    quill = QuillApp(app, settings, bridge)
    quill.start()
    if demo:
        from quill.demo import Demo
        quill.demo = Demo(quill)
        quill.window.add_demo_menu(quill.demo.scenarios())
        quill.window.set_log_collapsed(True)                       # (the log is shut by default in a shipped app: a demo or recording must not show it open)
        autorun = os.environ.get("QUILL_DEMO_AUTORUN")             # (for a recording: the promo story starts by itself this many seconds after launch)
        if autorun:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(int(float(autorun) * 1000), quill.demo.promo)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
