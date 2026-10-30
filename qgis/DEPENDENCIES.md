# Software Requirements

FastNSA for QGIS supports Windows AMD64 and Linux x86_64 with QGIS 3.34
through 3.x. QGIS 4/Qt6 and macOS are not supported in this version.

## What You Need

- QGIS using Qt5 and Python 3.11 or newer.
- NumPy 1.23.5 or newer available to QGIS's Python.
- FastNSA 0.3.0, either included in the plugin ZIP or installed separately.
- A compatible system C++ runtime to load the FastNSA analysis library.

A normal QGIS installation usually includes NumPy. If it is missing or too
old, use your QGIS installer or environment manager to repair the
installation. Do not replace QGIS's shared packages just to install FastNSA.

The plugin does not require pandas, GeoPandas, Shapely, NetworkX, or OSMnx.

## Does FastNSA Need a Separate Installation?

**Self-contained Windows or Linux ZIP:** the matching FastNSA package and
analysis library are already included. Choose the ZIP for your operating
system and CPU.

**Source-only ZIP:** install `fastnsa==0.3.0` separately. Open
**Plugins > FastNSA > Runtime setup** for instructions and installation
status, or follow [Set Up FastNSA](docs/external-runtime.md).

Both installation types provide the same four analysis workflows. The plugin
does not download packages, run pip, or change QGIS's NumPy automatically.

## Optional 3D Views

Matplotlib adds interactive 3D views for spatiotemporal K-function results.
Without it, you can still use the maps, result tables, summaries, and 2D views.
Install Matplotlib in QGIS's Python environment only if you need the 3D views.

## If Something Is Missing

Open **Runtime setup** and follow the message on **Installation status**.
For a first installation, **Check again** or **Save and enable** can activate
the tools without restarting. If QGIS was already using another FastNSA
installation, save your work and restart when requested.

When asking for help in
[GitHub Issues](https://github.com/fastnsa/FastNSA-QGIS/issues), include your
QGIS and plugin versions and the setup message. The **Details for support**
section also includes library compatibility information and file locations.

FastNSA's analysis engine is open source:
[FastNSA source](https://github.com/fastnsa/FastNSA/tree/v0.3.0) and
[Python package](https://pypi.org/project/fastnsa/0.3.0/).

See [Installation](docs/installation.md) for package selection and upgrade
steps.
