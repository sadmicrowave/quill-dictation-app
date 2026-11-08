"""Finding out whether a newer Quill has been released.

Quill asks the same small relay that takes problem reports (``relay/`` in the repository) for the newest release of its
public GitHub repository; the relay answers with a version, a page to download it from and a few lines of notes. Quill
itself never talks to GitHub, and sends nothing but the name of this program and its version (the standard
``User-Agent``). The answer is compared with the running version: only a *newer* release counts as an update, so a copy
built from newer sources than the last release is never told to "update" backwards.

Nothing here raises: a check that cannot be made is just ``unknown``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from quill.support import SUPPORT_URL

#: The relay's address for this question.
LATEST_URL = SUPPORT_URL.rstrip("/") + "/latest" if SUPPORT_URL else ""
#: Where releases are listed (used when the relay names no page).
RELEASES_URL = "https://github.com/sadmicrowave/quill-dictation-app/releases/latest"
#: The same release information straight from GitHub (the repository is public). Used only when the relay is an older build that does
#: not answer ``/latest`` yet (it says 404 or 405), so checking for updates keeps working while the relay is being updated.
GITHUB_LATEST_URL = "https://api.github.com/repos/sadmicrowave/quill-dictation-app/releases/latest"
TIMEOUT_S = 8


@dataclass(frozen=True)
class UpdateResult:
    """How a check went."""

    status: str                 # "available" | "current" | "unknown"
    latest: str = ""            # the newest released version ("" when none is published or it could not be read)
    url: str = RELEASES_URL     # where to download it
    notes: str = ""             # the first lines of the release notes
    error: str = ""             # a sentence for the person when the check could not be made


def version_tuple(text: str) -> tuple[int, ...]:
    """``"v0.2.10-beta"`` -> ``(0, 2, 10)`` (the leading numbers; anything after them is ignored)."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "", re.IGNORECASE)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_newer(latest: str, current: str) -> bool:
    """Is release *latest* newer than the running *current*? (Missing trailing numbers count as zero: 1.2 == 1.2.0.)"""
    a, b = version_tuple(latest), version_tuple(current)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def check(current: str | None = None, url: str | None = None, opener: Callable | None = None) -> UpdateResult:
    """Ask for the newest release and compare it with *current* (default: this program's version). Never raises.

    Args:
        current: The running version (tests pass one).
        url: The relay's ``/latest`` address; only ``https://`` is accepted.
        opener: ``urllib.request.urlopen`` (tests pass a fake).
    """
    if current is None:
        from quill import __version__ as current
    url = LATEST_URL if url is None else url
    if not url or not url.startswith("https://"):
        return UpdateResult("unknown", error="Updates can't be checked from this version.")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": f"Quill/{current}"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT_S) as response:   # noqa: S310  # nosec B310 (https only, above)
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 405) and url == LATEST_URL:                  # an older relay: ask GitHub directly
            return _from_github(current, opener)
        return UpdateResult("unknown", error=f"The update service answered with an error ({exc.code}).")
    except (OSError, ValueError):
        return UpdateResult("unknown", error="Couldn't reach the update service. Check your connection.")
    return _result(body, current)


def _from_github(current: str, opener: Callable | None) -> UpdateResult:
    """The newest release read from GitHub's public API (see :data:`GITHUB_LATEST_URL`). Never raises."""
    request = urllib.request.Request(GITHUB_LATEST_URL, method="GET", headers={
        "User-Agent": f"Quill/{current}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT_S) as response:   # noqa: S310  # nosec B310 (https only, constant)
            release = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return UpdateResult("current")                                # nothing has been released yet
        return UpdateResult("unknown", error=f"The update service answered with an error ({exc.code}).")
    except (OSError, ValueError):
        return UpdateResult("unknown", error="Couldn't reach the update service. Check your connection.")
    if not isinstance(release, dict):
        return UpdateResult("unknown", error="The update service could not say what the newest version is.")
    tag = str(release.get("tag_name") or "").strip()
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    return _result({"ok": True, "version": version, "url": release.get("html_url"), "notes": str(release.get("body") or "")[:600]}, current)


def _result(body: object, current: str) -> UpdateResult:
    if not isinstance(body, dict) or not body.get("ok"):
        return UpdateResult("unknown", error="The update service could not say what the newest version is.")
    latest = str(body.get("version") or "")
    if not latest:
        return UpdateResult("current")                                   # nothing has been released yet
    page = str(body.get("url") or "")
    page = page if page.startswith("https://github.com/") else RELEASES_URL
    result = dict(latest=latest, url=page, notes=str(body.get("notes") or ""))
    return UpdateResult("available" if is_newer(latest, current) else "current", **result)
