"""The (switched-off) account and subscription back end."""
import datetime as dt
import pathlib
import tempfile
import unittest

from quill.config.settings import Settings
from quill.licensing import (DEFAULT_ACCOUNT, LicenseService, NotAvailable, clean_account, is_secure_url)


class FakeTransport:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def request(self, base_url, path, payload, token=""):
        self.calls.append((base_url, path, payload, token))
        return self.answer


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.settings = Settings.load(self.dir)

    def service(self, transport=None, today=dt.date(2026, 11, 1)):
        return LicenseService(self.settings, transport, today=lambda: today)


class TestSettingsStorage(Case):
    def test_a_fresh_install_is_signed_out_and_not_enforced(self):
        self.assertEqual(self.settings.account, DEFAULT_ACCOUNT)

    def test_the_account_round_trips_through_the_settings_file(self):
        self.settings.account.update(email="a@b.co", plan="yearly", status="active", enforce=True,
                                     service_url="https://api.example.com")
        self.settings.save()
        again = Settings.load(self.dir)
        self.assertEqual(again.account["email"], "a@b.co")
        self.assertTrue(again.account["enforce"])
        self.assertEqual(again.account["plan"], "yearly")

    def test_insecure_or_wrong_values_are_dropped_on_load(self):
        cleaned = clean_account({"service_url": "http://plain.example.com", "plan": "gold",
                                 "status": "weird", "enforce": "yes", "extra": 1})
        self.assertEqual(cleaned, DEFAULT_ACCOUNT)

    def test_no_secret_is_ever_written_to_the_file(self):
        service = self.service(FakeTransport({"token": "SECRET-TOKEN", "plan": "monthly", "status": "active"}))
        self.settings.account["service_url"] = "https://api.example.com"
        service.sign_in("a@b.co", "hunter2")
        self.settings.save()
        text = (self.dir / "keywords.toml").read_text()
        self.assertNotIn("SECRET-TOKEN", text)
        self.assertNotIn("hunter2", text)


class TestEntitlement(Case):
    def test_everything_is_allowed_while_licensing_is_off(self):
        self.assertTrue(self.service().entitled())

    def test_when_enforced_a_signed_out_install_is_not_entitled(self):
        self.settings.account["enforce"] = True
        self.assertFalse(self.service().entitled())

    def test_an_active_plan_is_entitled_until_its_end_date(self):
        self.settings.account.update(enforce=True, status="active", plan="monthly", renews_on="2026-11-30")
        self.assertTrue(self.service().entitled())
        self.assertFalse(self.service(today=dt.date(2026, 12, 1)).entitled())
        self.assertEqual(self.service(today=dt.date(2026, 12, 1)).standing().status, "expired")

    def test_a_licence_not_confirmed_online_for_too_long_stops_working(self):
        self.settings.account.update(enforce=True, status="active", plan="lifetime", last_checked="2026-10-01T09:00:00")
        self.assertFalse(self.service().entitled())
        self.assertTrue(self.service(today=dt.date(2026, 10, 5)).entitled())


class TestActions(Case):
    def test_nothing_works_until_a_secure_service_is_configured(self):
        with self.assertRaises(NotAvailable):
            self.service().sign_in("a@b.co", "x")

    def test_the_default_transport_reports_not_available(self):
        self.settings.account["service_url"] = "https://api.example.com"
        with self.assertRaises(NotAvailable):
            self.service().refresh()

    def test_sign_in_records_the_plan_and_sign_out_forgets_it(self):
        transport = FakeTransport({"token": "t", "plan": "yearly", "status": "active", "renews_on": "2027-01-01"})
        self.settings.account["service_url"] = "https://api.example.com"
        service = self.service(transport)
        standing = service.sign_in("a@b.co", "pw")
        self.assertEqual((standing.email, standing.plan_label, standing.status_text), ("a@b.co", "Yearly Subscription", "Active"))
        self.assertEqual(transport.calls[0][1], "/v1/sign-in")
        service.refresh()
        self.assertEqual(transport.calls[1][3], "t")                     # the token is sent back
        service.sign_out()
        self.assertFalse(service.standing().signed_in)
        self.assertEqual(self.settings.account["status"], "signed_out")

    def test_checkout_and_account_links_come_from_the_site_address(self):
        self.settings.account["site_url"] = "https://quill.example.com/"
        service = self.service()
        self.assertEqual(service.checkout_url("monthly"), "https://quill.example.com/checkout?plan=monthly")
        self.assertEqual(service.checkout_url("nope"), "")
        self.assertEqual(service.manage_url(), "https://quill.example.com/account")

    def test_the_device_id_is_made_once(self):
        service = self.service()
        self.assertEqual(service.device_id(), service.device_id())
        self.assertEqual(len(service.device_id()), 32)

    def test_only_https_addresses_are_secure(self):
        self.assertTrue(is_secure_url("https://a.example.com/x"))
        self.assertFalse(is_secure_url("http://a.example.com"))
        self.assertFalse(is_secure_url("https://"))


if __name__ == "__main__":
    unittest.main()
