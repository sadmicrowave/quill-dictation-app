"""Model locator/downloader tests; downloads use a local file:// archive."""
import pathlib
import tempfile
import unittest
import zipfile

from quill.listener.model import download_model, find_model, is_model_dir


def make_model(path: pathlib.Path) -> pathlib.Path:
    (path / "am").mkdir(parents=True)
    (path / "conf").mkdir()
    return path


class TestFindModel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_is_model_dir(self):
        self.assertTrue(is_model_dir(make_model(self.root / "m")))
        self.assertFalse(is_model_dir(self.root))

    def test_finds_child_of_search_dir(self):
        model = make_model(self.root / "search" / "vosk-model-x")
        self.assertEqual(find_model(search_dirs=[self.root / "search"]), model)

    def test_configured_path_wins_and_may_be_the_model(self):
        mine = make_model(self.root / "mine")
        other = make_model(self.root / "search" / "other")
        self.assertEqual(find_model(mine, [self.root / "search"]), mine)
        self.assertEqual(find_model(None, [self.root / "search"]), other)

    def test_none_when_absent(self):
        self.assertIsNone(find_model(search_dirs=[self.root / "missing", self.root]))

    def test_ignores_non_model_children(self):
        (self.root / "junk").mkdir()
        self.assertIsNone(find_model(search_dirs=[self.root]))


class TestDownload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _zip(self, members):
        archive = self.root / "m.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for name, data in members.items():
                zf.writestr(name, data)
        return archive.as_uri()

    def test_download_and_unpack(self):
        url = self._zip({"vosk-model-t/am/final.mdl": "x", "vosk-model-t/conf/mfcc.conf": "y"})
        calls = []
        model = download_model(self.root / "dest", url, progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(model.name, "vosk-model-t")
        self.assertTrue(is_model_dir(model))
        self.assertTrue(calls and calls[-1][0] == calls[-1][1])

    def test_archive_without_model_rejected(self):
        with self.assertRaises(RuntimeError):
            download_model(self.root / "dest", self._zip({"readme.txt": "hi"}))

    def test_zip_slip_rejected(self):
        with self.assertRaises(RuntimeError):
            download_model(self.root / "dest", self._zip({"../evil.txt": "x"}))
        self.assertFalse((self.root / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()
