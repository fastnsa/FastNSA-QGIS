"""Discover a FastNSA runtime without importing QGIS or geospatial extras."""

from __future__ import annotations

import importlib
from importlib import metadata, util
from importlib.machinery import PathFinder
import json
import os
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_IMPORT_ROOT: str | None = None


class _RestartRequired(RuntimeError):
    """A different runtime may already own native objects in this process."""


def runtime_requirements() -> dict:
    policy = json.loads((PLUGIN_ROOT / "runtime-requirements.json").read_text(encoding="utf-8"))
    if (policy.get("schema_version") != 1 or policy.get("package") != "fastnsa"
            or not re.fullmatch(r"\d+\.\d+\.\d+", policy.get("version", ""))
            or type(policy.get("native_abi")) is not int or policy["native_abi"] < 1
            or not re.fullmatch(r"\d+\.\d+\.\d+", policy.get("numpy_min_version", ""))):
        raise ValueError("Invalid plugin runtime requirements.")
    return policy


def distribution_mode() -> str:
    marker = PLUGIN_ROOT / "distribution.json"
    if not marker.is_file():
        return "development"
    distribution = json.loads(marker.read_text(encoding="utf-8"))
    if (distribution.get("schema_version") != 1
            or distribution.get("mode") not in {"external", "bundled"}):
        raise ValueError("Invalid plugin distribution marker.")
    return distribution["mode"]


def default_runtime_root() -> Path | None:
    """Return the one versioned user directory documented in the install guide."""
    version = runtime_requirements()["version"]
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
    elif platform.system() == "Linux":
        base = Path.home() / ".local/share"
    else:
        return None
    return (base / "FastNSA" / f"runtime-{version}").resolve()


def runtime_has_been_loaded() -> bool:
    """Include partial imports; failing an import does not safely unload a DLL."""
    return _RUNTIME_IMPORT_ROOT is not None or any(
        module is not None and (name == "fastnsa" or name.startswith("fastnsa."))
        for name, module in tuple(sys.modules.items())
    )


def _check_loaded_location(root: Path):
    if _RUNTIME_IMPORT_ROOT is not None and Path(_RUNTIME_IMPORT_ROOT) != root:
        raise _RestartRequired(
            "FastNSA has already been started from another folder. "
            "Restart QGIS before choosing a different installation."
        )
    for name, module in tuple(sys.modules.items()):
        if module is None or not (name == "fastnsa" or name.startswith("fastnsa.")):
            continue
        origin = getattr(module, "__file__", None)
        if not origin or not Path(origin).resolve().is_relative_to(root / "fastnsa"):
            raise _RestartRequired(
                "QGIS is already using FastNSA from another folder. "
                "Restart QGIS before choosing a different installation."
            )


def _select_root(root: Path) -> str:
    root = root.expanduser().resolve()
    _check_loaded_location(root)
    if not (root / "fastnsa/__init__.py").is_file():
        raise ValueError(
            "FastNSA was not found in this folder. Choose the folder containing "
            "the fastnsa folder, not the fastnsa folder itself."
        )
    value = str(root)
    sys.path[:] = [value, *(entry for entry in sys.path if entry != value)]
    importlib.invalidate_caches()
    return value


def ensure_fastnsa_import_path(runtime_root: str | None = None) -> str | None:
    """Select an explicit, loaded, documented user, or environment runtime.

    Only the guide's exact versioned directory is searched outside sys.path;
    no ancestors, arbitrary home directories, or other environments are scanned.
    Old plugin-local files are ignored by source-only automatic discovery.
    """
    mode = distribution_mode()
    selected = str(PLUGIN_ROOT) if mode == "bundled" else (
        runtime_root or os.environ.get("FASTNSA_PYTHON_ROOT", "").strip()
    )
    if selected:
        return _select_root(Path(selected))
    loaded = sys.modules.get("fastnsa")
    if loaded is not None:
        origin = getattr(loaded, "__file__", None)
        if not origin:
            raise _RestartRequired("FastNSA was already opened in this session. Restart QGIS, then try setup again.")
        return _select_root(Path(origin).resolve().parent.parent)
    if runtime_has_been_loaded():
        raise _RestartRequired("An earlier attempt to load FastNSA did not finish. Restart QGIS before trying again.")
    default = default_runtime_root()
    if default is not None and (default / "fastnsa/__init__.py").is_file():
        return _select_root(default)
    importlib.invalidate_caches()
    spec = util.find_spec("fastnsa")
    if spec is not None and spec.origin:
        root = Path(spec.origin).resolve().parent.parent
        if mode != "external" or not root.is_relative_to(PLUGIN_ROOT):
            return _select_root(root)
        # A plugin directory can be on sys.path after an older bundled install.
        # Search existing external entries without importing the obsolete package.
        for entry in sys.path:
            candidate = PathFinder.find_spec("fastnsa", [entry])
            if candidate is not None and candidate.origin:
                root = Path(candidate.origin).resolve().parent.parent
                if not root.is_relative_to(PLUGIN_ROOT):
                    return _select_root(root)
    return None


def _installed_version(root: str) -> str | None:
    versions = []
    for distribution in metadata.distributions(path=[root], name="fastnsa"):
        if distribution.metadata.get("Name", "").lower() == "fastnsa":
            origin = Path(distribution.locate_file("fastnsa/__init__.py")).resolve()
            if origin == Path(root) / "fastnsa/__init__.py":
                versions.append(distribution.version)
    if len(versions) > 1:
        raise ValueError(
            "More than one FastNSA version was found in the same folder. "
            "Install FastNSA in a new, empty folder and select it in Runtime setup."
        )
    return versions[0] if versions else None


@dataclass(frozen=True)
class RuntimeDependencyStatus:
    available: bool
    python_root: str | None
    message: str
    code: str = "ready"
    runtime_version: str | None = None
    numpy_version: str | None = None
    native_abi: int | None = None
    native_library: str | None = None
    distribution: str = "development"
    restart_required: bool = False
    notices: tuple[str, ...] = ()


def check_runtime_dependencies(runtime_root: str | None = None) -> RuntimeDependencyStatus:
    """Check the exact tested package version, NumPy, import location, and ABI.

    No packages are installed. Imported Python/native modules are never unloaded
    or replaced; changing an already loaded runtime requires a QGIS restart.
    """
    global _RUNTIME_IMPORT_ROOT
    if sys.version_info < (3, 11):
        return RuntimeDependencyStatus(
            False, None,
            "FastNSA requires Python 3.11 or newer. "
            f"This QGIS installation uses Python {sys.version_info[0]}.{sys.version_info[1]}. "
            "Use a QGIS build with a supported Python runtime.",
            code="python_version",
        )
    original_path = list(sys.path)
    details = {"python_root": None}

    def unavailable(code, message):
        return RuntimeDependencyStatus(False, message=message, code=code, **details)

    try:
        policy = runtime_requirements()
        mode = distribution_mode()
        details["distribution"] = mode
        residue = mode == "external" and any(
            (PLUGIN_ROOT / name).exists() for name in ("fastnsa", "fastnsa.libs")
        )
        if residue:
            details["notices"] = (
                "Old FastNSA files remain inside the plugin folder and are ignored during automatic setup. "
                "No files have been deleted. To remove the old files, uninstall the plugin "
                "and reinstall the source-only ZIP.",
            )
        root = ensure_fastnsa_import_path(runtime_root)
        details["python_root"] = root
        if root is None:
            message = (
                "FastNSA is not installed, or QGIS cannot find it. Open Runtime setup > "
                "Installation Guide, follow the steps for your system, then click Check again."
            )
            if residue:
                message += " Old files inside the plugin folder were ignored, not loaded."
            return unavailable(
                "missing_package",
                message,
            )
        if mode == "external" and Path(root).is_relative_to(PLUGIN_ROOT):
            details["restart_required"] = runtime_has_been_loaded()
            return unavailable(
                "bundled_residue",
                ("QGIS is still using FastNSA from the previous plugin installation. Restart QGIS to use the separately installed package. "
                 if details["restart_required"] else
                 "This folder belongs to an old plugin installation. Choose the folder where you installed FastNSA separately. ")
                + "To remove old files, uninstall the plugin and reinstall the source-only ZIP.",
            )
        if mode != "development" and os.environ.get("FASTNSA_LIBRARY_PATH"):
            return unavailable(
                "library_override",
                "The FASTNSA_LIBRARY_PATH environment setting points to a custom analysis library. "
                "Remove this setting and restart QGIS to use this plugin's FastNSA installation.",
            )
        if mode == "bundled":
            info = json.loads((PLUGIN_ROOT / "build-info.json").read_text(encoding="utf-8"))
            version = info.get("runtime_version")
        else:
            version = _installed_version(root)
        development = mode == "development" and os.environ.get("FASTNSA_DEVELOPMENT_MODE") == "1"
        if version is None and development:
            version = importlib.import_module("fastnsa").__version__
        details["runtime_version"] = version
        accepted_development = development and version == policy["version"] + ".dev0"
        if version != policy["version"] and not accepted_development:
            details["restart_required"] = runtime_has_been_loaded()
            return unavailable(
                "package_version",
                f"This plugin needs FastNSA {policy['version']}; found "
                f"{version or 'an installation whose version could not be verified'}. "
                "Follow the Installation Guide to install the required version in a new folder, "
                "then click Check again. If QGIS was already using FastNSA, restart QGIS first.",
            )
        loaded = sys.modules.get("fastnsa")
        if loaded is not None and mode != "bundled":
            accepted_versions = {policy["version"]}
            if development:
                accepted_versions.add(policy["version"] + ".dev0")
            if getattr(loaded, "__version__", None) not in accepted_versions:
                details["restart_required"] = True
                return unavailable(
                    "restart_required",
                    "FastNSA has been updated, but QGIS is still using the previous version. "
                    "Restart QGIS to finish the update.",
                )
        # A pip --target directory must not replace QGIS's NumPy or Qt packages.
        sys.path[:] = original_path
        try:
            numpy = importlib.import_module("numpy")
        except Exception as exc:
            return unavailable(
                "missing_numpy",
                "QGIS could not load NumPy, which FastNSA needs. Repair NumPy using your "
                f"QGIS installer or environment manager, then try again. Details: {exc}",
            )
        details["numpy_version"] = numpy.__version__
        parsed = re.match(r"^(\d+)\.(\d+)\.(\d+)", numpy.__version__)
        minimum = tuple(int(part) for part in policy["numpy_min_version"].split("."))
        if parsed is None or tuple(map(int, parsed.groups())) < minimum:
            return unavailable(
                "numpy_version",
                f"FastNSA needs NumPy {policy['numpy_min_version']} or newer; "
                f"QGIS is using {numpy.__version__}. Use a QGIS installation with a compatible "
                "NumPy version. FastNSA does not change QGIS's NumPy installation.",
            )
        sys.path[:] = [root, *(entry for entry in sys.path if entry != root)]
        _RUNTIME_IMPORT_ROOT = root
        runtime = importlib.import_module("fastnsa.runtime")
        capi = importlib.import_module("fastnsa.bindings.capi")
        for module in (sys.modules["fastnsa"], runtime, capi):
            if not Path(module.__file__).resolve().is_relative_to(Path(root) / "fastnsa"):
                raise RuntimeError(
                    "QGIS is using files from more than one FastNSA installation. "
                    "Choose one installation folder and restart QGIS."
                )
        if not all(hasattr(runtime, name) for name in ("NativeNetwork", "NativePointSet")):
            raise ImportError("Required FastNSA analysis components are missing. Reinstall the FastNSA package.")
        details["native_abi"] = capi.NATIVE_ABI_VERSION
        details["native_library"] = str(Path(capi.lib._name).resolve())
        if capi.NATIVE_ABI_VERSION != policy["native_abi"]:
            details["restart_required"] = True
            return unavailable(
                "native_abi",
                "The FastNSA package and its analysis library do not match. "
                f"Reinstall fastnsa=={policy['version']} in a new folder and restart QGIS. "
                f"Compatibility details: required ABI {policy['native_abi']}, found {capi.NATIVE_ABI_VERSION}.",
            )
        if not development and not Path(details["native_library"]).is_relative_to(
            Path(root) / "fastnsa"
        ):
            raise RuntimeError(
                "QGIS loaded an analysis library from another FastNSA installation. "
                "Choose a clean installation folder and restart QGIS."
            )
        return RuntimeDependencyStatus(True, message="FastNSA is ready. You can open the analysis tools.", **details)
    except _RestartRequired as exc:
        details["restart_required"] = True
        return unavailable("restart_required", str(exc))
    except Exception as exc:
        details["restart_required"] = runtime_has_been_loaded()
        return unavailable(
            "runtime_error",
            "FastNSA could not be loaded. Check the Installation Guide, then try again. "
            f"Details ({platform.system()} {platform.machine()}): {exc}",
        )
    finally:
        # Packages retain __path__ for lazy submodules; do not shadow host packages.
        sys.path[:] = original_path


def require_runtime_dependencies(runtime_root: str | None = None) -> RuntimeDependencyStatus:
    """Raise an actionable import error when the selected runtime is unavailable."""
    status = check_runtime_dependencies(runtime_root)
    if not status.available:
        raise ImportError(status.message)
    return status
