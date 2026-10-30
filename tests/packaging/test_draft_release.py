"""Draft preparation and publication safeguards; never contacts GitHub."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from tests.packaging import test_plugin_archive as archives
from tests.packaging import test_release as release_tests

release = release_tests.release


with patch.dict("sys.modules", {"release_plugin": release, "validate_package": archives.validator}):
    draft = archives.load_tool("draft_release_under_test", "draft_release.py")


class DraftReleaseTest(unittest.TestCase):
    setUp = release_tests.ReleaseTest.setUp
    write_lock = release_tests.ReleaseTest.write_lock
    make_wheel = release_tests.ReleaseTest.make_wheel
    make_packages = release_tests.ReleaseTest.make_packages
    commit = release_tests.ReleaseTest.commit
    ref = release_tests.ReleaseTest.ref

    def inputs(self, root, legacy=False):
        self.make_packages(root / "platforms")
        source = archives.builder.build_archive(root / "source", distribution="external", source_commit=self.commit)
        if legacy:
            old = source
            source = source.with_name(source.name.replace("-source-only.zip", "-qgis-repository.zip"))
            old.rename(source)
            old.with_suffix(".build-info.json").rename(source.with_suffix(".build-info.json"))
            old.with_suffix(".zip.sha256").unlink()
            source.with_suffix(".zip.sha256").write_text(f"{release.sha256(source)}  {source.name}\n")
        archives.validator.validate_archive(source)
        summary = {"schema_version": 2, "archive": source.name, "archive_sha256": release.sha256(source),
                   "archive_source_commit": self.commit, "expected_source_commit": self.commit,
                   "local_gate": "passed", "status": "passed_with_warnings", "bandit_findings": 0,
                   "bandit_errors": 0, "unreviewed_potential_secrets": 0, "flake8_local_gate_errors": 0}
        security = root / "summary.json"
        security.write_text(json.dumps(summary))
        return source, security

    def prepare(self, root, legacy=False):
        source, security = self.inputs(root, legacy)
        output = root / "prepared"
        draft.prepare_assets(root / "source", root / "platforms", security, output,
                             self.commit, self.ref.removeprefix("refs/tags/"))
        summary = json.loads(security.read_text())
        renamed = next(output.glob("*-source-only.zip"))
        summary["archive"] = renamed.name
        security.write_text(json.dumps(summary))
        return source, security, output

    def test_legacy_rename_preserves_exact_zip_and_regenerates_sidecars(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, security, output = self.prepare(root, legacy=True)
            renamed = next(output.glob("*-source-only.zip"))
            self.assertEqual(source.read_bytes(), renamed.read_bytes())
            self.assertEqual(renamed.with_suffix(".zip.sha256").read_text(),
                             f"{release.sha256(source)}  {renamed.name}\n")
            report = json.loads(renamed.with_suffix(".validation.json").read_text())
            self.assertEqual(report["archive"], renamed.name)
            self.assertEqual(report["dependency_free_entry"], "passed")
            assets = draft.verify_assets(output, security, self.commit, self.ref.removeprefix("refs/tags/"))
            self.assertEqual(len(assets), 6)
            self.assertEqual(sum(p.suffix == ".zip" for p in assets), 3)

    def test_bad_security_summary_or_commit_cannot_be_prepared(self):
        for field, value in (("archive_sha256", "bad"), ("unreviewed_potential_secrets", 1),
                             ("bandit_errors", 1), ("archive_source_commit", "b" * 40)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, security = self.inputs(root)
                data = json.loads(security.read_text())
                data[field] = value
                security.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "Security summary"):
                    draft.prepare_assets(root / "source", root / "platforms", security,
                                         root / "out", self.commit, self.ref.removeprefix("refs/tags/"))
                self.assertFalse((root / "out").exists())

    def test_existing_outputs_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, security, output = self.prepare(root)
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                draft.prepare_assets(root / "source", root / "platforms", security,
                                     output, self.commit, self.ref.removeprefix("refs/tags/"))

    def test_tampered_prepared_assets_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, security, output = self.prepare(root)
            next(output.glob("*-source-only.zip")).write_bytes(b"tampered")
            with patch.object(draft, "gh") as remote:
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    draft.publish_draft(output, security, self.commit, self.ref.removeprefix("refs/tags/"))
            remote.assert_not_called()

    def test_published_release_is_never_downgraded_or_changed(self):
        with patch.object(draft, "gh_json", return_value=[[{"tag_name": "v0.1.1", "draft": False}]]):
            with self.assertRaisesRegex(ValueError, "published release"):
                draft.release_state("v0.1.1")

    def test_new_release_has_three_installers_and_checksums_but_stays_draft(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, security, output = self.prepare(root)
            assets = [p.name for p in output.iterdir() if p.suffix in {".zip", ".sha256"}]
            final = {"draft": True, "assets": [{"name": n} for n in assets], "html_url": "https://example.test/draft"}
            with patch.object(draft, "tag_commit", return_value=self.commit), \
                    patch.object(draft, "release_state", side_effect=[None, None, {"draft": True}, final]), \
                    patch.object(draft, "gh") as remote:
                result = draft.publish_draft(output, security, self.commit, self.ref.removeprefix("refs/tags/"))
            calls = [call.args for call in remote.call_args_list]
            self.assertIn("--verify-tag", calls[0])
            self.assertIn("--draft", calls[0])
            self.assertEqual(calls[1][:2], ("release", "upload"))
            self.assertNotIn("--clobber", calls[1])
            self.assertEqual(len(result["assets"]), 6)
            self.assertTrue(result["draft"])

    def test_existing_identical_assets_are_checked_not_uploaded_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, security, output = self.prepare(root)
            assets = [p.name for p in output.iterdir() if p.suffix in {".zip", ".sha256"}]
            state = {"draft": True, "assets": [{"name": n} for n in assets], "html_url": "https://example.test/draft"}

            def command(*args):
                if args[:2] == ("release", "download"):
                    name = args[args.index("--pattern") + 1]
                    directory = Path(args[args.index("--dir") + 1])
                    shutil.copyfile(output / name, directory / name)
                return ""

            with patch.object(draft, "tag_commit", return_value=self.commit), \
                    patch.object(draft, "release_state", return_value=state), \
                    patch.object(draft, "gh", side_effect=command) as remote:
                draft.publish_draft(output, security, self.commit, self.ref.removeprefix("refs/tags/"))
            calls = [call.args for call in remote.call_args_list]
            self.assertEqual(sum(args[:2] == ("release", "download") for args in calls), 6)
            self.assertEqual(sum(args[:2] == ("release", "edit") for args in calls), 1)
            self.assertFalse(any(args[:2] == ("release", "upload") for args in calls))

    def test_unrelated_existing_attachment_blocks_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, security, output = self.prepare(root)
            with patch.object(draft, "tag_commit", return_value=self.commit), \
                    patch.object(draft, "release_state", return_value={"draft": True, "assets": [{"name": "other.zip"}]}), \
                    patch.object(draft, "gh") as remote:
                with self.assertRaisesRegex(ValueError, "Unexpected existing"):
                    draft.publish_draft(output, security, self.commit, self.ref.removeprefix("refs/tags/"))
            remote.assert_not_called()

    def test_source_run_must_match_tag_and_have_all_required_checks(self):
        jobs = [{"name": name, "head_sha": self.commit, "conclusion": "success"} for name in (
            "checks / packaging-tests", "checks / Source-only QGIS repository candidate",
            "checks / QGIS package / Linux x86_64", "checks / QGIS package / Windows AMD64", "assemble")]
        run = {"head_sha": self.commit, "head_branch": "v0.1.1", "event": "push",
               "path": ".github/workflows/release.yml", "status": "completed", "conclusion": "success",
               "repository": {"full_name": draft.REPOSITORY}}
        with patch.object(draft, "tag_commit", return_value=self.commit), \
                patch.object(draft, "gh_json", side_effect=[run, {"total_count": len(jobs), "jobs": jobs}]):
            self.assertEqual(draft.inspect_run("v0.1.1", 123), self.commit)
        for change in ({"head_sha": "b" * 40}, {"head_branch": "main"}, {"event": "pull_request"}):
            with self.subTest(change=change), patch.object(draft, "tag_commit", return_value=self.commit), \
                    patch.object(draft, "gh_json", return_value={**run, **change}):
                with self.assertRaisesRegex(ValueError, "Source run"):
                    draft.inspect_run("v0.1.1", 123)
        jobs[-1]["conclusion"] = "failure"
        with patch.object(draft, "tag_commit", return_value=self.commit), \
                patch.object(draft, "gh_json", side_effect=[run, {"total_count": len(jobs), "jobs": jobs}]):
            with self.assertRaisesRegex(ValueError, "has not passed"):
                draft.inspect_run("v0.1.1", 123)


if __name__ == "__main__":
    unittest.main()
