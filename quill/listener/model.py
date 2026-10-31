"""Locate and download the Vosk speech model.

The model is large, so it is kept out of git. :func:`find_model` looks in the
places a packaged or source install would put it; :func:`download_model`
fetches the small English model on first run.
"""

from __future__ import annotations
import pathlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from typing import Callable

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

ProgressCallback = Callable[[int, int], None]
"""Called with ``(bytes_done, bytes_total)``; total is 0 when unknown."""


def is_model_dir(path: pathlib.Path) -> bool:
    """True if *path* looks like an unpacked Vosk model (has ``am`` and ``conf``)."""
    return (path / "am").is_dir() and (path / "conf").is_dir()


def bundled_archive(search_dirs: list[pathlib.Path] | None = None) -> pathlib.Path | None:
    """The speech-model zip that ships with Quill (``quill/model/<name>.zip``), if present."""
    bases = search_dirs if search_dirs is not None else default_search_dirs()[:-1]   # not the user folder
    for base in bases:
        archive = base / f"{MODEL_NAME}.zip"
        if archive.is_file():
            return archive
    return None


def unpack_bundled(dest_dir: pathlib.Path | None = None,
                   archive: pathlib.Path | None = None) -> pathlib.Path | None:
    """Unpack the bundled zip into *dest_dir* (default: the user's model folder).

    Returns:
        The unpacked model folder, or None if there is no bundled archive.

    Raises:
        RuntimeError: if the archive is unsafe or holds no model.
    """
    archive = archive or bundled_archive()
    if archive is None:
        return None
    dest = dest_dir or user_model_dir()
    dest.mkdir(parents=True, exist_ok=True)
    _safe_extract(archive, dest)
    model = find_model(search_dirs=[dest])
    if model is None:
        raise RuntimeError("The bundled archive did not contain a Vosk model.")
    return model


def ensure_model(configured: str | pathlib.Path | None = None) -> pathlib.Path | None:
    """Find a usable model, unpacking the bundled zip on first launch if needed.

    The repository keeps the model compressed (about 41 MB instead of 68 MB);
    the first launch unpacks it once into the per-user data folder.
    """
    found = find_model(configured)
    if found is not None:
        return found
    try:
        return unpack_bundled()
    except (RuntimeError, OSError):
        return None


def user_model_dir() -> pathlib.Path:
    """Per-user folder where a downloaded model is stored."""
    try:
        from platformdirs import user_data_dir
        return pathlib.Path(user_data_dir("Quill", appauthor=False)) / "model"
    except ImportError:
        return pathlib.Path.home() / ".quill" / "model"


def default_search_dirs() -> list[pathlib.Path]:
    """Folders searched for a model, most specific first.

    Order: the PyInstaller bundle (when frozen), the source tree's
    ``quill/model``, then the per-user data folder.
    """
    dirs: list[pathlib.Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        dirs.append(pathlib.Path(bundle) / "quill" / "model")
    dirs.append(pathlib.Path(__file__).resolve().parent.parent / "model")
    dirs.append(user_model_dir())
    return dirs


def find_model(
    configured: str | pathlib.Path | None = None,
    search_dirs: list[pathlib.Path] | None = None,
) -> pathlib.Path | None:
    """Return the first usable Vosk model folder, or None.

    Args:
        configured: A path from the user's settings. Used first; may be the
            model folder itself or a folder containing one.
        search_dirs: Override the default search folders (tests).
    """
    candidates = [pathlib.Path(configured)] if configured else []
    candidates += search_dirs if search_dirs is not None else default_search_dirs()
    for base in candidates:
        if not base.is_dir():
            continue
        if is_model_dir(base):
            return base
        for child in sorted(base.iterdir()):
            if child.is_dir() and is_model_dir(child):
                return child
    return None


def download_model(
    dest_dir: pathlib.Path,
    url: str = MODEL_URL,
    progress: ProgressCallback | None = None,
) -> pathlib.Path:
    """Download and unpack a model zip into *dest_dir*.

    Args:
        dest_dir: Folder to unpack into (created if needed).
        url: Zip location (``https://`` or, for tests, ``file://``).
        progress: Optional progress callback.

    Returns:
        The unpacked model folder.

    Raises:
        RuntimeError: if the archive is unsafe or contains no model.
        OSError / urllib.error.URLError: on network or disk failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = pathlib.Path(tmp) / "model.zip"
        with urllib.request.urlopen(url) as response, archive.open("wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        _safe_extract(archive, dest_dir)
    model = find_model(search_dirs=[dest_dir])
    if model is None:
        raise RuntimeError("The downloaded archive did not contain a Vosk model.")
    return model


def _safe_extract(archive: pathlib.Path, dest_dir: pathlib.Path) -> None:
    """Extract a zip, refusing members that would escape *dest_dir* (zip-slip)."""
    root = dest_dir.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (root / member.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"Unsafe path in model archive: {member.filename}")
        zf.extractall(root)
    shutil.rmtree(root / "__MACOSX", ignore_errors=True)
