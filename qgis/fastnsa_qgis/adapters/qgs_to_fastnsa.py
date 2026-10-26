"""Conversion helpers from QGIS layers to FastNSA-compatible inputs."""

from __future__ import annotations

from dataclasses import dataclass
from collections import OrderedDict
from datetime import date, datetime, time, timezone
from hashlib import sha256
from time import perf_counter
from typing import Any
from threading import RLock

import numpy as np
from qgis.PyQt.QtCore import QDate, QDateTime
from qgis.core import (
    NULL,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSource,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
)

from ..utils.layer_utils import get_field_names
from ..utils.validation import (
    validate_distance_crs,
    validate_line_layer,
    validate_point_layer,
    validate_same_crs,
)


_NETWORK_CACHE_MAX_SIZE = 2
_NETWORK_CACHE = OrderedDict()
_NETWORK_CACHE_LOCK = RLock()


def clear_network_cache():
    """Drop cached native road networks, primarily for tests and plugin reloads."""
    with _NETWORK_CACHE_LOCK:
        _NETWORK_CACHE.clear()


def _network_cache_identity(layer):
    if hasattr(layer, "fastnsaCacheIdentity"):
        return tuple(layer.fastnsaCacheIdentity())
    # Live Processing layers do not expose a reliable edit revision from worker
    # threads. Cache only snapshots whose identity was captured on the GUI thread.
    return None


def _cached_network(layer):
    key = _network_cache_identity(layer)
    if key is None:
        return None, None, "disabled"
    with _NETWORK_CACHE_LOCK:
        cached = _NETWORK_CACHE.pop(key, None)
        if cached is not None:
            _NETWORK_CACHE[key] = cached
            return key, cached, "hit"
        stale_keys = [existing for existing in _NETWORK_CACHE if existing[:3] == key[:3]]
        for stale_key in stale_keys:
            _NETWORK_CACHE.pop(stale_key, None)
    return key, None, "invalidated" if stale_keys else "miss"


def _store_cached_network(key, value):
    if key is None:
        return
    with _NETWORK_CACHE_LOCK:
        _NETWORK_CACHE[key] = value
        _NETWORK_CACHE.move_to_end(key)
        while len(_NETWORK_CACHE) > _NETWORK_CACHE_MAX_SIZE:
            _NETWORK_CACHE.popitem(last=False)


@dataclass
class NetworkEdgeRecord:
    """Plugin-side edge record used during QGIS/FastNSA adaptation."""

    edge_id: int
    source_fid: int
    part_index: int
    geometry_wkb: bytes


@dataclass
class PointRecord:
    """Plugin-side point record used during QGIS/FastNSA adaptation."""

    point_id: int
    source_fid: int
    part_index: int
    geometry_wkb: bytes
    source_attributes: list[Any]


@dataclass
class PointArrayData:
    """Minimal point data retained by the QGIS adapter."""

    x: np.ndarray
    y: np.ndarray
    times: np.ndarray | None = None
    temporal_metadata: "TemporalMetadata | None" = None

    def __len__(self):
        return len(self.x)


@dataclass(frozen=True)
class TemporalMetadata:
    """Description of the normalized temporal axis used by ST analysis."""

    requested_mode: str
    effective_mode: str
    requested_unit: str
    effective_unit: str
    origin: float
    origin_label: str
    span: float


@dataclass
class NearestEdgeInputBundle:
    """Real backend inputs plus plugin metadata for result reconstruction."""

    network: Any
    pointset: Any
    point_data: PointArrayData
    point_events_kwargs: dict[str, Any]
    point_records: list[PointRecord]
    point_fields: QgsFields
    edge_records: list[NetworkEdgeRecord]
    network_signature: str
    warnings: list[str]
    timings: dict[str, float]


def _import_fastnsa_dependencies():
    try:
        from fastnsa.runtime import NativeNetwork, NativePointSet  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised inside QGIS runtime
        raise RuntimeError(
            "The lightweight FastNSA runtime could not be imported. "
            "Please ensure fastnsa, NumPy, and the native FastNSA library are available."
        ) from exc

    return NativeNetwork, NativePointSet


def _import_fastnsa_analysis_dependencies():
    try:
        from fastnsa.stats.k_function import network_k_function  # type: ignore
        from fastnsa.stats.k_function import spatiotemporal_network_k_function  # type: ignore
        from fastnsa.stats.network_kde import network_kde  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised inside QGIS runtime
        raise RuntimeError(
            "FastNSA analysis functions could not be imported in the QGIS environment."
        ) from exc
    return network_k_function, spatiotemporal_network_k_function, network_kde


def format_timings_for_logs(timings: dict[str, float], prefix: str = "Timing") -> list[str]:
    """Convert timing measurements into log-friendly lines."""
    return [f"{prefix}: {key}={value:.4f}s" for key, value in sorted(timings.items())]


def _require_fields(layer: QgsFeatureSource, required_fields: list[str]):
    field_names = set(get_field_names(layer))
    missing = [name for name in required_fields if name not in field_names]
    if missing:
        raise ValueError(f"Layer is missing required field(s): {', '.join(missing)}")


def _layer_has_fields(layer: QgsFeatureSource, required_fields: list[str]) -> bool:
    field_names = set(get_field_names(layer))
    return all(name in field_names for name in required_fields)


def _validate_mapped_network_signature(
    layer: QgsFeatureSource,
    expected_signature: str,
    field_name: str = "network_sig",
) -> list[str]:
    """Verify that reusable edge mappings were produced from this network."""
    if field_name not in get_field_names(layer):
        return [
            "The mapped point layer has no network_sig field. Its edge_id/offset "
            "values cannot be verified against the selected road network."
        ]

    signatures = set()
    for feature in layer.getFeatures():
        value = feature[field_name]
        if value is None or value == NULL or not str(value).strip():
            continue
        signatures.add(str(value).strip())

    if not signatures:
        return [
            "The mapped point layer contains no usable network signature. Its "
            "edge_id/offset values cannot be verified."
        ]
    if len(signatures) != 1:
        raise ValueError(
            "The mapped point layer contains multiple network signatures and cannot "
            "be safely reused."
        )
    actual_signature = next(iter(signatures))
    if actual_signature != expected_signature:
        raise ValueError(
            "The mapped point layer was created from a different road network. "
            "Run Fast Nearest Edge Matching again for the selected network."
        )
    return []


def _transform_geometry_if_needed(geometry: QgsGeometry, source, target, transform_context=None) -> QgsGeometry:
    if source == target:
        return QgsGeometry(geometry)
    transformed = QgsGeometry(geometry)
    transformer = QgsCoordinateTransform(
        source,
        target,
        transform_context if transform_context is not None else QgsProject.instance(),
    )
    transformed.transform(transformer)
    return transformed


def _extract_qgs_line_parts(geometry: QgsGeometry):
    """Extract linear parts using only QGIS geometry APIs."""
    if geometry.isEmpty():
        return []

    linear_geometry = QgsGeometry(geometry)
    linear_geometry.convertToStraightSegment()

    if linear_geometry.isMultipart():
        multipart = linear_geometry.asMultiPolyline()
        if multipart:
            return [
                QgsGeometry.fromPolylineXY([QgsPointXY(point) for point in part])
                for part in multipart
                if len(part) >= 2
            ]
    else:
        polyline = linear_geometry.asPolyline()
        if polyline:
            return [QgsGeometry.fromPolylineXY([QgsPointXY(point) for point in polyline])]

    parts = []
    for child in linear_geometry.asGeometryCollection():
        parts.extend(_extract_qgs_line_parts(child))
    return parts


def _extract_qgs_point_parts(geometry: QgsGeometry) -> list[QgsPointXY]:
    """Extract point parts using only QGIS geometry APIs."""
    if geometry.isEmpty():
        return []
    if geometry.isMultipart():
        points = geometry.asMultiPoint()
        if points:
            return [QgsPointXY(point) for point in points]
    else:
        point = geometry.asPoint()
        if not point.isEmpty():
            return [QgsPointXY(point)]

    points = []
    for child in geometry.asGeometryCollection():
        points.extend(_extract_qgs_point_parts(child))
    return points


_TIME_MODES = {"auto", "datetime", "numeric", "unix_seconds", "unix_milliseconds"}
_TIME_UNITS = {"auto", "seconds", "minutes", "hours", "days"}
_SECONDS_PER_UNIT = {
    "seconds": 1.0,
    "minutes": 60.0,
    "hours": 3600.0,
    "days": 86400.0,
}


def _is_null_time(value) -> bool:
    return value is None or value == NULL


def _datetime_to_epoch_seconds(value, field_name: str) -> float:
    """Convert a date/time-like value to Unix seconds."""
    if value is None or value == NULL:
        raise ValueError(f"Time field {field_name!r} contains a null value.")
    if isinstance(value, QDateTime):
        if not value.isValid():
            raise ValueError(f"Time field {field_name!r} contains an invalid datetime.")
        return value.toMSecsSinceEpoch() / 1000.0
    if isinstance(value, QDate):
        value = value.toPyDate()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return float(value.timestamp())
    if isinstance(value, date):
        return float(datetime.combine(value, time.min, tzinfo=timezone.utc).timestamp())
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"Cannot parse value {value!r} in time field {field_name!r}."
            ) from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return float(parsed.timestamp())
    raise ValueError(
        f"Value {value!r} in time field {field_name!r} is not a date/time value."
    )


def _numeric_time(value, field_name: str) -> float:
    if _is_null_time(value) or isinstance(value, bool):
        raise ValueError(f"Time field {field_name!r} contains a null or invalid value.")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Value {value!r} in time field {field_name!r} is not numeric."
        ) from exc
    if not np.isfinite(converted):
        raise ValueError(f"Time field {field_name!r} contains NaN or infinity.")
    return converted


def _looks_numeric(value) -> bool:
    if isinstance(value, bool) or _is_null_time(value):
        return False
    if isinstance(value, (int, float, np.number)):
        return True
    if isinstance(value, str):
        try:
            float(value.strip())
            return True
        except ValueError:
            return False
    return False


def normalize_temporal_values(
    values,
    *,
    mode: str = "auto",
    unit: str = "auto",
    field_name: str = "time",
) -> tuple[np.ndarray, TemporalMetadata, str]:
    """Normalize temporal values to elapsed values in a documented unit."""
    requested_mode = (mode or "auto").strip().lower()
    requested_unit = (unit or "auto").strip().lower()
    if requested_mode not in _TIME_MODES:
        raise ValueError(f"Unsupported time interpretation mode: {mode!r}.")
    if requested_unit not in _TIME_UNITS:
        raise ValueError(f"Unsupported temporal analysis unit: {unit!r}.")

    raw_values = list(values)
    if not raw_values:
        raise ValueError("At least one temporal value is required.")
    if any(_is_null_time(value) for value in raw_values):
        raise ValueError(f"Time field {field_name!r} contains a null value.")

    effective_mode = requested_mode
    if effective_mode == "auto":
        numeric_flags = [_looks_numeric(value) for value in raw_values]
        if all(numeric_flags):
            effective_mode = "numeric"
        elif any(numeric_flags):
            raise ValueError(
                f"Time field {field_name!r} mixes numeric and date/time values. "
                "Choose an explicit interpretation or clean the field."
            )
        else:
            effective_mode = "datetime"

    if effective_mode == "datetime":
        source_values = np.asarray(
            [_datetime_to_epoch_seconds(value, field_name) for value in raw_values],
            dtype=np.float64,
        )
    else:
        source_values = np.asarray(
            [_numeric_time(value, field_name) for value in raw_values],
            dtype=np.float64,
        )
        if effective_mode == "unix_milliseconds":
            source_values = source_values / 1000.0

    uses_epoch_seconds = effective_mode in {
        "datetime",
        "unix_seconds",
        "unix_milliseconds",
    }
    effective_unit = requested_unit
    if effective_unit == "auto":
        effective_unit = "days" if uses_epoch_seconds else "native"

    origin = float(np.min(source_values))
    elapsed = source_values - origin
    if uses_epoch_seconds:
        elapsed = elapsed / _SECONDS_PER_UNIT[effective_unit]

    if uses_epoch_seconds:
        origin_label = datetime.fromtimestamp(origin, tz=timezone.utc).isoformat()
    else:
        origin_label = f"{origin:.12g}"
    metadata = TemporalMetadata(
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        requested_unit=requested_unit,
        effective_unit=effective_unit,
        origin=origin,
        origin_label=origin_label,
        span=float(np.max(elapsed)),
    )
    warning = (
        f"Time field {field_name!r} was interpreted as {effective_mode} and "
        f"normalized to elapsed {effective_unit} from {origin_label}."
    )
    return np.ascontiguousarray(elapsed, dtype=np.float64), metadata, warning


def qgs_layer_to_network(layer: QgsFeatureSource, **kwargs):
    """Convert a QGIS line layer into the existing fastnsa.Network API."""
    total_started = perf_counter()
    valid, message = validate_line_layer(layer)
    if not valid:
        raise ValueError(message)

    projected_ok, projected_message = validate_distance_crs(layer)
    if not projected_ok:
        raise ValueError(projected_message)
    warnings = []

    cache_key, cached, cache_status = _cached_network(layer)
    if cached is not None:
        network, edge_records, cached_warnings = cached
        warnings.extend(cached_warnings)
        warnings.append("NativeNetwork cache hit; reused the unchanged road network.")
        return network, edge_records, warnings, {
            "network.cache_hit": 1.0,
            "network.import_deps_s": 0.0,
            "network.feature_scan_s": 0.0,
            "network.backend_build_s": 0.0,
            "network.edge_record_build_s": 0.0,
            "network.total_s": perf_counter() - total_started,
        }
    if cache_status == "invalidated":
        warnings.append("NativeNetwork cache invalidated because the road layer changed.")
    elif cache_status == "disabled":
        warnings.append("NativeNetwork cache disabled for an actively edited or anonymous source.")
    else:
        warnings.append("NativeNetwork cache miss; building the selected road network.")

    import_started = perf_counter()
    NativeNetwork, _NativePointSet = _import_fastnsa_dependencies()
    import_elapsed = perf_counter() - import_started
    crs_authid = layer.sourceCrs().authid() if hasattr(layer, "sourceCrs") else layer.crs().authid()
    signature_builder = sha256()
    signature_builder.update(f"fastnsa-network-v1\0{crs_authid}\0".encode("utf-8"))

    node_index: dict[tuple[float, float], int] = {}
    adjacency: list[list[int]] = []
    edge_rows: list[tuple[int, int, float]] = []
    coordinate_rows: list[tuple[float, float]] = []
    geometry_offsets = [0]
    edge_records: list[NetworkEdgeRecord] = []

    scan_started = perf_counter()
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry is None or geometry.isNull():
            continue

        for part_index, part_geometry in enumerate(_extract_qgs_line_parts(geometry)):
            if part_geometry.isNull() or part_geometry.isEmpty():
                continue

            coords = part_geometry.asPolyline()
            if len(coords) < 2:
                continue

            length = float(part_geometry.length())
            if not np.isfinite(length) or length <= 0.0:
                continue

            start_key = (round(coords[0].x(), 12), round(coords[0].y(), 12))
            end_key = (round(coords[-1].x(), 12), round(coords[-1].y(), 12))

            if start_key not in node_index:
                node_index[start_key] = len(node_index)
                adjacency.append([])

            if end_key not in node_index:
                node_index[end_key] = len(node_index)
                adjacency.append([])

            u = node_index[start_key]
            v = node_index[end_key]
            edge_id = len(edge_rows)
            edge_rows.append((u, v, length))
            adjacency[u].append(edge_id)
            adjacency[v].append(edge_id)

            edge_wkb = bytes(part_geometry.asWkb())
            signature_builder.update(
                f"{edge_id}\0{int(feature.id())}\0{part_index}\0".encode("ascii")
            )
            signature_builder.update(edge_wkb)
            coordinate_rows.extend((point.x(), point.y()) for point in coords)
            geometry_offsets.append(len(coordinate_rows))
            edge_records.append(
                NetworkEdgeRecord(
                    edge_id=edge_id,
                    source_fid=int(feature.id()),
                    part_index=part_index,
                    geometry_wkb=edge_wkb,
                )
            )
    scan_elapsed = perf_counter() - scan_started

    if not edge_rows:
        raise ValueError("Road network layer does not contain usable line geometries.")

    backend_started = perf_counter()
    edge_count = len(edge_rows)
    node_count = len(adjacency)
    edges_arr = np.array(edge_rows, dtype=np.float64)
    offsets_arr = np.zeros(node_count + 1, dtype=np.int32)
    indices_arr = np.zeros(edge_count * 2, dtype=np.int32)

    cursor = 0
    for node_id, edge_ids in enumerate(adjacency):
        offsets_arr[node_id] = cursor
        for edge_id in edge_ids:
            indices_arr[cursor] = edge_id
            cursor += 1
    offsets_arr[node_count] = cursor

    network = NativeNetwork(
        crs=crs_authid,
        edges=edges_arr,
        offsets=offsets_arr,
        indices=indices_arr,
        coordinates=np.array(coordinate_rows, dtype=np.float64),
        geometry_offsets=np.array(geometry_offsets, dtype=np.int32),
    )
    network.signature = signature_builder.hexdigest()
    backend_elapsed = perf_counter() - backend_started

    timings = {
        "network.cache_hit": 0.0,
        "network.import_deps_s": import_elapsed,
        "network.feature_scan_s": scan_elapsed,
        "network.backend_build_s": backend_elapsed,
        "network.edge_record_build_s": 0.0,
        "network.total_s": perf_counter() - total_started,
    }
    _store_cached_network(cache_key, (network, edge_records, tuple()))
    return network, edge_records, warnings, timings


def qgs_layer_to_pointset(layer: QgsFeatureSource, **kwargs):
    """Map a QGIS point layer directly into a native FastNSA point set."""
    total_started = perf_counter()
    target_network = kwargs.get("target_network")
    target_crs = kwargs.get("target_crs")
    mapping_method = kwargs.get("mapping_method", "R-tree")
    comp_eps = kwargs.get("comp_eps", 10.0)
    n_threads = kwargs.get("n_threads", 0)
    time_col = kwargs.get("time_col")
    times = kwargs.get("times")
    time_mode = kwargs.get("time_mode", "auto")
    time_unit = kwargs.get("time_unit", "auto")
    transform_context = kwargs.get("transform_context")

    if target_network is None:
        raise ValueError("`target_network` is required for qgs_layer_to_pointset.")

    valid, message = validate_point_layer(layer)
    if not valid:
        raise ValueError(message)
    if time_col is not None:
        _require_fields(layer, [time_col])

    import_started = perf_counter()
    _NativeNetwork, NativePointSet = _import_fastnsa_dependencies()
    import_elapsed = perf_counter() - import_started

    warnings = []
    source_crs = layer.sourceCrs() if hasattr(layer, "sourceCrs") else layer.crs()
    if not source_crs.isValid() or (
        target_crs is not None and not target_crs.isValid()
    ):
        raise ValueError("Point and target layers must have valid CRS definitions.")
    if target_crs is None:
        target_crs = source_crs

    same_crs, same_crs_message = validate_same_crs(layer, kwargs.get("road_layer"))
    if not same_crs and same_crs_message:
        warnings.append(same_crs_message)

    x_values = []
    y_values = []
    time_values = [] if time_col is not None and times is None else None
    point_records = []
    point_counter = 0
    scan_started = perf_counter()
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry is None or geometry.isNull():
            continue

        transformed_geometry = _transform_geometry_if_needed(
            geometry,
            source_crs,
            target_crs,
            transform_context,
        )
        for part_index, point in enumerate(_extract_qgs_point_parts(transformed_geometry)):
            point_geometry = QgsGeometry.fromPointXY(point)
            x_values.append(point.x())
            y_values.append(point.y())
            if time_values is not None:
                time_values.append(feature[time_col])
            point_records.append(
                PointRecord(
                    point_id=point_counter,
                    source_fid=int(feature.id()),
                    part_index=part_index,
                    geometry_wkb=bytes(point_geometry.asWkb()),
                    source_attributes=list(feature.attributes()),
                )
            )
            point_counter += 1
    scan_elapsed = perf_counter() - scan_started

    if not point_records:
        raise ValueError("Point event layer does not contain usable point geometries.")

    array_started = perf_counter()
    x_array = np.ascontiguousarray(x_values, dtype=np.float64)
    y_array = np.ascontiguousarray(y_values, dtype=np.float64)
    temporal_metadata = None
    raw_times = times if times is not None else time_values
    if raw_times is not None:
        times_array, temporal_metadata, temporal_warning = normalize_temporal_values(
            raw_times,
            mode=time_mode,
            unit=time_unit,
            field_name=time_col or "provided times",
        )
        warnings.append(temporal_warning)
        if temporal_metadata.span <= 0.0:
            warnings.append(
                "All event times are equal after normalization; temporal interaction "
                "cannot vary across positive thresholds."
            )
    else:
        times_array = None
    if times_array is not None and len(times_array) != len(point_records):
        raise ValueError("Time input must have one value for each point geometry.")
    point_data = PointArrayData(
        x=x_array,
        y=y_array,
        times=times_array,
        temporal_metadata=temporal_metadata,
    )
    array_elapsed = perf_counter() - array_started

    pointset_started = perf_counter()
    pointset = NativePointSet.map_xy(
        target_network,
        x_array,
        y_array,
        mapping_method=mapping_method,
        comp_eps=comp_eps,
        n_threads=n_threads,
        times=times_array,
    )
    pointset_elapsed = perf_counter() - pointset_started
    timings = {
        "pointset.import_deps_s": import_elapsed,
        "pointset.feature_scan_s": scan_elapsed,
        "pointset.array_build_s": array_elapsed,
        "pointset.backend_build_s": pointset_elapsed,
        "pointset.total_s": perf_counter() - total_started,
    }
    return pointset, point_data, point_records, warnings, timings


def qgs_mapped_layer_to_pointset(layer: QgsFeatureSource, **kwargs):
    """Build a native point set directly from edge_id/offset fields."""
    total_started = perf_counter()
    target_network = kwargs.get("target_network")
    target_crs = kwargs.get("target_crs")
    time_col = kwargs.get("time_col")
    times = kwargs.get("times")
    time_mode = kwargs.get("time_mode", "auto")
    time_unit = kwargs.get("time_unit", "auto")
    transform_context = kwargs.get("transform_context")
    edge_id_field = kwargs.get("edge_id_field", "edge_id")
    offset_field = kwargs.get("offset_field", "offset")

    if target_network is None:
        raise ValueError("`target_network` is required for qgs_mapped_layer_to_pointset.")

    valid, message = validate_point_layer(layer)
    if not valid:
        raise ValueError(message)
    _require_fields(layer, [edge_id_field, offset_field])
    if time_col is not None:
        _require_fields(layer, [time_col])

    import_started = perf_counter()
    _NativeNetwork, NativePointSet = _import_fastnsa_dependencies()
    import_elapsed = perf_counter() - import_started

    field_names = get_field_names(layer)
    warnings = []
    source_crs = layer.sourceCrs() if hasattr(layer, "sourceCrs") else layer.crs()
    if not source_crs.isValid() or (
        target_crs is not None and not target_crs.isValid()
    ):
        raise ValueError("Mapped point and target layers must have valid CRS definitions.")
    if target_crs is None:
        target_crs = source_crs

    x_values = []
    y_values = []
    time_values = [] if time_col is not None and times is None else None
    point_records = []
    edge_ids = []
    offsets = []
    point_counter = 0
    scan_started = perf_counter()
    for feature in layer.getFeatures():
        geometry = feature.geometry()
        if geometry is None or geometry.isNull():
            continue

        transformed_geometry = _transform_geometry_if_needed(
            geometry,
            source_crs,
            target_crs,
            transform_context,
        )
        for part_index, point in enumerate(_extract_qgs_point_parts(transformed_geometry)):
            point_geometry = QgsGeometry.fromPointXY(point)
            x_values.append(point.x())
            y_values.append(point.y())
            if time_values is not None:
                time_values.append(feature[time_col])
            point_records.append(
                PointRecord(
                    point_id=(
                        int(feature["point_id"])
                        if "point_id" in field_names
                        else point_counter
                    ),
                    source_fid=int(feature.id()),
                    part_index=part_index,
                    geometry_wkb=bytes(point_geometry.asWkb()),
                    source_attributes=list(feature.attributes()),
                )
            )
            edge_ids.append(int(feature[edge_id_field]))
            offsets.append(float(feature[offset_field]))
            point_counter += 1
    scan_elapsed = perf_counter() - scan_started

    if not point_records:
        raise ValueError("Mapped layer does not contain usable point geometries.")

    array_started = perf_counter()
    x_array = np.ascontiguousarray(x_values, dtype=np.float64)
    y_array = np.ascontiguousarray(y_values, dtype=np.float64)
    temporal_metadata = None
    raw_times = times if times is not None else time_values
    if raw_times is not None:
        times_array, temporal_metadata, temporal_warning = normalize_temporal_values(
            raw_times,
            mode=time_mode,
            unit=time_unit,
            field_name=time_col or "provided times",
        )
        warnings.append(temporal_warning)
        if temporal_metadata.span <= 0.0:
            warnings.append(
                "All event times are equal after normalization; temporal interaction "
                "cannot vary across positive thresholds."
            )
    else:
        times_array = None
    if times_array is not None and len(times_array) != len(point_records):
        raise ValueError("Time input must have one value for each point geometry.")
    point_data = PointArrayData(
        x=x_array,
        y=y_array,
        times=times_array,
        temporal_metadata=temporal_metadata,
    )
    array_elapsed = perf_counter() - array_started

    pointset_started = perf_counter()
    pointset = NativePointSet.from_mapped(
        target_network,
        edge_ids=np.array(edge_ids, dtype=np.int32),
        offsets=np.array(offsets, dtype=np.float64),
        times=times_array,
    )
    pointset_elapsed = perf_counter() - pointset_started

    timings = {
        "pointset.import_deps_s": import_elapsed,
        "pointset.feature_scan_s": scan_elapsed,
        "pointset.array_build_s": array_elapsed,
        "pointset.backend_build_s": pointset_elapsed,
        "pointset.total_s": perf_counter() - total_started,
    }
    return pointset, point_data, point_records, warnings, timings


def qgs_layers_to_point_network_inputs(point_layer: QgsFeatureSource, road_layer: QgsFeatureSource, **kwargs):
    """Build shared FastNSA network + point inputs from QGIS layers."""
    total_started = perf_counter()
    valid, message = validate_point_layer(point_layer)
    if not valid:
        raise ValueError(message)
    valid, message = validate_line_layer(road_layer)
    if not valid:
        raise ValueError(message)

    stage_callback = kwargs.get("stage_callback")
    if stage_callback:
        stage_callback("Road network conversion")
    network, edge_records, network_warnings, network_timings = qgs_layer_to_network(road_layer, **kwargs)
    if stage_callback:
        stage_callback("Event mapping")
    pointset, point_data, point_records, point_warnings, point_timings = qgs_layer_to_pointset(
        point_layer,
        target_network=network,
        target_crs=road_layer.sourceCrs() if hasattr(road_layer, "sourceCrs") else road_layer.crs(),
        road_layer=road_layer,
        mapping_method=kwargs.get("mapping_method", "R-tree"),
        comp_eps=kwargs.get("comp_eps", 10.0),
        n_threads=kwargs.get("n_threads", 0),
        time_col=kwargs.get("time_col"),
        times=kwargs.get("times"),
        time_mode=kwargs.get("time_mode", "auto"),
        time_unit=kwargs.get("time_unit", "auto"),
        transform_context=kwargs.get("transform_context"),
    )

    timings = {
        **network_timings,
        **point_timings,
        "bundle.point_record_build_s": 0.0,
        "bundle.total_s": perf_counter() - total_started,
    }

    return NearestEdgeInputBundle(
        network=network,
        pointset=pointset,
        point_data=point_data,
        point_events_kwargs={
            "mapping_method": kwargs.get("mapping_method", "R-tree"),
            "comp_eps": kwargs.get("comp_eps", 10.0),
            "n_threads": kwargs.get("n_threads", 0),
            "time_col": kwargs.get("time_col"),
            "times": kwargs.get("times"),
            "time_mode": kwargs.get("time_mode", "auto"),
            "time_unit": kwargs.get("time_unit", "auto"),
            "pointset": pointset,
        },
        point_records=point_records,
        point_fields=QgsFields(point_layer.fields()),
        edge_records=edge_records,
        network_signature=network.signature,
        warnings=[*network_warnings, *point_warnings],
        timings=timings,
    )


def qgs_layers_to_nearest_edge_inputs(point_layer: QgsFeatureSource, road_layer: QgsFeatureSource, **kwargs):
    """Build the real FastNSA nearest-edge input objects from QGIS layers."""
    return qgs_layers_to_point_network_inputs(point_layer, road_layer, **kwargs)


def qgs_layers_to_kfunction_inputs(point_layer: QgsFeatureSource, road_layer: QgsFeatureSource, **kwargs):
    """Build the real FastNSA K-function input objects from QGIS layers."""
    edge_id_field = kwargs.get("edge_id_field", "edge_id")
    offset_field = kwargs.get("offset_field", "offset")
    if _layer_has_fields(point_layer, [edge_id_field, offset_field]):
        return qgs_layers_to_preprocessed_network_inputs(
            point_layer,
            road_layer,
            **kwargs,
        )
    return qgs_layers_to_point_network_inputs(point_layer, road_layer, **kwargs)


def qgs_layers_to_kde_inputs(point_layer: QgsFeatureSource, road_layer: QgsFeatureSource, **kwargs):
    """Build the real FastNSA KDE input objects from QGIS layers."""
    return qgs_layers_to_kfunction_inputs(point_layer, road_layer, **kwargs)


def qgs_layers_to_preprocessed_network_inputs(
    mapped_point_layer: QgsFeatureSource,
    road_layer: QgsFeatureSource,
    **kwargs,
):
    """Build a shared analysis bundle from an existing mapped points layer."""
    total_started = perf_counter()
    valid, message = validate_point_layer(mapped_point_layer)
    if not valid:
        raise ValueError(message)
    valid, message = validate_line_layer(road_layer)
    if not valid:
        raise ValueError(message)

    stage_callback = kwargs.get("stage_callback")
    if stage_callback:
        stage_callback("Road network conversion")
    network, edge_records, network_warnings, network_timings = qgs_layer_to_network(road_layer, **kwargs)
    signature_warnings = _validate_mapped_network_signature(
        mapped_point_layer,
        network.signature,
        kwargs.get("network_signature_field", "network_sig"),
    )
    if stage_callback:
        stage_callback("Reusing preprocessed event mappings")
    pointset, point_data, point_records, point_warnings, point_timings = qgs_mapped_layer_to_pointset(
        mapped_point_layer,
        target_network=network,
        target_crs=road_layer.sourceCrs() if hasattr(road_layer, "sourceCrs") else road_layer.crs(),
        time_col=kwargs.get("time_col"),
        times=kwargs.get("times"),
        time_mode=kwargs.get("time_mode", "auto"),
        time_unit=kwargs.get("time_unit", "auto"),
        edge_id_field=kwargs.get("edge_id_field", "edge_id"),
        offset_field=kwargs.get("offset_field", "offset"),
        transform_context=kwargs.get("transform_context"),
    )

    timings = {
        **network_timings,
        **point_timings,
        "bundle.point_record_build_s": 0.0,
        "bundle.total_s": perf_counter() - total_started,
    }

    return NearestEdgeInputBundle(
        network=network,
        pointset=pointset,
        point_data=point_data,
        point_events_kwargs={
            "mapping_method": "preprocessed",
            "comp_eps": None,
            "n_threads": None,
            "time_col": kwargs.get("time_col"),
            "times": kwargs.get("times"),
            "time_mode": kwargs.get("time_mode", "auto"),
            "time_unit": kwargs.get("time_unit", "auto"),
            "pointset": pointset,
            "edge_id_field": kwargs.get("edge_id_field", "edge_id"),
            "offset_field": kwargs.get("offset_field", "offset"),
        },
        point_records=point_records,
        point_fields=QgsFields(mapped_point_layer.fields()),
        edge_records=edge_records,
        network_signature=network.signature,
        warnings=[*network_warnings, *signature_warnings, *point_warnings],
        timings=timings,
    )


def run_network_k_function(bundle: NearestEdgeInputBundle, **kwargs):
    """Run the real FastNSA network K-function backend using adapted QGIS inputs."""
    network_k_function, _spatiotemporal_network_k_function, _network_kde = _import_fastnsa_analysis_dependencies()
    return network_k_function(
        network=bundle.network,
        points=bundle.pointset,
        r_min=kwargs.get("r_min", 0.0),
        r_max=kwargs.get("r_max", 2000.0),
        r_step=kwargs.get("r_step", 50),
        method=kwargs.get("method", "NS"),
        simulations=kwargs.get("simulations", 0),
        alpha=kwargs.get("alpha", 0.05),
        return_simulations=kwargs.get("return_simulations", False),
        epsilon=kwargs.get("epsilon", 0.1),
        progress_callback=kwargs.get("progress_callback"),
    )


def run_spatiotemporal_network_k_function(bundle: NearestEdgeInputBundle, **kwargs):
    """Run the real FastNSA spatiotemporal K-function backend using adapted QGIS inputs."""
    _network_k_function, spatiotemporal_network_k_function, _network_kde = _import_fastnsa_analysis_dependencies()
    result = spatiotemporal_network_k_function(
        network=bundle.network,
        points=bundle.pointset,
        s_min=kwargs.get("s_min", 0.0),
        s_max=kwargs.get("s_max", 2000.0),
        s_step=kwargs.get("s_step", 50),
        t_min=kwargs.get("t_min", 0.0),
        t_max=kwargs.get("t_max", 2000.0),
        t_step=kwargs.get("t_step", 50),
        method=kwargs.get("method", "EARTH"),
        simulations=kwargs.get("simulations", 0),
        alpha=kwargs.get("alpha", 0.05),
        return_simulations=kwargs.get("return_simulations", False),
        progress_callback=kwargs.get("progress_callback"),
    )
    metadata = bundle.point_data.temporal_metadata
    if metadata is not None:
        result.time_unit = metadata.effective_unit
        result.time_origin = metadata.origin_label
        result.time_mode = metadata.effective_mode
    return result


def run_network_kde(bundle: NearestEdgeInputBundle, **kwargs):
    """Run the real FastNSA network KDE backend using adapted QGIS inputs."""
    _network_k_function, _spatiotemporal_network_k_function, network_kde = _import_fastnsa_analysis_dependencies()
    return network_kde(
        network=bundle.network,
        points=bundle.pointset,
        bandwidth=kwargs.get("bandwidth", 500.0),
        lixel_length=kwargs.get("lixel_length", 50.0),
        method=kwargs.get("method", "LION"),
        kernel=kwargs.get("kernel", "EPANECHNIKOV"),
        normalize=kwargs.get("normalize", False),
        progress_callback=kwargs.get("progress_callback"),
    )
