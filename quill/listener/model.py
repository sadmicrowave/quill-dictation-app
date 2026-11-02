"""Locate and download the Vosk speech model.

The model is large, so it is kept out of git. :func:`find_model` looks in the
places a packaged or source install would put it; :func:`download_model`
fetches the small English model on first run.
"""

from __future__ import annotations
import hashlib
import pathlib
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Callable

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

#: SHA-256 of the official model archive. A download that does not match is rejected, so a tampered
#: or truncated file (or a hijacked connection) is never unpacked.
MODEL_SHA256 = "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498"


@dataclass(frozen=True)
class ModelSpec:
    """One speech model Quill can use: where it comes from and how to tell it is the right file."""

    key: str
    name: str            # the folder the archive unpacks to
    url: str
    sha256: str
    label: str
    size_mb: int


STANDARD = ModelSpec("standard", MODEL_NAME, MODEL_URL, MODEL_SHA256, "Standard", 40)

#: A larger English model (about 130 MB to download, 214 MB unpacked): the same streaming recogniser with a
#: richer graph, so it mishears less. Its checksum is that of the official archive as downloaded on 1 Nov 2026.
BETTER = ModelSpec(
    "better", "vosk-model-en-us-0.22-lgraph",
    "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
    "d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334", "Better", 130)

SPECS = {spec.key: spec for spec in (STANDARD, BETTER)}

#: The Whisper ``base.en`` model (CTranslate2 conversion, about 145 MB) that re-reads each phrase: ``(file, sha256)``.
#: The checksums are those of the files as downloaded on 1 Nov 2026.
WHISPER_NAME = "faster-whisper-base.en"
WHISPER_BASE_URL = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/main/"
WHISPER_FILES = (
    ("config.json", "f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb"),
    ("model.bin", "2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef"),
    ("tokenizer.json", "929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df"),
    ("vocabulary.txt", "ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf"),
)
WHISPER_SIZE_MB = 145

#: Safety limits when unpacking an archive (a "zip bomb" could otherwise fill the disk).
MAX_UNPACKED_BYTES = 600 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5_000

#: Seconds to wait for the network before giving up.
DOWNLOAD_TIMEOUT_S = 30

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


def find_spec_model(spec: ModelSpec, search_dirs: list[pathlib.Path] | None = None) -> pathlib.Path | None:
    """The unpacked folder of *spec*'s model, if it is installed in one of the search folders."""
    for base in search_dirs if search_dirs is not None else default_search_dirs():
        for candidate in (base / spec.name, base):
            if candidate.name == spec.name and is_model_dir(candidate):
                return candidate
    return None


def download_spec(dest_dir: pathlib.Path, progress: ProgressCallback | None = None,
                  spec: ModelSpec = STANDARD) -> pathlib.Path:
    """Download *spec*'s model into *dest_dir* (https only, checksum checked) and return its folder."""
    download_model(dest_dir, spec.url, progress, spec.sha256)
    found = find_spec_model(spec, [dest_dir])
    if found is None:
        raise RuntimeError("The downloaded archive did not contain the expected speech model.")
    return found


def find_whisper_model(search_dirs: list[pathlib.Path] | None = None) -> pathlib.Path | None:
    """The folder of the Whisper model, if every one of its files is there."""
    for base in search_dirs if search_dirs is not None else [user_model_dir()]:
        folder = base / WHISPER_NAME
        if all((folder / name).is_file() for name, _ in WHISPER_FILES):
            return folder
    return None


def download_whisper(dest_dir: pathlib.Path, progress: ProgressCallback | None = None,
                     base_url: str = WHISPER_BASE_URL, files=WHISPER_FILES) -> pathlib.Path:
    """Download the Whisper model's files into ``dest_dir/<name>`` (https only, each file's checksum checked).

    The files are fetched into a scratch folder first and moved into place together, so an interrupted download
    never leaves a half-installed model that looks complete.
    """
    if urllib.parse.urlparse(base_url).scheme != "https":
        raise RuntimeError("The speech model must be downloaded over https.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / WHISPER_NAME
    with tempfile.TemporaryDirectory(dir=dest_dir) as tmp:
        scratch = pathlib.Path(tmp) / WHISPER_NAME
        scratch.mkdir()
        sizes = {}
        done_before = 0
        for name, sha in files:
            digest = hashlib.sha256()
            with urllib.request.urlopen(base_url + name, timeout=DOWNLOAD_TIMEOUT_S) as response, (scratch / name).open("wb") as out:  # noqa: S310  # nosec B310
                total = int(response.headers.get("Content-Length") or 0)
                sizes[name] = total
                done = 0
                while chunk := response.read(1 << 16):
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress:
                        progress(min(done_before + done, WHISPER_SIZE_MB * 1024 * 1024), WHISPER_SIZE_MB * 1024 * 1024)
            if digest.hexdigest() != sha:
                raise RuntimeError(f"The downloaded file {name} is not the expected one (checksum mismatch).")
            done_before += done
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(scratch), str(target))
    return target


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
    expected_sha256: str | None = None,
    allow_local_file: bool = False,
) -> pathlib.Path:
    """Download and unpack a model zip into *dest_dir*.

    Args:
        dest_dir: Folder to unpack into (created if needed).
        url: Zip location. Only ``https://`` is accepted (``file://`` too when *allow_local_file* is set, for tests).
        progress: Optional progress callback.
        expected_sha256: Checksum the archive must have. Defaults to :data:`MODEL_SHA256` for the official
            URL and to no check for any other URL.
        allow_local_file: Accept a ``file://`` URL (tests only).

    Returns:
        The unpacked model folder.

    Raises:
        RuntimeError: if the address is not allowed, the checksum is wrong, the archive is unsafe or it
            contains no model.
        OSError / urllib.error.URLError: on network or disk failure.
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme != "https" and not (allow_local_file and scheme == "file"):
        raise RuntimeError(f"The model must be downloaded over https, not '{scheme or 'a bare path'}'.")
    if expected_sha256 is None and url == MODEL_URL:
        expected_sha256 = MODEL_SHA256
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        archive = pathlib.Path(tmp) / "model.zip"
        digest = hashlib.sha256()
        # (the scheme was checked above: only https, or file:// when a test allows it)
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_S) as response, archive.open("wb") as out:  # noqa: S310  # nosec B310
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if expected_sha256 and digest.hexdigest() != expected_sha256.lower():
            raise RuntimeError("The downloaded speech model is not the expected file (checksum mismatch).")
        _safe_extract(archive, dest_dir)
    model = find_model(search_dirs=[dest_dir])
    if model is None:
        raise RuntimeError("The downloaded archive did not contain a Vosk model.")
    return model


def _safe_extract(archive: pathlib.Path, dest_dir: pathlib.Path) -> None:
    """Extract a zip, refusing members that would escape *dest_dir* (zip-slip)."""
    root = dest_dir.resolve()
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS or sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
            raise RuntimeError("The model archive is larger than a speech model should be.")
        for member in members:
            target = (root / member.filename).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"Unsafe path in model archive: {member.filename}")
        zf.extractall(root)
    shutil.rmtree(root / "__MACOSX", ignore_errors=True)
