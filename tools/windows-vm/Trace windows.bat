@echo off
REM Run Quill from the synced source and write a list of every window that appears (kind, size, time) to the share's out folder.
REM Open Settings once (or do whatever flickers), quit Quill, then look at out\windows-trace.txt on the Mac.
set "QUILL_TRACE_WINDOWS=%~dp0..\..\..\out\windows-trace.txt"
call "%~dp0Run Quill from source.bat"
