"""Prepare immutable tag-built installers and update only a GitHub Release draft."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import zipfile

import release_plugin as release
from validate_package import validate_archive


REPOSITORY = "fastnsa/FastNSA-QGIS"
MANIFEST = "DRAFT_ASSETS.json"


def gh(*arguments):
    result = subprocess.run(["gh", *map(str, arguments)], capture_output=True,
                            text=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"GitHub command failed: {arguments[:2]}: {result.stderr.strip()}")
    return result.stdout


def gh_json(*arguments):
    return json.loads(gh(*arguments))


def check_commit(commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full source commit SHA")


def tag_commit(tag):
    release.release_metadata(f"refs/tags/{tag}")
    obj = gh_json("api", f"repos/{REPOSITORY}/git/ref/tags/{tag}")["object"]
    for _ in range(5):
        check_commit(obj["sha"])
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            break
        obj = gh_json("api", f"repos/{REPOSITORY}/git/tags/{obj['sha']}")["object"]
    raise ValueError("Release tag does not resolve to a commit")


def inspect_run(tag, run_id):
    if run_id <= 0:
        raise ValueError("Expected a positive run ID")
    commit = tag_commit(tag)
    run = gh_json("api", f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if (run.get("head_sha") != commit or run.get("head_branch") != tag
            or run.get("event") != "push" or run.get("path") != ".github/workflows/release.yml"
            or run.get("repository", {}).get("full_name") != REPOSITORY
            or (run.get("status") == "completed" and run.get("conclusion") != "success")):
        raise ValueError("Source run must be the successful release-tag workflow for this commit")
    jobs = gh_json("api", f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs?per_page=100")
    if jobs.get("total_count") != len(jobs.get("jobs", [])):
        raise ValueError("Incomplete source-run job inventory")
    for suffix in ("packaging-tests", "Source-only QGIS repository candidate",
                   "QGIS package / Linux x86_64", "QGIS package / Windows AMD64", "assemble"):
        matches = [job for job in jobs["jobs"]
                   if job["name"] == suffix or job["name"].endswith(" / " + suffix)]
        if not matches or any(job.get("conclusion") != "success"
                              or job.get("head_sha") != commit for job in matches):
            raise ValueError(f"Required source-run job has not passed: {suffix}")
    return commit


def regular_files(directory):
    paths = list(Path(directory).rglob("*"))
    if any(path.is_symlink() for path in paths):
        raise ValueError("Symlinks are not permitted in draft inputs")
    files = [path for path in paths if path.is_file()]
    if len({path.name for path in files}) != len(files):
        raise ValueError("Duplicate draft input filenames")
    return files


def check_security(summary, archive, commit):
    if (summary.get("schema_version") != 2 or summary.get("archive") != archive.name
            or summary.get("archive_sha256") != release.sha256(archive)
            or summary.get("archive_source_commit") != commit
            or summary.get("expected_source_commit") != commit
            or summary.get("local_gate") != "passed"
            or summary.get("status") not in {"passed", "passed_with_warnings"}
            or any(summary.get(key) != 0 for key in (
                "bandit_findings", "bandit_errors", "unreviewed_potential_secrets",
                "flake8_local_gate_errors"))):
        raise ValueError("Security summary does not pass or does not match the source ZIP")


def check_source(archive, version, commit, lock):
    data_hash = release.sha256(archive)
    info = json.loads(archive.with_suffix(".build-info.json").read_text(encoding="utf-8"))
    report = json.loads(archive.with_suffix(".validation.json").read_text(encoding="utf-8"))
    if archive.with_suffix(".zip.sha256").read_text(encoding="ascii").split() != [data_hash, archive.name]:
        raise ValueError("Source ZIP checksum or checksum filename does not match")
    with zipfile.ZipFile(archive) as zipped:
        release_source_policy(zipped)
        embedded = json.loads(zipped.read("fastnsa_qgis/build-info.json"))
    if (embedded != info or info.get("source_commit") != commit
            or info.get("plugin_version") != version or info.get("distribution") != "external"
            or info.get("runtime_version_requirement") != lock["version"]
            or info.get("runtime_abi_requirement") != lock["native_abi"]
            or info.get("runtime_lock_verified") is not False
            or any(report.get(key) != value for key, value in info.items())
            or report.get("archive") != archive.name or report.get("archive_sha256") != data_hash
            or report.get("source_archive_check") != "passed"
            or report.get("dependency_free_entry") != "passed"):
        raise ValueError("Source ZIP build information or validation does not match the tag")
    return info


def release_source_policy(zipped):
    from package_policy import check_source_archive

    check_source_archive(zipped)
    if zipped.testzip() is not None:
        raise ValueError("Source ZIP CRC check failed")


def prepare_assets(source_dir, platform_dir, security_path, output_dir, commit, tag):
    check_commit(commit)
    version, _, notes, lock = release.release_metadata(f"refs/tags/{tag}")
    platform_files = regular_files(platform_dir)
    release._check_packages(platform_files, version, lock, commit)
    sources = regular_files(source_dir)
    archives = [path for path in sources if path.suffix == ".zip"]
    allowed = {f"fastnsa_qgis-{version}-{suffix}.zip" for suffix in ("qgis-repository", "source-only")}
    if len(archives) != 1 or archives[0].name not in allowed:
        raise ValueError("Expected exactly one source-only installer")
    original = archives[0]
    if set(sources) != {original, original.with_suffix(".zip.sha256"),
                        original.with_suffix(".build-info.json"), original.with_suffix(".validation.json")}:
        raise ValueError("Unexpected or missing source-only sidecars")
    info = check_source(original, version, commit, lock)
    check_security(json.loads(Path(security_path).read_text(encoding="utf-8")), original, commit)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise ValueError("Draft output already exists; refusing to overwrite")
    output_dir.mkdir(parents=True)
    for path in platform_files:
        shutil.copyfile(path, output_dir / path.name)
    renamed = output_dir / f"fastnsa_qgis-{version}-source-only.zip"
    shutil.copyfile(original, renamed)
    if release.sha256(renamed) != release.sha256(original):
        raise ValueError("Source installer bytes changed during copying")
    renamed.with_suffix(".zip.sha256").write_text(
        f"{release.sha256(renamed)}  {renamed.name}\n", encoding="ascii")
    renamed.with_suffix(".build-info.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    validate_archive(renamed, expected_distribution="external")
    shutil.copyfile(notes, output_dir / "RELEASE_NOTES.md")
    audit = {"original_archive": original.name, "renamed_archive": renamed.name,
             "archive_sha256": release.sha256(renamed), "zip_bytes_unchanged": True,
             "tagged_source_commit": commit, "preparation_commit": os.environ.get("GITHUB_SHA"),
             "original_validation_sha256": release.sha256(original.with_suffix(".validation.json"))}
    (output_dir / "SOURCE_RENAME.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    manifest = {"schema_version": 1, "tag": tag, "source_commit": commit,
                "files": [{"name": path.name, "sha256": release.sha256(path)}
                          for path in sorted(output_dir.iterdir())]}
    (output_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_assets(directory, security_path, commit, tag):
    directory = Path(directory)
    check_commit(commit)
    version, _, _, lock = release.release_metadata(f"refs/tags/{tag}")
    manifest = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("tag") != tag or manifest.get("source_commit") != commit:
        raise ValueError("Draft asset manifest does not match the release")
    records = manifest["files"]
    names = [row["name"] for row in records]
    if (len(names) != len(set(names)) or any(
            not name or Path(name).name != name or "/" in name or "\\" in name
            or name in {".", "..", MANIFEST} for name in names)
            or {p.name for p in regular_files(directory)} != set(names) | {MANIFEST}):
        raise ValueError("Unexpected or unsafe draft assets")
    for row in records:
        if release.sha256(directory / row["name"]) != row["sha256"]:
            raise ValueError("Draft asset checksum mismatch")
    platform_files = [directory / name for name in names
                      if any(name.startswith(f"fastnsa_qgis-{version}-{platform}") for platform in lock["wheels"])]
    release._check_packages(platform_files, version, lock, commit)
    source = directory / f"fastnsa_qgis-{version}-source-only.zip"
    check_source(source, version, commit, lock)
    check_security(json.loads(Path(security_path).read_text(encoding="utf-8")), source, commit)
    return sorted(p for p in directory.iterdir() if p.suffix in {".zip", ".sha256"})


def release_state(tag):
    pages = gh_json("api", f"repos/{REPOSITORY}/releases?per_page=100", "--paginate", "--slurp")
    matches = [row for page in pages for row in page if row.get("tag_name") == tag]
    if len(matches) > 1:
        raise ValueError("Multiple releases use the target tag")
    state = matches[0] if matches else None
    if state is not None and state.get("draft") is not True:
        raise ValueError("Refusing to change a published release; only drafts may be updated")
    return state


def publish_draft(directory, security_path, commit, tag):
    assets = verify_assets(directory, security_path, commit, tag)
    if len(assets) != 6 or tag_commit(tag) != commit:
        raise ValueError("Expected six verified download assets and the original tag commit")
    state = release_state(tag)
    wanted = {path.name: path for path in assets}
    existing = {row["name"] for row in state.get("assets", [])} if state else set()
    if existing - set(wanted):
        raise ValueError("Unexpected existing attachments; review them before changing the draft")
    with tempfile.TemporaryDirectory(prefix="fastnsa-draft-check-") as temporary:
        for name in sorted(existing):
            gh("release", "download", tag, "--repo", REPOSITORY,
               "--pattern", name, "--dir", temporary)
            if release.sha256(Path(temporary) / name) != release.sha256(wanted[name]):
                raise ValueError(f"Refusing to overwrite a different existing attachment: {name}")
    release_state(tag)
    notes = Path(directory) / "RELEASE_NOTES.md"
    title = f"FastNSA for QGIS {tag.removeprefix('v')}"
    if state:
        gh("release", "edit", tag, "--repo", REPOSITORY, "--draft=true",
           "--title", title, "--notes-file", notes)
    else:
        gh("release", "create", tag, "--repo", REPOSITORY, "--verify-tag", "--draft",
           "--title", title, "--notes-file", notes)
    missing = [str(path) for path in assets if path.name not in existing]
    if missing:
        release_state(tag)
        gh("release", "upload", tag, *missing, "--repo", REPOSITORY)
    state = release_state(tag)
    if state is None or {row["name"] for row in state.get("assets", [])} != set(wanted):
        raise ValueError("Draft attachment inventory is incomplete")
    return {"tag": tag, "draft": True, "assets": sorted(wanted), "url": state["html_url"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect-run")
    inspect.add_argument("--run-id", type=int, required=True)
    inspect.add_argument("--github-output", type=Path)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source-dir", type=Path, required=True)
    prepare.add_argument("--platform-dir", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--asset-dir", type=Path, required=True)
    for command in (prepare, publish):
        command.add_argument("--source-commit", required=True)
        command.add_argument("--security-summary", type=Path, required=True)
    for command in (inspect, prepare, publish):
        command.add_argument("--tag", required=True)
    args = parser.parse_args()
    if args.command == "inspect-run":
        commit = inspect_run(args.tag, args.run_id)
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as stream:
                stream.write(f"commit={commit}\nversion={args.tag.removeprefix('v')}\n")
        result = {"tag": args.tag, "source_commit": commit}
    elif args.command == "prepare":
        result = prepare_assets(args.source_dir, args.platform_dir, args.security_summary,
                                args.output_dir, args.source_commit, args.tag)
    else:
        result = publish_draft(args.asset_dir, args.security_summary, args.source_commit, args.tag)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
