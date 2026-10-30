# FastNSA QGIS User Guide

Match event locations to road networks, map density hotspots, and explore
spatial and temporal clustering in QGIS. This guide covers version `0.1.2`.

## Start Here

- [Installation](installation.md): choose a package and install or upgrade.
- [Set Up FastNSA](external-runtime.md): install FastNSA separately when using
  a source-only package.
- [Quick Start](quickstart.md): prepare your layers and run your first analysis.
- [Analysis Workflows](workflows.md): choose methods and parameters.
- [Time Fields](time-fields.md): select dates, numeric timestamps, and units.
- [Outputs and Interpretation](outputs-and-interpretation.md): understand
  maps, charts, simulation envelopes, and saved results.
- [Troubleshooting](troubleshooting.md): get help with setup, data, and analyses.
- [Algorithm References](references.md): find the research behind the methods.

A [Chinese overview](../README_ZH.md) and
[Chinese time-field guide](TIME_GUIDE_ZH.md) are also available.

## Available Analyses

| Workflow | What you get | Methods |
| --- | --- | --- |
| Fast Nearest Edge Matching | Reusable matched points; optional projected points and connector lines | R-tree and grid compression |
| Fast Network KDE | Road segments colored by event density | LION or ADA with the Epanechnikov kernel |
| Fast Network K-Function | Result table and chart; optional CSV | NS (exact) or STARS (approximate) |
| Fast Spatiotemporal Network K-Function | Result table and surface viewer; optional CSV | EARTH, MTS, EAR, SPS, or RQS |

This version does not include spatiotemporal NKDE, OSM downloading,
pause/resume, or saving and reopening result viewers.

## Choose How to Work

Use the **FastNSA window** to set up analyses, inspect maps and interactive
results, and follow progress while continuing to use QGIS.

Use **Processing Toolbox > FastNSA** for batch analyses or QGIS models.
Processing creates layers and tables, but does not open the FastNSA chart or
surface viewers.

Check the parameters before each run. Some defaults, including whether
Monte Carlo simulations are enabled, differ between the two entry points.

## Before You Start

- Use a road line layer in a projected CRS.
- Use event points with a valid CRS; they can be transformed to the road CRS.
- Enter distances in the road layer's map units.
- For spatiotemporal analysis, choose a time field with at least two distinct,
  usable values.
- Reuse matched points only with the same road network. After editing the
  roads, run matching again.

Temporary outputs are useful while exploring. Save layers to GeoPackage and
tables to CSV when you want to keep the results.
