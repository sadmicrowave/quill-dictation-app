# Quill — Packaging

Build on the platform you are targeting (PyInstaller does not cross-compile).
Both specs build in CI (the release workflow).

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

## Windows (installer and portable folder)

    pyinstaller packaging\quill_win.spec
    # Output: the folder dist\Quill (Quill.exe and its _internal folder). Not one self-extracting file: that unpacked itself to a
    # temporary folder on every start (slow, and antivirus dislikes it).
    ISCC /DAppVersion=0.1.0 packaging\quill_win.iss
    # Output: dist\installer\Quill-Setup.exe  (Inno Setup 6.3 or newer: choco install innosetup)

`Quill-Setup.exe` installs for the current user only (no administrator rights) into `%LOCALAPPDATA%\Programs\Quill`, with a Start menu
entry, an optional desktop shortcut, an entry in Settings > Apps and an uninstaller. Running a newer one over an older Quill replaces it
(same `AppId`: never change it) and closes a running Quill first. An uninstall leaves the user's settings and speech model (their own
data folder). The portable zip (`Quill-windows.zip`) is the same folder: unzip it and run `Quill\Quill.exe`.

The dev-build and release workflows build both, install the installer silently on the runner, run the *installed* `Quill.exe --selftest`,
uninstall it and check nothing is left.

## Vosk speech model

The model is **not bundled** (it is ~40 MB). On first launch Quill offers a
"Download speech model" button and stores the model in the per-user data
folder. To bundle one instead, unpack it to:

    quill/model/vosk-model-small-en-us-0.15/

and add `("quill/model", "quill/model")` to `datas` in the spec. The model
directory is git-ignored (see .gitignore).

## Minimum macOS

The app declares macOS 26.0 (`LSMinimumSystemVersion` in `quill_mac.spec`): the PySide6 6.12 libraries it bundles are built for
macOS 26, while Qt itself needs only 14.4. To support older systems, pin an older PySide6 (6.8 to 6.10), run the full tests, look at
every screen, have a tester on that macOS confirm it, and only then lower the number (and the site's download page, which says it).

## Releasing

    # bump __version__ in quill/__init__.py, merge to main, then:
    git tag v0.1.0 && git push origin v0.1.0

The `release` workflow (`.github/workflows/release.yml`) builds Windows, macOS Apple Silicon and macOS Intel on GitHub's
machines and attaches `Quill-Setup.exe`, `Quill-windows.zip`, `Quill-mac-apple-silicon.dmg`, `Quill-mac-intel.dmg` and `SHA256SUMS.txt` to a
**draft** release. Nothing is public until you read the notes and press *Publish release*. (The tag must equal `__version__`.)
The site's download buttons and the app's update check read the newest published, non-pre-release release.

## First run of an unsigned download

The downloads are not signed with a paid Apple or Windows certificate, so each system warns once:

* **macOS:** "Apple could not verify Quill is free of malware". Choose *Done*, open System Settings > Privacy & Security,
  scroll down and press *Open Anyway* (on macOS before 15, right-click the app and choose *Open*). Then allow the microphone,
  and Automation for the spreadsheet program, when asked. Pick the build for the chip (Apple menu > About This Mac).
* **Windows:** SmartScreen shows "Windows protected your PC". Choose *More info*, then *Run anyway*.

The same words are on the site's download page and in the release notes. Signing (an Apple Developer ID with notarization,
and a Windows code-signing certificate) removes these warnings; it is not set up yet.
