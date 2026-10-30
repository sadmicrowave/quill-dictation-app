# Quill — Packaging

## macOS (.app)

    pip install pyinstaller
    pyinstaller packaging/quill_mac.spec
    # Output: dist/Quill.app  — drag to /Applications

## Windows (.exe)

    pip install pyinstaller
    pyinstaller packaging\quill_win.spec
    # Output: dist\Quill.exe

## Vosk model

Place a downloaded model folder at:

    quill/model/vosk-model-small-en-us-0.15/

Download from https://alphacephei.com/vosk/models
The model directory is git-ignored (see .gitignore).
