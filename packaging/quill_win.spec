# -*- mode: python ; coding: utf-8 -*-
# Windows one-file .exe — run: pyinstaller packaging\quill_win.spec  (from repo root)
from PyInstaller.utils.hooks import collect_all
vosk_d, vosk_b, vosk_h = collect_all("vosk")
sd_d, sd_b, sd_h = collect_all("sounddevice")

a = Analysis(
    ["main.py"], pathex=["."],
    binaries=[*vosk_b, *sd_b],
    datas=[("quill/model","quill/model"),("quill/config/defaults.json","quill/config"),*vosk_d,*sd_d],
    hiddenimports=[*vosk_h,*sd_h,
        "quill.bridge.win_bridge","quill.parser.vocab","quill.parser.phrase_parser",
        "quill.parser.commands","quill.config.settings","quill.speaker.speaker",
        "quill.listener.listener","quill.ui.main_window","quill.ui.tray","quill.ui.settings_dialog",
        "pyttsx3.drivers.sapi5","win32com.client"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="Quill", console=False, icon=None)
