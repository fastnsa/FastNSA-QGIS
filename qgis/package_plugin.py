"""Build a platform-specific, self-contained FastNSA QGIS plugin archive."""

from __future__ import annotations

import argparse
import configparser
from datetime import datetime, timezone
from email.parser import Parser
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = REPO_ROOT / "qgis" / "fastnsa_qgis"
PYTHON_SOURCE = REPO_ROOT / "python" / "fastnsa"
QGIS_DOCS_SOURCE = REPO_ROOT / "qgis" / "docs"
LICENSE_SOURCE = REPO_ROOT / "LICENSE"
if not LICENSE_SOURCE.is_file():
    LICENSE_SOURCE = REPO_ROOT / "python" / "LICENSE"

RUNTIME_FILES = (
    "__init__.py",
    "enums.py",
    "exceptions.py",
    "runtime.py",
    "bindings/__init__.py",
    "bindings/_lib.py",
    "bindings/capi.py",
    "core/__init__.py",
    "core/types.py",
    "stats/__init__.py",
    "stats/k_function.py",
    "stats/network_kde.py",
)

RELEASE_DOCS = (
    (REPO_ROOT / "qgis" / "README.md", Path("README.md")),
    (REPO_ROOT / "qgis" / "README_ZH.md", Path("README_ZH.md")),
    (REPO_ROOT / "qgis" / "DEPENDENCIES.md", Path("DEPENDENCIES.md")),
    (LICENSE_SOURCE, Path("LICENSE")),
)


def _native_library_name() -> str:
    return {
        "Linux": "libfastnsa.so",
        "Darwin": "libfastnsa.dylib",
        "Windows": "fastnsa.dll",
    }.get(platform.system(), "")


def _copy_plugin_tree(destination: Path):
    shutil.copytree(
        PLUGIN_SOURCE,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


def _copy_runtime(destination: Path, native_library: Path):
    for relative_name in RUNTIME_FILES:
        source = PYTHON_SOURCE / relative_name
        target = destination / relative_name
        if not source.is_file():
            raise FileNotFoundError(f"Required runtime file is missing: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    library_name = _native_library_name()
    if not library_name:
        raise RuntimeError(f"Unsupported packaging platform: {platform.system()}")
    source_library = native_library
    if not source_library.is_file():
        raise FileNotFoundError(
            f"Native library is missing: {source_library}. "
            "Build libfastnsa for the target QGIS platform first."
        )
    shutil.copy2(source_library, destination / "bindings" / library_name)


def _copy_wheel_runtime(destination: Path, wheel_path: Path) -> dict:
    platform_tags = wheel_path.stem.rsplit("-", 1)[-1].split(".")
    system = platform.system()
    machine = platform.machine().lower()
    architecture = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    compatible = any(
        (system == "Linux" and tag.startswith(("manylinux", "linux_"))
         and tag.endswith(f"_{architecture}"))
        or (system == "Windows" and tag == {"x86_64": "win_amd64", "arm64": "win_arm64"}.get(architecture))
        or (system == "Darwin" and tag.startswith("macosx_")
            and tag.endswith((f"_{architecture}", "_universal2")))
        for tag in platform_tags
    )
    if not compatible:
        raise ValueError(f"Wheel does not match {system}/{machine}: {wheel_path.name}")

    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())
        library_name = _native_library_name()
        required = {f"fastnsa/{name}" for name in RUNTIME_FILES}
        required.add(f"fastnsa/bindings/{library_name}")
        missing = required - names
        if missing:
            raise ValueError(f"Wheel is missing required runtime files: {sorted(missing)}")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("Expected exactly one wheel metadata file.")
        metadata = Parser().parsestr(wheel.read(metadata_names[0]).decode("utf-8"))
        if metadata.get("Name", "").lower() != "fastnsa":
            raise ValueError("The wheel must contain the fastnsa package.")

        for name in sorted(names):
            if name.endswith("/"):
                continue
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError(f"Unsafe wheel member: {name}")
            # Keep repaired-wheel support directories, including DLL load-order
            # files. Their paths are relative to the package's patched loader.
            support_directory = path.parts[0].endswith(".libs") or (
                path.parts[0] == "fastnsa" and
                any(part in {".libs", ".dylibs"} for part in path.parts[1:])
            )
            native_file = path.parts[0] == "fastnsa" and (
                path.suffix.lower() in {".dll", ".so", ".dylib"} or ".so." in path.name
            )
            if name not in required and not support_directory and not native_file:
                continue
            target = destination.parent / Path(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(wheel.read(name))

    return {
        "wheel": wheel_path.name,
        "wheel_sha256": hashlib.sha256(wheel_path.read_bytes()).hexdigest(),
        "runtime_version": metadata.get("Version"),
    }


def _copy_release_docs(destination: Path):
    for source, relative_target in RELEASE_DOCS:
        if not source.is_file():
            raise FileNotFoundError(f"Required release document is missing: {source}")
        target = destination / relative_target
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    if not QGIS_DOCS_SOURCE.is_dir():
        raise FileNotFoundError(f"QGIS user documentation is missing: {QGIS_DOCS_SOURCE}")
    shutil.copytree(QGIS_DOCS_SOURCE, destination / "docs", dirs_exist_ok=True)


def build_archive(
    output_dir: Path,
    native_library: Path | None = None,
    *,
    wheel: Path | None = None,
    source_commit: str | None = None,
) -> Path:
    if (native_library is None) == (wheel is None):
        raise ValueError("Provide exactly one of native_library or wheel.")
    config = configparser.ConfigParser()
    config.read(PLUGIN_SOURCE / "metadata.txt", encoding="utf-8")
    version = config.get("general", "version")
    platform_tag = f"{platform.system().lower()}-{platform.machine().lower()}"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"fastnsa_qgis-{version}-{platform_tag}.zip"

    with tempfile.TemporaryDirectory(prefix="fastnsa-qgis-") as temporary_dir:
        package_root = Path(temporary_dir) / "fastnsa_qgis"
        _copy_plugin_tree(package_root)
        if wheel is not None:
            runtime_info = _copy_wheel_runtime(package_root / "fastnsa", wheel)
        else:
            _copy_runtime(package_root / "fastnsa", native_library)
            runtime_info = {
                "native_library_sha256": hashlib.sha256(native_library.read_bytes()).hexdigest(),
            }
        _copy_release_docs(package_root)

        commit = source_commit or os.environ.get("GITHUB_SHA")
        if not commit:
            try:
                commit = subprocess.check_output(
                    ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], text=True
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                commit = None
        build_info = {
            "plugin_version": version,
            "source_commit": commit,
            "platform": platform.system(),
            "architecture": platform.machine(),
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "ci_run_url": (
                f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
                f"/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                if all(os.environ.get(key) for key in (
                    "GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"
                )) else None
            ),
            **runtime_info,
        }
        info_text = json.dumps(build_info, indent=2) + "\n"
        (package_root / "build-info.json").write_text(info_text, encoding="utf-8")

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(package_root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(package_root.parent))

    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    archive_path.with_suffix(".zip.sha256").write_text(
        f"{checksum}  {archive_path.name}\n", encoding="ascii"
    )
    archive_path.with_suffix(".build-info.json").write_text(info_text, encoding="utf-8")

    return archive_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "qgis" / "dist",
    )
    runtime_source = parser.add_mutually_exclusive_group(required=True)
    runtime_source.add_argument(
        "--native-library",
        type=Path,
        help="Target-platform libfastnsa shared library produced by CMake.",
    )
    runtime_source.add_argument(
        "--wheel", type=Path,
        help="Tested target-platform FastNSA wheel to use for the bundled runtime.",
    )
    parser.add_argument("--source-commit", help="Source commit recorded in build-info.json.")
    arguments = parser.parse_args()
    archive = build_archive(
        arguments.output_dir, arguments.native_library,
        wheel=arguments.wheel, source_commit=arguments.source_commit,
    )
    print(archive)


if __name__ == "__main__":
    main()
