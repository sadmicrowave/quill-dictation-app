# -*- mode: python ; coding: utf-8 -*-
# macOS .app bundle — run: pyinstaller packaging/quill_mac.spec  (from repo root)
from PyInstaller.utils.hooks import collect_all, collect_submodules
vosk_d, vosk_b, vosk_h = collect_all("vosk")
sd_d, sd_b, sd_h = collect_all("sounddevice")

a = Analysis(
    ["main.py"], pathex=["."],
    binaries=[*vosk_b, *sd_b],
    datas=[("quill/config/defaults.json","quill/config"),("quill/sounds","quill/sounds"),("quill/model","quill/model"),("quill/assets","quill/assets"),*vosk_d,*sd_d],
    hiddenimports=[*vosk_h, *sd_h, *collect_submodules("quill"), "xlwings", "AppKit", "objc"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Quill", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Quill")
app = BUNDLE(coll, name="Quill.app", icon="quill/assets/Quill.icns", bundle_identifier="com.quill.app",
    info_plist={"CFBundleShortVersionString":"0.1.0",
        # no LSUIElement: Quill shows in the Dock and the menu bar; Settings has "Hide the Dock Icon"
        "NSMicrophoneUsageDescription":"Quill needs the microphone to hear your voice.",
        "NSAppleEventsUsageDescription":"Quill needs to control Excel to read your lists and fill in your rows."})
