# -*- mode: python ; coding: utf-8 -*-
# macOS .app bundle — run: pyinstaller packaging/quill_mac.spec  (from repo root)
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
    hiddenimports=[*vosk_h, *sd_h, *extra_h, *collect_submodules("quill"), "quill.platforms.macos", *collect_submodules("xlwings"), "appscript", "aem", "mactypes", "psutil", "AppKit", "objc", "defusedxml"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Quill", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Quill")
import re
VERSION = re.search(r'__version__ = "([^"]+)"', open(r("quill", "__init__.py")).read()).group(1)     # (one place to bump it)
FILES = "Quill reads and writes the spreadsheets you choose, so it can fill in your rows."
app = BUNDLE(coll, name="Quill.app", icon=r("quill", "assets", "Quill.icns"), bundle_identifier="com.quill.app",
    info_plist={"CFBundleShortVersionString": VERSION, "CFBundleVersion": VERSION,
        "CFBundleDisplayName": "Quill", "CFBundleName": "Quill", "CFBundleDevelopmentRegion": "en",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "Copyright (c) 2026 Corey Farmer",
        # 26.0: the PySide6 6.12 libraries inside are built for macOS 26 (Qt itself needs 14.4). Lower it only after a tester on an
        # older macOS confirms the app runs there (possibly with an older PySide6 pinned).
        "LSMinimumSystemVersion": "26.0",
        # no LSUIElement: Quill shows in the Dock and the menu bar; Settings has "Hide the Dock Icon"
        "NSMicrophoneUsageDescription": "Quill needs the microphone to hear your voice.",
        "NSAppleEventsUsageDescription": "Quill needs to control your spreadsheet program to read your lists and fill in your rows.",
        # the words macOS shows when a spreadsheet lives in one of these places (without them it shows a generic sentence)
        "NSDocumentsFolderUsageDescription": FILES, "NSDesktopFolderUsageDescription": FILES,
        "NSDownloadsFolderUsageDescription": FILES, "NSRemovableVolumesUsageDescription": FILES,
        "NSNetworkVolumesUsageDescription": FILES})
