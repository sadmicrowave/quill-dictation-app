"""A log file for a packaged app that nobody runs from a terminal.

A double-clicked app has no console, so anything printed or any traceback would
vanish. :func:`setup_logging` writes the app's log lines and any uncaught error
(on the main thread or a background one) to ``quill.log`` in the per-user log
folder, which Settings can open.

Every line of the log carries a label right after its level: ``SYS`` or ``USR``. A ``SYS`` line is written only with
fixed wording and safe facts (counts, program names, error kinds, code locations): it can be sent to the developer in a
support report. A ``USR`` line is anything else (file names, sheet names, spoken words, cell values, paths) and never
leaves this computer. A line is ``USR`` unless the code asked for ``SYS`` on purpose (the ``quill.sys`` logger or
``append_log(..., safe=...)``), so forgetting to label something can only keep it private. :func:`sys_lines` is the one
way the report reads the log back, and it reads only ``SYS`` lines.
"""

from __future__ import annotations
import logging
import logging.handlers
import os
import pathlib
import sys
import platform
import re
import threading
import traceback

LOG_NAME = "quill.log"
CRASH_NAME = "crash.flag"                    # written when the program fails; the next start offers a report
SYS_NAME = "quill.sys"                       # the logger whose lines are labelled SYS (everything else is USR)
_FORMAT = "%(asctime)s %(levelname)s %(tag)s %(message)s"
_SYS_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} [A-Z]+ SYS ")


def syslog() -> logging.Logger:
    """The logger for lines that are safe to send in a support report.

    Rules for what goes in: the message is a fixed string (never an f-string or a ``%s`` of text the user could have
    typed or said); arguments are numbers, names from a fixed list (a program, a setting, an error kind) or
    :func:`exc_kind` of an error. Never a file, sheet, column or program-window name, a path, a word or a cell value.
    """
    return logging.getLogger(SYS_NAME)


def exc_kind(exc: BaseException | None) -> str:
    """An error's class name (``PermissionError``) without its message, which often holds a path or a name."""
    return type(exc).__name__ if exc is not None else "none"


def safe_trace(exc_type, tb) -> list[str]:
    """A traceback as code locations only (``quill/app.py:120 in _check``): no messages, values or source lines.

    Frames inside Quill show their path from the ``quill`` folder; frames in other packages show the last two parts of
    the path, so a user's folder names never appear.
    """
    lines = [exc_type.__name__ if exc_type is not None else "error"]
    for frame in traceback.extract_tb(tb):
        parts = pathlib.PurePath(frame.filename).parts
        if "quill" in parts:
            where = "/".join(parts[len(parts) - 1 - parts[::-1].index("quill"):])
        else:
            where = "/".join(parts[-2:])
        lines.append(f"  at {where}:{frame.lineno} in {frame.name}")
    return lines


class _Formatter(logging.Formatter):
    """The log line with its SYS/USR label; a SYS error shows code locations only, a USR one the usual traceback."""

    def format(self, record: logging.LogRecord) -> str:
        record.tag = "SYS" if record.name == SYS_NAME else "USR"
        if record.tag == "SYS" and record.exc_info and record.exc_info[0] is not None:
            info, record.exc_info, record.exc_text = record.exc_info, None, None
            head = super().format(record)
            record.exc_info = info
            first = head.split(" SYS ", 1)[0] + " SYS "
            return "\n".join([head] + [first + line for line in safe_trace(info[0], info[2])])
        return super().format(record)


def mark_crash(folder: pathlib.Path | None = None) -> None:
    """Remember that the program failed, so the next start can offer to send a report."""
    try:
        ((folder or log_dir()) / CRASH_NAME).write_text("1", encoding="utf-8")
    except OSError:
        pass


def take_crash(folder: pathlib.Path | None = None) -> bool:
    """True once after a failure was marked (and forgets it)."""
    path = (folder or log_dir()) / CRASH_NAME
    try:
        found = path.exists()
        path.unlink(missing_ok=True)
        return found
    except OSError:
        return False


def sys_lines(folder: pathlib.Path | None = None, limit: int = 400) -> list[str]:
    """The last *limit* ``SYS`` lines of the log (oldest first), read across the rotated files.

    This is the only way a support report reads the log. A line with no label (written before labels existed, or by
    anything else) is ignored.
    """
    folder = folder or log_dir()
    lines: list[str] = []
    for name in [f"{LOG_NAME}.{n}" for n in (3, 2, 1)] + [LOG_NAME]:
        path = folder / name
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines += [line for line in text.splitlines() if _SYS_LINE.match(line)]
    return lines[-limit:]


def environment_facts() -> dict[str, str]:
    """Version and system facts for a support report: nothing personal."""
    from quill import __version__
    return {
        "Quill": __version__,
        "System": f"{platform.system()} {platform.release()}",
        "Computer": platform.machine(),
        "Python": platform.python_version(),
        "Packaged app": "yes" if getattr(sys, "frozen", False) else "no",
    }


def log_dir() -> pathlib.Path:
    """The per-user folder for Quill's log file (created if needed)."""
    try:
        from platformdirs import user_log_dir
        folder = pathlib.Path(user_log_dir("Quill", appauthor=False))
    except ImportError:
        folder = pathlib.Path.home() / ".quill" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def verbose_requested(flag: bool = False) -> bool:
    """True if detailed (debug) logging was asked for: ``--verbose`` or the ``QUILL_DEBUG`` environment variable."""
    return flag or os.environ.get("QUILL_DEBUG", "").lower() in ("1", "true", "yes", "on")


def setup_logging(folder: pathlib.Path | None = None, verbose: bool = False) -> pathlib.Path:
    """Send the ``quill`` logger and uncaught exceptions to a rotating log file.

    Safe to call more than once (it replaces its own handler rather than adding another).

    Args:
        folder: Where the log file goes (default: the per-user log folder).
        verbose: Also log debug detail (microphone on / off, background tasks, file and program detection) and
            copy the log to the terminal. The log stays on this computer and rotates at 500 KB (three
            backups); the window's own log lines, which can include the values of a saved row, go into it too.

    Returns:
        The log file's path.
    """
    folder = folder or log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    logger = logging.getLogger("quill")
    logger.setLevel(logging.DEBUG if verbose_requested(verbose) else logging.INFO)
    for handler in list(logger.handlers):
        if getattr(handler, "_quill_file", False):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=500_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(_Formatter(_FORMAT))
    handler._quill_file = True
    logger.addHandler(handler)
    if verbose_requested(verbose) and sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(_Formatter(_FORMAT))
        console._quill_file = True            # removed and replaced like the file handler on a second call
        logger.addHandler(console)

    def log_uncaught(exc_type, exc, tb) -> None:
        mark_crash(folder)
        logger.error("Uncaught error", exc_info=(exc_type, exc, tb))                  # USR: the full traceback stays here
        syslog().error("Uncaught error", exc_info=(exc_type, exc, tb))                # SYS: code locations only
        sys.__excepthook__(exc_type, exc, tb)

    def log_thread(args) -> None:
        logger.error("Uncaught error in thread %s", getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        syslog().error("Uncaught error in a background thread", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread
    logger.info("Quill started")
    from quill import __version__
    syslog().info("Quill started: version %s on %s %s (%s)", __version__, platform.system(), platform.release(), platform.machine())
    return path
