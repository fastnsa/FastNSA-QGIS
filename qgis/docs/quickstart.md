# Quick Start

This walkthrough uses existing QGIS road and event layers. It applies equally
to the main dialog and Processing Toolbox unless a step says otherwise.

## 1. Prepare the Layers

Load:

- a road network as a line layer;
- event locations as a point layer.

The road layer must use a projected CRS. Check **Layer Properties >
Information** and confirm that its units are appropriate for your distance
parameters. Reproject a longitude/latitude road layer before analysis.

Event points may use a different valid CRS. FastNSA transforms them to the road
CRS during adaptation.

## 2. Preprocess Reusable Events

Open FastNSA and select **Fast Nearest Edge Matching**.

1. Choose the event and road layers.
2. Keep **R-tree** for a conservative first run.
3. Enable projected points or point-to-edge lines if you want visual quality
   control.
4. Use a temporary output for the first run.
5. Run the task and inspect the output near several events.

The matched output contains `edge_id`, `offset`, `distance`, `method`, and
`network_sig`, plus non-conflicting source event attributes. Save this layer to
a GeoPackage if it will be reused later.

## 3. Run Network KDE

Select **Network KDE** and use the matched points as the event layer.

Suggested first-run parameters:

- method: `LION`;
- kernel: `Epanechnikov`;
- bandwidth: a meaningful neighborhood distance in road CRS units;
- segment resolution: substantially smaller than the bandwidth;
- normalization: off until the unnormalized result is understood;
- default Turbo style: on.

The result is a lixel line layer. Open its attribute table and verify that
`density` values and geometries are present.

## 4. Run Network K-Function

Select **Network K-Function** and again use the matched points.

1. Choose a distance range that is meaningful for the study area.
2. Start with **NS (exact)** on a small test case or **STARS (approximate)** when approximation is
   acceptable.
3. For a fast smoke test, disable Monte Carlo or use five simulations.
4. Run the analysis and inspect the observed curve and result summary.

Monte Carlo simulations are required for a simulation-based theoretical curve
and lower/upper envelope. Five simulations are useful for software testing but
are generally too few for scientific inference.

## 5. Run ST Network K-Function

The event layer must contain a usable time field. Choose **Spatiotemporal
Network K-Function**, select that field, and keep **Auto detect** only when the
field type is unambiguous.

For date/time data, `Auto` analysis units use elapsed days from the earliest
event. A spatial range of `0-2000` and temporal range of `0-30` therefore mean
road-map units and days respectively when those defaults apply.

Start with a coarse spatial/temporal grid and no more than five simulations.
After the run, inspect the result table, summary, 2D surface, and optional
Matplotlib 3D surface.

## 6. Save Results

- Save matched points and NKDV lixels to GeoPackage.
- Export K-function and ST K-function tables to CSV when they are needed
  outside the current project.
- Record the FastNSA version, method, thresholds, bandwidth/lixel length,
  Monte Carlo count, time interpretation, and input-layer identity.

Viewer state and complete run packages are not currently persisted. A QGIS
project alone is therefore not a complete reproducibility record for charts or
surface views.

## 7. Use Background Execution

Click **Hide Windows & Run in Background** to continue using the map. Restore
details through the FastNSA toolbar action or the status-bar **Show** button.
**Cancel** is cooperative; a native phase may take time to reach its next safe
checkpoint.
