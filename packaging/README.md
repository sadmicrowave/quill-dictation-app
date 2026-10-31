# Quill — Packaging

Build on the platform you are targeting (PyInstaller does not cross-compile).
Neither spec has been build-tested yet; see the To Do's Phase 10 checklist.

    pip install -r requirements.txt

## macOS (.app)

    pyinstaller packaging/quill_mac.spec
    # Output: dist/Quill.app  — drag to /Applications

The first time Quill drives Excel, macOS asks to allow Automation access to
Microsoft Excel. Choose OK (System Settings > Privacy & Security > Automation).
The first time it listens, macOS asks for microphone access. `tools/build_mac.sh` signs the app with a
requirement that names only its identifier (`com.quill.app`), so that choice is remembered across rebuilds;
without that step every rebuild looks like a new app and asks again. (The first run after this change asks
once more, because the earlier permission was tied to an older build.)

## Windows (.exe)

    pyinstaller packaging\quill_win.spec
    # Output: dist\Quill.exe

## Vosk speech model

The model is **not bundled** (it is ~40 MB). On first launch Quill offers a
"Download speech model" button and stores the model in the per-user data
folder. To bundle one instead, unpack it to:

    quill/model/vosk-model-small-en-us-0.15/

and add `("quill/model", "quill/model")` to `datas` in the spec. The model
directory is git-ignored (see .gitignore).
