"""Exercise release assembly with synthetic archives; no native code is loaded."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.packaging import test_plugin_archive as archive_tests


builder = archive_tests.builder


with patch.dict("sys.modules", {"package_plugin": builder}):
    release = archive_tests.load_tool("plugin_release", "release_plugin.py")


class ReleaseTest(unittest.TestCase):
    setUp = archive_tests.PluginArchiveTest.setUp
    write_lock = archive_tests.PluginArchiveTest.write_lock
    make_wheel = archive_tests.PluginArchiveTest.make_wheel

    commit = "a" * 40
    ref = "refs/tags/v0.1.0"

    def make_packages(self, root):
        for system, machine in (("Linux", "x86_64"), ("Windows", "AMD64")):
            directory = root / system
            directory.mkdir(parents=True)
            with patch.object(builder.platform, "system", return_value=system), \
                    patch.object(builder.platform, "machine", return_value=machine):
                archive = builder.build_archive(
                    directory / "dist", wheel=self.make_wheel(directory), source_commit=self.commit
                )
            info = json.loads(archive.with_suffix(".build-info.json").read_text())
            report = {**info, "archive": archive.name, "archive_sha256": release.sha256(archive),
                      "native_abi": self.lock["native_abi"], "runtime_smoke_test": "passed",
                      "qgis_gui_acceptance": "pending"}
            archive.with_suffix(".validation.json").write_text(json.dumps(report))
            # Only the actual CI output files are inputs to release assembly.
            for path in (directory / "dist").iterdir():
                path.rename(directory / path.name)
            (directory / "dist").rmdir()
            (directory / self.lock["wheels"]["linux-x86_64" if system == "Linux" else "windows-amd64"]["filename"]).unlink()

    def test_requirement_contains_only_target_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "requirements.txt"
            release.write_requirement(output)
            wheel = self.lock["wheels"][builder.target_platform()]
            self.assertEqual(output.read_text(), f"fastnsa=={self.lock['version']} --hash=sha256:{wheel['sha256']}\n")

    def test_preflight_requires_matching_tag(self):
        version, tag, _, _ = release.release_metadata(self.ref)
        self.assertEqual(version, "0.1.0")
        self.assertEqual(tag, "v0.1.0")
        with self.assertRaisesRegex(ValueError, "tag does not match"):
            release.release_metadata("refs/tags/v0.1.1")

    def test_assemble_and_verify_both_platforms(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_packages(root / "packages")
            result = release.assemble_release(root / "packages", root / "release", self.commit, self.ref)
            self.assertEqual(len(result["files"]), 9)
            self.assertEqual(result["qgis_gui_acceptance"], "pending")
            self.assertEqual(result, release.verify_release(root / "release", self.commit, self.ref))
            self.assertTrue((root / "release/SHA256SUMS").is_file())
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                release.assemble_release(root / "packages", root / "release", self.commit, self.ref)

    def test_missing_platform_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_packages(root / "packages")
            next((root / "packages/Windows").glob("*.zip")).unlink()
            with self.assertRaisesRegex(ValueError, "one Linux and one Windows"):
                release.assemble_release(root / "packages", root / "release", self.commit, self.ref)

    def test_modified_provenance_or_report_is_rejected(self):
        cases = ((".build-info.json", "source_commit", "b" * 40),
                 (".validation.json", "runtime_smoke_test", "failed"),
                 (".validation.json", "native_abi", 999),
                 (".validation.json", "wheel_sha256", "f" * 64))
        for suffix, key, value in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.make_packages(root / "packages")
                path = next((root / "packages/Linux").glob(f"*{suffix}"))
                report = json.loads(path.read_text())
                report[key] = value
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    release.assemble_release(root / "packages", root / "release", self.commit, self.ref)

    def test_missing_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_packages(root / "packages")
            next((root / "packages/Linux").glob("*.validation.json")).unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                release.assemble_release(root / "packages", root / "release", self.commit, self.ref)

    def test_duplicate_artifact_filenames_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_packages(root / "packages")
            archive = next((root / "packages/Linux").glob("*.zip"))
            (root / "packages" / archive.name).write_bytes(archive.read_bytes())
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                release.assemble_release(root / "packages", root / "release", self.commit, self.ref)

    def test_verify_rejects_tampering_and_wrong_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_packages(root / "packages")
            release.assemble_release(root / "packages", root / "release", self.commit, self.ref)
            with self.assertRaisesRegex(ValueError, "provenance"):
                release.verify_release(root / "release", "b" * 40, self.ref)
            path = root / "release/RELEASE_NOTES.md"
            path.write_bytes(path.read_bytes() + b"tampered")
            with self.assertRaisesRegex(ValueError, "checksum"):
                release.verify_release(root / "release", self.commit, self.ref)

    def test_verify_rejects_unexpected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.make_packages(root / "packages")
            release.assemble_release(root / "packages", root / "release", self.commit, self.ref)
            (root / "release/unexpected.txt").write_text("extra")
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                release.verify_release(root / "release", self.commit, self.ref)

    def test_workflow_drafts_only_on_tag_push(self):
        workflow = (release.REPO_ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')", workflow)
        self.assertIn("--verify-tag --draft", workflow)
        self.assertIn("--notes-file release/RELEASE_NOTES.md", workflow)
        self.assertIn("release/SHA256SUMS release/RELEASE_NOTES.md", workflow)
        self.assertIn("contents: write", workflow)
        self.assertIn("git merge-base --is-ancestor", workflow)
        self.assertNotIn("secrets: inherit", workflow)
        self.assertNotIn("environment:", workflow)


if __name__ == "__main__":
    unittest.main()
