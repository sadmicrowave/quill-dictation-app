#!/bin/sh
# Build the macOS app:  sh tools/build_mac.sh        (run from the repository root, venv active)
# The result is dist/Quill.app. First build takes a few minutes; later ones reuse build/ and are quicker.
set -e
cd "$(dirname "$0")/.."
python tools/make_app_icon.py            # keep the icon files in step with the design
pyinstaller --noconfirm packaging/quill_mac.spec
echo "Built: $(pwd)/dist/Quill.app ($(du -sh dist/Quill.app | cut -f1))"
echo "Open it by double-clicking in Finder, not from a terminal, so you test what a user gets."
