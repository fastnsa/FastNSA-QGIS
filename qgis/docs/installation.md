# Installation

## Supported Candidate

The current QGIS candidate targets:

- Linux x86_64 and Windows AMD64 candidate archives;
- QGIS 3.34 or newer, using Qt5;
- Python 3.11 or newer in the QGIS environment;
- NumPy available in the QGIS Python environment;
- a compatible C++ system runtime.

CI generates Linux and Windows candidates from tested wheels and validates
their runtime in isolation. Windows RC4 smoke testing has been reported without
platform compatibility failures. Recent fixes require a newly built candidate
and another manual acceptance pass before public release. macOS QGIS archives
are not yet provided.

For internal testing, download the matching `fastnsa-qgis-rc5-*` artifact from
the successful GitHub Actions run and extract it. Install the inner
`fastnsa_qgis-0.1.0-rc5-*.zip`, not the outer GitHub artifact download ZIP.
The artifact also includes a SHA-256 sidecar, build information, and a runtime
validation report. A report marked `qgis_gui_acceptance: pending` is expected
until the manual checklist has been completed.

The Windows acceptance target is QGIS 3.34 with Python 3.12.7, NumPy 1.26.4,
and Qt 5.15.13. Initial testing on this host does not certify every workflow or
subsequent source change. Package CI tests Python 3.11/3.12 with NumPy 1.26.4;
QGIS 3.34 GUI and Processing acceptance remains a separate release gate.
QGIS 4.x and Qt6 compatibility has not yet been validated.

## Install from ZIP

1. Download the archive for the correct operating system and CPU architecture.
2. Open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the FastNSA ZIP and accept QGIS's installation prompt.
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
2. Install only the candidate ZIP.
3. Open the plugin and inspect its startup diagnostic.
4. Run nearest-edge matching on a small projected network.
5. Run one NKDV and one K-function analysis.
6. Restart QGIS and verify that the plugin and Processing provider load again.

If the plugin works only when the repository's `python/` directory is on
`PYTHONPATH`, the release archive is incomplete.

## Upgrading a Candidate

Disable or uninstall the old candidate before installing a ZIP with a changed
native library. Restart QGIS after replacement so the process does not retain
the previously loaded shared library. Use a separate test profile when
comparing two release candidates.

## Development Installation

Do not use an editable Python installation to validate a public plugin ZIP. It
can hide missing bundled modules and native libraries. Maintainer build and
source-testing steps are in the
[development guide](https://github.com/fastnsa/FastNSA-QGIS/blob/main/qgis/DEVELOPMENT.md),
which is intentionally excluded from the plugin archive.
