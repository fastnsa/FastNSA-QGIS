"""Prepare and verify QGIS release artifacts; never upload or publish them."""

import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import zipfile

from package_plugin import REPO_ROOT, read_runtime_lock, target_platform


def release_metadata(ref=None):
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / "qgis/fastnsa_qgis/metadata.txt", encoding="utf-8")
    general = config["general"]
    version = general["version"]
    if not re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version):
        raise ValueError("A stable X.Y.Z plugin version is required.")
    if general.getboolean("experimental") or general.getboolean("deprecated"):
        raise ValueError("Stable release metadata must not be experimental or deprecated.")
    tag = f"v{version}"
    if ref and ref.startswith("refs/tags/") and ref != f"refs/tags/{tag}":
        raise ValueError("Release tag does not match plugin metadata.")
    notes = REPO_ROOT / "qgis/releases" / f"{version}.md"
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        raise ValueError("Release notes are missing or empty.")
    return version, tag, notes, read_runtime_lock()


def write_requirement(output):
    lock = read_runtime_lock()
    wheel = lock["wheels"][target_platform()]
    output.write_text(
        f"{lock['package']}=={lock['version']} --hash=sha256:{wheel['sha256']}\n",
        encoding="ascii",
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_packages(files, version, lock, commit):
    archives = sorted(path for path in files if path.suffix == ".zip")
    expected_names = {f"fastnsa_qgis-{version}-{target}.zip" for target in lock["wheels"]}
    if {path.name for path in archives} != expected_names or len(archives) != 2:
        raise ValueError("Expected exactly one Linux and one Windows plugin archive.")
    expected_files = set()
    for archive in archives:
        sidecars = {archive, archive.with_suffix(".zip.sha256"),
                    archive.with_suffix(".build-info.json"),
                    archive.with_suffix(".validation.json")}
        if not all(path.is_file() for path in sidecars):
            raise ValueError("Missing platform artifact sidecars.")
        expected_files.update(sidecars)
        info = json.loads(archive.with_suffix(".build-info.json").read_text(encoding="utf-8"))
        report = json.loads(archive.with_suffix(".validation.json").read_text(encoding="utf-8"))
        checksum = archive.with_suffix(".zip.sha256").read_text(encoding="ascii")
        if checksum != f"{sha256(archive)}  {archive.name}\n":
            raise ValueError("Plugin archive checksum mismatch.")
        with zipfile.ZipFile(archive) as zipped:
            if zipped.testzip() is not None:
                raise ValueError("Plugin archive CRC check failed.")
            for name in zipped.namelist():
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or "\\" in name
                        or not path.parts or path.parts[0] != "fastnsa_qgis"):
                    raise ValueError("Unsafe plugin archive member.")
            embedded = json.loads(zipped.read("fastnsa_qgis/build-info.json"))
            metadata = configparser.ConfigParser()
            metadata.read_string(zipped.read("fastnsa_qgis/metadata.txt").decode("utf-8"))
        if embedded != info or metadata["general"]["version"] != version:
            raise ValueError("Plugin metadata or embedded build information mismatch.")
        if (metadata["general"].getboolean("experimental")
                or metadata["general"].getboolean("deprecated")):
            raise ValueError("Packaged metadata is not a stable release.")
        target = archive.stem.removeprefix(f"fastnsa_qgis-{version}-")
        wheel = lock["wheels"][target]
        expected_system = "Linux" if target == "linux-x86_64" else "Windows"
        if (info.get("source_commit") != commit or info.get("plugin_version") != version
                or info.get("platform") != expected_system
                or info.get("architecture", "").lower() not in {"x86_64", "amd64"}
                or info.get("runtime_lock_verified") is not True
                or info.get("runtime_version") != lock["version"]
                or info.get("runtime_abi") != lock["native_abi"]
                or info.get("wheel") != wheel["filename"]
                or info.get("wheel_sha256") != wheel["sha256"]):
            raise ValueError("Plugin provenance does not match the release commit/runtime lock.")
        if (any(report.get(key) != value for key, value in info.items())
                or report.get("archive") != archive.name
                or report.get("archive_sha256") != sha256(archive)
                or report.get("native_abi") != lock["native_abi"]
                or report.get("runtime_smoke_test") != "passed"
                or report.get("qgis_gui_acceptance") not in {"pending", "passed"}):
            raise ValueError("Missing or inconsistent isolated runtime validation.")
    if set(files) != expected_files:
        raise ValueError("Unexpected or missing platform artifact sidecars.")


def assemble_release(input_dir, output_dir, commit, ref):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full source commit SHA.")
    version, tag, notes, lock = release_metadata(ref)
    files = sorted(path for path in input_dir.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in input_dir.rglob("*")):
        raise ValueError("Symlinks are not permitted in release artifacts.")
    if len({path.name for path in files}) != len(files):
        raise ValueError("Duplicate artifact filenames.")
    _check_packages(files, version, lock, commit)
    if output_dir.exists():
        raise ValueError("Release output directory already exists; refusing to overwrite.")
    output_dir.mkdir(parents=True)
    for path in files:
        shutil.copyfile(path, output_dir / path.name)
    shutil.copyfile(notes, output_dir / "RELEASE_NOTES.md")
    manifest = {
        "schema_version": 1,
        "plugin_version": version,
        "tag": tag,
        "source_commit": commit,
        "source_ref": ref,
        "runtime_lock": lock,
        "qgis_gui_acceptance": "pending",
        "files": [{"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}
                  for path in sorted(output_dir.iterdir())],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(output_dir.iterdir()))
    (output_dir / "SHA256SUMS").write_text(checksums, encoding="ascii")
    verify_release(output_dir, commit, ref)
    return manifest


def verify_release(bundle_dir, commit, ref):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected a full source commit SHA.")
    version, tag, notes, lock = release_metadata(ref)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != 1 or manifest.get("plugin_version") != version
            or manifest.get("tag") != tag or manifest.get("source_commit") != commit
            or manifest.get("source_ref") != ref or manifest.get("runtime_lock") != lock
            or manifest.get("qgis_gui_acceptance") != "pending"):
        raise ValueError("Release manifest provenance mismatch.")
    records = manifest["files"]
    names = [record["name"] for record in records]
    if len(names) != len(set(names)) or any(
        not name or Path(name).name != name or "/" in name or "\\" in name
        or name in {".", "..", "manifest.json", "SHA256SUMS"} for name in names
    ):
        raise ValueError("Unsafe or duplicate release filename.")
    expected_names = set(names) | {"manifest.json", "SHA256SUMS"}
    if {path.name for path in bundle_dir.iterdir()} != expected_names:
        raise ValueError("Unexpected or missing release bundle files.")
    if any(path.is_symlink() or not path.is_file() for path in bundle_dir.iterdir()):
        raise ValueError("Release bundle must contain regular files only.")
    for record in records:
        path = bundle_dir / record["name"]
        if sha256(path) != record["sha256"] or path.stat().st_size != record["size"]:
            raise ValueError(f"Release asset checksum mismatch: {path.name}")
    sums = "".join(f"{sha256(path)}  {path.name}\n" for path in sorted(bundle_dir.iterdir())
                   if path.name != "SHA256SUMS")
    if (bundle_dir / "SHA256SUMS").read_text(encoding="ascii") != sums:
        raise ValueError("Release checksum inventory mismatch.")
    if (bundle_dir / "RELEASE_NOTES.md").read_bytes() != notes.read_bytes():
        raise ValueError("Release notes do not match the source commit.")
    _check_packages([bundle_dir / name for name in names if name != "RELEASE_NOTES.md"],
                    version, lock, commit)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--github-output", type=Path)
    requirement = commands.add_parser("requirement")
    requirement.add_argument("--output", type=Path, required=True)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("--input-dir", type=Path, required=True)
    assemble.add_argument("--output-dir", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle-dir", type=Path, required=True)
    for command in (assemble, verify):
        command.add_argument("--source-commit", required=True)
        command.add_argument("--source-ref", required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        version, tag, _, _ = release_metadata(os.environ.get("GITHUB_REF"))
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as output:
                output.write(f"version={version}\ntag={tag}\n")
        print(json.dumps({"version": version, "tag": tag}))
    elif args.command == "requirement":
        write_requirement(args.output)
    elif args.command == "assemble":
        print(json.dumps(assemble_release(args.input_dir, args.output_dir, args.source_commit, args.source_ref)))
    else:
        print(json.dumps(verify_release(args.bundle_dir, args.source_commit, args.source_ref)))


if __name__ == "__main__":
    main()
