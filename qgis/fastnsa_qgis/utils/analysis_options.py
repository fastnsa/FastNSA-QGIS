"""Stable backend identifiers and user-facing algorithm descriptions."""

K_METHOD_OPTIONS = (("NS (exact)", "NS"), ("STARS (approximate)", "STARS"))
DEFAULT_K_MAX_DISTANCE = 2000
EPSILON_HELP = (
    "STARS only. Smaller epsilon uses more samples and takes longer."
)
NEAREST_METHOD_OPTIONS = (
    ("R-tree", "R-tree"),
    ("Grid compression (approximate)", "comp_a"),
    ("Grid compression (refined)", "comp_e"),
)
# Preserve index 3 for existing Processing models using the former Grid-ENN.
NEAREST_PROCESSING_OPTIONS = NEAREST_METHOD_OPTIONS + (
    ("Grid compression (refined; legacy Grid-ENN alias)", "comp_e"),
)
GRID_HELP = (
    "Grid only: compression tolerance in road CRS units. Ignored by R-tree."
)
