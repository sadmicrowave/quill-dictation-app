# -*- mode: python ; coding: utf-8 -*-
# Windows one-file .exe — run: pyinstaller packaging\quill_win.spec  (from repo root)
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# PyInstaller resolves relative paths against the folder of this spec file, so anchor everything to the repo root.
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
r = lambda *parts: os.path.join(ROOT, *parts)
vosk_d, vosk_b, vosk_h = collect_all("vosk")
sd_d, sd_b, sd_h = collect_all("sounddevice")

a = Analysis(
    [r("main.py")], pathex=[ROOT],
    binaries=[*vosk_b, *sd_b],
    datas=[(r("quill", "config", "defaults.json"), "quill/config"), (r("quill", "sounds"), "quill/sounds"),
           (r("quill", "model"), "quill/model"), (r("quill", "assets"), "quill/assets"),*vosk_d,*sd_d],
    hiddenimports=[*vosk_h, *sd_h, *collect_submodules("quill"), *collect_submodules("xlwings"), "win32com.client", "pyttsx3.drivers.sapi5"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Quill", console=False, icon=r("quill", "assets", "Quill.ico"))
