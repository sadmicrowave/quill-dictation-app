"""Pytest config: force Qt to render offscreen so UI tests run headless."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QUILL_NO_SOUND", "1")   # tests must never make noise


import pytest


@pytest.fixture(autouse=True)
def _close_windows_after_each_test():
    """Destroy every window a test opened.

    Each test builds its own windows; left alive they pile up, and every later
    style-sheet change has to re-polish all of them, which makes the suite
    slower and slower.
    """
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _no_window_animation():
    """Resize instantly in tests (the animation has its own test)."""
    try:
        from quill.ui.main_window import MainWindow
    except ImportError:
        yield
        return
    saved = MainWindow.animation_ms
    MainWindow.animation_ms = 0
    yield
    MainWindow.animation_ms = saved
