@echo off
REM Run the Quill code synced from the Mac (see sync-to-share.sh). Add -SelfTest to run the self-check instead.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Run-QuillFromSource.ps1" %*
pause
