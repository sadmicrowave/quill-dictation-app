#!/bin/sh
# Build the macOS app:  sh tools/build_mac.sh        (run from the repository root, venv active)
# The result is dist/Quill.app. First build takes a few minutes; later ones reuse build/ and are quicker.
set -e
cd "$(dirname "$0")/.."
python tools/make_app_icon.py            # keep the icon files in step with the design
pyinstaller --noconfirm --distpath dist --workpath build packaging/quill_mac.spec
# Every build is signed ad hoc, which by default names the exact bytes of that build, so macOS treated each rebuild as
# a new app and asked for the microphone (and Automation) permission again. This signs the app with a requirement
# that names only its identifier, so a permission granted once survives rebuilds and updates.
codesign --force --sign - -r='designated => identifier "com.quill.app"' dist/Quill.app
codesign --verify --deep dist/Quill.app
echo "Built: $(pwd)/dist/Quill.app ($(du -sh dist/Quill.app | cut -f1))"
echo "Open it by double-clicking in Finder, not from a terminal, so you test what a user gets."
