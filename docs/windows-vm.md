# Testing Quill on a Windows virtual machine (on the Mac)

GitHub's Windows runner runs the test suite, but it has no screen, microphone or Excel. A Windows 11 virtual machine on the development Mac does: try the real window, the dev build, Excel, the microphone, and take screenshots, without the download-and-report loop.

**Why not WinBoat / Docker.** WinBoat and `dockur/windows` need Linux with KVM; Docker Desktop on a Mac has none, so Windows would run in software emulation, far too slow. A virtual machine is the direct way.

## What you need (you do these: they need your accounts)

| Piece | Where | Size (about) | Notes |
|---|---|---|---|
| **VMware Fusion** (free) | Broadcom's support portal (a free Broadcom account is needed to download) | 0.6 GB | Supports Intel Macs and macOS 26 as a host; has the virtual TPM Windows 11 asks for. UTM (free, `brew install --cask utm`) also works but has no graphical snapshots. |
| **Windows 11 Enterprise evaluation ISO** (x64) | <https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise> (register, then download) | 5 to 7 GB | 90 days, no product key. After 90 days the desktop goes black and the PC shuts down hourly: make a new VM (the steps below take about an hour). Choose *Windows 11 Enterprise*, English (United States), **64-bit ISO**. |

The Windows 10 evaluation is no longer offered (its page redirects to Windows 11), so Windows 10 stays untested unless an ISO is available some other way.

## Make the machine

1. Fusion: **File > New > Install from disc or image**, choose the ISO. It recognises Windows 11.
2. Settings before the first start (**Virtual Machine > Settings**):
   - **Processors & Memory**: 4 cores, 8 GB.
   - **Hard Disk**: 80 GB (it grows only as it fills).
   - **Display**: *Accelerate 3D Graphics* on.
   - **Sound Card**: on, and **Sound & Microphone > Microphone** = the Mac's microphone (the first start asks macOS for permission).
   - **Encryption**: Windows 11 needs a TPM; Fusion adds one only when the VM is encrypted: set a password and keep it.
3. Start; install Windows. When asked, sign in with a Microsoft account (the page says a local account is not offered during the evaluation).
4. Install **VMware Tools** (Fusion offers it; it gives the clipboard, shared folders and the right display size).
5. In the VM, open PowerShell once and run:

   ```powershell
   winget install --id GitHub.cli
   gh auth login        # GitHub.com, HTTPS, sign in with the browser
   ```

   Also copy `tools\windows-vm\Get-QuillDevBuild.ps1` into the VM (the Mac's shared folder, or `gh repo clone sadmicrowave/quill-dictation-app`).
6. Optional, for the Excel tests: install Excel (Microsoft 365 trial) or LibreOffice (`winget install TheDocumentFoundation.LibreOffice`).
7. **Shut down and take a snapshot called "clean"** (Virtual Machine > Snapshots).

## The shared folder (the everyday way)

A Windows program can only be built on Windows, so the Mac cannot drop a finished `Quill.exe` into a folder. What it can share is the **code**: the VM builds or runs it from there, with no commit, push, GitHub download or zip. Edit on the Mac, sync, run.

One-time setup:

1. On the Mac: `tools/windows-vm/sync-to-share.sh` (it makes `~/Developer/QuillShare/src` and `.../out`; the repository and its `.git` are never shared, only this copy).
2. Fusion, VM shut down or running: **Virtual Machine > Settings > Sharing**: tick **Enable Shared Folders**, **+**, choose `~/Developer/QuillShare`, **Read & Write**. (VMware Tools must be installed in Windows. macOS may ask to let Fusion see the folder.)
3. In the VM the folder is `\\vmware-host\Shared Folders\QuillShare` (Explorer > Network > vmware-host). Open `src\tools\windows-vm` there.
4. Install Python once: `winget install -e --id Python.Python.3.13`, then open a new PowerShell.

Every change:

| On the Mac | In the VM (double-click in `QuillShare\src\tools\windows-vm`) | You get |
|---|---|---|
| `tools/windows-vm/sync-to-share.sh` | **Run Quill from source.bat** | Quill running as plain Python, seconds after the sync (the first run makes the Python environment and installs the requirements; later runs only when `requirements.txt` changes). `-SelfTest` runs the self-check instead. |
| `tools/windows-vm/sync-to-share.sh` | **Build Quill exe.bat** | The packaged `Quill.exe`, built like the release (PyInstaller), self-checked and started. A copy and the report land in `QuillShare\out` (`~/Developer/QuillShare/out` on the Mac). |

- **From source** is the quick loop for layout and behaviour. **The built exe** is what finds packaging problems (a missing data file, a different startup path): build it before saying a change is done.
- The build is stamped *"<commit> + local changes on <branch> (shared folder)"*, so the self-check report shows exactly what was tried.
- The Python environment and the working copy live in `C:\QuillTest` inside the VM (running from the share is slow and Python's files do not belong there).
- To use another shared folder, give the Mac script its path and set `QUILL_SHARE` in the VM to the share's Windows path.

## The GitHub build (to check what CI makes)

The shared-folder build is built by you; the CI dev build is built the way the release will be. To try that one, run in the VM:

```powershell
.\Get-QuillDevBuild.ps1 -Start          # newest green dev build of develop, self-check, start it
.\Get-QuillDevBuild.ps1 -Branch fix/windows-chrome -Start   # a branch (it needs a dev build first:
                                                            #   gh workflow run "dev build" --ref fix/windows-chrome)
```

(It needs the one-time `winget install --id GitHub.cli` and `gh auth login`.)

## Every test

1. Start the VM from "clean" (or revert to it).
2. Sync from the Mac and double-click the .bat for what you want to try (above).
3. Look at the window, try the things the change touched; **Win+Shift+S** takes a screenshot (it lands in the VM's Pictures folder; save it into the shared `out` folder and it is on the Mac).
4. Revert to "clean" when done (the Python environment is rebuilt in a few minutes, or take the snapshot *after* the first successful run to keep it).

With the VM window open on the Mac, Claude can also look at it and drive it through computer use (an approval is asked for VMware Fusion).

## Running the tests inside the VM

CI already runs the whole suite on a Windows runner; a run in the VM adds only what needs a real desktop. In the VM: install Python 3.13 (`winget install Python.Python.3.13`), clone the repository, then

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m pytest -q
```

## Not covered

Windows 10 (no evaluation ISO), Windows on Arm (Quill needs `vosk`, which has no Arm64 wheel), a PC with a different display scale or language than the VM (change the VM's display scaling in Windows Settings to try 125 % and 150 %).
