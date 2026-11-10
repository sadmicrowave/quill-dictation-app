# -*- mode: python ; coding: utf-8 -*-
# Windows one-file .exe — run: pyinstaller packaging\quill_win.spec  (from repo root)
import os
import sys
import re
from PyInstaller.utils.hooks import collect_all, collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
                                                 VSVersionInfo)

# PyInstaller resolves relative paths against the folder of this spec file, so anchor everything to the repo root.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
r = lambda *parts: os.path.join(ROOT, *parts)
sys.path.insert(0, ROOT)      # (collect_submodules imports quill: the system providers in quill.platforms are loaded by name at run time)
vosk_d, vosk_b, vosk_h = collect_all("vosk")
sd_d, sd_b, sd_h = collect_all("sounddevice")
# The optional "Best" speech model (Whisper through faster-whisper): bundled when its packages are installed.
extra_d, extra_b, extra_h = [], [], []
for package in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers"):
    try:
        d, b, h = collect_all(package)
        extra_d += d; extra_b += b; extra_h += h
    except Exception:
        pass

a = Analysis(
    [r("main.py")], pathex=[ROOT],
    binaries=[*vosk_b, *sd_b, *extra_b],
    datas=[(r("quill", "config", "defaults.json"), "quill/config"), (r("quill", "sounds"), "quill/sounds"),
           (r("quill", "model"), "quill/model"), (r("quill", "assets"), "quill/assets"), (r("quill", "help"), "quill/help"),*vosk_d,*sd_d,*extra_d],
    hiddenimports=[*vosk_h, *sd_h, *extra_h, *collect_submodules("quill"), "quill.platforms.windows", *collect_submodules("xlwings"), "win32com.client", "pyttsx3.drivers.sapi5", "defusedxml"],
)
# The version resource of Quill.exe: what the file's Properties > Details tab, SmartScreen and the task manager show.
VERSION = re.search(r'__version__ = "([^"]+)"', open(r("quill", "__init__.py")).read()).group(1)     # (one place to bump it)
numbers = (tuple(int(part) for part in VERSION.split(".") if part.isdigit()) + (0, 0, 0, 0))[:4]
version_file = os.path.join(SPECPATH, "..", "build", "quill_win_version.txt")
os.makedirs(os.path.dirname(version_file), exist_ok=True)
with open(version_file, "w", encoding="utf-8") as handle:
    handle.write(str(VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Corey Farmer"), StringStruct("FileDescription", "Quill: dictate into a spreadsheet by voice"),
            StringStruct("FileVersion", VERSION), StringStruct("InternalName", "Quill"), StringStruct("LegalCopyright", "Copyright (c) 2026 Corey Farmer"),
            StringStruct("OriginalFilename", "Quill.exe"), StringStruct("ProductName", "Quill"), StringStruct("ProductVersion", VERSION)])]),
            VarFileInfo([VarStruct("Translation", [0x409, 1200])])])))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Quill", console=False, icon=r("quill", "assets", "Quill.ico"), version=version_file)
