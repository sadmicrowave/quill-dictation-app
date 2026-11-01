"""Tests never show a real file dialog (Start with no file open would otherwise wait for a click)."""
import pytest


@pytest.fixture(autouse=True)
def _no_file_dialog(monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
