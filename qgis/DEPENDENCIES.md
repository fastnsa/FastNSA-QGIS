# FastNSA QGIS Runtime Dependencies

The self-contained archive bundles the FastNSA 0.3.0 Python runtime and native library.
NumPy and compatible operating-system C/C++ runtimes are supplied by the QGIS
or host environment.

## Required at runtime

- QGIS 3.34 through QGIS 3.x, using Qt5
- Python 3.11 or newer in the QGIS environment
- NumPy
- The platform-specific FastNSA native library bundled in the plugin archive
- a C++ runtime compatible with the packaged native library

The plugin does not require Pandas, GeoPandas, Shapely, NetworkX, or OSMnx.

## Optional at runtime

Matplotlib enables the interactive spatiotemporal 3D surface. If it is absent,
the plugin disables that view while keeping result tables, summaries, and 2D
views available. No other optional Python package is required by the four
published workflows.

## Platform compatibility

Each operating system and architecture needs its own native library and plugin
archive. Installing an archive for another platform or CPU architecture will
fail during the startup dependency check.

Linux x86_64 and Windows AMD64 archives are packaged from the exact PyPI wheels
pinned by filename, version, SHA-256, and native ABI in `runtime-lock.json`.
Linux uses a manylinux2014-built runtime. Windows uses a repaired AMD64 wheel
with its required bundled native dependencies. The Windows acceptance baseline
is QGIS 3.34, Python 3.12.7, NumPy 1.26.4, and Qt 5.15.13. Inspect the archive's
build and validation reports for provenance. Runtime CI does not replace QGIS
GUI acceptance. macOS plugin archives and QGIS 4/Qt6 remain unsupported.

The native-backed package is distributed through GitHub Releases. The
[official QGIS plugin repository requirements](https://plugins.qgis.org/docs/publish/)
prohibit bundled binaries and require external dependencies to be documented.
Do not submit the current native-backed ZIP there. A separate variant using
an externally installed FastNSA runtime would need dependency discovery,
version/ABI checks, installation instructions, and binary-free packaging.
That variant is not implemented; simply deleting the native library from the
current ZIP does not produce a working plugin.

The bundled runtime's source is available in the
[FastNSA v0.3.0 source release](https://github.com/fastnsa/FastNSA/tree/v0.3.0)
and the [PyPI source distribution](https://pypi.org/project/fastnsa/0.3.0/#files).

See the QGIS developer documentation for
[plugin structure](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)
and
[release validation](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/releasing.html).

Maintainer wheel-based archive creation steps are in the
[development guide](https://github.com/fastnsa/FastNSA-QGIS/blob/main/qgis/DEVELOPMENT.md).
They are not part of the installed plugin documentation.
