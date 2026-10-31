# -*- mode: python ; coding: utf-8 -*-
# macOS .app bundle — run: pyinstaller packaging/quill_mac.spec  (from repo root)
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
           (r("quill", "model"), "quill/model"), (r("quill", "assets"), "quill/assets"), (r("quill", "help"), "quill/help"),*vosk_d,*sd_d],
    hiddenimports=[*vosk_h, *sd_h, *collect_submodules("quill"), *collect_submodules("xlwings"), "appscript", "aem", "mactypes", "psutil", "AppKit", "objc"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Quill", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Quill")
app = BUNDLE(coll, name="Quill.app", icon=r("quill", "assets", "Quill.icns"), bundle_identifier="com.quill.app",
    info_plist={"CFBundleShortVersionString":"0.1.0",
        # no LSUIElement: Quill shows in the Dock and the menu bar; Settings has "Hide the Dock Icon"
        "NSMicrophoneUsageDescription":"Quill needs the microphone to hear your voice.",
        "NSAppleEventsUsageDescription":"Quill needs to control Excel to read your lists and fill in your rows."})
