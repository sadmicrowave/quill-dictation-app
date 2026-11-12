#!/bin/bash
# Mac side: copy the working tree (what is on disk now, committed or not) into the folder the Windows VM shares.
#
#   tools/windows-vm/sync-to-share.sh                 # to ~/Developer/QuillShare
#   tools/windows-vm/sync-to-share.sh /some/folder    # to another shared folder
#
# Makes  <share>/src  (the code, without .git, virtual environments or build output) and <share>/out (where the VM puts what it builds).
# The repository itself is never shared: the VM only sees this copy.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
share="${1:-$HOME/Developer/QuillShare}"
mkdir -p "$share/src" "$share/out"

rsync -a --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc' \
  --exclude 'dist/' --exclude 'build/' --exclude '.DS_Store' --exclude '/quill/model/*/' --exclude '/docs/test-runs/' \
  "$repo/" "$share/src/"

commit="$(git -C "$repo" rev-parse --short HEAD)"
branch="$(git -C "$repo" branch --show-current)"
changes=""
[ -n "$(git -C "$repo" status --porcelain)" ] && changes=" + local changes"
echo "BUILD = \"${commit}${changes} on ${branch} (shared folder)\"" > "$share/src/quill/_build.py"   # what About and the self-check report

echo "Synced $repo"
echo "    to $share/src  (${commit}${changes} on ${branch})"
echo "In the VM: run  Run Quill from source.bat  or  Build Quill exe.bat  from  \\\\vmware-host\\Shared Folders\\$(basename "$share")\\src\\tools\\windows-vm"
