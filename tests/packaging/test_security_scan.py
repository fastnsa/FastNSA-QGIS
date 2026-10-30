"""Security report and archive safeguards without requiring scanner packages."""

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tests.packaging import test_plugin_archive as archive_tests


scanner = archive_tests.load_tool("security_scan_under_test", "scan_package.py")


class SecurityScanTest(unittest.TestCase):
    def setUp(self):
        self.bandit = {"results": [], "errors": [], "metrics": {"_totals": {"loc": 1}}}
        self.secrets = {"results": {}, "plugins_used": [{"name": "FixtureDetector"}]}
        self.codes = {"bandit": 0, "detect-secrets": 0, "flake8": 0}

    def summary(self, lint=""):
        return scanner.summarize(self.bandit, self.secrets, lint, self.codes)

    def test_clean_report_passes(self):
        self.assertEqual(self.summary()["status"], "passed")

    def test_style_findings_are_visible_not_claimed_as_a_clean_flake8_pass(self):
        self.codes["flake8"] = 1
        report = self.summary("fastnsa_qgis/plugin.py:1:80: E501 line too long\n")
        self.assertEqual(report["local_gate"], "passed")
        self.assertEqual(report["status"], "passed_with_warnings")
        self.assertEqual(report["flake8_by_code"], {"E501": 1})

    def test_any_unreviewed_bandit_finding_blocks(self):
        self.bandit["results"] = [{"test_id": "B112", "issue_severity": "LOW"}]
        self.codes["bandit"] = 1
        self.assertEqual(self.summary()["local_gate"], "failed")

    def test_bandit_parse_errors_block(self):
        self.bandit["errors"] = [{"filename": "bad.py", "reason": "syntax error"}]
        self.assertEqual(self.summary()["status"], "failed")

    def test_potential_secrets_block_even_when_the_scan_command_returns_zero(self):
        self.secrets["results"] = {"plugin.py": [{"type": "Fixture secret", "hashed_secret": "fixture"}]}
        self.assertEqual(self.summary()["potential_secrets"], 1)
        self.assertEqual(self.summary()["local_gate"], "failed")

    def commit_fixture(self):
        commit = "0bcda10093c77d8cd019d80a0ff41ef036ff9f6d"
        text = json.dumps({"source_commit": commit}, indent=2) + "\n"
        row = {
            "type": "Hex High Entropy String", "filename": "fastnsa_qgis/build-info.json",
            "hashed_secret": scanner.hashlib.sha1(commit.encode(), usedforsecurity=False).hexdigest(),
            "line_number": 2,
        }
        return commit, text, row

    def test_trusted_commit_is_reported_as_reviewed_not_hidden(self):
        commit, text, row = self.commit_fixture()
        self.secrets["results"] = {row["filename"]: [row]}
        reviewed = scanner.review_commit_findings(self.secrets, text, commit)
        report = scanner.summarize(self.bandit, self.secrets, "", self.codes, reviewed)
        self.assertEqual(report["potential_secrets"], 1)
        self.assertEqual(report["unreviewed_potential_secrets"], 0)
        self.assertEqual(len(report["reviewed_commit_hash_findings"]), 1)
        self.assertEqual(report["status"], "passed_with_warnings")
        self.assertEqual(self.secrets["results"][row["filename"]], [row])

    def test_commit_findings_without_an_external_expected_sha_still_block(self):
        _, text, row = self.commit_fixture()
        self.secrets["results"] = {row["filename"]: [row]}
        self.assertEqual(scanner.review_commit_findings(self.secrets, text, None), [])
        self.assertEqual(self.summary()["local_gate"], "failed")

    def test_unrelated_strings_or_secret_detectors_cannot_use_the_commit_review(self):
        commit, text, row = self.commit_fixture()
        cases = (
            {"filename": "fastnsa_qgis/other.json"},
            {"type": "Secret Keyword"},
            {"hashed_secret": "different-value"},
            {"line_number": 1},
            {"line_number": 200},
            {"line_number": True},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                changed = {**row, **changes}
                self.secrets["results"] = {changed["filename"]: [changed]}
                self.assertEqual(scanner.review_commit_findings(self.secrets, text, commit), [])
                self.assertEqual(self.summary()["local_gate"], "failed")
        self.secrets["results"] = {row["filename"]: [row]}
        same_value_other_field = json.dumps({"api_key": commit, "source_commit": commit}, indent=2)
        self.assertEqual(scanner.review_commit_findings(self.secrets, same_value_other_field, commit), [])

    def test_an_extra_secret_on_the_provenance_file_still_blocks(self):
        commit, text, row = self.commit_fixture()
        self.secrets["results"] = {row["filename"]: [row, {**row, "type": "Secret Keyword"}]}
        reviewed = scanner.review_commit_findings(self.secrets, text, commit)
        report = scanner.summarize(self.bandit, self.secrets, "", self.codes, reviewed)
        self.assertEqual(report["potential_secrets"], 2)
        self.assertEqual(report["unreviewed_potential_secrets"], 1)
        self.assertEqual(report["local_gate"], "failed")

    def test_invalid_or_mismatched_expected_commits_are_rejected(self):
        commit, text, _ = self.commit_fixture()
        for expected in ("working-tree", commit[:7], "b" * 40):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                scanner.review_commit_findings(self.secrets, text, expected)

    def test_python_name_and_syntax_errors_fail_the_local_lint_gate(self):
        for code in ("F401", "F821", "E999"):
            with self.subTest(code=code):
                self.codes["flake8"] = 1
                report = self.summary(f"fastnsa_qgis/plugin.py:1:1: {code} fixture issue\n")
                self.assertEqual(report["local_gate"], "failed")

    def test_empty_or_unrecognized_reports_do_not_pass(self):
        with self.assertRaisesRegex(ValueError, "Unrecognized Flake8"):
            self.summary("unexpected tool traceback")
        self.bandit["metrics"] = {}
        with self.assertRaisesRegex(ValueError, "did not report scanning"):
            self.summary()

    def test_no_detectors_is_not_a_clean_secrets_scan(self):
        self.secrets["plugins_used"] = []
        with self.assertRaisesRegex(ValueError, "Incomplete detect-secrets"):
            self.summary()

    def test_failed_tools_without_findings_are_not_treated_as_success(self):
        for name in ("bandit", "flake8"):
            with self.subTest(tool=name):
                self.codes = {"bandit": 0, "detect-secrets": 0, "flake8": 0}
                self.codes[name] = 1
                with self.assertRaisesRegex(ValueError, "failed without reporting"):
                    self.summary()

    def fake_run(self, command, **kwargs):
        self.assertEqual(command[1:3], ["-I", "-m"])
        self.assertTrue((Path(kwargs["cwd"]) / "fastnsa_qgis/metadata.txt").is_file())
        module = command[3]
        if module == "bandit":
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.bandit), stderr="")
        if module == "detect_secrets":
            self.assertIn("--all-files", command)
            self.assertIn("--no-verify", command)
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.secrets), stderr="")
        self.assertEqual(module, "flake8")
        self.assertIn("--isolated", command)
        self.assertIn("--disable-noqa", command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def test_scans_the_zip_records_its_hash_and_keeps_reports_outside_the_plugin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = archive_tests.builder.build_archive(root / "dist", distribution="external")
            before = archive.read_bytes()
            with patch.object(scanner.metadata, "version", return_value="fixture"), \
                    patch.object(scanner.subprocess, "run", side_effect=self.fake_run) as run:
                report = scanner.scan_archive(archive, root / "reports")
            self.assertEqual(run.call_count, 3)
            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["archive_sha256"], scanner.hashlib.sha256(before).hexdigest())
            self.assertFalse(report["credential_network_verification"])
            self.assertEqual(report["official_security_scan"], "not_run")
            self.assertGreater(report["python_files"], 0)
            self.assertTrue((root / "reports/summary.json").is_file())
            self.assertEqual(archive.read_bytes(), before)
            with zipfile.ZipFile(archive) as zipped:
                self.assertNotIn("fastnsa_qgis/scan_package.py", zipped.namelist())
                self.assertFalse(any("reports/" in name for name in zipped.namelist()))

    def test_existing_report_directory_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                scanner.scan_archive(root / "missing.zip", root)

    def test_committed_archive_review_preserves_raw_reports_and_zip(self):
        commit, _, row = self.commit_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = archive_tests.builder.build_archive(
                root / "dist", distribution="external", source_commit=commit,
            )
            before = archive.read_bytes()
            with zipfile.ZipFile(archive) as zipped:
                text = zipped.read(row["filename"]).decode("utf-8")
            row["line_number"] = next(
                index for index, line in enumerate(text.splitlines(), 1) if '"source_commit"' in line
            )
            self.secrets["results"] = {row["filename"]: [row]}
            with patch.object(scanner.metadata, "version", return_value="fixture"), \
                    patch.object(scanner.subprocess, "run", side_effect=self.fake_run):
                report = scanner.scan_archive(archive, root / "reports", expected_source_commit=commit)
            self.assertEqual(report["status"], "passed_with_warnings")
            self.assertEqual(report["expected_source_commit"], commit)
            self.assertEqual(report["potential_secrets"], 1)
            self.assertEqual(report["unreviewed_potential_secrets"], 0)
            self.assertEqual(json.loads((root / "reports/detect-secrets.json").read_text()), self.secrets)
            self.assertEqual(archive.read_bytes(), before)
            with patch.object(scanner.metadata, "version", return_value="fixture"), \
                    patch.object(scanner.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "does not match"):
                    scanner.scan_archive(archive, root / "mismatch", expected_source_commit="b" * 40)
            run.assert_not_called()

    def test_unsafe_archive_is_rejected_before_any_tool_is_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = archive_tests.builder.build_archive(root / "dist", distribution="external")
            with zipfile.ZipFile(archive, "a") as zipped:
                zipped.writestr("../escape.py", "print('must not be extracted')")
            with patch.object(scanner.metadata, "version", return_value="fixture"), \
                    patch.object(scanner.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "Unsafe source archive"):
                    scanner.scan_archive(archive, root / "reports")
            run.assert_not_called()
            self.assertFalse((root / "reports").exists())

    def test_tool_crash_cannot_produce_a_passing_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = archive_tests.builder.build_archive(root / "dist", distribution="external")
            with patch.object(scanner.metadata, "version", return_value="fixture"), \
                    patch.object(scanner.subprocess, "run", return_value=(
                        SimpleNamespace(returncode=2, stdout="", stderr="fixture tool error")
                    )):
                with self.assertRaisesRegex(ValueError, "failed to run"):
                    scanner.scan_archive(archive, root / "reports")
            self.assertFalse((root / "reports/summary.json").exists())

    def test_tool_timeout_cannot_produce_a_passing_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = archive_tests.builder.build_archive(root / "dist", distribution="external")
            with patch.object(scanner.metadata, "version", return_value="fixture"), \
                    patch.object(scanner.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 180)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    scanner.scan_archive(archive, root / "reports")
            self.assertFalse((root / "reports/summary.json").exists())

    def test_optional_matplotlib_uses_the_hosts_cache_configuration(self):
        source = (archive_tests.builder.PLUGIN_SOURCE / "gui/st_kfunction_dialog.py").read_text()
        self.assertNotIn("MPLCONFIGDIR", source)
        self.assertNotIn("/tmp/fastnsa-mpl", source)


if __name__ == "__main__":
    unittest.main()
