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
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from package_policy import MAX_SOURCE_ARCHIVE_BYTES, check_source_archive

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = REPO_ROOT / "qgis" / "fastnsa_qgis"
PYTHON_SOURCE = REPO_ROOT / "python" / "fastnsa"
QGIS_DOCS_SOURCE = REPO_ROOT / "qgis" / "docs"
LICENSE_SOURCE = REPO_ROOT / "LICENSE"
RUNTIME_LOCK = REPO_ROOT / "runtime-lock.json"
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


def read_runtime_lock() -> dict:
    lock = json.loads(RUNTIME_LOCK.read_text(encoding="utf-8"))
    if (lock.get("schema_version") != 1 or lock.get("package") != "fastnsa"
            or not re.fullmatch(r"\d+\.\d+\.\d+", lock.get("version", ""))
            or type(lock.get("native_abi")) is not int or lock["native_abi"] < 1):
        raise ValueError("Invalid FastNSA runtime lock metadata.")
    wheels = lock.get("wheels", {})
    if set(wheels) != {"linux-x86_64", "windows-amd64"}:
        raise ValueError("Runtime lock must cover Linux x86_64 and Windows AMD64.")
    suffixes = {
        "linux-x86_64": "manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
        "windows-amd64": "win_amd64.whl",
    }
    for target, record in wheels.items():
        expected = f"fastnsa-{lock['version']}-py3-none-{suffixes[target]}"
        if (record.get("filename") != expected
                or not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", ""))):
            raise ValueError(f"Invalid locked wheel for {target}.")
    return lock


def target_platform() -> str:
    machine = platform.machine().lower()
    if machine not in {"x86_64", "amd64"} or platform.system() not in {"Linux", "Windows"}:
        raise ValueError(f"Unsupported plugin target: {platform.system()}/{machine}")
    return "linux-x86_64" if platform.system() == "Linux" else "windows-amd64"


def _native_library_name() -> str:
    return {
        "Linux": "libfastnsa.so",
        "Darwin": "libfastnsa.dylib",
        "Windows": "fastnsa.dll",
    }.get(platform.system(), "")


def _copy_plugin_tree(destination: Path):
    def ignore(directory, names):
        excluded = {name for name in names if name in {"__pycache__", ".git"}
                    or name.endswith((".pyc", ".pyo"))}
        if Path(directory) == PLUGIN_SOURCE:
            excluded.update(name for name in names if name in {
                "fastnsa", "fastnsa.libs", "distribution.json", "build-info.json"
            } or name.startswith("fastnsa-"))
        for name in set(names) - excluded:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f"Symlink in plugin source: {name}")
        return excluded

    shutil.copytree(
        PLUGIN_SOURCE,
        destination,
        ignore=ignore,
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
    lock = read_runtime_lock()
    record = lock["wheels"][target_platform()]
    if wheel_path.name != record["filename"]:
        raise ValueError(f"Wheel does not match the locked filename: {record['filename']}")
    wheel_sha256 = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    if wheel_sha256 != record["sha256"]:
        raise ValueError("Wheel SHA-256 does not match the runtime lock.")
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
        if metadata.get("Version") != lock["version"]:
            raise ValueError("Wheel version does not match the runtime lock.")

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
        "wheel_sha256": wheel_sha256,
        "runtime_version": metadata.get("Version"),
        "runtime_abi": lock["native_abi"],
        "runtime_lock_verified": True,
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
    distribution: str = "bundled",
) -> Path:
    if distribution not in {"bundled", "external"}:
        raise ValueError("Unknown plugin distribution mode.")
    if distribution == "external" and (native_library is not None or wheel is not None):
        raise ValueError("External-runtime packages cannot include a wheel or native library.")
    if distribution == "bundled" and (native_library is None) == (wheel is None):
        raise ValueError("Provide exactly one of native_library or wheel.")
    lock = read_runtime_lock()
    requirements = json.loads((PLUGIN_SOURCE / "runtime-requirements.json").read_text(encoding="utf-8"))
    if (requirements.get("package") != lock["package"] or requirements.get("version") != lock["version"]
            or requirements.get("native_abi") != lock["native_abi"]):
        raise ValueError("Plugin runtime requirements and runtime lock do not match.")
    config = configparser.ConfigParser()
    config.read(PLUGIN_SOURCE / "metadata.txt", encoding="utf-8")
    version = config.get("general", "version")
    platform_tag = (f"{platform.system().lower()}-{platform.machine().lower()}"
                    if distribution == "bundled" else "qgis-repository")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"fastnsa_qgis-{version}-{platform_tag}.zip"
    if archive_path.exists():
        raise ValueError("Plugin archive already exists; use a new output directory.")

    with tempfile.TemporaryDirectory(prefix="fastnsa-qgis-") as temporary_dir:
        package_root = Path(temporary_dir) / "fastnsa_qgis"
        _copy_plugin_tree(package_root)
        if distribution == "external":
            runtime_info = {
                "runtime_lock_verified": False,
                "runtime_version_requirement": requirements["version"],
                "runtime_abi_requirement": requirements["native_abi"],
            }
        elif wheel is not None:
            runtime_info = _copy_wheel_runtime(package_root / "fastnsa", wheel)
        else:
            _copy_runtime(package_root / "fastnsa", native_library)
            runtime_info = {
                "native_library_sha256": hashlib.sha256(native_library.read_bytes()).hexdigest(),
                "runtime_lock_verified": False,
                "runtime_version": requirements["version"],
                "runtime_abi": requirements["native_abi"],
            }
        _copy_release_docs(package_root)
        (package_root / "distribution.json").write_text(
            json.dumps({"schema_version": 1, "mode": distribution}, indent=2) + "\n",
            encoding="utf-8",
        )

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
            "distribution": distribution,
            "source_commit": commit,
            "platform": platform.system() if distribution == "bundled" else "any",
            "architecture": platform.machine() if distribution == "bundled" else "any",
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

        if distribution == "external":
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    check_source_archive(archive)
                if archive_path.stat().st_size > MAX_SOURCE_ARCHIVE_BYTES:
                    raise ValueError("Plugin source ZIP exceeds 25 MB.")
            except Exception:
                archive_path.unlink()
                raise

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
    parser.add_argument("--distribution", choices=("bundled", "external"), default="bundled")
    runtime_source = parser.add_mutually_exclusive_group()
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
        distribution=arguments.distribution,
    )
    print(archive)


if __name__ == "__main__":
    main()
