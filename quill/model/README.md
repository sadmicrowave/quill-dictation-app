# Speech model

`vosk-model-small-en-us-0.15.zip` (about 41 MB) is the small US-English speech recognition model from the
[Vosk](https://alphacephei.com/vosk/models) project (Alpha Cephei, Apache License 2.0; see the `README`
inside the archive). It is kept compressed in the repository (68 MB unpacked) and is unpacked **once, on
first launch**, into Quill's per-user data folder (`platformdirs.user_data_dir("Quill")/model`), so Quill
works with no download. `quill/listener/model.py` does this (`ensure_model`).

An unpacked copy placed next to the zip is used too (and ignored by git). To use a different model
(another language or a larger, more accurate one), set `model_path` in the settings file; the
**Download speech model** button in the window remains as a fallback.
