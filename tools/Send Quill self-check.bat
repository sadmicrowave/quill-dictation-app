@echo off
rem Runs Quill's self-check and sends the report to the developer (an issue in a private repository).
rem The report holds versions, counts and yes/no answers: no file names, words, sheet names or device names.
start "" /wait "%~dp0Quill.exe" --selftest --send
