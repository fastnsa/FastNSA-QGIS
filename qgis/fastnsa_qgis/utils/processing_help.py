"""Shared parameter explanations for the public Processing algorithms."""

MAPPING_REUSE_HELP = (
    "Raw event points are matched automatically. Compatible Matched points with "
    "edge_id and offset reuse their mapping; keep network_sig and use the same "
    "unchanged road network. Edge IDs are FastNSA internal IDs, not road feature IDs."
)

MONTE_CARLO_HELP = (
    "When enabled, simulate random event sets with the same event count and compute "
    "a nominal 95% pointwise quantile envelope. This is not a global significance "
    "envelope. When disabled, no simulations are run."
)

COMMON_PARAMETER_HELP = {
    "POINT_LAYER": (
        "Point events with a valid CRS. Coordinates are transformed to the road "
        "layer CRS when necessary."
    ),
    "ROAD_LAYER": (
        "Road lines in a projected CRS. All spatial distances use the road CRS "
        "map units; values are metres only for a metre-based CRS."
    ),
    "MONTE_CARLO": MONTE_CARLO_HELP,
    "SIMULATIONS": (
        "Number of simulated event sets, used only when Monte Carlo envelope is "
        "enabled. The default 5 is for quick testing; choose a larger count for "
        "inference. This is not the number of distance or time thresholds."
    ),
    "OUTPUT_TABLE": (
        "Result table without geometry. Choose temporary output or save to a file. "
        "Save temporary results separately if they must survive closing QGIS."
    ),
    "OUTPUT_CSV": "Optional CSV export, independent of the result table destination.",
    "LOAD_CSV": (
        "Load the exported CSV as a table in QGIS when a CSV destination is set. "
        "This does not open an external application."
    ),
}


def set_parameter_help(algorithm, descriptions=None):
    """Explain existing parameters without changing their IDs or defaults."""
    help_text = {**COMMON_PARAMETER_HELP, **(descriptions or {})}
    for name, description in help_text.items():
        parameter = algorithm.parameterDefinition(name)
        if parameter is not None:
            parameter.setHelp(description)
