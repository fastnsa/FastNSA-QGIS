# Installation

## Supported Platforms

FastNSA for QGIS `0.1.0` supports:

- Linux x86_64 and Windows AMD64 archives;
- QGIS 3.34 through QGIS 3.x, using Qt5;
- Python 3.11 or newer in the QGIS environment;
- NumPy available in the QGIS Python environment;
- a compatible C++ system runtime.

Download one of these assets from
[GitHub Releases](https://github.com/fastnsa/FastNSA-QGIS/releases):

| Platform | Installable archive |
| --- | --- |
| Linux x86_64 | `fastnsa_qgis-0.1.0-linux-x86_64.zip` |
| Windows AMD64 | `fastnsa_qgis-0.1.0-windows-amd64.zip` |

These archives bundle the checksum-verified FastNSA 0.3.0 runtime. No separate
FastNSA installation is needed. macOS plugin archives, QGIS 4.x, and Qt6 are not
supported. The Windows acceptance baseline is QGIS 3.34 with Python 3.12.7,
NumPy 1.26.4, and Qt 5.15.13.

Install the plugin ZIP, not GitHub's automatically generated **Source code** ZIP
or the outer ZIP downloaded from an Actions artifact. Checksums and build reports
are provided alongside release assets. Maintainer validation steps are in the
[release guide](https://github.com/fastnsa/FastNSA-QGIS/blob/main/qgis/RELEASING.md).

## Install from ZIP

1. Download the archive for the correct operating system and CPU architecture.
2. Open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the FastNSA ZIP and accept QGIS's installation prompt. Only install
   plugins from a source you trust; this package includes native code.
4. Enable **FastNSA** in the installed plugin list.
5. Confirm that the FastNSA toolbar action opens the main dialog.
6. Confirm that **Processing Toolbox > FastNSA** lists four algorithms.

Restart QGIS if the Processing provider does not appear immediately.

## Bundled and Host Dependencies

The plugin archive bundles the lightweight FastNSA Python runtime and the
platform-specific native library. It does not require pandas, GeoPandas,
Shapely, NetworkX, or OSMnx.

The QGIS/host environment supplies NumPy and operating-system runtime
libraries. Matplotlib is optional: it enables interactive ST 3D surfaces but
does not affect tables, summaries, 2D views, or other analyses.

See [DEPENDENCIES.md](../DEPENDENCIES.md) for platform requirements and current
distribution status.

## Clean-Profile Verification

Release validation should use a new QGIS profile without repository paths or
an editable FastNSA installation:

1. Start QGIS with a clean profile.
2. Install only the release ZIP.
3. Open the plugin and inspect its startup diagnostic.
4. Run nearest-edge matching on a small projected network.
5. Run one NKDV and one K-function analysis.
6. Restart QGIS and verify that the plugin and Processing provider load again.

If the plugin works only when the repository's `python/` directory is on
`PYTHONPATH`, the release archive is incomplete.

## Upgrading

Disable or uninstall the old plugin before installing a ZIP with a changed
native library. Restart QGIS after replacement so the process does not retain
the previously loaded shared library. Use a separate test profile when
comparing two plugin versions.

## Development Installation

Do not use an editable Python installation to validate a public plugin ZIP. It
can hide missing bundled modules and native libraries. Maintainer build and
source-testing steps are in the
[development guide](https://github.com/fastnsa/FastNSA-QGIS/blob/main/qgis/DEVELOPMENT.md),
which is intentionally excluded from the plugin archive.
