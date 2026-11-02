"""The Better speech model: catalog, finding it, choosing it in Settings, and listening with it."""
import pathlib
import tempfile
import unittest

from PySide6.QtWidgets import QApplication

from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings
from quill.listener import model as M
from quill.ui.settings_dialog import SettingsDialog
from tests.test_app import FakeListener, FakeSpeaker, make_workbook

_app = QApplication.instance() or QApplication([])


def fake_model(base: pathlib.Path, name: str) -> pathlib.Path:
    folder = base / name
    (folder / "am").mkdir(parents=True)
    (folder / "conf").mkdir()
    return folder


class TestCatalog(unittest.TestCase):
    def test_the_two_models_and_their_checks(self):
        self.assertEqual(set(M.SPECS), {"standard", "better"})
        for spec in M.SPECS.values():
            self.assertTrue(spec.url.startswith("https://"))
            self.assertEqual(len(spec.sha256), 64)
        self.assertEqual(M.STANDARD.sha256, M.MODEL_SHA256)

    def test_find_picks_the_named_model_not_just_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            small = fake_model(base, M.STANDARD.name)
            better = fake_model(base, M.BETTER.name)
            self.assertEqual(M.find_spec_model(M.BETTER, [base]), better)
            self.assertEqual(M.find_spec_model(M.STANDARD, [base]), small)

    def test_missing_model_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(M.find_spec_model(M.BETTER, [pathlib.Path(tmp)]))

    def test_download_spec_uses_the_models_own_address_and_checksum(self):
        seen = {}
        real = M.download_model
        M.download_model = lambda dest, url, progress, sha: seen.update(url=url, sha=sha) or fake_model(dest, M.BETTER.name)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = M.download_spec(pathlib.Path(tmp), None, M.BETTER)
                self.assertEqual(path.name, M.BETTER.name)
        finally:
            M.download_model = real
        self.assertEqual(seen, {"url": M.BETTER.url, "sha": M.BETTER.sha256})

    def test_the_default_downloader_is_callable_with_a_folder_and_a_progress_callback(self):
        # (it used to be the raw download function, which took the progress callback as the address)
        import inspect
        params = list(inspect.signature(M.download_spec).parameters)
        self.assertEqual(params[:2], ["dest_dir", "progress"])


class TestChoosingTheModel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.standard = self.dir / "standard"
        self.better = self.dir / "better"
        self.better_present = False
        self.used = []
        self.settings = Settings.load(self.dir / "cfg")
        self.app = QuillApp(
            _app, self.settings, XlsxBridge(make_workbook(self.dir / "w.xlsx")),
            listener_factory=lambda model, t, e: self.used.append(model) or FakeListener(model, t, e),
            model_finder=lambda c: self.standard, speaker=FakeSpeaker(),
            better_finder=lambda: self.better if self.better_present else None)

    def test_standard_is_the_default(self):
        self.app.start()
        self.assertEqual(self.used, [self.standard])
        self.assertEqual(self.settings.preferences["speech_quality"], "standard")

    def test_better_is_used_when_chosen_and_installed(self):
        self.settings.preferences["speech_quality"] = "better"
        self.better_present = True
        self.app.start()
        self.assertEqual(self.used, [self.better])

    def test_better_chosen_but_missing_falls_back_and_says_so(self):
        self.settings.preferences["speech_quality"] = "better"
        self.app.start()
        self.assertEqual(self.used, [self.standard])
        self.assertIn("Broad speech model is not installed", self.app.window.log.toPlainText())

    def test_switching_in_settings_restarts_the_listener_with_the_other_model(self):
        self.better_present = True
        self.app.start()
        self.settings.preferences["speech_quality"] = "better"
        self.app.apply_settings(quiet=True)
        self.assertEqual(self.used, [self.standard, self.better])
        self.app.apply_settings(quiet=True)                         # nothing changed: no second restart
        self.assertEqual(len(self.used), 2)

    def test_a_finished_download_of_the_chosen_model_starts_listening_with_it(self):
        self.app.start()
        self.settings.preferences["speech_quality"] = "better"
        self.app._downloading = "better"
        self.better_present = True
        self.app._on_model_ready(self.better)
        self.assertEqual(self.used[-1], self.better)

    def test_the_better_download_is_asked_for_by_spec(self):
        calls = []
        self.app._model_downloader = lambda dest, progress, spec=None: calls.append(spec) or self.better
        import threading
        done = threading.Event()
        self.app.relay.model_ready.connect(lambda p: done.set())
        self.app.start()
        self.app.download_model("better")
        for _ in range(100):
            _app.processEvents()
            if done.is_set():
                break
            threading.Event().wait(0.02)
        self.assertEqual(calls, [M.BETTER])


class TestSettingsChoice(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.settings = Settings.load(pathlib.Path(self._tmp.name))
        self.installed = {"standard": True, "better": False, "best": False}
        self.asked = []
        self.d = SettingsDialog(self.settings, on_download_model=self.asked.append,
                                model_installed=lambda quality: self.installed[quality])
        self.d.build()

    def test_choosing_better_shows_its_state_and_downloads_that_one(self):
        standard, better = self.d.model_rows["standard"], self.d.model_rows["better"]
        self.assertFalse(standard.uninstall_button.isHidden())
        self.assertTrue(standard.download_button.isHidden())
        better.radio.setChecked(True)
        self.assertFalse(better.download_button.isHidden())
        self.assertEqual("130 MB", better.size_label.text())
        better.download_button.click()
        self.assertEqual(self.asked, ["better"])

    def test_the_choice_is_stored_live(self):
        self.d.model_rows["better"].radio.setChecked(True)
        self.assertEqual(self.settings.preferences["speech_quality"], "better")

    def test_a_bad_stored_value_goes_back_to_standard(self):
        (pathlib.Path(self._tmp.name) / Settings.KEYWORDS_FILE).write_text('[preferences]\nspeech_quality = "huge"\n')
        self.assertEqual(Settings.load(pathlib.Path(self._tmp.name)).preferences["speech_quality"], "standard")


if __name__ == "__main__":
    unittest.main()


class TestUninstallingAndChoosingOnInstall(unittest.TestCase):
    """A finished install is chosen; an uninstall hands over to the next best model; an old setup moves up once."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.root = self.dir / "models"
        self.root.mkdir()
        self.standard = self.root / "standard"
        self.better = self.root / "better"
        for folder in (self.standard, self.better):
            folder.mkdir()
            (folder / "f.bin").write_bytes(b"x" * 2048)
        self.used = []
        self.settings = Settings.load(self.dir / "cfg")
        self.app = QuillApp(
            _app, self.settings, XlsxBridge(make_workbook(self.dir / "w.xlsx")),
            listener_factory=lambda model, t, e: self.used.append(model) or FakeListener(model, t, e),
            model_finder=lambda c: self.standard, speaker=FakeSpeaker(),
            better_finder=lambda: self.better if self.better_present else None,
            whisper_finder=lambda: None, whisper_engine=lambda: False)
        self.removed = []
        self.app._model_remover = lambda folder: self.removed.append(folder) or 2048
        import quill.app as A
        self._real_dir = A._user_model_dir
        A._user_model_dir = lambda: self.root
        self.addCleanup(setattr, A, "_user_model_dir", self._real_dir)
        self.better_present = True

    def test_a_finished_install_becomes_the_chosen_model(self):
        self.app.start()
        self.app._downloading = "better"
        self.app._on_model_ready(self.better)
        self.assertEqual(self.settings.preferences["speech_quality"], "better")
        self.assertEqual(self.used[-1], self.better)

    def test_removing_the_chosen_model_switches_to_the_next_best_one(self):
        self.settings.preferences["speech_quality"] = "better"
        self.app.start()
        self.app.uninstall_model("better")
        self.assertEqual(self.removed, [self.better])
        self.assertEqual(self.settings.preferences["speech_quality"], "standard")

    def test_the_bundled_model_is_never_removed(self):
        self.app._model_finder = lambda c: self.dir / "elsewhere"
        self.assertFalse(self.app.quality_removable("standard"))
        self.app.uninstall_model("standard")
        self.assertEqual(self.removed, [])

    def test_standard_stays_while_best_builds_on_it(self):
        self.app._whisper_finder = lambda: self.root / "whisper"
        self.app._whisper_engine = lambda: True
        self.assertFalse(self.app.quality_removable("standard"))

    def test_an_old_setup_with_a_better_model_installed_moves_up_once(self):
        self.settings.preferences["model_migrated"] = False
        self.app.start()
        self.assertEqual(self.settings.preferences["speech_quality"], "better")
        self.assertTrue(self.settings.preferences["model_migrated"])
        self.settings.preferences["speech_quality"] = "standard"           # the user's later choice is left alone
        self.app._use_best_installed()
        self.assertEqual(self.settings.preferences["speech_quality"], "standard")


class TestRemovingAModelFolder(unittest.TestCase):
    def test_only_a_folder_inside_the_models_folder_is_deleted(self):
        from quill.listener.model import fallback_choice, remove_model
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "models"
            inside = root / "m"
            inside.mkdir(parents=True)
            (inside / "a.bin").write_bytes(b"x" * 100)
            outside = pathlib.Path(tmp) / "other"
            outside.mkdir()
            with self.assertRaises(ValueError):
                remove_model(outside, root)
            with self.assertRaises(ValueError):
                remove_model(root, root)
            self.assertEqual(remove_model(inside, root), 100)
            self.assertFalse(inside.exists())
            self.assertTrue(outside.exists())
        self.assertEqual(fallback_choice("best", lambda k: k == "better"), "better")
        self.assertEqual(fallback_choice("best", lambda k: False), "standard")
        self.assertEqual(fallback_choice("better", lambda k: k in ("best", "standard")), "best")


class TestSpeechModelOnTheTurnPanel(unittest.TestCase):
    """The Turn Options panel picks the speech model while dictating: no restart, no file reload."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.standard, self.better = self.dir / "standard", self.dir / "better"
        self.better_present = True
        self.used, self.listeners = [], []

        def factory(model, t, e):
            listener = FakeListener(model, t, e)
            self.used.append(model)
            self.listeners.append(listener)
            return listener

        self.settings = Settings.load(self.dir / "cfg")
        self.app = QuillApp(
            _app, self.settings, XlsxBridge(make_workbook(self.dir / "w.xlsx")), listener_factory=factory,
            model_finder=lambda c: self.standard, speaker=FakeSpeaker(),
            better_finder=lambda: self.better if self.better_present else None,
            whisper_finder=lambda: None, whisper_engine=lambda: False)
        self.app.start()
        self.panel = self.app.window.panel

    def names(self):
        return [self.panel.model_combo.itemText(i) for i in range(self.panel.model_combo.count())]

    def test_the_drop_down_lists_the_three_models_and_marks_the_missing_one(self):
        self.assertEqual(self.names(), ["Quick", "Broad", "Careful (not installed)"])
        self.assertEqual(self.panel.model_combo.currentData(), "standard")

    def test_picking_an_installed_model_swaps_the_listener_at_once_and_keeps_listening(self):
        self.app.toggle_listening(True)
        self.app.controller.handle_transcript("start listening")
        session = self.app.controller.session
        bridge = self.app.controller.bridge
        before = len(self.used)
        self.panel.model_combo.setCurrentIndex(self.panel.model_combo.findData("better"))
        self.panel.model_combo.activated.emit(self.panel.model_combo.currentIndex())
        self.assertEqual(self.used[before:], [self.better])                      # a new listener, with the other model
        self.assertEqual(self.settings.preferences["speech_quality"], "better")
        self.assertIs(self.app.controller.session, session)                       # same turn state ...
        self.assertIs(self.app.controller.bridge, bridge)                         # ... and the same file, not reloaded
        self.assertTrue(self.app.controller.session.listening)
        self.assertTrue(self.app._mic_open)                                       # the microphone is open again
        self.assertFalse(self.listeners[before - 1].running if hasattr(self.listeners[before - 1], "running") else False)

    def test_picking_a_model_that_is_not_installed_opens_the_models_page_and_changes_nothing(self):
        opened = []
        self.app.open_settings = lambda page=None: opened.append(page)
        self.panel.model_combo.setCurrentIndex(self.panel.model_combo.findData("best"))
        self.panel.model_combo.activated.emit(self.panel.model_combo.currentIndex())
        self.assertEqual(opened, ["Speech Model"])
        self.assertEqual(self.settings.preferences["speech_quality"], "standard")
        self.assertEqual(self.panel.model_combo.currentData(), "standard")        # back to the model in use

    def test_the_drop_down_follows_installs_removals_and_the_settings_choice(self):
        self.better_present = False
        self.app.sync_model_panel()
        self.assertEqual(self.names()[1], "Broad (not installed)")
        self.better_present = True
        self.settings.preferences["speech_quality"] = "better"
        self.app.apply_settings(quiet=True)
        self.assertEqual(self.names()[1], "Broad")
        self.assertEqual(self.panel.model_combo.currentData(), "better")

    def test_the_settings_page_shows_the_choice_made_on_the_panel_and_cancel_keeps_it(self):
        self.app.open_settings()
        dialog = self.app._settings_dialog
        self.panel.model_combo.setCurrentIndex(self.panel.model_combo.findData("better"))
        self.panel.model_combo.activated.emit(self.panel.model_combo.currentIndex())
        self.assertTrue(dialog.model_rows["better"].radio.isChecked())
        self.assertEqual(dialog._original["speech_quality"], "better")
        dialog.close_now() if hasattr(dialog, "close_now") else None
