# -*- mode: python ; coding: utf-8 -*-
# macOS .app bundle — run: pyinstaller packaging/quill_mac.spec  (from repo root)
from PyInstaller.utils.hooks import collect_all
vosk_d, vosk_b, vosk_h = collect_all("vosk")
sd_d, sd_b, sd_h = collect_all("sounddevice")

a = Analysis(
    ["main.py"], pathex=["."],
    binaries=[*vosk_b, *sd_b],
    datas=[("quill/model","quill/model"),("quill/config/defaults.json","quill/config"),*vosk_d,*sd_d],
    hiddenimports=[*vosk_h,*sd_h,
        "quill.bridge.mac_bridge","quill.parser.vocab","quill.parser.phrase_parser",
        "quill.parser.commands","quill.config.settings","quill.speaker.speaker",
        "quill.listener.listener","quill.ui.main_window","quill.ui.tray","quill.ui.settings_dialog"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Quill", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Quill")
app = BUNDLE(coll, name="Quill.app", icon=None, bundle_identifier="com.quill.app",
    info_plist={"CFBundleShortVersionString":"0.1.0","LSUIElement":True,
        "NSMicrophoneUsageDescription":"Quill needs the microphone to hear your voice."})
