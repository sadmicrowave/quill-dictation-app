"""The "Best" speech model: Whisper re-reads each finished phrase; Vosk's text is the fallback."""
import io
import pathlib
import struct
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.listener import model as M
from quill.listener.whisper_refiner import WhisperRefiner, normalize
from tests.test_app import FakeListener, FakeSpeaker, make_workbook
from tests.test_listener import ListenerCase, wait_for

_app = QApplication.instance() or QApplication([])


class FakeModel:
    def __init__(self, text):
        self.text, self.calls = text, []

    def transcribe(self, audio, **options):
        self.calls.append((len(audio), options))
        return iter([type("S", (), {"text": self.text})()]), None


def speech(seconds=1.0):
    return struct.pack(f"<{int(16000 * seconds)}h", *([1000] * int(16000 * seconds)))


class TestNormalize(unittest.TestCase):
    def test_sentences_become_plain_lowercase_words(self):
        self.assertEqual(normalize("I bought a black pair of jeans, size medium, in the 1990s."),
                         "i bought a black pair of jeans size medium in the 1990s")

    def test_decimals_and_apostrophes_survive(self):
        self.assertEqual(normalize("Price $3.50 at Levi's."), "price $3.50 at levi's")

    def test_empty(self):
        self.assertEqual(normalize(" . , "), "")


class TestRefiner(unittest.TestCase):
    def test_reads_audio_with_the_sheets_words_as_a_prompt(self):
        model = FakeModel("Black jeans, size medium.")
        refiner = WhisperRefiner("dir", hint=lambda: "Size: S, M, L.", loader=lambda d: model)
        self.assertEqual(refiner.refine(speech()), "black jeans size medium")
        self.assertEqual(model.calls[0][1]["initial_prompt"], "Size: S, M, L.")
        self.assertFalse(model.calls[0][1]["condition_on_previous_text"])

    def test_the_model_loads_once(self):
        loads = []
        refiner = WhisperRefiner("dir", loader=lambda d: loads.append(d) or FakeModel("a"))
        refiner.refine(speech())
        refiner.refine(speech())
        self.assertEqual(len(loads), 1)

    def test_too_short_or_failing_audio_gives_none(self):
        refiner = WhisperRefiner("dir", loader=lambda d: FakeModel("x"))
        self.assertIsNone(refiner.refine(speech(0.1)))
        broken = WhisperRefiner("dir", loader=lambda d: (_ for _ in ()).throw(RuntimeError("no model")))
        self.assertIsNone(broken.refine(speech()))


class TestListenerSecondPass(ListenerCase):
    class Refiner:
        def __init__(self, answer):
            self.answer, self.audio = answer, []

        def refine(self, pcm):
            self.audio.append(pcm)
            return self.answer

    def test_the_refined_text_replaces_the_live_text(self):
        refiner = self.Refiner("black jeans")
        self.listener.set_refiner(refiner)
        self.start()
        self.listener._phrase_audio += b"abc"                      # (the fake chunks are words, not audio)
        self.push(b"blue jeans")
        self.assertTrue(wait_for(lambda: self.heard == ["black jeans"]))
        self.assertTrue(refiner.audio[0].endswith(b"blue jeans"))

    def test_when_the_second_pass_hears_nothing_the_live_text_stands(self):
        self.listener.set_refiner(self.Refiner(None))
        self.start()
        self.push(b"blue jeans")
        self.assertTrue(wait_for(lambda: self.heard == ["blue jeans"]))

    def test_without_a_refiner_nothing_changes_and_no_audio_is_kept(self):
        self.start()
        self.push(b"hello")
        self.assertTrue(wait_for(lambda: self.heard == ["hello"]))
        self.assertEqual(len(self.listener._phrase_audio), 0)


class TestDownload(unittest.TestCase):
    def fake_urlopen(self, payloads):
        def opener(url, timeout=0):
            data = payloads[url.rsplit("/", 1)[1]]
            response = io.BytesIO(data)
            response.headers = {"Content-Length": str(len(data))}
            return response
        return opener

    def test_files_are_checked_and_moved_in_together(self):
        import hashlib
        payloads = {"a.json": b"{}", "model.bin": b"weights"}
        files = tuple((n, hashlib.sha256(d).hexdigest()) for n, d in payloads.items())
        real = M.urllib.request.urlopen
        M.urllib.request.urlopen = self.fake_urlopen(payloads)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                seen = []
                path = M.download_whisper(pathlib.Path(tmp), lambda d, t: seen.append(d), "https://example.test/", files)
                self.assertEqual(sorted(p.name for p in path.iterdir()), ["a.json", "model.bin"])
                self.assertTrue(seen)
                self.assertEqual(sorted(p.name for p in pathlib.Path(tmp).iterdir()), [M.WHISPER_NAME])   # no scratch left
        finally:
            M.urllib.request.urlopen = real

    def test_a_wrong_checksum_installs_nothing(self):
        real = M.urllib.request.urlopen
        M.urllib.request.urlopen = self.fake_urlopen({"a.json": b"{}"})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(RuntimeError, "checksum"):
                    M.download_whisper(pathlib.Path(tmp), None, "https://example.test/", (("a.json", "0" * 64),))
                self.assertEqual(list(pathlib.Path(tmp).iterdir()), [])
        finally:
            M.urllib.request.urlopen = real

    def test_only_https(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RuntimeError):
            M.download_whisper(pathlib.Path(tmp), None, "http://example.test/", ())

    def test_find_needs_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            folder = base / M.WHISPER_NAME
            folder.mkdir()
            for name, _ in M.WHISPER_FILES[:-1]:
                (folder / name).write_text("x")
            self.assertIsNone(M.find_whisper_model([base]))
            (folder / M.WHISPER_FILES[-1][0]).write_text("x")
            self.assertEqual(M.find_whisper_model([base]), folder)


class TestBestInTheApp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.settings = Settings.load(self.dir / "cfg")
        self.listeners = []
        self.whisper = self.dir / "whisper"
        self.have_whisper, self.engine = False, True
        self.refiners = []

        def listener(model, t, e):
            fake = FakeListener(model, t, e)
            fake.refiner = "unset"
            fake.set_refiner = lambda r, fake=fake: setattr(fake, "refiner", r)
            self.listeners.append(fake)
            return fake

        self.app = QuillApp(
            _app, self.settings, XlsxBridge(make_workbook(self.dir / "w.xlsx")), listener_factory=listener,
            model_finder=lambda c: self.dir, speaker=FakeSpeaker(),
            whisper_finder=lambda: self.whisper if self.have_whisper else None,
            whisper_engine=lambda: self.engine,
            refiner_factory=lambda folder, hint: self.refiners.append((folder, hint)) or "refiner")

    def test_best_with_everything_installed_gives_the_listener_a_refiner(self):
        self.settings.preferences["speech_quality"] = "best"
        self.have_whisper = True
        self.app.start()
        self.assertEqual(self.listeners[0].refiner, "refiner")
        self.assertEqual(self.refiners[0][0], self.whisper)

    def test_best_without_its_model_falls_back_and_says_so(self):
        self.settings.preferences["speech_quality"] = "best"
        self.app.start()
        self.assertIsNone(self.listeners[0].refiner)
        self.assertIn("Best speech model is not ready", self.app.window.log.toPlainText())

    def test_standard_has_no_refiner(self):
        self.app.start()
        self.assertIsNone(self.listeners[0].refiner)

    def test_installed_needs_the_files_and_the_engine(self):
        self.have_whisper, self.engine = True, False
        self.assertFalse(self.app.quality_installed("best"))
        self.engine = True
        self.assertTrue(self.app.quality_installed("best"))

    def test_the_hint_lists_the_sheets_values(self):
        self.app.start()
        self.assertTrue(self.app._whisper_hint())

    def test_download_refused_when_the_engine_is_missing(self):
        self.engine = False
        self.app.start()
        self.app.download_model("best")
        self.assertIn("not available in this build", self.app.window.log.toPlainText())
        self.assertFalse(self.app._model_busy)

    def test_switching_to_best_in_settings_reloads_the_listener(self):
        self.have_whisper = True
        self.app.start()
        self.settings.preferences["speech_quality"] = "best"
        self.app.apply_settings(quiet=True)
        self.assertEqual(len(self.listeners), 2)
        self.assertEqual(self.listeners[1].refiner, "refiner")

    def test_settings_offers_three_choices(self):
        from quill.ui.settings_dialog import SettingsDialog
        d = SettingsDialog(self.settings, model_installed=lambda q: True)
        d.build()
        self.assertEqual([d.quality_combo.itemData(i) for i in range(d.quality_combo.count())],
                         ["standard", "better", "best"])


if __name__ == "__main__":
    unittest.main()
