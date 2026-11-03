"""Pytest config: force Qt to render offscreen so UI tests run headless."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QUILL_NO_SOUND", "1")   # tests must never make noise
os.environ.setdefault("QUILL_NO_HOSTS", "1")   # ... and never ask the system which programs are running


import pathlib

import pytest

SLOW_LIST = pathlib.Path(__file__).parent / "tests" / "slow_tests.txt"


def pytest_addoption(parser):
    parser.addoption("--full", action="store_true", default=False,
                     help="run every test (a plain run skips the slow ones listed in tests/slow_tests.txt)")


def pytest_collection_modifyitems(config, items):
    """A plain run is the quick one (about a minute and a half); ``--full`` (or QUILL_FULL=1) is the whole suite, for before a commit,
    a build, or when something big changed."""
    if config.getoption("--full") or os.environ.get("QUILL_FULL") or not SLOW_LIST.is_file():
        return
    slow = {line.strip() for line in SLOW_LIST.read_text().splitlines() if line.strip() and not line.startswith("#")}
    if config.args and any("::" in a for a in config.args):
        return                                          # a test named on the command line is always run
    kept = [item for item in items if item.nodeid not in slow]
    dropped = [item for item in items if item.nodeid in slow]
    if dropped:
        items[:] = kept
        config.hook.pytest_deselected(items=dropped)


def pytest_report_header(config):
    if not (config.getoption("--full") or os.environ.get("QUILL_FULL")) and SLOW_LIST.is_file():
        return "quick run (~1.5 min): slow tests skipped (pytest --full runs everything)"

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
        from quill.ui.sorting_window import SortingWindow
    except ImportError:
        yield
        return
    saved = MainWindow.animation_ms, SortingWindow.animation_ms
    MainWindow.animation_ms = SortingWindow.animation_ms = 0
    yield
    MainWindow.animation_ms, SortingWindow.animation_ms = saved
