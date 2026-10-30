"""Dependency-free plugin lifecycle and non-modal runtime setup regressions."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QApplication, QMainWindow
    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python bindings are unavailable")
class RuntimeSetupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.qgis import qgis_test_application
        cls.app = qgis_test_application()

    def setUp(self):
        from fastnsa_qgis.plugin import FastNsaPlugin
        from fastnsa_qgis.utils.bootstrap import RuntimeDependencyStatus
        from fastnsa_qgis.gui import dependency_dialog
        self.status_type = RuntimeDependencyStatus
        self.settings = {}
        fake_settings = MagicMock()
        fake_settings.value.side_effect = lambda key, default="", **kwargs: self.settings.get(key, default)
        fake_settings.setValue.side_effect = self.settings.__setitem__
        for name in ("fastnsa_qgis.plugin.QgsSettings", "fastnsa_qgis.gui.dependency_dialog.QgsSettings"):
            patcher = patch(name, return_value=fake_settings)
            patcher.start()
            self.addCleanup(patcher.stop)
        loaded = patch("fastnsa_qgis.plugin.runtime_has_been_loaded", return_value=False)
        loaded.start()
        self.addCleanup(loaded.stop)
        self.window = QMainWindow()
        self.iface = MagicMock()
        self.iface.mainWindow.return_value = self.window
        self.plugin = FastNsaPlugin(self.iface)
        self.addCleanup(self.window.deleteLater)
        self.addCleanup(self.plugin.unload)

    def test_missing_runtime_still_registers_actions_and_opens_nonmodal_setup(self):
        status = self.status_type(False, None, "Install the FastNSA runtime.", code="missing_package")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=status), \
                patch.dict(sys.modules, {"fastnsa_qgis.provider": None,
                                         "fastnsa_qgis.gui.main_dialog": None}):
            self.plugin.initGui()
            self.assertIsNotNone(self.plugin.action)
            self.assertIsNotNone(self.plugin.runtime_action)
            self.assertIsNone(self.plugin.provider)
            self.plugin.open_main_dialog()
            dialog = self.plugin.runtime_dialog
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.windowModality(), Qt.NonModal)
            self.assertIsNone(QApplication.activeModalWidget())
            self.assertIn("Install", dialog.message.text())
            self.assertIsNone(self.plugin.dialog)

    def test_provider_registration_is_deferred_until_runtime_is_ready(self):
        missing = self.status_type(False, None, "Missing runtime", code="missing_package")
        ready = self.status_type(True, "/test/runtime", "Runtime ready")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", side_effect=[missing, ready]):
            self.plugin.initGui()
            self.assertIsNone(self.plugin.provider)
            self.assertTrue(self.plugin._ensure_runtime())
            self.assertEqual(len(self.plugin.provider.algorithms()), 4)

    def test_saved_path_is_applied_without_restart_before_first_import(self):
        status = self.status_type(False, None, "Missing runtime", code="missing_package")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=status) as check:
            self.plugin.initGui()
            self.plugin.open_runtime_setup()
            dialog = self.plugin.runtime_dialog
            with tempfile.TemporaryDirectory() as temporary:
                package = Path(temporary) / "fastnsa"
                package.mkdir()
                (package / "__init__.py").write_text("# Runtime fixture\n")
                dialog.path_edit.setText(temporary)
                check.return_value = self.status_type(True, temporary, "Runtime ready")
                dialog._save()
                self.assertEqual(self.settings["FastNSA/runtimePythonRoot"], str(Path(temporary).resolve()))
                self.assertEqual(self.plugin.runtime_root, str(Path(temporary).resolve()))
                self.assertEqual(len(self.plugin.provider.algorithms()), 4)
                self.assertIn("no restart", dialog.saved_message.text())

    def test_failed_setup_can_be_rechecked_after_manual_install(self):
        missing = self.status_type(False, None, "Missing runtime", code="missing_package")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=missing) as check:
            self.plugin.initGui()
            self.plugin.open_runtime_setup()
            dialog = self.plugin.runtime_dialog
            dialog._save()
            self.assertIsNone(self.plugin.provider)
            self.assertIn("not ready", dialog.saved_message.text())
            check.return_value = self.status_type(True, "/test/runtime", "Runtime ready")
            dialog.refresh()
            self.assertEqual(len(self.plugin.provider.algorithms()), 4)
            self.assertIn("Runtime ready", dialog.message.text())

    def test_changing_loaded_runtime_saves_for_restart_without_disabling_provider(self):
        ready = self.status_type(True, "/test/active", "Runtime ready")
        blocked = self.status_type(False, None, "Restart QGIS to switch runtime.",
                                   code="restart_required", restart_required=True)
        self.plugin.runtime_root = "/test/active"
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=ready) as check:
            self.plugin.initGui()
            self.plugin.open_runtime_setup()
            provider = self.plugin.provider
            dialog = self.plugin.runtime_dialog
            with tempfile.TemporaryDirectory() as temporary:
                package = Path(temporary) / "fastnsa"
                package.mkdir()
                (package / "__init__.py").write_text("# Runtime fixture\n")
                root = str(Path(temporary).resolve())
                check.side_effect = lambda selected: blocked if selected == root else ready
                dialog.path_edit.setText(temporary)
                dialog._save()
                self.assertEqual(self.settings["FastNSA/runtimePythonRoot"], root)
                self.assertEqual(self.plugin.runtime_root, "/test/active")
                self.assertIs(self.plugin.provider, provider)
                self.assertTrue(self.plugin.runtime_status.available)
                self.assertIn("Restart QGIS", dialog.saved_message.text())
                dialog.refresh()
                self.assertIn("Restart QGIS", dialog.message.text())
                self.assertIs(self.plugin.provider, provider)

    def test_partial_native_load_failure_is_saved_for_next_start(self):
        missing = self.status_type(False, None, "Missing runtime", code="missing_package")
        failure = self.status_type(False, "/test/broken", "Native load failed", code="runtime_error")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=missing):
            self.plugin.initGui()
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=failure), \
                patch("fastnsa_qgis.plugin.runtime_has_been_loaded", return_value=True):
            status = self.plugin.configure_runtime("/test/broken")
        self.assertTrue(status.restart_required)
        self.assertEqual(self.plugin.runtime_root, "")
        self.assertIsNone(self.plugin.provider)

    def test_bundled_runtime_cannot_be_overridden_in_setup(self):
        status = self.status_type(False, None, "Bundled diagnostic fixture", distribution="bundled")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=status):
            self.plugin.initGui()
            self.plugin.open_runtime_setup()
            self.assertFalse(self.plugin.runtime_dialog.path_edit.isEnabled())
            self.plugin.runtime_dialog._save()
            self.assertEqual(self.settings, {})

    def test_setup_uses_plain_labels_and_keeps_technical_details_for_support(self):
        status = self.status_type(False, "/test/runtime", "Install FastNSA to continue.",
                                  code="missing_package", distribution="external")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", return_value=status):
            self.plugin.initGui()
            self.plugin.open_runtime_setup()
            dialog = self.plugin.runtime_dialog
            self.assertEqual(dialog.windowTitle(), "FastNSA Setup")
            self.assertEqual(dialog.apply_button.text(), "Save and enable")
            details = dialog.details.toPlainText()
            self.assertIn("FastNSA installed separately", details)
            self.assertIn("Recommended installation folder", details)
            self.assertIn("Status code: missing_package", details)
            self.assertLess(details.index("Details for support"), details.index("Library compatibility (ABI)"))

    def test_headless_processing_does_not_require_iface_or_create_widgets(self):
        from fastnsa_qgis.plugin import FastNsaPlugin
        plugin = FastNsaPlugin(None)
        missing = self.status_type(False, None, "Missing runtime", code="missing_package")
        ready = self.status_type(True, "/test/runtime", "Runtime ready")
        with patch("fastnsa_qgis.plugin.check_runtime_dependencies", side_effect=[missing, ready]):
            try:
                plugin.initProcessing()
                self.assertIsNone(plugin.provider)
                plugin.initProcessing()
                self.assertEqual(len(plugin.provider.algorithms()), 4)
                self.assertIsNone(plugin.action)
                self.assertIsNone(plugin.runtime_dialog)
            finally:
                plugin.unload()


if __name__ == "__main__":
    unittest.main()
