"""Check FastNSA icon decoding and Qt's multi-resolution image selection."""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QImage

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python bindings are unavailable")
class PluginIconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.qgis import qgis_test_application

        cls.app = qgis_test_application()

    def test_all_icon_images_decode_with_alpha(self):
        from fastnsa_qgis.utils.icons import ICON_SIZES, plugin_icon_path

        resources = Path(plugin_icon_path()).parent
        for size in ICON_SIZES:
            filename = "icon.png" if size == 256 else f"icon_{size}.png"
            with self.subTest(size=size):
                image = QImage(str(resources / filename))
                self.assertFalse(image.isNull())
                self.assertEqual(image.size(), QSize(size, size))
                self.assertTrue(image.hasAlphaChannel())

    def test_qt_icon_exposes_and_renders_each_supplied_resolution(self):
        from fastnsa_qgis.utils.icons import ICON_SIZES, plugin_icon

        icon = plugin_icon()
        self.assertFalse(icon.isNull())
        self.assertEqual(
            {(size.width(), size.height()) for size in icon.availableSizes()},
            {(size, size) for size in ICON_SIZES},
        )
        for size in ICON_SIZES:
            with self.subTest(size=size):
                self.assertEqual(icon.actualSize(QSize(size, size)), QSize(size, size))
                self.assertFalse(icon.pixmap(QSize(size, size)).isNull())

    def test_toolbar_and_provider_use_the_same_multiresolution_assets(self):
        from qgis.PyQt.QtWidgets import QMainWindow
        from fastnsa_qgis.plugin import FastNsaPlugin
        from fastnsa_qgis.utils.icons import ICON_SIZES, plugin_icon_path

        window = QMainWindow()
        iface = MagicMock()
        iface.mainWindow.return_value = window
        plugin = FastNsaPlugin(iface)
        expected = {(size, size) for size in ICON_SIZES}
        with patch("fastnsa_qgis.plugin.QgsApplication.processingRegistry"):
            try:
                plugin.initGui()
                for icon in (plugin.action.icon(), plugin.provider.icon()):
                    self.assertEqual(
                        {(size.width(), size.height()) for size in icon.availableSizes()},
                        expected,
                    )
                self.assertEqual(plugin.provider.iconPath(), plugin_icon_path())
                iface.addToolBarIcon.assert_called_once_with(plugin.action)
            finally:
                plugin.unload()
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
