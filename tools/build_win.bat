@echo off
rem Build the Windows app:  tools\build_win.bat   (from the repository root, venv active)
rem The result is dist\Quill.exe.
cd /d "%~dp0\.."
python tools\make_app_icon.py
pyinstaller --noconfirm packaging\quill_win.spec
echo Built: %CD%\dist\Quill.exe
