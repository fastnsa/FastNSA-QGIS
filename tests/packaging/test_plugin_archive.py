"""Check wheel provenance, native dependencies, and candidate integrity."""

import importlib.util
import configparser
import hashlib
import json
from pathlib import Path
import platform
import struct
import tempfile
import unittest
import zipfile
import zlib
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load_tool(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "qgis" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load_tool("candidate_builder", "package_plugin.py")
validator = load_tool("candidate_validator", "validate_package.py")


class PluginArchiveTest(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(builder.RUNTIME_LOCK.read_text(encoding="utf-8"))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lock_path = Path(directory.name) / "runtime-lock.json"
        self.write_lock()
        patcher = patch.object(builder, "RUNTIME_LOCK", self.lock_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_lock(self):
        self.lock_path.write_text(json.dumps(self.lock), encoding="utf-8")

    def test_icon_resources_are_valid_multiresolution_pngs(self):
        for size in (16, 24, 32, 48, 64, 96, 128, 256):
            filename = "icon.png" if size == 256 else f"icon_{size}.png"
            with self.subTest(size=size):
                data = (builder.PLUGIN_SOURCE / "resources" / filename).read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))
                self.assertEqual(data[25], 6, "Icons must preserve RGBA transparency")
                cursor = 8
                last_type = None
                while cursor < len(data):
                    self.assertGreaterEqual(len(data) - cursor, 12)
                    length = struct.unpack(">I", data[cursor:cursor + 4])[0]
                    end = cursor + length + 12
                    self.assertLessEqual(end, len(data))
                    payload = data[cursor + 4:end - 4]
                    checksum = struct.unpack(">I", data[end - 4:end])[0]
                    self.assertEqual(zlib.crc32(payload), checksum)
                    last_type = payload[:4]
                    cursor = end
                self.assertEqual(last_type, b"IEND")

    def test_metadata_describes_current_platforms_and_features(self):
        metadata = configparser.ConfigParser()
        metadata.read(builder.PLUGIN_SOURCE / "metadata.txt", encoding="utf-8")
        general = metadata["general"]
        for text in ("Linux x86_64", "Windows AMD64", "NS", "STARS", "NumPy", "Matplotlib"):
            self.assertIn(text, general["about"])
        self.assertEqual(general["qgisMinimumVersion"], "3.34")
        self.assertEqual(general["qgisMaximumVersion"], "3.99")
        self.assertTrue((builder.PLUGIN_SOURCE / general["icon"]).is_file())
        self.assertTrue(general["changelog"].strip())

    def test_stable_version_matches_release_docs(self):
        metadata = configparser.ConfigParser()
        metadata.read(builder.PLUGIN_SOURCE / "metadata.txt", encoding="utf-8")
        version = metadata["general"]["version"]
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")
        self.assertFalse(metadata["general"].getboolean("experimental"))
        workflow = (ROOT / ".github/workflows/multiplatform.yml").read_text(encoding="utf-8")
        for target in ("linux-x86_64", "windows-amd64"):
            self.assertIn(f"artifact: fastnsa-qgis-{target}", workflow)
        self.assertNotIn("FASTNSA_RUNTIME_PUBLISHED", workflow)
        self.assertIn("--require-hashes", workflow)
        self.assertIn("workflow_call:", workflow)
        for relative in ("README.md", "README_ZH.md", "docs/index.md", "docs/installation.md"):
            text = (ROOT / "qgis" / relative).read_text(encoding="utf-8")
            self.assertIn(version, text, msg=f"Outdated version in {relative}")
        self.assertTrue((ROOT / "qgis/releases" / f"{version}.md").is_file())

    def test_repository_links_target_the_standalone_plugin_repository(self):
        metadata = configparser.ConfigParser()
        metadata.read(builder.PLUGIN_SOURCE / "metadata.txt", encoding="utf-8")
        repository = "https://github.com/fastnsa/FastNSA-QGIS"
        self.assertEqual(metadata["general"]["repository"], repository)
        self.assertEqual(metadata["general"]["homepage"], repository)
        self.assertEqual(metadata["general"]["tracker"], repository + "/issues")
        for relative in ("README.md", "README_ZH.md", "DEPENDENCIES.md", "docs/installation.md"):
            text = (ROOT / "qgis" / relative).read_text(encoding="utf-8")
            self.assertIn(repository, text)
            self.assertNotIn("FastNSA" + "-dev", text)

    def make_wheel(self, directory, *, platform_tag=None, omit=None, metadata_version=None):
        target = builder.target_platform()
        version = self.lock["version"]
        filename = self.lock["wheels"][target]["filename"]
        if platform_tag is not None:
            filename = f"fastnsa-{version}-py3-none-{platform_tag}.whl"
        wheel = directory / filename
        with zipfile.ZipFile(wheel, "w") as archive:
            for relative in builder.RUNTIME_FILES:
                if relative == omit:
                    continue
                data = b'"""Synthetic runtime payload for archive tests."""\n'
                if relative == "enums.py":
                    data += b"\nWHEEL_BUILD_SENTINEL = True\n"
                archive.writestr(f"fastnsa/{relative}", data)
            archive.writestr(
                f"fastnsa/bindings/{builder._native_library_name()}", b"native-test-data"
            )
            archive.writestr("fastnsa.libs/dependency.dll", b"dependency-test-data")
            archive.writestr("fastnsa.libs/.load-order-fastnsa", "dependency.dll\n")
            archive.writestr(
                f"fastnsa-{version}.dist-info/METADATA",
                f"Name: fastnsa\nVersion: {metadata_version or version}\n",
            )
        # Tests lock their synthetic wheel; production builds use the checked-in lock.
        self.lock["wheels"][target]["sha256"] = hashlib.sha256(wheel.read_bytes()).hexdigest()
        self.write_lock()
        return wheel

    def test_candidate_uses_wheel_runtime_and_preserves_repaired_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wheel = self.make_wheel(directory)
            candidate = builder.build_archive(
                directory / "dist", wheel=wheel, source_commit="test-commit"
            )
            with zipfile.ZipFile(candidate) as archive:
                self.assertIn(
                    b"WHEEL_BUILD_SENTINEL", archive.read("fastnsa_qgis/fastnsa/enums.py")
                )
                self.assertEqual(
                    archive.read("fastnsa_qgis/fastnsa.libs/dependency.dll"),
                    b"dependency-test-data",
                )
                self.assertIn("fastnsa_qgis/fastnsa.libs/.load-order-fastnsa", archive.namelist())
                info = json.loads(archive.read("fastnsa_qgis/build-info.json"))
                self.assertEqual(info["source_commit"], "test-commit")
                self.assertEqual(info["runtime_version"], self.lock["version"])
                self.assertTrue(info["runtime_lock_verified"])
                self.assertEqual(info["runtime_abi"], self.lock["native_abi"])
                self.assertEqual(info["wheel_sha256"], self.lock["wheels"][builder.target_platform()]["sha256"])
                self.assertEqual(info["wheel"], wheel.name)
                source_metadata = configparser.ConfigParser()
                source_metadata.read(builder.PLUGIN_SOURCE / "metadata.txt", encoding="utf-8")
                packaged_metadata = configparser.ConfigParser()
                packaged_metadata.read_string(archive.read("fastnsa_qgis/metadata.txt").decode("utf-8"))
                self.assertEqual(info["plugin_version"], source_metadata["general"]["version"])
                self.assertEqual(packaged_metadata["general"], source_metadata["general"])
                for size in (16, 24, 32, 48, 64, 96, 128, 256):
                    filename = "icon.png" if size == 256 else f"icon_{size}.png"
                    self.assertEqual(
                        archive.read(f"fastnsa_qgis/resources/{filename}"),
                        (builder.PLUGIN_SOURCE / "resources" / filename).read_bytes(),
                    )
                for relative in (
                    "gui/processing_widgets.py", "utils/analysis_options.py",
                    "utils/processing_outputs.py", "README.md", "README_ZH.md",
                    "DEPENDENCIES.md", "docs/workflows.md",
                ):
                    self.assertIn(f"fastnsa_qgis/{relative}", archive.namelist())
                self.assertNotIn("fastnsa_qgis/RELEASING.md", archive.namelist())
                self.assertNotIn("fastnsa_qgis/DEVELOPMENT.md", archive.namelist())
            self.assertTrue(candidate.with_suffix(".zip.sha256").is_file())
            self.assertEqual(
                json.loads(candidate.with_suffix(".build-info.json").read_text()), info
            )

    def test_wrong_platform_wheel_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wheel = self.make_wheel(directory, platform_tag="unsupported_arch")
            with self.assertRaisesRegex(ValueError, "does not match"):
                builder.build_archive(directory / "dist", wheel=wheel)

    def test_modified_wheel_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wheel = self.make_wheel(directory)
            with wheel.open("ab") as output:
                output.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                builder.build_archive(directory / "dist", wheel=wheel)

    def test_mismatched_metadata_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wheel = self.make_wheel(directory, metadata_version="0.2.0")
            with self.assertRaisesRegex(ValueError, "version does not match"):
                builder.build_archive(directory / "dist", wheel=wheel)

    def test_invalid_lock_is_rejected(self):
        for key, value in (("version", "0.3.0\nmalicious"), ("native_abi", True),
                           ("wheels", {}), ("package", "other")):
            with self.subTest(key=key):
                original = self.lock[key]
                self.lock[key] = value
                self.write_lock()
                with self.assertRaises(ValueError):
                    builder.read_runtime_lock()
                self.lock[key] = original
        self.write_lock()

    def test_wheel_packaging_does_not_require_python_source_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with patch.object(builder, "PYTHON_SOURCE", directory / "absent-python-source"):
                wheel = self.make_wheel(directory)
                candidate = builder.build_archive(directory / "dist", wheel=wheel)
            with zipfile.ZipFile(candidate) as archive:
                self.assertEqual(archive.read("fastnsa_qgis/LICENSE"), builder.LICENSE_SOURCE.read_bytes())
                self.assertIn("fastnsa_qgis/fastnsa/runtime.py", archive.namelist())

    def test_incomplete_runtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wheel = self.make_wheel(directory, omit="runtime.py")
            with self.assertRaisesRegex(ValueError, "missing required runtime"):
                builder.build_archive(directory / "dist", wheel=wheel)

    def test_tampered_archive_is_rejected_before_native_load(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            candidate = builder.build_archive(
                directory / "dist", wheel=self.make_wheel(directory)
            )
            with candidate.open("ab") as archive:
                archive.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                validator.validate_archive(candidate)


if __name__ == "__main__":
    unittest.main()
