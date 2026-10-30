# Analysis Workflows

All distance parameters use road-layer map units. The examples use metres only
when the selected projected CRS uses metres.

## Nearest-Edge Preprocessing

Nearest-edge matching projects each event to a road edge and records its
position along that edge. Run it once when the same event set will feed several
analyses.

### Parameters

| Parameter | Guidance |
| --- | --- |
| Point event layer | Point features with a valid CRS. Source attributes are preserved unless they conflict with FastNSA output fields. |
| Road network layer | Line features in a projected CRS. Feature order and segmentation are part of the reusable mapping identity. |
| Method | Start with `R-tree`. The grid compression choices offer approximate and refined matching. |
| Compression tolerance | Used only by grid methods, in road CRS units. It is not needed for R-tree. |
| Number of threads | Leave `0 (auto)` for most analyses. FastNSA chooses a worker count based on your computer and the input size. |
| Projected points | Optional points located on their matched road edges. Useful for visual validation. |
| Point-to-edge lines | Optional connector lines showing displacement from each source event to its projection. |

Inspect large `distance` values before downstream analysis. They can indicate
an unsuitable road network, wrong CRS metadata, disconnected coverage, or
events that do not belong to the study network.

Older saved Processing models may show `Grid-ENN`, which uses refined grid
matching. Review the selected method after upgrading. Projected points and
connector lines are available with every matching method.

### Reuse Matched Points

Downstream workflows detect `edge_id` and `offset` and skip matching when the
mapping is valid. `network_sig` protects against using offsets with a different
or edited network. Preserve these fields unchanged.

## Network KDE / NKDV

Network KDE estimates intensity along the network and emits line segments
called lixels.

### Parameters

| Parameter | Guidance |
| --- | --- |
| Method | Choose `LION` (the default) or `ADA`. Both use the selected bandwidth and segment resolution. |
| Kernel | This version supports `Epanechnikov`. |
| Bandwidth | Network-distance neighborhood size. Larger values smooth more broadly and generally cost more. |
| Segment resolution | Target lixel length. Smaller values increase output size and rendering/computation work. |
| Normalize density | Scales the output using the network integral and actual lixel lengths. Compare only results produced with the same normalization convention. |
| Density classification | `Quantile` distributes positive lixels across classes; `Equal interval` uses equal numeric widths. |
| Density classes | Between 3 and 30; 12 is the current default. |
| Separate zero density | Gives non-positive values a dedicated lowest class instead of consuming the positive Turbo ramp. |
| Apply default style | Adds the shared Turbo renderer to the loaded result. Disable it when custom styling is required. |

Choose segment resolution relative to both the bandwidth and network scale. A
very small lixel length can create a large layer without adding meaningful
visual detail.

## Network K-Function

Network K-function compares observed event interaction over network-distance
thresholds with a complete-spatial-randomness reference estimated by Monte
Carlo simulation.

### Methods and Parameters

| Parameter | Guidance |
| --- | --- |
| NS (exact) | An exact calculation, useful for smaller jobs or checking an approximate result. It can take longer on large networks. |
| STARS (approximate) | Approximate sampling and threshold-sharing method for larger analyses. Record epsilon with the result. |
| Min / max / step | Set the distance range and spacing of the result values. Smaller steps create more thresholds and can increase calculation time. |
| Epsilon | STARS only; disabled for NS. Up to ceil(1 / epsilon) source events per occupied edge; 0.01 means up to 100. Smaller values usually improve accuracy at greater cost, but are not a guaranteed percentage error bound. |
| Monte Carlo envelope | Enables simulated reference, lower/upper envelope, and chart interpretation. |
| Number of simulations | Five is the default for trying the workflow quickly. Use a suitably larger count for statistical interpretation. |

Network K and ST Network K use a default maximum spatial distance of 2000 road
CRS units in both the main dialog and Processing (2000 m for metre-based CRSs).

Use NS on a small subset or compact network to establish a reference before
relying on STARS for a new data regime. Do not compare K curves created from
different network extents or event-selection rules without accounting for
those differences.

## Spatiotemporal Network K-Function

ST Network K evaluates event interaction over a grid of spatial thresholds
`s` and temporal thresholds `t`.

### Methods

| Method | Role |
| --- | --- |
| RQS | Direct/reference-style spatiotemporal query path. |
| SPS | Reuses shortest-path work across thresholds. |
| EAR | Edge aggregation strategy. |
| MTS | Multi-threshold sharing strategy. |
| EARTH | Combined accelerated strategy and current UI default. |

EARTH and threshold-sharing methods benefit from regular threshold axes. Use
positive steps and avoid unnecessarily dense grids: the number of result cells
is the number of spatial thresholds multiplied by the number of temporal
thresholds.

### Parameters

- Select the time field, interpretation mode, and analysis unit before entering
  temporal thresholds. See [Time Fields](time-fields.md).
- Spatial thresholds use road CRS units.
- Temporal thresholds use the effective analysis time unit.
- Monte Carlo multiplies the cost of the selected threshold grid; start coarse
  and increase simulations after checking a first result.

The result viewer supports observed, theoretical/residual information when
available, envelope status, 2D views, and optional Matplotlib 3D surfaces.

## Main Dialog Versus Processing

For K and ST K, **Add temporary result table to QGIS** creates a no-geometry
memory table without requiring a CSV path. **Save result table (CSV)** is an
independent optional export. Temporary tables are not permanent exports; save
them with QGIS if they must survive closing the project.
Turning off CSV export clears the CSV path and unchecks external file opening.
When CSV is saved, the added result table uses the CSV filename without its
extension; otherwise it keeps its descriptive temporary name.

In the main dialog, **Open exported file after completion** opens a saved CSV
with the operating system's default application. It is unchecked by default,
reset when switching tasks, and disabled when CSV export is off. Nearest-edge
and NKDV do not expose this option or launch GeoPackage files externally; use
**Add result layer to QGIS** instead. Opening a CSV requires an OS file
association and is separate from adding the result table to QGIS.

For saved nearest-edge output, the matched-point layer uses the GeoPackage
filename without its extension. Optional layers append `_projected_points` or
`_point_to_edge_lines`. Saved NKDV layers also use the filename stem. Display
names retain spaces; internal GeoPackage table names are sanitized for storage.

### Output Path Reset Rules

- Nearest-edge and NKDV: selecting **Use temporary output** clears the previous
  GeoPackage path. Switching back to file output leaves it blank until you
  choose a destination again.
- K and ST K: turning off **Save result table (CSV)** clears the CSV path and
  unchecks external opening. A path for an inapplicable output type is also
  cleared rather than retained behind hidden controls.
- Switching to a different task or opening/clearing a project resets both
  output paths, preventing accidental reuse of another analysis's destination.
  Selecting the same task again preserves its active destination.
- Changing style, mapping options, or whether to add a layer/table to QGIS does
  not clear an otherwise active file destination. CSV export is independent of
  adding a temporary result table.
- Canceling a file-selection dialog preserves the active destination. Resetting
  a path never deletes a previously written file or changes input layer sources.

In Processing, select the temporary-output option to create a temporary
result. Leaving an optional destination empty may skip that output instead.

In Processing, the normal output-layer loading option adds result sinks to
QGIS after completion. K and ST K also provide **Load exported CSV table into
QGIS**, which explicitly loads the CSV after writing. This avoids depending
on version-specific generic file-opening controls. It does not launch an
external application or affect headless Processing runs without a project.

Both entry points provide the same analyses, with different ways to work:

- the main dialog can reuse an unchanged road network, show task details
  and interactive viewers, and add final layers to the project;
- Processing creates layers/tables for models and batch use, styles the
  loaded NKDV result, and writes optional CSV files;
- Processing does not persist main-dialog chart or surface viewer state;
- review method and kernel selections in saved Processing models after
  upgrading the plugin.
