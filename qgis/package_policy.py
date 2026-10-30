"""Structural checks shared by source-only plugin packaging and validation."""

from pathlib import PurePosixPath
import configparser
import json
import re
import stat


MAX_SOURCE_ARCHIVE_BYTES = 25_000_000
NATIVE_SUFFIXES = {
    ".dll", ".so", ".dylib", ".pyd", ".exe", ".o", ".obj", ".a", ".lib",
    ".whl", ".zip", ".pyc", ".pyo", ".7z", ".gz", ".tar",
}
NATIVE_MAGIC = {
    b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08",
    b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
}


def check_source_member(name: str, data: bytes):
    path = PurePosixPath(name)
    if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
            or path.as_posix() != name.rstrip("/")
            or not path.parts or path.parts[0] != "fastnsa_qgis"):
        raise ValueError(f"Unsafe source archive member: {name}")
    if any(part.startswith(".") or part in {"__pycache__", "__MACOSX"} for part in path.parts):
        raise ValueError(f"Hidden/development file in source archive: {name}")
    if len(path.parts) > 1 and (path.parts[1] == "fastnsa"
                               or path.parts[1].startswith(("fastnsa.libs", "fastnsa-"))):
        raise ValueError(f"Bundled runtime in external-runtime archive: {name}")
    if (path.suffix.lower() in NATIVE_SUFFIXES or re.search(r"\.so(?:\.|$)", path.name.lower())
            or data[:4] in NATIVE_MAGIC or data[:2] == b"MZ"):
        raise ValueError(f"Compiled or nested binary payload in source archive: {name}")


def check_source_archive(archive):
    names = archive.namelist()
    if len(names) != len({name.casefold() for name in names}):
        raise ValueError("Duplicate source archive member names.")
    if sum(info.file_size for info in archive.infolist()) > MAX_SOURCE_ARCHIVE_BYTES:
        raise ValueError("Source archive exceeds the 25 MB unpacked safety limit.")
    required = {f"fastnsa_qgis/{name}" for name in (
        "__init__.py", "plugin.py", "metadata.txt", "LICENSE", "README.md",
        "runtime-requirements.json", "distribution.json", "docs/external-runtime.md",
    )}
    if not required.issubset(names):
        raise ValueError(f"Missing source archive files: {sorted(required - set(names))}")
    for info in archive.infolist():
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"Symlink in source archive: {info.filename}")
        check_source_member(info.filename, archive.read(info) if not info.is_dir() else b"")
    requirements = json.loads(archive.read("fastnsa_qgis/runtime-requirements.json"))
    if (requirements.get("schema_version") != 1 or requirements.get("package") != "fastnsa"
            or type(requirements.get("native_abi")) is not int or requirements["native_abi"] < 1
            or not re.fullmatch(r"\d+\.\d+\.\d+", requirements.get("version", ""))
            or not re.fullmatch(r"\d+\.\d+\.\d+", requirements.get("numpy_min_version", ""))):
        raise ValueError("Invalid source runtime requirements.")
    marker = json.loads(archive.read("fastnsa_qgis/distribution.json"))
    if marker != {"schema_version": 1, "mode": "external"}:
        raise ValueError("Source archive must declare an external runtime.")
    metadata = configparser.ConfigParser()
    metadata.read_string(archive.read("fastnsa_qgis/metadata.txt").decode("utf-8"))
    if metadata.get("general", "category") != "Vector" or "external" not in metadata.get("general", "about").lower():
        raise ValueError("Source metadata must state its external dependency and Vector category.")
