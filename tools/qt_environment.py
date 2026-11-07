"""Print what Qt sees on this machine (the offscreen platform): screen size, DPI, fonts. Used by the CI run, so a layout test that
fails only on one system can be explained by the numbers instead of guessed at."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QToolTip

app = QApplication([])
screen = app.primaryScreen()
font = app.font()
tip = QToolTip.font()
text = "Move cursor to the next row."
print("platform plugin :", app.platformName())
print("screen          :", screen.availableGeometry(), "dpr", screen.devicePixelRatio(), "logical dpi", screen.logicalDotsPerInch(),
      "physical dpi", screen.physicalDotsPerInch())
print("app font        :", font.family(), font.pointSizeF(), "px", font.pixelSize(), "->", QFontMetrics(font).horizontalAdvance(text), "px for the sample line")
print("tooltip font    :", tip.family(), tip.pointSizeF(), "px", tip.pixelSize(), "->", QFontMetrics(tip).horizontalAdvance(text), "px for the sample line")
