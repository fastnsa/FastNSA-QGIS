# FastNSA for QGIS

FastNSA brings high-performance network spatial analysis to the QGIS desktop
and Processing Toolbox. The `0.1.0-rc5` candidate provides four workflows:

- nearest-edge preprocessing with reusable `edge_id`, `offset`, `distance`,
  and `network_sig` fields;
- network kernel density visualization (NKDV) with ADA or LION;
- network K-function analysis with NS (exact) or STARS (approximate);
- spatiotemporal network K-function analysis with RQS, SPS, EAR, MTS, or
  EARTH.

Spatiotemporal NKDE, OSM downloading, and pause/resume are not part of the
`0.1.0` release scope.

## Requirements

- Candidate targets: Linux x86_64 and Windows AMD64
- QGIS 3.34 or newer, using Qt5
- Python 3.11 or newer in the QGIS environment
- NumPy in the QGIS Python environment
- a C++ runtime compatible with the bundled native library

The Windows acceptance target is QGIS 3.34 / Python 3.12.7 / NumPy 1.26.4 /
Qt 5.15.13. Windows RC4 smoke testing has been reported without platform
compatibility failures. Recent fixes still need acceptance using a newly built
candidate. QGIS 4.x and Qt6 are not yet supported.

The release ZIP bundles the lightweight FastNSA Python runtime and
`libfastnsa.so` on Linux or `fastnsa.dll` on Windows. GeoPandas, Shapely,
NetworkX, and OSMnx are not required.
Matplotlib is optional and is used only for interactive spatiotemporal 3D
surfaces; the result table and 2D views remain available without it.

Candidate ZIPs are built by CI from tested Linux/Windows wheels. Linux runtimes
are built using manylinux2014; inspect each archive's build information and
validation report for its provenance. Historical RC2 system-runtime requirements
do not describe the current wheel-based candidates. Manual QGIS acceptance is
required for each new candidate. macOS plugin packages are not yet provided.

## Installation

1. Download the ZIP for your operating system and architecture.
2. In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**.
3. Select the archive and enable **FastNSA**.
4. Open the FastNSA window from its toolbar button or plugin menu. The same
   four algorithms are available under **Processing Toolbox > FastNSA**.

Restart QGIS if the Processing provider does not appear immediately. A startup
diagnostic reports missing NumPy, native-library, or ABI dependencies.

For runtime and platform compatibility details, see
[DEPENDENCIES.md](DEPENDENCIES.md).

## User Documentation

The [FastNSA QGIS User Guide](docs/index.md) is the primary English manual. It
includes installation, a quick start, workflow parameter guidance, time-field
handling, output interpretation, troubleshooting, and algorithm references.
The complete `qgis/docs/` directory is included in release archives.

## Data Requirements

- The road input must be a line layer in a projected CRS whose map units are
  suitable for distance analysis.
- The event input must be a point layer with a valid CRS. FastNSA transforms
  event coordinates to the road CRS when required.
- ST K-function additionally requires a non-null time field with at least two
  distinct values.

Do not run distance-based analysis directly on a longitude/latitude road
layer. Reproject the road network first.

## Recommended Workflow

1. Run **Fast Nearest Edge Matching** when the same events will be analyzed
   more than once.
2. Use the matched-point output as the event input for NKDV, Network K, or ST
   Network K. FastNSA reuses valid `edge_id` and `offset` values instead of
   matching the events again.
3. Keep the road layer unchanged. FastNSA compares the matched points'
   `network_sig` with the selected road network and rejects incompatible
   mappings.
4. Use temporary outputs for exploration and GeoPackage or CSV outputs for
   results that must survive project reloads.

An unchanged road layer can also reuse its in-memory native-network cache in
the main dialog. The activity log reports cache hits, misses, and invalidation.

## Analysis Notes

### Network KDE / NKDV

The release UI exposes ADA and LION with the validated Epanechnikov kernel.
Results are lixel line segments with a density field. The optional default
style uses a Turbo color ramp, Quantile (equal-count) or Equal interval
classification, a configurable class count, and an optional separate color for
zero density. Density normalization is applied before classification.

### Network K-function

NS (exact) and STARS (approximate) produce `r`, observed K, theoretical K, and optional
Monte Carlo envelope values. Five simulations is the interactive default; use
more simulations only after validating the network, events, and threshold
range. Both entry points can create a temporary no-geometry result table and
optionally export CSV. The main dialog additionally provides an interactive
chart. Epsilon controls STARS sampling and is disabled for NS.

### Spatiotemporal Network K-function

The time field can be interpreted automatically, as date/time, as ordinary
numeric values, or as Unix seconds/milliseconds. Analysis units can be seconds,
minutes, hours, or days. See the packaged
[Chinese time-field guide](docs/TIME_GUIDE_ZH.md) for detailed examples.

The result viewer includes table, summary, 2D surface, and envelope views.
Interactive Matplotlib 3D surfaces are enabled only when Matplotlib is
available.

## Progress and Cancellation

Analyses run as non-modal `QgsTask` jobs. The progress window reports input
validation, network conversion, event matching, native computation, Monte
Carlo work, output writing, and styling where applicable.

Use **Hide Windows & Run in Background** to return to the map. The FastNSA
toolbar action or the status-bar **Show** button restores task details. **Cancel**
requests cooperative cancellation; a long native step may need to reach its
next safe checkpoint before stopping. Canceled runs do not finalize outputs.

## Troubleshooting

- **Plugin fails to load:** review the startup diagnostic for NumPy, native
  library or GLIBC/GLIBCXX errors.
- **3D view is unavailable:** install Matplotlib in the QGIS Python environment;
  other plugin features remain usable.
- **Mapped points are rejected:** the road network changed after preprocessing.
  Run nearest-edge matching again.
- **Analysis is unexpectedly slow:** start with a smaller threshold grid and
  five or fewer simulations, then inspect adapter/cache messages in the log.
- **QGIS closes after a native crash:** report the input description, method,
  parameters, platform, QGIS version, and plugin log through the issue tracker.

## Distribution Status

Candidate archives are prepared for project-controlled distribution. Linux,
Windows, and macOS native/wheel CI has passed; this does not replace QGIS plugin
acceptance, and macOS plugin archives remain deferred. The
[official QGIS plugin repository requirements](https://plugins.qgis.org/docs/publish/)
prohibit bundled binaries. The current self-contained ZIP is for
project-controlled distribution, not official-repository submission. An
official-repository variant would require external FastNSA installation,
dependency discovery, and separate packaging; that variant is not implemented.

## Algorithm References

- Nearest-edge matching: [Ye et al., KDD 2026](https://doi.org/10.1145/3770855.3817711)
- ADA: [Chan et al., PVLDB 2021](https://doi.org/10.14778/3461535.3461540)
- LION: [Chan et al., PVLDB 2024](https://doi.org/10.14778/3648160.3648168)
- Network K-function: [Chan et al., PVLDB 2022](https://doi.org/10.14778/3551793.3551836)
- STARS: [Ye et al., KDD 2026](https://doi.org/10.1145/3770855.3817709)
- EARTH: [Chan et al., KDD 2026](https://doi.org/10.1145/3770855.3817706)

For scientific reporting, cite the paper for the selected method and record the
FastNSA version, parameters, and random seed.

## Support

- Source: <https://github.com/fastnsa/FastNSA-QGIS>
- Issues: <https://github.com/fastnsa/FastNSA-QGIS/issues>
- User guide: [docs/index.md](docs/index.md)
- Chinese guide: [README_ZH.md](README_ZH.md)
