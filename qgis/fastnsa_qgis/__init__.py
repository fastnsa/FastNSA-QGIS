"""FastNSA QGIS plugin entry point."""


def classFactory(iface):
    """Load FastNsaPlugin from file plugin.py."""
    from .plugin import FastNsaPlugin

    return FastNsaPlugin(iface)
