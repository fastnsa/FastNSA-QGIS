# Troubleshooting

## Plugin Does Not Load

Read the startup diagnostic and QGIS Python error before installing extra
packages. Common causes are:

- NumPy is unavailable in the Python environment used by QGIS;
- the archive contains a native library for another OS or architecture;
- GLIBC or GLIBCXX runtime symbols are unavailable;
- the archive is incomplete and accidentally relies on a repository or
  editable installation.

Do not install packages into an unrelated system Python. Identify the Python
interpreter used by the running QGIS installation first.

## Processing Provider Is Missing

Restart QGIS after installation, confirm that FastNSA is enabled, and inspect
the plugin error log. A healthy installation registers four algorithms under
**Processing Toolbox > FastNSA**.

## Road CRS Is Rejected

FastNSA requires a projected road CRS for distance analysis. Assigning a
projected CRS label without transforming coordinates is not sufficient. Use
QGIS **Reproject layer** and verify that the resulting map units and extent are
plausible.

Event points may remain in another valid CRS because the adapter transforms
them to the road CRS.

## Mapped Points Are Rejected

The `network_sig` in matched points does not match the selected road layer.
This can happen after editing geometry, changing CRS, reordering features, or
using another network export. Re-run nearest-edge matching with the current
road layer.

If an old mapped layer has no `network_sig`, FastNSA may warn and continue, but
the mapping cannot be proven compatible.

## Projection Distances Are Too Large

Check the road/event CRS metadata, road-network coverage, and source point
quality. Display projected points and connector lines. A mathematically nearest
road may still be semantically wrong when the network omits local streets or
contains unrelated transport links.

## NKDV Layer Has No Style

Confirm **Apply default FastNSA style** was enabled and the output was loaded
on completion. The renderer needs a usable `density` field. For persistent
GeoPackage output, inspect the Processing log for a style-database error.

All-zero results use a single low-color symbol. With separate zero enabled,
non-positive values do not consume the positive Turbo classes.

## K or ST K Is Slow

Runtime depends on network size, active source edges, threshold count, method,
and simulations. Start by:

1. disabling Monte Carlo;
2. using a coarser/smaller threshold range;
3. testing a smaller network or event subset;
4. reusing matched points;
5. checking the log for a native-network cache hit;
6. comparing NS/reference methods with STARS or EARTH only after validating
   a small case.

Five simulations are the current smoke-test default, not a performance-free
setting.

## Cancellation Is Not Immediate

Cancellation is cooperative. The native backend checks at safe points rather
than killing its worker thread. The progress dialog changes to a cancellation
request message while the current native step finishes or reaches a check.

Do not force-close QGIS during normal delayed cancellation unless the process
is genuinely unresponsive for an exceptional period; forced termination can
interrupt unrelated QGIS writes.

## Main Window or Task Details Are Hidden

Background mode intentionally hides both FastNSA windows. Use the FastNSA
toolbar action or the status-bar **Show** button to restore the main dialog and
active task details.

## Matplotlib 3D Is Unavailable

Install Matplotlib into the QGIS Python environment if 3D interaction is
required. The built-in tables and 2D result views remain available without it.
Toolbars can also be hard to see under some QGIS themes; test both the QGIS
theme and Matplotlib canvas before treating a missing-looking icon as a missing
action.

## QGIS Terminates with Signal 11

A segmentation fault occurs outside Python exception handling and can end the
whole QGIS process. Collect:

- plugin, QGIS, Python, NumPy, and operating-system versions;
- method and every parameter;
- event count, road feature count, CRS, and data-source type;
- whether matched points and Monte Carlo were used;
- the last progress stage and QGIS log;
- a minimal reproducible dataset when licensing permits.

Report these through the project issue tracker. `QgsTask` keeps the interface
responsive but does not isolate native crashes in another process.
