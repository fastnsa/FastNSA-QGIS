# Install FastNSA for QGIS

These instructions describe version `0.1.1`, currently being prepared for
release. It is not yet available in the official QGIS plugin directory.

## Choose an Installation Package

| Package | Best for | Separate FastNSA installation? |
| --- | --- | --- |
| Self-contained Windows or Linux ZIP | Getting started with fewer setup steps | No |
| Source-only ZIP | Using a separate FastNSA installation | Yes, `fastnsa==0.3.0` |

Download released self-contained packages from
[GitHub Releases](https://github.com/fastnsa/FastNSA-QGIS/releases). Choose the
version you want to install and the archive for your system.

For version 0.1.1 test builds, the package names are:

| System | Self-contained package |
| --- | --- |
| Linux x86_64 | `fastnsa_qgis-0.1.1-linux-x86_64.zip` |
| Windows AMD64 | `fastnsa_qgis-0.1.1-windows-amd64.zip` |

The source-only test package is
`fastnsa_qgis-0.1.1-source-only.zip`. If downloading from GitHub Actions,
choose `fastnsa-official-repository-candidate`, extract the download, and use
the plugin ZIP inside it.

Do not install GitHub's automatically generated **Source code** ZIP or the
outer ZIP downloaded from Actions. If you want to check a download's
integrity, its matching `.zip.sha256` file contains the expected checksum.

## Requirements

- Windows AMD64 or Linux x86_64.
- QGIS 3.34 through QGIS 3.x with Qt5.
- Python 3.11 or newer and NumPy 1.23.5 or newer in QGIS.
- A compatible system C++ runtime for FastNSA's analysis library.

macOS and QGIS 4/Qt6 are not supported in this version. Matplotlib is optional
and only needed for interactive 3D surfaces.

You do not need pandas, GeoPandas, Shapely, NetworkX, or OSMnx to use the plugin.
See [Software Requirements](../DEPENDENCIES.md) for more detail.

## Install from ZIP

1. Open **Plugins > Manage and Install Plugins > Install from ZIP** in QGIS.
2. Select the plugin ZIP for your system and accept the installation prompt.
   Only install software from a source you trust.
3. In the **Installed** list, make sure **FastNSA** is checked.
4. Open FastNSA from its toolbar button or **Plugins > FastNSA**.
5. If the setup window opens, follow [Set Up FastNSA](external-runtime.md),
   then click **Check again**.
6. Once setup is complete, the four analysis tools appear under
   **Processing Toolbox > FastNSA**.

The self-contained ZIP already includes FastNSA 0.3.0. With the source-only
ZIP, install FastNSA separately using QGIS's Python or the recommended user
folder. The plugin does not download or install packages automatically.

For your first analysis, follow the [Quick Start](quickstart.md).

## Upgrade an Existing Installation

1. Finish or cancel any running FastNSA analysis and save your project.
2. Install the new plugin ZIP.
3. Restart QGIS before using the updated plugin.

If the installer says it succeeded but the FastNSA menu is missing, restart
QGIS and check that FastNSA is enabled in the **Installed** list. If it still
does not appear, see [Troubleshooting](troubleshooting.md).

When switching between self-contained and source-only packages, uninstall the
old plugin and close QGIS before installing the other type. They are
alternatives, not two plugins to install together in the same profile.
See [Set Up FastNSA](external-runtime.md) for the full steps.
