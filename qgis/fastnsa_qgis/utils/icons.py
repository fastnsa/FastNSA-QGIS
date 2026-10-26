"""Multi-resolution FastNSA icons for menus, toolbars, and Processing."""

from pathlib import Path

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QIcon


ICON_SIZES = (16, 24, 32, 48, 64, 96, 128, 256)
_RESOURCE_DIRECTORY = Path(__file__).resolve().parents[1] / "resources"


def plugin_icon_path() -> str:
    """Return the large PNG used by plugin metadata and provider icon paths."""
    return str(_RESOURCE_DIRECTORY / "icon.png")


def plugin_icon() -> QIcon:
    """Let Qt select the supplied raster size for normal and high-DPI displays."""
    icon = QIcon()
    for size in ICON_SIZES:
        filename = "icon.png" if size == 256 else f"icon_{size}.png"
        icon.addFile(str(_RESOURCE_DIRECTORY / filename), QSize(size, size))
    return icon
