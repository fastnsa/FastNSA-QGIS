# FastNSA QGIS User Guide

FastNSA provides native-accelerated network spatial analysis through both a
workflow-oriented dialog and the QGIS Processing Toolbox. This guide documents
version `0.1.0`.

## Start Here

- [Installation](installation.md): platform support, dependencies, and clean
  installation checks.
- [Quick Start](quickstart.md): prepare layers, preprocess events, and run a
  first analysis.
- [Analysis Workflows](workflows.md): parameters, methods, and practical
  guidance for all four published workflows.
- [Time Fields](time-fields.md): date/time, numeric, and Unix timestamp handling
  for spatiotemporal analysis.
- [Outputs and Interpretation](outputs-and-interpretation.md): result fields,
  styles, charts, Monte Carlo envelopes, and persistence.
- [Troubleshooting](troubleshooting.md): dependency, CRS, mapping, performance,
  cancellation, and native crash diagnostics.
- [Algorithm References](references.md): publications and research artifacts
  behind the implemented methods.

The [Chinese plugin overview](../README_ZH.md) and
[Chinese time-field guide](TIME_GUIDE_ZH.md) are retained as supplementary
translations. The English documents above are the primary release
documentation.

## Published Workflows

| Workflow | Main outputs | Available methods |
| --- | --- | --- |
| Fast Nearest Edge Matching | Matched points; optional projected points and connector lines | R-tree, approximate/refined grid compression |
| Fast Network KDE | Lixel line layer with density values | LION, ADA; Epanechnikov kernel |
| Fast Network K-Function | Temporary result table, chart, optional CSV | NS (exact), STARS (approximate) |
| Fast Spatiotemporal Network K-Function | Result table, surface viewer, optional CSV | EARTH, MTS, EAR, SPS, RQS |

Spatiotemporal NKDE, OSM downloading, pause/resume, and saved viewer packages
are not included in this release.

## Two Entry Points

The **FastNSA main dialog** is intended for interactive analysis. It provides
task cards, a run summary, activity logs, non-modal background execution,
charts, and ST surface views.

The **Processing Toolbox** algorithms are intended for models, batch workflows,
and reproducible parameterized runs. Processing produces standard QGIS sinks
and tables but does not open the main-dialog result viewers.

Some defaults differ between the two entry points, especially whether Monte
Carlo is initially enabled. Always inspect the visible parameters rather than
assuming that a saved Processing configuration matches the main dialog.

## Data Contract

- Road networks must be line layers in a projected CRS.
- Event data must be a point layer with a valid CRS.
- Distance parameters use the road layer's map units.
- Event points may use another CRS; FastNSA transforms them to the road CRS.
- ST analysis requires a usable time field with at least two distinct finite
  values.
- Preprocessed mappings are reusable only with the same unchanged road
  network, as checked through `network_sig`.

Use temporary outputs while exploring and GeoPackage/CSV outputs when results
must survive a project reload.
