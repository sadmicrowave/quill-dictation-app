"""Pytest config: force Qt to render offscreen so UI tests run headless."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
