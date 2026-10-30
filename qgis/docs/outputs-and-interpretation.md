# Outputs and Interpretation

## Nearest-Edge Layers

Matched points, projected points, and connector lines share these FastNSA
fields:

| Field | Meaning |
| --- | --- |
| `point_id` | Sequential FastNSA event identifier for the run. |
| `edge_id` | Internal edge identifier in the adapted road network. It is not necessarily the source road feature ID. |
| `distance` | Point-to-network projection distance in road CRS units. |
| `offset` | Distance along the matched road edge from its first endpoint to the projected event position. |
| `method` | Matching method recorded for the output. |
| `network_sig` | Fingerprint used to validate reuse with the selected road network. |

Non-conflicting source event attributes are appended. Do not manually edit
`edge_id`, `offset`, or `network_sig` if the layer will be reused.

The matched-points geometry represents the adapted event location; projected
points lie on the network; connector lines make the projection displacement
visible.

## NKDV Lixel Layer

| Field | Meaning |
| --- | --- |
| `edge_id` | Road edge containing the lixel, using FastNSA's edge numbering. |
| `start_n1`, `end_n1` | Lixel start and end offsets measured from endpoint 1. |
| `offset_n1`, `offset_n2` | Lixel center offsets measured from the two edge endpoints. |
| `lixel_len` | Actual output segment length, including shortened terminal lixels. |
| `density` | Estimated density, normalized only when that option was enabled. |

The default renderer uses a Turbo-like ramp. Quantile classification is useful
when density is highly skewed because it allocates similar feature counts to
classes. Equal interval preserves equal numeric widths but can leave many
classes empty when a few values dominate. Zero/non-positive density can be
shown as a separate low class.

Processing styles the result when it is added to the map and also tries to
save the style in a GeoPackage output. Temporary layers keep their style only
while they remain available in the project or QGIS session.

## Network K Result Table

| Field | Meaning |
| --- | --- |
| `r` | Network-distance threshold. |
| `k_obs` | Observed normalized network K value. |
| `k_theo` | Monte Carlo reference value when available. |
| `k_lo`, `k_hi` | Lower and upper Monte Carlo envelope limits when available. |

Values above an upper envelope indicate more interaction/clustering than the
simulated reference at that threshold; values below a lower envelope indicate
less interaction/more regularity. Pointwise envelope crossings should not be
treated as a global multiple-testing conclusion.

Five simulations produce a very coarse envelope and are intended for workflow
testing. Record simulation count and randomization settings when results are
used scientifically.

## ST K Result Table

Each row represents one spatial-temporal threshold cell.

| Field | Meaning |
| --- | --- |
| `s`, `t` | Spatial and temporal thresholds. |
| `k_obs` | Observed ST K value. |
| `k_lo`, `k_hi` | Monte Carlo envelope values when enabled. |
| `status` | `above envelope`, `below envelope`, `within envelope`, or `unbounded`. |
| `time_unit` | Effective temporal analysis unit. |
| `time_origin` | Earliest event used as the elapsed-time origin. |
| `time_mode` | Effective interpretation mode. |

The viewer can display observed surfaces, envelope surfaces, residual or
exceedance information, and a mode that highlights observed values above the
upper envelope or below the lower envelope. Matplotlib controls appear only
when Matplotlib is importable in QGIS Python.

## Temporary Versus Persistent Outputs

- Temporary layers disappear when the project/session no longer retains them.
- GeoPackage outputs preserve vector features and attributes across reloads.
- CSV preserves K/ST K tables but not QGIS styles or viewers.
- NKDV GeoPackage output can store the default renderer when style application
  succeeds.
- Chart and 3D viewer state is not currently saved as a FastNSA analysis
  package.

For reproducibility, retain the input data version, CRS, full parameters,
FastNSA/plugin version, method, simulation count, and output table alongside
the QGIS project.

## Reading the Activity Log

Timing messages show how much time was spent preparing the roads, matching
events, calculating results, and saving outputs. They can help identify which
step is slow. Cache messages mean:

- `cache miss`: the network is being converted and stored;
- `cache hit`: the roads have not changed, so the previous preparation was reused;
- `cache invalidated`: a related layer changed and its old entry was removed;
- cache disabled: this input cannot be safely reused, so the roads are read
  again. This is normal for some Processing inputs.
