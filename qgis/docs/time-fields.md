# Time Fields for Spatiotemporal Analysis

FastNSA converts event times to elapsed values relative to the earliest event.
This keeps the differences between event times unchanged, so you do not
need to calculate elapsed times in the attribute table yourself.

## Interpretation Modes

| Mode | Use for | Behavior |
| --- | --- | --- |
| Auto detect | Unambiguous QGIS date/time or numeric fields | Date/time values and parseable date strings are treated as datetimes; purely numeric fields stay numeric. Mixed values are rejected. |
| Date / datetime | QGIS Date, DateTime, or ISO-like date strings | Forces datetime parsing. |
| Numeric values | Domain-specific hour/day indices or elapsed values | Preserves numeric differences; does not apply Unix timestamp conversion. |
| Unix timestamp (seconds) | Values such as `1767225600` | Interprets values as Unix seconds before converting units. |
| Unix timestamp (milliseconds) | Values such as `1767225600000` | Divides by 1000, then converts units. |

If you know how your field stores time, choose that mode explicitly. Auto
detection cannot tell whether an ordinary numeric value means hours or days.

## Analysis Units

- **Auto:** datetime and Unix modes use days; ordinary numeric values retain
  their original unit.
- **Seconds / Minutes / Hours / Days:** datetime and Unix values are converted
  to the selected unit.
- For **Numeric values**, the selected unit labels the values; it does not
  rescale them. If `0, 1, 2` already mean days, choose `Numeric values + Days`.

Temporal minimum, maximum, and step parameters must use the effective analysis
unit. The result log, table, and CSV record `time_unit`, `time_origin`, and
`time_mode`.

## Examples

| Source field | Recommended selection | Meaning of `t_max = 30` |
| --- | --- | --- |
| QGIS DateTime | Auto detect + Auto | 30 days |
| ISO date strings | Date / datetime + Days | 30 days |
| Unix milliseconds | Unix timestamp (milliseconds) + Days | 30 days |
| Existing day index | Numeric values + Days | 30 input units, declared as days |
| Sensor timestamps in Unix seconds | Unix timestamp (seconds) + Seconds | 30 seconds |

## Comparing ST K Values

RQS, SPS, EAR, MTS, and EARTH use the same time units and estimator:
`K(s, t) = network_length * observed_time_span * ordered_pair_count / (n * (n - 1))`.
EARTH chooses between EAR range counting and MTS prefix counting internally.
MTS and EARTH require at least two evenly spaced thresholds on each axis.

Changing the time unit changes the magnitude of K, not just the axis labels.
For example, converting events and thresholds from days to seconds multiplies
observed K and its Monte Carlo reference/envelope by 86400. Divide those K
values by 86400 before comparing them with a result expressed in days.
Changing only the time origin does not change K.

When comparing old and new results, keep the road network, matched events,
time interpretation, effective unit, thresholds, simulation seed, and estimator
normalization identical. Earlier raw pair counts are not directly comparable
with normalized K values. QGIS DateTime values retain millisecond precision.

## Validation Rules

The selected field must contain finite usable values and at least two distinct
times. Null-only fields, mixed unparseable values, and a zero time span are
rejected. Temporal maximum must exceed temporal minimum, and step must be
positive.

Inspect a sample of converted values when using strings or imported CSV fields.
QGIS provider type inference can differ from the apparent text shown in the
attribute table.

## Reusing Matched Points

Nearest-edge output preserves non-conflicting source attributes, including the
time field. It can therefore be used directly for ST K-function analysis.

- Matching is reused when `edge_id` and `offset` are present.
- `network_sig` must match the currently selected road network.
- Older mapped layers without `network_sig` may be accepted with a warning but
  cannot be verified safely.
- Re-run matching after editing road geometry, CRS, feature order, or network
  segmentation.

The supplementary [Chinese time-field guide](TIME_GUIDE_ZH.md) summarizes the
same rules.
