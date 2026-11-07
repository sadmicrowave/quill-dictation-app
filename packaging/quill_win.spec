# -*- mode: python ; coding: utf-8 -*-
# Windows one-file .exe — run: pyinstaller packaging\quill_win.spec  (from repo root)
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

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
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Quill", console=False, icon=r("quill", "assets", "Quill.ico"))
