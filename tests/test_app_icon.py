"""The application icon files (idea 66), how the app uses them and how they are packaged."""
import pathlib
import struct
import sys
import tempfile
import unittest

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from quill import assets
from quill.app import QuillApp
from quill.bridge.xlsx_bridge import XlsxBridge
from quill.config.settings import Settings

_app = QApplication.instance() or QApplication([])
ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestIconFiles(unittest.TestCase):
    def test_every_png_size_exists_and_is_the_right_size(self):
        for size in assets.ICON_SIZES:
            image = QImage(str(assets.asset_path(f"icon-{size}.png")))
            self.assertEqual((image.width(), image.height()), (size, size))

    def test_the_icon_has_a_transparent_corner_and_a_filled_middle(self):
        image = QImage(str(assets.asset_path("icon-256.png")))
        self.assertEqual(image.pixelColor(2, 2).alpha(), 0)
        self.assertEqual(image.pixelColor(128, 128).alpha(), 255)

    def test_it_is_violet_not_orange(self):
        c = QImage(str(assets.asset_path("icon-256.png"))).pixelColor(128, 20)       # body near the top edge
        self.assertGreater(c.blue(), c.green())
        self.assertGreater(c.blue(), 150)
        self.assertLess(c.red() - c.blue(), 10)

    def test_icns_is_a_real_macos_icon(self):
        data = assets.asset_path("Quill.icns").read_bytes()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack(">I", data[4:8])[0], len(data))
        self.assertGreater(len(data), 50_000)

    def test_ico_holds_several_png_sizes(self):
        data = assets.asset_path("Quill.ico").read_bytes()
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 6)
        sizes = []
        for i in range(count):
            w, h, _, _, planes, bits, length, offset = struct.unpack("<BBBBHHII", data[6 + 16 * i: 22 + 16 * i])
            sizes.append(w or 256)
            self.assertEqual(data[offset: offset + 8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(len(data[offset: offset + length]), length)
        self.assertIn(16, sizes)
        self.assertIn(256, sizes)

    def test_the_svg_matches_the_chosen_design(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_icon_ideas
        self.assertEqual(assets.asset_path("icon.svg").read_text(encoding="utf-8"),
                         make_icon_ideas.sheet_offset_body("#7A55C2"))

    def test_the_small_box_is_centred_vertically_in_the_icon(self):
        svg = assets.asset_path("icon.svg").read_text(encoding="utf-8")
        import re
        box = re.search(r'<rect x="16" y="([\d.]+)" width="50" height="50" rx="11" fill="#5F4297"', svg)
        self.assertIsNotNone(box)
        self.assertAlmostEqual(float(box.group(1)) + 25, 64.0, places=1)

    def test_the_tile_sheet_behind_it_is_centred_too(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_icon_ideas
        svg = make_icon_ideas.sheet_offset_body("#7A55C2")
        self.assertIn('<rect x="42" y="21" width="68" height="86"', svg)         # 21 + 43 = 64

    def test_the_ico_builder_is_deterministic_about_layout(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_app_icon
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "x.ico"
            make_app_icon.write_ico(path)
            self.assertEqual(struct.unpack("<H", path.read_bytes()[4:6])[0], len(make_app_icon.ICO_SIZES))


class TestSmallSizes(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_app_icon
        self.tool = make_app_icon

    def test_small_sizes_use_five_bold_lines_and_large_ones_seven_thin_ones(self):
        small, large = self.tool.svg_for(16), self.tool.svg_for(256)
        self.assertNotEqual(small, large)
        self.assertEqual(self.tool.svg_for(48), small)
        self.assertEqual(self.tool.svg_for(64), large)
        # the sound lines are drawn three times (two shadows and the white ones)
        self.assertEqual(small.count('fill="#FFFFFF" opacity="1"'), 5)
        self.assertEqual(large.count('fill="#FFFFFF" opacity="1"'), 7)

    def test_the_simplified_svg_is_shipped_too(self):
        self.assertEqual(assets.asset_path("icon-small.svg").read_text(encoding="utf-8"), self.tool.svg_for(16))

    def test_the_16_pixel_png_comes_from_the_simplified_design(self):
        from PySide6.QtCore import QByteArray, QRectF
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgRenderer
        image = QImage(16, 16, QImage.Format.Format_ARGB32)
        image.fill(0)
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        QSvgRenderer(QByteArray(self.tool.svg_for(16).encode())).render(p, QRectF(0, 0, 16, 16))
        p.end()
        self.assertEqual(image, QImage(str(assets.asset_path("icon-16.png"))).convertToFormat(QImage.Format.Format_ARGB32))


class TestAssetsHelper(unittest.TestCase):
    def test_path_in_source(self):
        self.assertEqual(assets.assets_dir(), ROOT / "quill" / "assets")

    def test_path_in_a_frozen_build(self):
        sys._MEIPASS = "/bundle"
        try:
            self.assertEqual(assets.assets_dir(), pathlib.Path("/bundle/quill/assets"))
        finally:
            del sys._MEIPASS

    def test_the_qicon_offers_every_size(self):
        icon = assets.app_icon()
        self.assertFalse(icon.isNull())
        self.assertEqual({s.width() for s in icon.availableSizes()}, set(assets.ICON_SIZES))


class TestUsedByTheApp(unittest.TestCase):
    def test_the_app_sets_the_window_and_dock_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            _app.setWindowIcon(assets.app_icon().__class__())            # start from nothing
            self.assertTrue(_app.windowIcon().isNull())
            QuillApp(_app, Settings.load(pathlib.Path(tmp)), XlsxBridge(pathlib.Path(tmp) / "none.xlsx"),
                     listener_factory=lambda *a: None, model_finder=lambda c: None, sound_player=lambda p: None)
            self.assertFalse(_app.windowIcon().isNull())


class TestPackaging(unittest.TestCase):
    def test_both_specs_use_the_icons_and_ship_the_assets(self):
        mac = (ROOT / "packaging" / "quill_mac.spec").read_text()
        win = (ROOT / "packaging" / "quill_win.spec").read_text()
        self.assertIn('icon=r("quill", "assets", "Quill.icns")', mac)
        self.assertIn('icon=r("quill", "assets", "Quill.ico")', win)
        for spec in (mac, win):
            self.assertIn('(r("quill", "assets"), "quill/assets")', spec)

    def test_the_icon_files_are_not_git_ignored(self):
        import subprocess
        for name in ("Quill.icns", "Quill.ico", "icon.svg", "icon-1024.png"):
            result = subprocess.run(["git", "check-ignore", "-q", str(assets.asset_path(name))], cwd=ROOT,
                                    capture_output=True)
            self.assertEqual(result.returncode, 1, name)


if __name__ == "__main__":
    unittest.main()
