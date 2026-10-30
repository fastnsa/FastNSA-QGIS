"""Runtime discovery unit tests with fake modules; no native library or QGIS."""

import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "bootstrap_under_test", ROOT / "qgis/fastnsa_qgis/utils/bootstrap.py"
)
bootstrap = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {spec.name: bootstrap}):
    spec.loader.exec_module(bootstrap)


class RuntimeBootstrapTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.plugin = root / "plugin"
        self.plugin.mkdir()
        self.runtime = root / "runtime"
        package = self.runtime / "fastnsa"
        (package / "bindings").mkdir(parents=True)
        (package / "__init__.py").write_text("# Fake package; never executed.\n")
        (self.plugin / "runtime-requirements.json").write_text(
            (ROOT / "qgis/fastnsa_qgis/runtime-requirements.json").read_text()
        )
        self.marker("external")
        self.metadata("0.3.0")
        self.modules = {}
        for name, relative in (("fastnsa", "__init__.py"), ("fastnsa.runtime", "runtime.py"),
                               ("fastnsa.bindings", "bindings/__init__.py"),
                               ("fastnsa.bindings.capi", "bindings/capi.py")):
            module = types.ModuleType(name)
            module.__file__ = str(package / relative)
            module.__spec__ = importlib.util.spec_from_file_location(name, module.__file__)
            self.modules[name] = module
        self.modules["fastnsa"].__path__ = [str(package)]
        self.modules["fastnsa"].__version__ = "0.3.0"
        self.modules["fastnsa.runtime"].NativeNetwork = object
        self.modules["fastnsa.runtime"].NativePointSet = object
        self.modules["fastnsa.bindings.capi"].NATIVE_ABI_VERSION = 2
        self.modules["fastnsa.bindings.capi"].lib = types.SimpleNamespace(
            _name=str(package / "bindings/libfastnsa.so")
        )
        self.modules["numpy"] = types.SimpleNamespace(__version__="1.26.4")
        patchers = (
            patch.object(bootstrap, "PLUGIN_ROOT", self.plugin),
            patch.object(bootstrap, "_RUNTIME_IMPORT_ROOT", None),
            patch.object(bootstrap.Path, "home", return_value=root / "home"),
            patch.dict(sys.modules, self.modules),
            patch.dict(os.environ, {"FASTNSA_PYTHON_ROOT": "", "FASTNSA_LIBRARY_PATH": "",
                                    "FASTNSA_DEVELOPMENT_MODE": ""}),
        )
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def marker(self, mode):
        (self.plugin / "distribution.json").write_text(json.dumps({"schema_version": 1, "mode": mode}))

    def metadata(self, version):
        directory = self.runtime / "fastnsa-0.3.0.dist-info"
        directory.mkdir(exist_ok=True)
        (directory / "METADATA").write_text(f"Name: fastnsa\nVersion: {version}\n")

    @contextmanager
    def cold_runtime(self):
        """Simulate the first import without loading real native code."""
        original = bootstrap.importlib.import_module

        def load(name):
            if name.startswith("fastnsa"):
                sys.modules.update({key: value for key, value in self.modules.items()
                                    if key.startswith("fastnsa")})
                return self.modules[name]
            return original(name)

        with patch.dict(sys.modules), patch.object(bootstrap.importlib, "import_module", side_effect=load):
            for name in tuple(sys.modules):
                if name == "fastnsa" or name.startswith("fastnsa."):
                    del sys.modules[name]
            yield

    def test_installed_environment_package_is_discovered_without_custom_path(self):
        before = list(sys.path)
        status = bootstrap.check_runtime_dependencies()
        self.assertTrue(status.available, status.message)
        self.assertEqual(status.runtime_version, "0.3.0")
        self.assertEqual(status.native_abi, 2)
        self.assertEqual(status.python_root, str(self.runtime))
        self.assertEqual(sys.path, before)

    def test_explicit_runtime_directory_does_not_remain_on_sys_path(self):
        before = list(sys.path)
        status = bootstrap.check_runtime_dependencies(str(self.runtime))
        self.assertTrue(status.available, status.message)
        self.assertEqual(sys.path, before)

    def test_selected_runtime_directory_does_not_shadow_host_numpy(self):
        original = bootstrap.importlib.import_module
        def load(name):
            if name == "numpy":
                self.assertNotIn(str(self.runtime), sys.path)
            return original(name)
        with patch.object(bootstrap.importlib, "import_module", side_effect=load):
            status = bootstrap.check_runtime_dependencies(str(self.runtime))
        self.assertTrue(status.available, status.message)

    def test_missing_package_has_actionable_message(self):
        with patch.object(bootstrap, "ensure_fastnsa_import_path", return_value=None):
            status = bootstrap.check_runtime_dependencies()
        self.assertFalse(status.available)
        self.assertEqual(status.code, "missing_package")
        self.assertIn("Runtime setup", status.message)

    def test_wrong_package_version_is_rejected_before_loading_native_modules(self):
        self.metadata("0.2.0")
        with patch.object(bootstrap.importlib, "import_module") as load:
            status = bootstrap.check_runtime_dependencies()
        self.assertEqual(status.code, "package_version")
        self.assertIn("0.3.0", status.message)
        load.assert_not_called()

    def test_missing_and_old_numpy_are_diagnosed(self):
        original = bootstrap.importlib.import_module
        def load(name):
            if name == "numpy":
                raise ImportError("NumPy test fixture")
            return original(name)
        with patch.object(bootstrap.importlib, "import_module", side_effect=load):
            self.assertEqual(bootstrap.check_runtime_dependencies().code, "missing_numpy")
        self.modules["numpy"].__version__ = "1.22.0"
        self.assertEqual(bootstrap.check_runtime_dependencies().code, "numpy_version")

    def test_abi_mismatch_is_rejected(self):
        self.modules["fastnsa.bindings.capi"].NATIVE_ABI_VERSION = 999
        status = bootstrap.check_runtime_dependencies()
        self.assertEqual(status.code, "native_abi")
        self.assertIn("restart", status.message.lower())

    def test_mixed_modules_and_native_library_are_rejected(self):
        module = self.modules["fastnsa.runtime"]
        original = module.__file__
        module.__file__ = str(self.plugin / "unrelated/runtime.py")
        self.assertEqual(bootstrap.check_runtime_dependencies().code, "restart_required")
        module.__file__ = original
        self.modules["fastnsa.bindings.capi"].lib._name = str(self.plugin / "wrong.so")
        self.assertEqual(bootstrap.check_runtime_dependencies().code, "runtime_error")

    def test_loaded_runtime_is_never_hot_swapped(self):
        replacement = self.runtime.parent / "other"
        (replacement / "fastnsa").mkdir(parents=True)
        (replacement / "fastnsa/__init__.py").write_text("# Replacement\n")
        before = list(sys.path)
        status = bootstrap.check_runtime_dependencies(str(replacement))
        self.assertFalse(status.available)
        self.assertIn("Restart QGIS", status.message)
        self.assertIs(sys.modules["fastnsa"], self.modules["fastnsa"])
        self.assertEqual(sys.path, before)

    def test_upgraded_files_do_not_reuse_an_old_module_from_the_same_directory(self):
        self.modules["fastnsa"].__version__ = "0.2.0"
        with patch.object(bootstrap.importlib, "import_module") as load:
            status = bootstrap.check_runtime_dependencies()
        self.assertEqual(status.code, "restart_required")
        load.assert_not_called()

    def test_source_distribution_rejects_development_library_override(self):
        with patch.dict(os.environ, {"FASTNSA_LIBRARY_PATH": "/tmp/unapproved.so"}):
            self.assertEqual(bootstrap.check_runtime_dependencies().code, "library_override")

    def test_ancestor_python_directories_are_not_searched(self):
        nearby = self.plugin.parent / "python/fastnsa"
        nearby.mkdir(parents=True)
        (nearby / "__init__.py").write_text("# Must not be discovered\n")
        with self.cold_runtime(), patch.object(bootstrap.util, "find_spec", return_value=None):
            self.assertIsNone(bootstrap.ensure_fastnsa_import_path())

    def test_documented_user_target_is_discovered_without_restart(self):
        before = list(sys.path)
        with self.cold_runtime(), patch.object(bootstrap, "default_runtime_root", return_value=self.runtime):
            status = bootstrap.check_runtime_dependencies()
        self.assertTrue(status.available, status.message)
        self.assertFalse(status.restart_required)
        self.assertEqual(status.python_root, str(self.runtime))
        self.assertEqual(sys.path, before)

    def test_installing_into_documented_target_is_detected_on_check_again(self):
        with self.cold_runtime(), patch.object(bootstrap.util, "find_spec", return_value=None):
            self.assertEqual(bootstrap.check_runtime_dependencies().code, "missing_package")
            with patch.object(bootstrap, "default_runtime_root", return_value=self.runtime):
                self.assertTrue(bootstrap.check_runtime_dependencies().available)

    def test_default_targets_match_the_windows_and_linux_guides(self):
        with patch.object(bootstrap.platform, "system", return_value="Linux"):
            self.assertEqual(bootstrap.default_runtime_root(),
                             bootstrap.Path.home() / ".local/share/FastNSA/runtime-0.3.0")
        with patch.object(bootstrap.platform, "system", return_value="Windows"), \
                patch.dict(os.environ, {"APPDATA": str(self.runtime.parent / "roaming")}):
            self.assertEqual(bootstrap.default_runtime_root(),
                             self.runtime.parent / "roaming/FastNSA/runtime-0.3.0")

    def test_unloaded_old_plugin_files_do_not_block_external_runtime(self):
        (self.plugin / "fastnsa").mkdir()
        (self.plugin / "fastnsa/__init__.py").write_text("raise AssertionError('Old runtime was executed')\n")
        with self.cold_runtime(), patch.object(bootstrap, "default_runtime_root", return_value=self.runtime):
            status = bootstrap.check_runtime_dependencies()
        self.assertTrue(status.available, status.message)
        self.assertTrue(status.notices)
        self.assertFalse(status.restart_required)

    def test_unloaded_residue_is_skipped_when_searching_environment_paths(self):
        (self.plugin / "fastnsa").mkdir()
        old = self.plugin / "fastnsa/__init__.py"
        old.write_text("raise AssertionError('Old runtime was executed')\n")
        old_spec = importlib.util.spec_from_file_location("fastnsa", old)
        before = list(sys.path)
        with self.cold_runtime(), patch.object(sys, "path", [str(self.plugin), str(self.runtime), *before]), \
                patch.object(bootstrap.util, "find_spec", return_value=old_spec):
            status = bootstrap.check_runtime_dependencies()
        self.assertTrue(status.available, status.message)
        self.assertEqual(status.python_root, str(self.runtime))

    def test_unloaded_residue_without_external_runtime_is_an_installation_hint(self):
        (self.plugin / "fastnsa").mkdir()
        old = self.plugin / "fastnsa/__init__.py"
        old.write_text("# Never import this residue\n")
        old_spec = importlib.util.spec_from_file_location("fastnsa", old)
        original = bootstrap.PathFinder.find_spec
        with self.cold_runtime(), patch.object(bootstrap.util, "find_spec", return_value=old_spec), \
                patch.object(bootstrap.PathFinder, "find_spec", side_effect=(
                    lambda name, *args: None if name == "fastnsa" else original(name, *args)
                )):
            status = bootstrap.check_runtime_dependencies()
        self.assertEqual(status.code, "missing_package")
        self.assertTrue(status.notices)
        self.assertFalse(status.restart_required)
        self.assertIn("ignored", status.message)

    def test_explicit_missing_directory_does_not_silently_fall_back(self):
        with self.cold_runtime(), patch.object(bootstrap, "default_runtime_root", return_value=self.runtime):
            status = bootstrap.check_runtime_dependencies(str(self.runtime.parent / "missing"))
        self.assertFalse(status.available)
        self.assertFalse(status.restart_required)

    def test_loaded_old_plugin_runtime_still_requires_restart(self):
        for module in self.modules.values():
            if getattr(module, "__file__", "").startswith(str(self.runtime)):
                module.__file__ = module.__file__.replace(str(self.runtime), str(self.plugin))
        (self.plugin / "fastnsa").mkdir()
        (self.plugin / "fastnsa/__init__.py").write_text("# Old runtime\n")
        status = bootstrap.check_runtime_dependencies()
        self.assertEqual(status.code, "bundled_residue")
        self.assertTrue(status.restart_required)
        with patch.object(bootstrap.importlib, "import_module") as load:
            status = bootstrap.check_runtime_dependencies(str(self.runtime))
        self.assertEqual(status.code, "restart_required")
        load.assert_not_called()

    def test_partial_import_without_parent_package_cannot_be_hot_swapped(self):
        with patch.dict(sys.modules):
            del sys.modules["fastnsa"]
            status = bootstrap.check_runtime_dependencies(str(self.plugin.parent / "replacement"))
        self.assertEqual(status.code, "restart_required")
        self.assertTrue(status.restart_required)

    def test_failed_native_import_blocks_switching_even_if_python_modules_disappear(self):
        with self.cold_runtime(), patch.object(bootstrap, "_RUNTIME_IMPORT_ROOT", str(self.runtime)):
            status = bootstrap.check_runtime_dependencies(str(self.plugin.parent / "replacement"))
        self.assertEqual(status.code, "restart_required")
        self.assertTrue(status.restart_required)

    def test_existing_runtime_takes_precedence_over_a_new_default_target(self):
        with patch.object(bootstrap, "default_runtime_root", return_value=self.runtime.parent / "other"):
            status = bootstrap.check_runtime_dependencies()
        self.assertTrue(status.available, status.message)
        self.assertEqual(status.python_root, str(self.runtime))

    def test_actual_failed_native_import_prevents_switching_locations(self):
        original = bootstrap.importlib.import_module

        def load(name):
            if name == "fastnsa.runtime":
                raise OSError("Native loader fixture failure")
            return original(name)

        with self.cold_runtime(), patch.object(bootstrap.importlib, "import_module", side_effect=load):
            status = bootstrap.check_runtime_dependencies(str(self.runtime))
        self.assertEqual(status.code, "runtime_error")
        self.assertTrue(status.restart_required)
        self.assertEqual(bootstrap._RUNTIME_IMPORT_ROOT, str(self.runtime))
        replacement = self.runtime.parent / "another-runtime"
        with self.cold_runtime():
            status = bootstrap.check_runtime_dependencies(str(replacement))
        self.assertEqual(status.code, "restart_required")

    def test_bundled_mode_does_not_search_the_external_default_directory(self):
        self.marker("bundled")
        with patch.object(bootstrap, "default_runtime_root") as discover:
            status = bootstrap.check_runtime_dependencies()
        self.assertEqual(status.code, "restart_required")
        discover.assert_not_called()

    def test_old_bundled_runtime_inside_source_plugin_is_rejected(self):
        root = self.plugin
        (root / "fastnsa").mkdir()
        (root / "fastnsa/__init__.py").write_text("# Old runtime\n")
        with patch.object(bootstrap, "ensure_fastnsa_import_path", return_value=str(root)):
            self.assertEqual(bootstrap.check_runtime_dependencies().code, "bundled_residue")

    def test_development_checkout_requires_explicit_opt_in(self):
        (self.plugin / "distribution.json").unlink()
        (self.runtime / "fastnsa-0.3.0.dist-info/METADATA").unlink()
        self.modules["fastnsa"].__version__ = "0.3.0.dev0"
        self.assertEqual(bootstrap.check_runtime_dependencies().code, "package_version")
        with patch.dict(os.environ, {"FASTNSA_DEVELOPMENT_MODE": "1"}):
            self.assertTrue(bootstrap.check_runtime_dependencies().available)

    def test_unsupported_python_does_not_try_discovery(self):
        with patch.object(bootstrap.sys, "version_info", (3, 10, 0)), \
                patch.object(bootstrap, "ensure_fastnsa_import_path") as discover:
            self.assertEqual(bootstrap.check_runtime_dependencies().code, "python_version")
        discover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
