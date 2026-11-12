@echo off
REM Build Quill.exe from the code synced from the Mac and put it in the share (see sync-to-share.sh).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-QuillExe.ps1" -Start
pause
