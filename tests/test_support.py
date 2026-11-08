"""The support report: what it holds, what it never holds, and how it is sent."""

import io
import json
import logging
import pathlib
import tempfile
import unittest
import urllib.error

from PySide6.QtWidgets import QApplication

from quill import diagnostics, support
from quill.ui.support_dialog import SupportDialog

APP = QApplication.instance() or QApplication([])


class Fake:
    """A stand-in for urlopen's response."""

    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.body).encode()


class ReportCase(unittest.TestCase):
    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp())
        diagnostics.setup_logging(self.folder)
        self.addCleanup(lambda: [logging.getLogger("quill").removeHandler(h) or h.close()
                                 for h in list(logging.getLogger("quill").handlers) if getattr(h, "_quill_file", False)])
        logging.getLogger("quill.controller").info("Connected to Personal Debt.xlsx, sheet Salary")
        logging.getLogger("quill.listener").debug("heard: paid thirty dollars to Acme")
        diagnostics.syslog().info("Microphone on")


class TestReport(ReportCase):
    def report(self, **kw):
        return support.Report("It stopped", log_folder=self.folder, **kw)

    def test_the_payload_has_the_message_the_facts_and_only_sys_lines(self):
        payload = self.report().payload()
        self.assertEqual(payload["message"], "It stopped")
        self.assertIn("Quill", payload["facts"])
        text = "\n".join(payload["log"])
        self.assertIn("Microphone on", text)
        for private in ("Personal Debt", "Salary", "Acme", "thirty"):
            self.assertNotIn(private, json.dumps(payload))

    def test_leaving_the_log_out_sends_no_log_lines(self):
        self.assertEqual(self.report(include_log=False).payload()["log"], [])

    def test_the_preview_is_the_payload(self):
        report = self.report(contact="me@example.com")
        text = report.text()
        self.assertIn("me@example.com", text)
        self.assertIn("It stopped", text)
        self.assertIn("Microphone on", text)

    def test_a_very_long_message_is_cut_at_the_limit(self):
        long = support.Report("x" * (support.MAX_MESSAGE + 500), log_folder=self.folder)
        self.assertEqual(len(long.payload()["message"]), support.MAX_MESSAGE)

    def test_the_failure_marker_is_taken_once(self):
        diagnostics.mark_crash(self.folder)
        self.assertTrue(diagnostics.take_crash(self.folder))
        self.assertFalse(diagnostics.take_crash(self.folder))


class TestSend(unittest.TestCase):
    def test_it_posts_json_and_returns_the_reference(self):
        seen = {}

        def opener(request, timeout):
            seen["url"], seen["body"], seen["method"] = request.full_url, json.loads(request.data), request.get_method()
            return Fake({"ok": True, "reference": "#42"})
        result = support.send({"message": "hi"}, "https://relay.example/report", opener)
        self.assertTrue(result.ok)
        self.assertEqual(result.reference, "#42")
        self.assertEqual((seen["url"], seen["method"], seen["body"]), ("https://relay.example/report", "POST", {"message": "hi"}))

    def test_nothing_is_sent_without_a_relay_address(self):
        self.assertFalse(support.send({}, "").ok)

    def test_nothing_is_sent_over_plain_http(self):
        def opener(*a, **k): raise AssertionError("must not be called")
        result = support.send({}, "http://relay.example", opener)
        self.assertFalse(result.ok)
        self.assertIn("not secure", result.error)

    def test_failures_come_back_as_sentences_and_never_raise(self):
        def offline(*a, **k): raise OSError("down")
        def limited(*a, **k): raise urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO())
        def broken(*a, **k): return Fake({"ok": False})
        self.assertIn("reach", support.send({}, "https://r.example", offline).error)
        self.assertIn("Too many", support.send({}, "https://r.example", limited).error)
        self.assertFalse(support.send({}, "https://r.example", broken).ok)


class TestDialog(ReportCase):
    def make(self, configured=True, kind="problem"):
        self.sent = []
        dialog = SupportDialog(None, self.sent.append, lambda: None, kind, self.folder, configured)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_send_waits_for_a_message(self):
        dialog = self.make()
        self.assertFalse(dialog.send_button.isEnabled())
        dialog.message.setPlainText("It stopped")
        self.assertTrue(dialog.send_button.isEnabled())

    def test_without_a_relay_send_is_off_and_copy_still_works(self):
        dialog = self.make(configured=False)
        dialog.message.setPlainText("It stopped")
        self.assertFalse(dialog.send_button.isEnabled())
        dialog.copy_diagnostics()
        self.assertIn("It stopped", QApplication.clipboard().text())
        self.assertIn("Microphone on", QApplication.clipboard().text())

    def test_the_preview_follows_the_form(self):
        dialog = self.make()
        dialog.message.setPlainText("first")
        dialog.toggle_preview()
        self.assertIn("first", dialog.preview.toPlainText())
        dialog.message.setPlainText("second")
        self.assertIn("second", dialog.preview.toPlainText())
        dialog.include_log.setChecked(False)
        self.assertIn("(not included)", dialog.preview.toPlainText())

    def test_pressing_send_hands_over_exactly_the_previewed_payload(self):
        dialog = self.make()
        dialog.message.setPlainText("It stopped")
        dialog.send_clicked()
        self.assertEqual(self.sent, [dialog.report().payload()])
        self.assertFalse(dialog.send_button.isEnabled())

    def test_a_success_closes_the_loop_and_a_failure_lets_the_person_try_again(self):
        dialog = self.make()
        dialog.message.setPlainText("It stopped")
        dialog.send_clicked()
        dialog.finished(support.SendResult(False, error="Couldn't reach the support service."))
        self.assertTrue(dialog.send_button.isEnabled())
        self.assertEqual(dialog.notice.kind, "error")                   # a red notice, not a line of text
        self.assertIn("reach", dialog.notice.label.text())
        dialog.send_clicked()
        self.assertEqual(dialog.notice.kind, "")                        # the old outcome goes while sending again
        dialog.finished(support.SendResult(True, "#7"))
        self.assertEqual(dialog.notice.kind, "ok")                      # a green notice
        self.assertIn("#7", dialog.notice.label.text())
        self.assertFalse(dialog.send_button.isEnabled())

    def test_a_crash_report_says_why_it_opened(self):
        dialog = self.make(kind="crash")
        self.assertEqual(dialog.report().kind, "crash")
        self.assertIn("unexpected error", support.render(dialog.report().payload()))


if __name__ == "__main__":
    unittest.main()
