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

## Every test

1. Start the VM from "clean" (or revert to it).
2. Run the script from `tools\windows-vm`:

   ```powershell
   .\Get-QuillDevBuild.ps1 -Start          # newest green dev build of develop, self-check, start it
   .\Get-QuillDevBuild.ps1 -Branch fix/windows-chrome -Start   # a branch (it needs a dev build first:
                                                               #   gh workflow run "dev build" --ref fix/windows-chrome)
   ```

3. Look at the window, try the things the change touched; **Win+Shift+S** takes a screenshot (it lands in the VM's Pictures folder; drag it to the Mac, or use a shared folder).
4. Revert to "clean" when done.

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
