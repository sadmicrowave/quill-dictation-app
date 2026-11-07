"""The macOS provider's tests run on a Mac only (they use fake AppKit objects, but they exist to check Mac behaviour)."""
import sys

import pytest


def pytest_collection_modifyitems(config, items):
    if sys.platform == "darwin":
        return
    skip = pytest.mark.skip(reason="macOS provider tests run on a Mac")
    for item in items:
        if "tests/macos/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
