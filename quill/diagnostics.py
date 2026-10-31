"""A log file for a packaged app that nobody runs from a terminal.

A double-clicked app has no console, so anything printed or any traceback would
vanish. :func:`setup_logging` writes the app's log lines and any uncaught error
(on the main thread or a background one) to ``quill.log`` in the per-user log
folder, which Settings can open.
"""

from __future__ import annotations
import logging
import logging.handlers
import pathlib
import sys
import threading

LOG_NAME = "quill.log"
_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def log_dir() -> pathlib.Path:
    """The per-user folder for Quill's log file (created if needed)."""
    try:
        from platformdirs import user_log_dir
        folder = pathlib.Path(user_log_dir("Quill", appauthor=False))
    except ImportError:
        folder = pathlib.Path.home() / ".quill" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def setup_logging(folder: pathlib.Path | None = None) -> pathlib.Path:
    """Send the ``quill`` logger and uncaught exceptions to a rotating log file.

    Safe to call more than once (it replaces its own handler rather than adding another).

    Returns:
        The log file's path.
    """
    folder = folder or log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    logger = logging.getLogger("quill")
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        if getattr(handler, "_quill_file", False):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=500_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler._quill_file = True
    logger.addHandler(handler)

    def log_uncaught(exc_type, exc, tb) -> None:
        logger.error("Uncaught error", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    def log_thread(args) -> None:
        logger.error("Uncaught error in thread %s", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread
    logger.info("Quill started")
    return path
