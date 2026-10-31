"""Accounts and subscriptions: the back end of the paid version, switched off for now.

Planned model: a hosted website (HTTPS only) with sign-up, sign-in and secure checkout; the app signs in,
receives a signed licence for a plan (a one-off purchase or a recurring subscription), and re-checks it
now and then. Until that service exists, nothing here talks to the network and nothing is restricted:
:meth:`LicenseService.entitled` is always true while ``enforce`` is off.

What lives where:
  * ``Settings.account`` (the ``[account]`` table of the settings file): the *non-secret* facts: service
    address, e-mail, plan, status, renewal date, device id, when it was last checked.
  * A :class:`TokenStore`: the secret session token. Never written to the settings file. The default
    store keeps it in memory; the macOS Keychain / Windows Credential Manager store replaces it later.
  * A :class:`Transport`: how requests reach the service. The default one says the service is not
    available yet, so everything keeps working offline.
"""

from __future__ import annotations
import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

#: Plans the website will sell: key -> (label, recurring?).
PLANS: dict[str, tuple[str, bool]] = {
    "trial": ("Free Trial", False),
    "monthly": ("Monthly Subscription", True),
    "yearly": ("Yearly Subscription", True),
    "lifetime": ("One-Time Purchase", False),
}

#: Licence states. ``signed_out`` is the state of a fresh install.
STATUSES = ("signed_out", "trial", "active", "past_due", "expired", "canceled")

#: How long a licence last confirmed online keeps working without a new check (days).
OFFLINE_GRACE_DAYS = 7

#: Defaults of the ``[account]`` settings table, and the type each value must keep.
DEFAULT_ACCOUNT: dict[str, object] = {
    "enforce": False,        # licensing is not applied until this is switched on
    "service_url": "",       # https:// address of the licence service ("" = not configured)
    "site_url": "",          # https:// address of the website (sign-up, billing, account)
    "email": "",
    "plan": "",              # one of PLANS, "" when signed out
    "status": "signed_out",  # one of STATUSES
    "renews_on": "",         # ISO date of the next renewal / end of the plan
    "last_checked": "",      # ISO timestamp of the last successful online check
    "device_id": "",         # random id of this installation, made on first use
}


class NotAvailable(Exception):
    """The licence service can't be reached or is not set up yet."""


def is_secure_url(url: str) -> bool:
    """True for a well-formed ``https://`` address (accounts and payments never go over plain HTTP)."""
    parts = urlparse(url)
    return parts.scheme == "https" and bool(parts.netloc)


def clean_account(raw: dict | None) -> dict[str, object]:
    """The account table with unknown keys dropped, wrong types and insecure addresses reset to defaults."""
    account = dict(DEFAULT_ACCOUNT)
    for key, default in DEFAULT_ACCOUNT.items():
        value = (raw or {}).get(key)
        if value is not None and type(value) is type(default):
            account[key] = value
    for key in ("service_url", "site_url"):
        if account[key] and not is_secure_url(str(account[key])):
            account[key] = ""
    if account["plan"] not in ("", *PLANS):
        account["plan"] = ""
    if account["status"] not in STATUSES:
        account["status"] = DEFAULT_ACCOUNT["status"]
    return account


class TokenStore(Protocol):
    """Where the secret session token is kept."""

    def get(self) -> str: ...
    def set(self, token: str) -> None: ...
    def clear(self) -> None: ...


# (bandit flags empty strings assigned to token-like names; these are placeholders, not secrets)
class MemoryTokenStore:
    """Keeps the token for this run only (the placeholder until a keychain store exists)."""

    def __init__(self) -> None:
        self._token = ""  # nosec B105

    def get(self) -> str:
        return self._token

    def set(self, token: str) -> None:
        self._token = token

    def clear(self) -> None:
        self._token = ""  # nosec B105


class Transport(Protocol):
    """Sends a request to the licence service and returns its JSON answer as a dict."""

    def request(self, base_url: str, path: str, payload: dict, token: str = "") -> dict: ...  # nosec B107


class UnavailableTransport:
    """The stand-in used until the service exists: every request says it is not available."""

    def request(self, base_url: str, path: str, payload: dict, token: str = "") -> dict:  # nosec B107
        raise NotAvailable("The account service is not available yet.")


@dataclass(frozen=True)
class Standing:
    """What the account screen shows."""

    signed_in: bool
    email: str
    plan_label: str
    status: str
    status_text: str
    renews_on: str


class LicenseService:
    """Reads and updates the account state in the settings and answers "may the app be used?".

    Args:
        settings: The :class:`~quill.config.settings.Settings` holding ``account``.
        transport: How the service is reached (default: not available).
        tokens: Where the session token lives (default: memory).
        today: Replaces ``datetime.date.today`` (tests).
    """

    def __init__(self, settings, transport: Transport | None = None, tokens: TokenStore | None = None,
                 today=None) -> None:
        self._settings = settings
        self._transport = transport or UnavailableTransport()
        self._tokens = tokens or MemoryTokenStore()
        self._today = today or dt.date.today

    # ------------------------------------------------------------------ #

    @property
    def account(self) -> dict:
        """The ``[account]`` settings table this service reads and updates."""
        return self._settings.account

    @property
    def configured(self) -> bool:
        """Is there a secure service address to talk to?"""
        return is_secure_url(str(self.account["service_url"]))

    def device_id(self) -> str:
        """This installation's random id, created the first time it is needed."""
        if not self.account["device_id"]:
            self.account["device_id"] = uuid.uuid4().hex
        return str(self.account["device_id"])

    def entitled(self) -> bool:
        """May the app be used? Always yes while licensing is not enforced."""
        if not self.account["enforce"]:
            return True
        status = self.account["status"]
        if status in ("trial", "active", "past_due"):
            return not self._lapsed() and not self._unchecked()
        return False

    def _unchecked(self) -> bool:
        """True when the licence has not been confirmed online within the offline grace period."""
        stamp = self.account["last_checked"]
        try:
            return bool(stamp) and (self._today() - dt.date.fromisoformat(str(stamp)[:10])).days > OFFLINE_GRACE_DAYS
        except ValueError:
            return False

    def _lapsed(self) -> bool:
        """True when the plan's end date has passed (a paid plan with no date never lapses)."""
        ends = self.account["renews_on"]
        try:
            return bool(ends) and dt.date.fromisoformat(str(ends)) < self._today()
        except ValueError:
            return False

    def standing(self) -> Standing:
        """A summary for the account screen."""
        account = self.account
        plan = PLANS.get(str(account["plan"]), ("", False))[0]
        status = str(account["status"])
        if not self.entitled() and account["enforce"] and status in ("trial", "active", "past_due"):
            status = "expired"
        text = {"signed_out": "Not signed in", "trial": "Trial", "active": "Active", "past_due": "Payment due",
                "expired": "Expired", "canceled": "Canceled"}[status]
        return Standing(bool(account["email"]), str(account["email"]), plan, status, text, str(account["renews_on"]))

    # ------------------------------------------------------------------ #
    # Actions (each raises NotAvailable until the service exists)          #
    # ------------------------------------------------------------------ #

    def sign_in(self, email: str, password: str) -> Standing:
        """Sign in and store the licence the service returns."""
        answer = self._send("/v1/sign-in", {"email": email, "password": password, "device": self.device_id()})
        self._tokens.set(str(answer.get("token", "")))
        self._apply(answer, email=email)
        return self.standing()

    def sign_out(self) -> None:
        """Forget the session and licence on this device."""
        self._tokens.clear()
        for key in ("email", "plan", "renews_on", "last_checked"):
            self.account[key] = DEFAULT_ACCOUNT[key]
        self.account["status"] = "signed_out"

    def refresh(self) -> Standing:
        """Ask the service for the current licence."""
        answer = self._send("/v1/license", {"device": self.device_id()}, token=self._tokens.get())
        self._apply(answer)
        return self.standing()

    def checkout_url(self, plan: str) -> str:
        """The website page that sells *plan*, or '' when no site is configured."""
        site = str(self.account["site_url"]).rstrip("/")
        return f"{site}/checkout?plan={plan}" if site and plan in PLANS else ""

    def manage_url(self) -> str:
        """The website's billing / account page, or '' when no site is configured."""
        site = str(self.account["site_url"]).rstrip("/")
        return f"{site}/account" if site else ""

    # ------------------------------------------------------------------ #

    def _send(self, path: str, payload: dict, token: str = "") -> dict:  # nosec B107
        if not self.configured:
            raise NotAvailable("The account service is not set up yet.")
        return self._transport.request(str(self.account["service_url"]), path, payload, token)

    def _apply(self, answer: dict, email: str = "") -> None:
        account = self.account
        if email:
            account["email"] = email
        if answer.get("plan") in PLANS:
            account["plan"] = answer["plan"]
        if answer.get("status") in STATUSES:
            account["status"] = answer["status"]
        if isinstance(answer.get("renews_on"), str):
            account["renews_on"] = answer["renews_on"]
        account["last_checked"] = dt.datetime.now().isoformat(timespec="seconds")
