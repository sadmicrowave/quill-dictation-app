# -*- mode: python ; coding: utf-8 -*-
# Windows one-file .exe — run: pyinstaller packaging\quill_win.spec  (from repo root)
from PyInstaller.utils.hooks import collect_all, collect_submodules
vosk_d, vosk_b, vosk_h = collect_all("vosk")
sd_d, sd_b, sd_h = collect_all("sounddevice")

a = Analysis(
    ["main.py"], pathex=["."],
    binaries=[*vosk_b, *sd_b],
    datas=[("quill/config/defaults.json","quill/config"),("quill/sounds","quill/sounds"),*vosk_d,*sd_d],
    hiddenimports=[*vosk_h, *sd_h, *collect_submodules("quill"), "xlwings","win32com.client","pyttsx3.drivers.sapi5"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Quill", console=False, icon=None)
