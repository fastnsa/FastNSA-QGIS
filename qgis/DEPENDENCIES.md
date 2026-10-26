# FastNSA QGIS Runtime Dependencies

The self-contained candidate archive bundles the FastNSA Python runtime and native library.
NumPy and compatible operating-system C/C++ runtimes are supplied by the QGIS
or host environment.

## Required at runtime

- QGIS 3.34 or newer, using Qt5
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

Linux x86_64 and Windows AMD64 candidate archives are packaged by CI from
tested wheels. Linux candidates use a manylinux2014-built runtime, not the
older Ubuntu-built RC2 library; historical RC2 GLIBC/GLIBCXX requirements must
not be applied to current candidates. Windows RC4 testing has been reported
on QGIS 3.34, Python 3.12.7, NumPy 1.26.4, and Qt 5.15.13 without platform
compatibility failures. Recent fixes still require a new candidate and manual
acceptance. Inspect each candidate's build and validation reports; neither a
successful wheel test nor an isolated runtime test replaces QGIS acceptance.
macOS native/wheel CI has passed, but macOS plugin archives remain deferred.

The current native-backed candidate is distributed through GitHub Releases or
another project-controlled channel. The
[official QGIS plugin repository requirements](https://plugins.qgis.org/docs/publish/)
prohibit bundled binaries and require external dependencies to be documented.
Do not submit the current native-backed ZIP there. A separate variant using
an externally installed FastNSA runtime would need dependency discovery,
version/ABI checks, installation instructions, and binary-free packaging.
That variant is not implemented; simply deleting the native library from the
current ZIP does not produce a working plugin.

See the QGIS developer documentation for
[plugin structure](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/plugins.html)
and
[release validation](https://docs.qgis.org/3.44/en/docs/pyqgis_developer_cookbook/plugins/releasing.html).

Maintainer wheel-based archive creation steps are in the
[development guide](https://github.com/fastnsa/FastNSA-QGIS/blob/main/qgis/DEVELOPMENT.md).
They are not part of the installed plugin documentation.
