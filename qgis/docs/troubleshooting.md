# Troubleshooting

## FastNSA Is Installed but Its Menu Is Missing

After updating the plugin, save your project and restart QGIS. Then open
**Plugins > Manage and Install Plugins > Installed** and make sure FastNSA
is checked.

If the menu is still missing, check **View > Panels > Log Messages** for a
Python or plugin error. Include that message when asking for help.

## The Setup Window Opens Instead of the Analysis Tools

Open **FastNSA > Runtime setup** and follow the message on
**Installation status**. If FastNSA is missing, use the
[installation guide](external-runtime.md) for your system.

After a first installation, click **Check again**. If you used a custom
folder, choose the folder containing `fastnsa` and click **Save and enable**.
Clear a saved old folder if you want FastNSA to be found automatically.

If a restart is requested, QGIS has already used another installation or an
earlier attempt to load it did not finish. Save your work and restart QGIS.
Do not replace package files while QGIS is using them.

For NumPy problems, repair the QGIS Python environment rather than installing
into an unrelated Python. If a message mentions GLIBC, GLIBCXX, or a missing
DLL, check that you have the correct package for your system and include the
full error in a support request.

## FastNSA Is Missing from the Processing Toolbox

First check **Runtime setup**: the analysis tools are enabled only after
FastNSA is ready. A working installation lists four algorithms under
**Processing Toolbox > FastNSA**.

After upgrading the plugin, restart QGIS and confirm FastNSA is still enabled.
If setup says it is ready but the tools remain missing, share the plugin log
with your support request.

## The Road CRS Is Rejected

Use a road layer in a projected CRS. Simply assigning a different CRS label
does not transform the coordinates. Use QGIS **Reproject layer**, then check
the map units and that the roads still appear in the correct location.

Event points can use another valid CRS; FastNSA transforms them to match the
roads.

## Matched Points Are Rejected

The roads may have changed since the events were matched. This can happen
after editing geometry, changing CRS, reordering features, or using another
road export. Run nearest-edge matching again with the road layer you want
to analyze.

FastNSA checks the `network_sig` field to identify the road network. Older
matched layers without it may be accepted with a warning, but cannot be
checked in the same way.

## Events Are Matched to Distant Roads

Check the coordinate systems and make sure the road network covers your
events. Display projected points and connector lines to inspect the matches.

The nearest available road is not always the right road for an event. Your
network may be missing local streets or may include unrelated transport
features.

## The Density Layer Has No Colors

Check that **Apply default FastNSA style** was enabled and the result was
added to the map. The layer needs a usable `density` field. If a saved
GeoPackage loses its style when reopened, check the Processing log for a
style-saving error.

All-zero results use a single low-color symbol. With separate zero enabled,
zero and non-positive values do not use the positive Turbo color classes.

## K-Function Takes a Long Time

Calculation time depends on the road network, events, thresholds, selected
method, and number of simulations. To get a first result sooner:

1. Turn off Monte Carlo, or start with a small simulation count.
2. Reduce the distance/time range or use larger steps.
3. Try a smaller study area or event subset.
4. Reuse matched points with the same road network.
5. Check the activity log to see which stage takes the most time.

For larger network K analyses, consider STARS if an approximate result is
suitable. For spatiotemporal analysis, try EARTH after checking the inputs on
a small example.

Five simulations are useful for trying the workflow, but may still take time
on a large network and are generally too few for statistical inference.

## Cancel Does Not Stop Immediately

Click **Cancel** once and wait for the task to confirm it has stopped. Some
calculation steps take time to respond. Avoid force-closing QGIS while it is
saving files, as this can interrupt other work in the project.

## The Analysis or Progress Window Is Hidden

Clicking **Hide Windows & Run in Background** hides the FastNSA windows so you
can use the map. Use the FastNSA toolbar button or the status-bar **Show**
button to bring them back.

## The 3D View Is Unavailable

Matplotlib must be installed in QGIS's Python environment for interactive 3D
views. Tables, summaries, and 2D views work without it.

If toolbar icons are difficult to see, try another QGIS theme before assuming
a button is missing.

## QGIS Closes Unexpectedly

An error in the analysis library can close QGIS before a normal Python
message appears. To help us investigate, include:

- QGIS, FastNSA plugin, Python, NumPy, and operating-system versions;
- the analysis method and settings;
- event and road counts, coordinate systems, and input formats;
- whether matched points and Monte Carlo were used;
- the last progress message and available QGIS logs;
- a small example dataset, if you have permission to share it.

Send reports to [GitHub Issues](https://github.com/fastnsa/FastNSA-QGIS/issues).
Review logs and file paths for private information before posting.
