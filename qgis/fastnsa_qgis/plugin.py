"""Plugin bootstrap for FastNSA."""

from dataclasses import replace

from qgis.PyQt.QtWidgets import QAction
from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsSettings

from .utils.bootstrap import check_runtime_dependencies, runtime_has_been_loaded
from .utils.icons import plugin_icon


class FastNsaPlugin:
    """QGIS plugin wrapper that registers the provider and opens the main UI."""

    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.action = None
        self.dialog = None
        self.runtime_dialog = None
        self.runtime_action = None
        self.runtime_status = None
        self.pending_runtime_status = None
        self.runtime_root = QgsSettings().value("FastNSA/runtimePythonRoot", "", type=str)
        self.menu_name = "&FastNSA"

    def initGui(self):
        """Register the Processing provider and plugin actions."""
        if self.action is None:
            self.action = QAction(plugin_icon(), "Open FastNSA", self.iface.mainWindow())
            self.action.triggered.connect(self.open_main_dialog)
            self.iface.addToolBarIcon(self.action)
            self.iface.addPluginToMenu(self.menu_name, self.action)

        if self.runtime_action is None:
            self.runtime_action = QAction(plugin_icon(), "Runtime setup...", self.iface.mainWindow())
            self.runtime_action.triggered.connect(self.open_runtime_setup)
            self.iface.addPluginToMenu(self.menu_name, self.runtime_action)
        if not self._ensure_runtime():
            QgsMessageLog.logMessage(self.runtime_status.message, "FastNSA", Qgis.Warning)

    def initProcessing(self):
        """Register algorithms in a Processing host without constructing widgets."""
        if not self._ensure_runtime():
            QgsMessageLog.logMessage(self.runtime_status.message, "FastNSA", Qgis.Warning)

    def _ensure_runtime(self):
        return self._activate_runtime(check_runtime_dependencies(self.runtime_root or None))

    def configure_runtime(self, root):
        """Save a selection and activate it only if no runtime swap is required."""
        QgsSettings().setValue("FastNSA/runtimePythonRoot", root)
        status = check_runtime_dependencies(root or None)
        if status.restart_required or (not status.available and runtime_has_been_loaded()):
            # Keep a running provider and its current settings intact.
            self.pending_runtime_status = replace(status, restart_required=True)
            return self.pending_runtime_status
        self.pending_runtime_status = None
        self.runtime_root = root
        self._activate_runtime(status)
        return self.runtime_status

    def _activate_runtime(self, status):
        self.runtime_status = status
        if not self.runtime_status.available:
            return False
        if self.provider is None:
            try:
                from .provider import FastNsaProvider

                provider = FastNsaProvider()
                if not QgsApplication.processingRegistry().addProvider(provider):
                    raise RuntimeError("Processing registry rejected the provider")
            except Exception as exc:
                self.runtime_status = replace(
                    self.runtime_status, available=False, code="processing_provider",
                    message=f"The runtime is available, but FastNSA algorithms could not be registered: {exc}",
                )
                return False
            self.provider = provider
        return True

    def open_runtime_setup(self):
        """Open diagnostics without importing NumPy, FastNSA, or the analysis UI."""
        from .gui.dependency_dialog import RuntimeSetupDialog

        if self.runtime_dialog is None:
            self.runtime_dialog = RuntimeSetupDialog(self, self.iface.mainWindow())
        self.runtime_dialog.refresh()
        self.runtime_dialog.show()
        self.runtime_dialog.raise_()
        self.runtime_dialog.activateWindow()

    def unload(self):
        """Remove the provider and plugin actions when the plugin unloads."""
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

        if self.runtime_dialog is not None:
            self.runtime_dialog.close()
            self.runtime_dialog.deleteLater()
            self.runtime_dialog = None

        if self.runtime_action is not None:
            self.iface.removePluginMenu(self.menu_name, self.runtime_action)
            self.runtime_action.deleteLater()
            self.runtime_action = None

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
        if not self._ensure_runtime():
            self.open_runtime_setup()
            return
        if self.dialog is None:
            from .gui.main_dialog import FastNSAMainDialog

            self.dialog = FastNSAMainDialog(self.iface)

        self.dialog.show_active_task()
