#!/bin/sh
# Gets the machine ready for the on-screen journeys (docs/onscreen-journeys.md), so a test run starts from a known state.
#
#   sh tools/onscreen_setup.sh            build the app if it is out of date, then start Quill in demo mode and open the sample
#                                         workbook once in Numbers
#   sh tools/onscreen_setup.sh status     say what is open now (Quill, and each document Numbers has: there must be one)
#   sh tools/onscreen_setup.sh stop       quit the Quill this script started
#
# Demo mode keeps its settings in a throw-away folder, so a run never changes your own words, themes or layouts. The sample
# workbook has a third, empty sheet called Blank (QUILL_DEMO_BLANK_SHEET) for the "sheet with no columns" journey.
# It never closes a Numbers document or quits Numbers: close what is left from an earlier run yourself (or the run's own step does).
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP="$ROOT/dist/Quill.app"
DIR="${QUILL_ONSCREEN_DIR:-${TMPDIR:-/tmp}/quill-onscreen}"
BOOK="$DIR/Demo Inventory.xlsx"

# Numbers: the newer app first (a Mac can still have the classic one installed: asking for "Numbers" by name could start that one).
numbers_bundle() {
  for id in com.apple.Numbers com.apple.iWork.Numbers; do
    if [ -n "$(mdfind "kMDItemCFBundleIdentifier == '$id'" 2>/dev/null)" ]; then echo "$id"; return; fi
  done
}

numbers_documents() {
  id="$(numbers_bundle)"
  [ -n "$id" ] || { echo "(Numbers is not installed)"; return; }
  osascript -l JavaScript -e "const a = Application('$id'); a.running() ? a.documents().map(d => d.name()).join('\\n') : '(Numbers is not running)'"
}

case "${1:-start}" in
  status)
    if pgrep -f "$APP/Contents/MacOS/Quill" >/dev/null; then echo "Quill: running ($APP)"; else echo "Quill: not running"; fi
    echo "Sample workbook: $BOOK $( [ -f "$BOOK" ] && echo '(exists)' || echo '(missing)')"
    echo "Numbers documents:"; numbers_documents | sed 's/^/  /'
    exit 0 ;;
  stop)
    pkill -f "$APP/Contents/MacOS/Quill" 2>/dev/null || true
    echo "Quill stopped."; exit 0 ;;
esac

# 1. The app must be built from the code as it is now.
if [ ! -d "$APP" ] || [ -n "$(find quill main.py packaging -newer "$APP" -type f \( -name '*.py' -o -name '*.spec' \) 2>/dev/null | head -1)" ]; then
  echo "Building the app (the code is newer than dist/Quill.app)..."
  if [ -x "$ROOT/.venv/bin/python" ]; then PATH="$ROOT/.venv/bin:$PATH"; export PATH; fi
  command -v python >/dev/null 2>&1 || { echo "python is not on the path: activate the virtual environment first"; exit 1; }
  sh tools/build_mac.sh
else
  echo "dist/Quill.app is up to date."
fi
codesign --verify --deep "$APP"

# 2. A clean start: no earlier Quill, no earlier sample workbook.
pkill -f "$APP/Contents/MacOS/Quill" 2>/dev/null || true
sleep 1
rm -rf "$DIR"
mkdir -p "$DIR"

# 3. Quill in demo mode (the Demo menu feeds text through the same path a spoken phrase takes).
open -n --env QUILL_DEMO=1 --env QUILL_DEMO_DIR="$DIR" --env QUILL_DEMO_BLANK_SHEET=1 "$APP"
i=0
while [ ! -f "$BOOK" ] && [ "$i" -lt 40 ]; do sleep 0.5; i=$((i + 1)); done
[ -f "$BOOK" ] || { echo "Quill did not write the sample workbook: is it running?"; exit 1; }

# 4. The workbook, once, in Numbers.
BUNDLE="$(numbers_bundle)"
if [ -n "$BUNDLE" ]; then open -g -b "$BUNDLE" "$BOOK"; else open -g "$BOOK"; fi
sleep 6

echo
echo "Ready. Sample workbook: $BOOK"
echo "Numbers documents now:"
numbers_documents | sed 's/^/  /'
echo "Next: follow docs/onscreen-journeys.md (S1 to S8) and write the report."
