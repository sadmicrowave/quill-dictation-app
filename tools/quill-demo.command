#!/bin/sh
# Double-click to open Quill in demo mode (a sample workbook and a Demo menu that fills the screens with data).
# Uses dist/Quill.app in this repository.
cd "$(dirname "$0")/.." || exit 1
pkill -x Quill 2>/dev/null
sleep 1
open -n dist/Quill.app --args --demo
