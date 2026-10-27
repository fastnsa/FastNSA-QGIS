# FastNSA for QGIS

FastNSA brings network-constrained spatial analysis to QGIS. It provides an
interactive analysis workspace and Processing Toolbox algorithms for exploring
point events on road networks.

## Features

| Workflow | Purpose | Outputs |
| --- | --- | --- |
| Nearest-edge matching | Locate events on the network | Matched points with reusable edge IDs and offsets |
| Network KDE / NKDV | Explore network density with ADA or LION | Density-valued line segments and graduated styles |
| Network K-function | Analyze spatial point patterns with NS or STARS | Result tables, charts, and Monte Carlo envelopes |
| Spatiotemporal network K-function | Analyze patterns across distance and time | Result tables, 2D surfaces, and optional Matplotlib 3D views |

The plugin supports temporary results, GeoPackage and CSV outputs, background
execution, progress reporting, and cooperative cancellation.

## Requirements

- QGIS 3.34 through QGIS 3.x, using Qt5.
- Python 3.11 or newer and NumPy in the QGIS environment.
- A plugin package matching the operating system and CPU architecture.

Version **0.1.0** targets Linux x86_64 and Windows AMD64. macOS plugin
packages and QGIS 4/Qt6 are not yet supported. Matplotlib is optional and enables
interactive 3D surfaces.

The installable ZIP includes the lightweight FastNSA 0.3.0 runtime. GeoPandas,
Shapely, NetworkX, and OSMnx are not required.

## Installation

1. Download the FastNSA plugin ZIP matching your operating system and architecture
   from [GitHub Releases](https://github.com/fastnsa/FastNSA-QGIS/releases).
2. In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the ZIP, enable **FastNSA**, and open it from the toolbar or plugin menu.

The four workflows are also available under **Processing Toolbox > FastNSA**.
A GitHub source-code ZIP is not an installable plugin package.

## Getting Started

1. Load a road line layer in a projected CRS and a point event layer.
2. Run **Fast Nearest Edge Matching** to prepare reusable event mappings.
3. Use the matched points with the same road network for density, K-function,
   or spatiotemporal K-function analysis.
4. Inspect styled layers and result viewers, then save the outputs you need.

Spatiotemporal analysis also requires an event time field. See the
[time-field guide](qgis/docs/time-fields.md) for supported formats and units.

## Documentation

- [User guide](qgis/docs/index.md)
- [Installation and dependencies](qgis/docs/installation.md)
- [Workflow parameters](qgis/docs/workflows.md)
- [Outputs and interpretation](qgis/docs/outputs-and-interpretation.md)
- [Troubleshooting](qgis/docs/troubleshooting.md)
- [Algorithm references](qgis/docs/references.md)
- [Chinese introduction](qgis/README_ZH.md)
- [Development guide](qgis/DEVELOPMENT.md)

## Support and License

Report bugs and feature requests through the
[issue tracker](https://github.com/fastnsa/FastNSA-QGIS/issues).
FastNSA for QGIS is licensed under [LGPL-2.1-only](LICENSE).
