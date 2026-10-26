"""Plugin bootstrap for FastNSA."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .gui.main_dialog import FastNSAMainDialog
from .provider import FastNsaProvider


class FastNsaPlugin:
    """QGIS plugin wrapper that registers the provider and opens the main UI."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        self.dialog = None
        self.menu_name = "&FastNSA"

    def initGui(self):
        """Register the Processing provider and plugin actions."""
        if self.provider is None:
            self.provider = FastNsaProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

        if self.action is None:
            icon = QIcon(str(Path(__file__).resolve().parent / "resources" / "icon.png"))
            self.action = QAction(icon, "Open FastNSA", self.iface.mainWindow())
            self.action.triggered.connect(self.open_main_dialog)
            self.iface.addToolBarIcon(self.action)
            self.iface.addPluginToMenu(self.menu_name, self.action)

    def unload(self):
        """Remove the provider and plugin actions when the plugin unloads."""
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

        if self.action is not None:
            self.iface.removePluginMenu(self.menu_name, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None

    def open_main_dialog(self):
        """Open the main FastNSA workflow dialog."""
        if self.dialog is None:
            self.dialog = FastNSAMainDialog(self.iface)

        self.dialog.show_active_task()
