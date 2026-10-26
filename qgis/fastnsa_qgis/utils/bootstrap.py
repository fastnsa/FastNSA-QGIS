"""Bootstrap helpers for making the local fastnsa package importable in QGIS."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path


def ensure_fastnsa_import_path() -> str | None:
    """Add a usable fastnsa Python root to ``sys.path`` for local testing.

    Resolution order:
    1. ``FASTNSA_PYTHON_ROOT`` environment variable
    2. a plugin-local vendored directory containing ``fastnsa``
    3. the repository ``python/`` directory discovered relative to this file
    """

    candidates: list[Path] = []

    env_root = os.environ.get("FASTNSA_PYTHON_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root))

    plugin_root = Path(__file__).resolve().parents[1]
    candidates.append(plugin_root)

    for parent in Path(__file__).resolve().parents:
        repo_python_root = parent / "python"
        candidates.append(repo_python_root)

    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str in seen:
            continue
        seen.add(candidate_str)

        if (candidate / "fastnsa").is_dir():
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return candidate_str

    return None


@dataclass(frozen=True)
class RuntimeDependencyStatus:
    available: bool
    python_root: str | None
    message: str


def check_runtime_dependencies() -> RuntimeDependencyStatus:
    """Check the minimal public-plugin runtime without importing geo extras."""
    if sys.version_info < (3, 11):
        return RuntimeDependencyStatus(
            False,
            None,
            "FastNSA requires Python 3.11 or newer. "
            f"This QGIS installation uses Python {sys.version_info[0]}.{sys.version_info[1]}. "
            "Use a QGIS build with a supported Python runtime.",
        )
    python_root = ensure_fastnsa_import_path()
    if python_root is None:
        return RuntimeDependencyStatus(
            False,
            None,
            "The bundled fastnsa runtime package was not found.",
        )

    try:
        import numpy  # noqa: F401
    except Exception as exc:
        return RuntimeDependencyStatus(
            False,
            python_root,
            f"NumPy is unavailable in the QGIS Python environment: {exc}",
        )

    try:
        from fastnsa.runtime import NativeNetwork  # noqa: F401
    except Exception as exc:
        system = platform.system() or "unknown platform"
        machine = platform.machine() or "unknown architecture"
        return RuntimeDependencyStatus(
            False,
            python_root,
            f"The FastNSA native runtime could not be loaded on {system}/{machine}: {exc}",
        )

    return RuntimeDependencyStatus(True, python_root, "FastNSA runtime is available.")


def require_runtime_dependencies() -> RuntimeDependencyStatus:
    """Raise an actionable import error when the minimal runtime is unavailable."""
    status = check_runtime_dependencies()
    if not status.available:
        raise ImportError(status.message)
    return status
