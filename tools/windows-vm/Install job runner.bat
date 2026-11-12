@echo off
REM Make the VM start the job runner at every sign-in (and start it now): from then on the Mac can run tests here without anyone touching the VM.
REM It needs the Python environment that "Run Quill from source.bat" makes in C:\QuillTest, so run that once first.
set "PY=C:\QuillTest\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Run "Run Quill from source.bat" once first: it makes the Python environment ^(%PY%^).
  pause
  exit /b 1
)
"%PY%" "%~dp0jobrunner.py" --install "%~dp0..\..\.."
echo.
echo The job runner is installed and running. On the Mac:  python tools/windows-vm/send_job.py ping
pause
