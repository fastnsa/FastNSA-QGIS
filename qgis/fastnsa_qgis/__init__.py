"""FastNSA QGIS plugin entry point."""

from .utils.bootstrap import require_runtime_dependencies

require_runtime_dependencies()

from .plugin import FastNsaPlugin


def classFactory(iface):
    """Load FastNsaPlugin from file plugin.py."""
    return FastNsaPlugin(iface)
