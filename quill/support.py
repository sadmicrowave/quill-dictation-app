"""Getting help: the support report a person can send without a GitHub account.

The report is a small JSON document: what the person wrote, an optional reply address, a few facts about the program
and computer, and (if they allow it) the ``SYS`` lines of the log (see :mod:`quill.diagnostics`: ``USR`` lines, which
may hold file names, sheet names, spoken words or cell values, are never read). :func:`render` turns that same
document into the text the form shows under *Show what will be sent*, so the preview is exactly what leaves the
computer.

It is sent to a small relay (``relay/`` in the repository, running on Cloudflare) which creates the issue. The relay
holds the only secret; this program holds just its public address. :data:`SUPPORT_URL` stays empty until the relay is
deployed, and the form then offers *Copy Diagnostics* and the GitHub issues page instead.
"""

from __future__ import annotations

import json
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

from quill import diagnostics

#: https:// address of the relay ("" = not deployed yet).
SUPPORT_URL = ""
ISSUES_URL = "https://github.com/sadmicrowave/quill-dictation-app/issues"
NEW_ISSUE_URL = ISSUES_URL + "/new"

MAX_MESSAGE = 4000          # characters the person may write
MAX_LOG_LINES = 400         # SYS lines attached (about 40 KB)
TIMEOUT_S = 20
KINDS = ("problem", "crash")


@dataclass
class Report:
    """A support report as the form builds it.

    Args:
        message: What happened, in the person's words (trimmed to :data:`MAX_MESSAGE`).
        contact: An address to reply to ("" = none; the person chose to give it).
        include_log: Attach the ``SYS`` lines of the log.
        kind: ``"problem"`` or ``"crash"`` (Quill hit an unexpected error last time).
        log_folder: Where the log is (default: the per-user log folder; tests pass their own).
    """

    message: str = ""
    contact: str = ""
    include_log: bool = True
    kind: str = "problem"
    log_folder: pathlib.Path | None = field(default=None, repr=False)

    def payload(self) -> dict:
        """The document that is sent (and previewed)."""
        data = {
            "kind": self.kind if self.kind in KINDS else "problem",
            "message": self.message.strip()[:MAX_MESSAGE],
            "contact": self.contact.strip()[:200],
            "facts": diagnostics.environment_facts(),
            "log": diagnostics.sys_lines(self.log_folder, MAX_LOG_LINES) if self.include_log else [],
        }
        return data

    def text(self) -> str:
        """The readable form of :meth:`payload`: what the preview shows and *Copy Diagnostics* copies."""
        return render(self.payload())


def render(payload: dict) -> str:
    """The payload as plain text, section by section, with nothing hidden."""
    out = []
    out.append("WHAT HAPPENED" + (" (Quill hit an unexpected error last time)" if payload.get("kind") == "crash" else ""))
    out.append(payload.get("message") or "(nothing written)")
    out.append("")
    out.append("REPLY ADDRESS")
    out.append(payload.get("contact") or "(none)")
    out.append("")
    out.append("ABOUT THIS COPY OF QUILL")
    out += [f"{key}: {value}" for key, value in payload.get("facts", {}).items()]
    out.append("")
    log = payload.get("log") or []
    out.append(f"DIAGNOSTIC LOG ({len(log)} lines: only the ones marked SYS, never file names, sheet names, words or values)")
    out += log or ["(not included)"]
    return "\n".join(out)


@dataclass
class SendResult:
    """What came back from sending a report."""

    ok: bool
    reference: str = ""       # e.g. "#42" for the person to quote
    error: str = ""           # a sentence for the person when it did not go


def send(payload: dict, url: str | None = None, opener: Callable | None = None) -> SendResult:
    """Post *payload* to the relay. Never raises: a failure comes back as a sentence.

    Args:
        payload: From :meth:`Report.payload`.
        url: The relay address (default :data:`SUPPORT_URL`); only ``https://`` is accepted.
        opener: ``urllib.request.urlopen`` (tests pass a fake).
    """
    url = SUPPORT_URL if url is None else url
    if not url:
        return SendResult(False, error="Sending isn't set up in this version yet. Use Copy Diagnostics, or the GitHub issues page.")
    if not url.startswith("https://"):
        return SendResult(False, error="The support address is not secure, so nothing was sent.")
    from quill import __version__
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": f"Quill/{__version__}"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT_S) as response:   # noqa: S310  # nosec B310 (https only, above)
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return SendResult(False, error="Too many reports were sent from this connection. Try again in an hour.")
        return SendResult(False, error=f"The support service answered with an error ({exc.code}). Nothing was lost: use Copy Diagnostics.")
    except (OSError, ValueError):
        return SendResult(False, error="Couldn't reach the support service. Check your connection, or use Copy Diagnostics.")
    if not body.get("ok"):
        return SendResult(False, error="The support service could not take the report. Use Copy Diagnostics.")
    return SendResult(True, reference=str(body.get("reference", "")))
