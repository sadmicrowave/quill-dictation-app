"""Main Quill window — compact, OS-native, dark-mode-aware.

Layout (~340 px wide):
  title bar: "Quill"  [● listening]  [⚙ settings]
  Workbook / Sheet labels
  Current row fields (building)
  Scrolling action log

Full implementation in Phase 7.
"""
from __future__ import annotations

class MainWindow:
    def __init__(self) -> None:
        self._window = None  # QMainWindow, built in setup()

    def setup(self) -> None:
        pass  # TODO Phase 7

    def show(self) -> None:
        if self._window is not None:
            self._window.show()
            self._window.raise_()

    def update_workbook(self, name: str) -> None:
        pass  # TODO Phase 7

    def update_sheet(self, name: str) -> None:
        pass  # TODO Phase 7

    def update_current_row(self, fields: dict[str, str]) -> None:
        pass  # TODO Phase 7

    def append_log(self, text: str) -> None:
        pass  # TODO Phase 7

    def set_listening_indicator(self, active: bool) -> None:
        pass  # TODO Phase 7
