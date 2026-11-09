"""The live link to LibreOffice Calc: a connection that stays open, so Quill is told what happens there.

The helper script (see :mod:`quill.bridge.libreoffice_mirror`) starts a small server inside the running LibreOffice.
This module is Quill's side: it reads where that server listens and the secret from Quill's own folder, connects
(this computer only), and keeps the connection open on a background thread. Then

* what is open and which sheet each document shows is always at hand (a look costs nothing, and nothing is started);
* LibreOffice *tells* Quill when a document opens, closes or moves to another sheet, so Quill follows at once instead of
  at the next timed look;
* saving and writing cells are requests on the same connection.

Nothing here raises: a connection that cannot be made or is lost just means "not live", and the caller uses the older
way (one script launch per question).
"""

from __future__ import annotations

import itertools
import json
import logging
import pathlib
import socket
import threading
from typing import Callable
import contextlib

log = logging.getLogger("quill.libreoffice")

#: Seconds to wait for LibreOffice to answer a request.
REQUEST_TIMEOUT_S = 8.0
#: Called with ``(kind, url, sheet)``: ``kind`` is ``opened``, ``closed``, ``sheet``, ``changed`` (edited, once it is quiet) or ``lost`` (the link dropped).
EventCallback = Callable[[str, str, str], None]


class LiveLink:
    """The open connection (or the lack of one) to the helper server inside LibreOffice.

    Args:
        base: Quill's job folder, where the server leaves its address and secret (``live.json``).
        on_event: Called on the reader thread for every event; keep it quick (the app hands it to the window's thread).
        connect: ``connect((host, port), timeout)`` returning a socket (tests).
    """

    def __init__(self, base: pathlib.Path, on_event: EventCallback | None = None,
                 connect: Callable | None = None) -> None:
        self.base = base
        self.on_event = on_event
        self._connect = connect or socket.create_connection
        self.docs: dict[str, dict] = {}
        self.version = 0
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._ids = itertools.count(1)
        self._waiting: dict[int, tuple[threading.Event, list]] = {}

    # ------------------------------------------------------------------ #

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> bool:
        """Open the connection if the server is there. False if it is not (the caller may start it and try again)."""
        if self.connected:
            return True
        try:
            info = json.loads((self.base / "live.json").read_text(encoding="utf-8"))
            sock = self._connect(("127.0.0.1", int(info["port"])), 3.0)
        except (OSError, ValueError, KeyError):
            return False
        try:
            sock.settimeout(5.0)
            reader = sock.makefile("r", encoding="utf-8", newline="\n")
            sock.sendall((json.dumps({"hello": info["token"]}) + "\n").encode("utf-8"))
            hello = json.loads(reader.readline() or "{}")
            if hello.get("hello") != "ok":
                sock.close()
                return False
            sock.settimeout(None)
        except (OSError, ValueError):
            with contextlib.suppress(OSError):
                sock.close()
            return False
        with self._lock:
            self._sock = sock
            self.version = int(hello.get("version", 0))
            self.docs = {d["url"]: d for d in hello.get("docs", []) if d.get("url")}
        threading.Thread(target=self._read, args=(sock, reader), name="quill-live-link", daemon=True).start()
        return True

    def close(self) -> None:
        """Hang up (the server keeps running in LibreOffice and stops by itself when nobody comes back)."""
        self._lost(self._sock, quiet=True)

    def ask_to_quit(self) -> None:
        """Ask the server to stop (an older helper being replaced)."""
        self.request("quit")
        self.close()

    # ------------------------------------------------------------------ #

    def request(self, command: str, timeout: float = REQUEST_TIMEOUT_S, **fields) -> dict | None:
        """Send one request and wait for its answer; None if the link is down, broke or did not answer in time."""
        sock = self._sock
        if sock is None:
            return None
        number = next(self._ids)
        waiter: tuple[threading.Event, list] = (threading.Event(), [])
        self._waiting[number] = waiter
        try:
            with self._send_lock:
                sock.sendall((json.dumps(dict(fields, cmd=command, id=number)) + "\n").encode("utf-8"))
            if not waiter[0].wait(timeout) or not waiter[1]:
                return None
            return waiter[1][0]
        except OSError:
            self._lost(sock)
            return None
        finally:
            self._waiting.pop(number, None)

    def find(self, urls: list[str]) -> dict | None:
        """What is known of the open document at any of *urls* (``{"url", "sheet", "sheets", "modified"}``), or None."""
        for url in urls:
            if url in self.docs:
                return self.docs[url]
        return None

    # ------------------------------------------------------------------ #

    def _read(self, sock: socket.socket, reader) -> None:
        try:
            for line in reader:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if message.get("id") is not None:
                    waiter = self._waiting.get(message["id"])
                    if waiter is not None:
                        waiter[1].append(message)
                        waiter[0].set()
                else:
                    self._event(message)
        except (OSError, ValueError):
            pass
        finally:
            self._lost(sock)

    def _event(self, message: dict) -> None:
        kind, url = str(message.get("event", "")), str(message.get("url", ""))
        if kind in ("opened", "sheet"):
            self.docs[url] = {k: message.get(k) for k in ("url", "sheet", "sheets", "modified")}
        elif kind == "closed":
            self.docs.pop(url, None)
        elif kind != "changed":                                    # (changed: the document was edited; nothing to remember, just say so)
            return
        self._emit(kind, url, str(message.get("sheet", "") or ""))

    def _lost(self, sock: socket.socket | None, quiet: bool = False) -> None:
        with self._lock:
            if sock is None or self._sock is not sock:
                return
            self._sock = None
            self.docs = {}
        with contextlib.suppress(OSError):
            sock.close()
        for number, waiter in list(self._waiting.items()):          # nobody waits for an answer that cannot come
            waiter[0].set()
        if not quiet:
            self._emit("lost", "", "")

    def _emit(self, kind: str, url: str, sheet: str) -> None:
        if self.on_event is not None:
            try:
                self.on_event(kind, url, sheet)
            except Exception:                                      # (a listener never stops the link)
                log.debug("a live-link listener failed", exc_info=True)
