"""Source-only archives must never need or contain a native runtime."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.packaging import test_plugin_archive as archive_tests


builder = archive_tests.builder
validator = archive_tests.validator


class SourceArchiveTest(unittest.TestCase):
    def test_source_archive_needs_no_wheel_or_core_checkout_and_loads_without_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(builder, "PYTHON_SOURCE", root / "absent"), \
                    patch.object(builder, "target_platform", side_effect=AssertionError("No host selection")):
                archive = builder.build_archive(root / "dist", distribution="external")
            self.assertTrue(archive.name.endswith("-qgis-repository.zip"))
            with zipfile.ZipFile(archive) as zipped:
                names = zipped.namelist()
                self.assertFalse(any(name.startswith("fastnsa_qgis/fastnsa/") for name in names))
                info = json.loads(zipped.read("fastnsa_qgis/build-info.json"))
                self.assertEqual(info["distribution"], "external")
                self.assertEqual(info["platform"], "any")
            report = validator.validate_archive(archive)
            self.assertEqual(report["source_archive_check"], "passed")
            self.assertEqual(report["dependency_free_entry"], "passed")
            self.assertEqual(report["runtime_smoke_test"], "not_run_external_dependency")
            with self.assertRaisesRegex(ValueError, "expected distribution"):
                validator.validate_archive(archive, expected_distribution="bundled")

    def test_external_mode_rejects_native_or_wheel_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            for kwargs in ({"wheel": Path("runtime.whl")}, {"native_library": Path("native.so")}):
                with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "cannot include"):
                    builder.build_archive(Path(temporary), distribution="external", **kwargs)

    def test_stale_vendored_runtime_is_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            shutil.copytree(builder.PLUGIN_SOURCE, source)
            for folder in ("fastnsa", "fastnsa.libs"):
                (source / folder).mkdir()
                (source / folder / "old.so").write_bytes(b"\x7fELF")
            with patch.object(builder, "PLUGIN_SOURCE", source):
                archive = builder.build_archive(root / "dist", distribution="external")
            with zipfile.ZipFile(archive) as zipped:
                self.assertFalse(any("old.so" in name for name in zipped.namelist()))

    def test_compiled_or_nested_payloads_fail_even_with_innocent_names(self):
        cases = (("bad.dll", b"payload"), ("renamed.txt", b"\x7fELFrest"),
                 ("renamed.md", b"MZrest"), ("renamed.dat", b"PK\x03\x04rest"),
                 ("bad.so.1", b"payload"), ("cache.pyc", b"compiled"))
        for name, data in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = builder.build_archive(root / "dist", distribution="external")
                with zipfile.ZipFile(archive, "a") as zipped:
                    zipped.writestr("fastnsa_qgis/" + name, data)
                archive.with_suffix(".zip.sha256").write_text(
                    f"{builder.hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
                )
                with self.assertRaisesRegex(ValueError, "binary payload"):
                    validator.validate_archive(archive)

    def test_bad_source_is_rejected_by_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(builder.PLUGIN_SOURCE, root / "source")
            (root / "source/hidden-native.txt").write_bytes(b"MZpayload")
            with patch.object(builder, "PLUGIN_SOURCE", root / "source"):
                with self.assertRaisesRegex(ValueError, "binary payload"):
                    builder.build_archive(root / "dist", distribution="external")
            self.assertFalse(list((root / "dist").glob("*.zip")))

    def test_windows_incompatible_paths_and_duplicate_case_are_rejected(self):
        for name in ("fastnsa_qgis/unsafe:stream.txt", "fastnsa_qgis/../escape.txt",
                     "fastnsa_qgis//extra.txt", "fastnsa_qgis/readme.md"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = builder.build_archive(root / "dist", distribution="external")
                with zipfile.ZipFile(archive, "a") as zipped:
                    zipped.writestr(name, "Unexpected payload")
                archive.with_suffix(".zip.sha256").write_text(
                    f"{builder.hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
                )
                with self.assertRaises(ValueError):
                    validator.validate_archive(archive, expected_distribution="external")

    def test_existing_archive_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            archive = builder.build_archive(output, distribution="external")
            original = archive.read_bytes()
            with self.assertRaisesRegex(ValueError, "already exists"):
                builder.build_archive(output, distribution="external")
            self.assertEqual(archive.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
