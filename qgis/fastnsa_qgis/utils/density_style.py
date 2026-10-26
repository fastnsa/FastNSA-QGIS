"""Shared configuration and classification helpers for NKDV density styles."""

from __future__ import annotations

import math


DENSITY_CLASSIFICATION_OPTIONS = (
    ("Equal count (quantile)", "quantile"),
    ("Equal interval", "equal_interval"),
)
DEFAULT_DENSITY_CLASSIFICATION = "quantile"
DEFAULT_DENSITY_CLASSES = 12
DEFAULT_SEPARATE_ZERO = True

# Samples from Google's Turbo colour map, ordered from low to high density.
TURBO_COLORS = (
    "#30123b", "#4145ab", "#4675ed", "#39a2fc", "#1bcfd4",
    "#24eca6", "#61fc6c", "#a4fc3b", "#d1e834", "#f3c63a",
    "#fe9b2d", "#f36315", "#d93806", "#a91601", "#7a0403",
)


def density_classification_label(mode: str) -> str:
    return next(
        (label for label, key in DENSITY_CLASSIFICATION_OPTIONS if key == mode),
        DENSITY_CLASSIFICATION_OPTIONS[0][0],
    )


def calculate_density_ranges(
    values,
    mode=DEFAULT_DENSITY_CLASSIFICATION,
    classes=DEFAULT_DENSITY_CLASSES,
):
    """Return non-overlapping positive-value ranges for a graduated renderer."""
    positive = sorted(
        float(value)
        for value in values
        if math.isfinite(float(value)) and float(value) > 0.0
    )
    if not positive:
        return []

    supported = {key for _label, key in DENSITY_CLASSIFICATION_OPTIONS}
    if mode not in supported:
        raise ValueError(f"Unsupported density classification mode: {mode!r}.")
    classes = max(1, min(int(classes), len(set(positive))))
    minimum, maximum = positive[0], positive[-1]
    if minimum == maximum:
        return [(minimum, maximum)]

    if mode == "equal_interval":
        width = (maximum - minimum) / classes
        boundaries = [minimum + width * index for index in range(classes + 1)]
        boundaries[-1] = maximum
    else:
        boundaries = [minimum]
        last_index = len(positive) - 1
        for index in range(1, classes):
            position = last_index * index / classes
            lower_index = int(math.floor(position))
            upper_index = int(math.ceil(position))
            fraction = position - lower_index
            boundaries.append(
                positive[lower_index] * (1.0 - fraction)
                + positive[upper_index] * fraction
            )
        boundaries.append(maximum)

    ranges = [
        (lower, upper)
        for lower, upper in zip(boundaries, boundaries[1:])
        if upper > lower
    ]
    return ranges or [(minimum, maximum)]


def turbo_color(index: int, count: int) -> str:
    if count <= 1:
        return TURBO_COLORS[len(TURBO_COLORS) // 2]
    return TURBO_COLORS[round(index * (len(TURBO_COLORS) - 1) / (count - 1))]
