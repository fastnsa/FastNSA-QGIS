"""Conversion helpers from FastNSA outputs to QGIS-friendly objects."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from math import isfinite

from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsRendererRange,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from ..utils.layer_utils import safe_layer_name
from ..utils.density_style import (
    DEFAULT_DENSITY_CLASSES,
    DEFAULT_DENSITY_CLASSIFICATION,
    DEFAULT_SEPARATE_ZERO,
    calculate_density_ranges,
    turbo_color,
)


@dataclass
class TemporaryNearestEdgeMatch:
    """Temporary compatibility record for nearest-edge outputs."""

    point_id: int
    edge_id: int
    distance: float
    offset: float
    method: str
    network_signature: str
    source_attributes: list
    matched_point_wkb: bytes
    projected_point_wkb: bytes
    connection_line_wkb: bytes


@dataclass
class TemporaryNearestEdgeResult:
    """Temporary compatibility wrapper until FastNSA exposes pointset arrays."""

    records: list[TemporaryNearestEdgeMatch]
    source_fields: QgsFields


@dataclass
class FastNsaNearestEdgeMatch:
    """Nearest-edge match built from real PointEvents backend outputs."""

    point_id: int
    edge_id: int
    distance: float
    offset: float
    method: str
    network_signature: str
    source_attributes: list
    matched_point_wkb: bytes
    projected_point_wkb: bytes
    connection_line_wkb: bytes


@dataclass
class FastNsaNearestEdgeResult:
    """Adapter-facing nearest-edge result reconstructed from PointEvents."""

    records: list[FastNsaNearestEdgeMatch]
    source_fields: QgsFields


def build_nearest_edge_result_from_pointset(bundle, method: str):
    """Reconstruct nearest-edge results from real FastNSA PointEvents mappings."""
    records = []
    edge_lookup = _edge_geometry_lookup(bundle.edge_records)
    edge_ids = bundle.pointset.edge_ids_array()
    offsets = bundle.pointset.offsets_array()

    for index, point_record in enumerate(bundle.point_records):
        edge_id = int(edge_ids[index])
        line = edge_lookup.get(edge_id)
        if line is None:
            continue

        point_geometry = _geometry_from_wkb(point_record.geometry_wkb)
        projected_point = line.interpolate(float(offsets[index]))
        distance = float(point_geometry.distance(projected_point))
        connection_line = _connection_line(point_geometry, projected_point)

        records.append(
            FastNsaNearestEdgeMatch(
                point_id=point_record.point_id,
                edge_id=edge_id,
                distance=distance,
                offset=float(offsets[index]),
                method=method,
                network_signature=bundle.network_signature,
                source_attributes=point_record.source_attributes,
                matched_point_wkb=point_record.geometry_wkb,
                projected_point_wkb=bytes(projected_point.asWkb()),
                connection_line_wkb=bytes(connection_line.asWkb()),
            )
        )

    return FastNsaNearestEdgeResult(
        records=records,
        source_fields=QgsFields(bundle.point_fields),
    )


def build_temporary_nearest_edge_result(bundle, point_layer, road_layer, method: str):
    """Create a nearest-edge fallback using QGIS geometry operations."""
    del point_layer, road_layer
    records = []
    edge_lookup = _edge_geometry_lookup(bundle.edge_records)
    for point_record in bundle.point_records:
        point_geometry = _geometry_from_wkb(point_record.geometry_wkb)
        best_edge_id = None
        best_projected = None
        best_distance = None
        best_offset = None

        for edge_id, line in edge_lookup.items():
            offset = float(line.lineLocatePoint(point_geometry))
            if offset < 0:
                continue
            projected = line.interpolate(offset)
            distance = float(point_geometry.distance(projected))
            if best_distance is None or distance < best_distance:
                best_edge_id = edge_id
                best_projected = projected
                best_distance = distance
                best_offset = offset

        if best_edge_id is None or best_projected is None or best_distance is None or best_offset is None:
            continue

        connection_line = _connection_line(point_geometry, best_projected)

        records.append(
            TemporaryNearestEdgeMatch(
                point_id=point_record.point_id,
                edge_id=best_edge_id,
                distance=float(best_distance),
                offset=float(best_offset),
                method=method,
                network_signature=bundle.network_signature,
                source_attributes=point_record.source_attributes,
                matched_point_wkb=point_record.geometry_wkb,
                projected_point_wkb=bytes(best_projected.asWkb()),
                connection_line_wkb=bytes(connection_line.asWkb()),
            )
        )

    return TemporaryNearestEdgeResult(
        records=records,
        source_fields=QgsFields(bundle.point_fields),
    )


def _geometry_from_wkb(wkb: bytes) -> QgsGeometry:
    geometry = QgsGeometry()
    geometry.fromWkb(wkb)
    return geometry


def _edge_geometry_lookup(edge_records) -> dict[int, QgsGeometry]:
    return {
        record.edge_id: _geometry_from_wkb(record.geometry_wkb)
        for record in edge_records
    }


def _connection_line(point: QgsGeometry, projected: QgsGeometry) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY(
        [QgsPointXY(point.asPoint()), QgsPointXY(projected.asPoint())]
    )


def _nearest_edge_output_fields(source_fields: QgsFields):
    fields = QgsFields()
    fields.append(QgsField("point_id", QVariant.Int))
    fields.append(QgsField("edge_id", QVariant.Int))
    fields.append(QgsField("distance", QVariant.Double))
    fields.append(QgsField("offset", QVariant.Double))
    fields.append(QgsField("method", QVariant.String))
    fields.append(QgsField("network_sig", QVariant.String, len=64))
    reserved_names = {field.name().lower() for field in fields}
    source_indexes = []
    for index, source_field in enumerate(source_fields):
        if source_field.name().lower() in reserved_names:
            continue
        fields.append(QgsField(source_field))
        source_indexes.append(index)
    return fields, source_indexes


def nearest_edge_result_to_qgs_layers(
    result,
    crs,
    include_projected_points: bool = True,
    include_lines: bool = True,
):
    """Convert a nearest-edge compatibility result into QGIS memory layers."""
    output_fields, source_indexes = _nearest_edge_output_fields(result.source_fields)
    matched_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", safe_layer_name("fastnsa_matched_points"), "memory")
    matched_provider = matched_layer.dataProvider()
    matched_provider.addAttributes(output_fields)
    matched_layer.updateFields()

    projected_layer = None
    projected_provider = None
    if include_projected_points:
        projected_layer = QgsVectorLayer(
            f"Point?crs={crs.authid()}",
            safe_layer_name("fastnsa_projected_points"),
            "memory",
        )
        projected_provider = projected_layer.dataProvider()
        projected_provider.addAttributes(output_fields)
        projected_layer.updateFields()

    line_layer = None
    line_provider = None
    if include_lines:
        line_layer = QgsVectorLayer(
            f"LineString?crs={crs.authid()}",
            safe_layer_name("fastnsa_point_to_edge_lines"),
            "memory",
        )
        line_provider = line_layer.dataProvider()
        line_provider.addAttributes(output_fields)
        line_layer.updateFields()

    matched_features = []
    projected_features = []
    line_features = []

    for record in result.records:
        attributes = [
            record.point_id,
            record.edge_id,
            record.distance,
            record.offset,
            record.method,
            record.network_signature,
            *[
                record.source_attributes[index]
                for index in source_indexes
            ],
        ]

        matched_feature = QgsFeature(matched_layer.fields())
        matched_geometry = QgsGeometry()
        matched_geometry.fromWkb(record.matched_point_wkb)
        matched_feature.setGeometry(matched_geometry)
        matched_feature.setAttributes(attributes)
        matched_features.append(matched_feature)

        if projected_layer is not None:
            projected_feature = QgsFeature(projected_layer.fields())
            projected_geometry = QgsGeometry()
            projected_geometry.fromWkb(record.projected_point_wkb)
            projected_feature.setGeometry(projected_geometry)
            projected_feature.setAttributes(attributes)
            projected_features.append(projected_feature)

        if line_layer is not None:
            line_feature = QgsFeature(line_layer.fields())
            line_geometry = QgsGeometry()
            line_geometry.fromWkb(record.connection_line_wkb)
            line_feature.setGeometry(line_geometry)
            line_feature.setAttributes(attributes)
            line_features.append(line_feature)

    matched_provider.addFeatures(matched_features)
    matched_layer.updateExtents()

    if projected_provider is not None:
        projected_provider.addFeatures(projected_features)
        projected_layer.updateExtents()

    if line_provider is not None:
        line_provider.addFeatures(line_features)
        line_layer.updateExtents()

    layers = [matched_layer]
    if projected_layer is not None:
        layers.append(projected_layer)
    if line_layer is not None:
        layers.append(line_layer)
    return layers


def apply_density_style(
    layer: QgsVectorLayer,
    *,
    classification=DEFAULT_DENSITY_CLASSIFICATION,
    classes=DEFAULT_DENSITY_CLASSES,
    separate_zero=DEFAULT_SEPARATE_ZERO,
):
    """Apply the shared Turbo renderer used by the dialog and Processing."""
    values = []
    density_index = layer.fields().indexOf("density")
    if density_index < 0:
        return False

    for feature in layer.getFeatures():
        try:
            value = float(feature["density"])
            if isfinite(value):
                values.append(value)
        except (TypeError, ValueError, OverflowError):
            continue

    if not values:
        return False

    positive_ranges = calculate_density_ranges(values, classification, classes)
    nonpositive = [value for value in values if value <= 0.0]
    has_zero_class = separate_zero and bool(nonpositive)
    if not positive_ranges:
        symbol_factory = QgsLineSymbol if layer.geometryType() == 1 else QgsMarkerSymbol
        symbol = symbol_factory.createSimple(
            {"color": turbo_color(0, 2), "width": "0.8", "size": "2.4"}
        )
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()
        return True

    ranges = []
    color_count = len(positive_ranges) + (1 if has_zero_class else 0)
    if has_zero_class:
        symbol_factory = QgsLineSymbol if layer.geometryType() == 1 else QgsMarkerSymbol
        symbol = symbol_factory.createSimple(
            {"color": turbo_color(0, color_count), "width": "0.8", "size": "2.4"}
        )
        lower = min(nonpositive)
        label = "No density (0)" if lower == 0.0 else f"Non-positive ({lower:.4g} - 0)"
        ranges.append(QgsRendererRange(lower, 0.0, symbol, label))

    for index, (lower, upper) in enumerate(positive_ranges):
        color = turbo_color(index + (1 if has_zero_class else 0), color_count)
        if index == 0 and not has_zero_class:
            lower = min(lower, min(values))
        if layer.geometryType() == 1:
            symbol = QgsLineSymbol.createSimple({"color": color, "width": "1.0"})
        else:
            symbol = QgsMarkerSymbol.createSimple({"name": "circle", "color": color, "size": "2.6"})
        label = f"{lower:.4g} - {upper:.4g}"
        ranges.append(QgsRendererRange(lower, upper, symbol, label))

    renderer = QgsGraduatedSymbolRenderer("density", ranges)
    layer.setRenderer(renderer)
    layer.triggerRepaint()
    return True


def density_result_to_qgs_layer(bundle, result, crs, apply_style: bool = False):
    """Convert a FastNSA network KDE result into a QGIS memory layer."""
    layer = QgsVectorLayer(f"LineString?crs={crs.authid()}", safe_layer_name("fastnsa_kde_lixels"), "memory")
    provider = layer.dataProvider()

    fields = QgsFields()
    fields.append(QgsField("edge_id", QVariant.Int))
    fields.append(QgsField("start_n1", QVariant.Double))
    fields.append(QgsField("end_n1", QVariant.Double))
    fields.append(QgsField("offset_n1", QVariant.Double))
    fields.append(QgsField("offset_n2", QVariant.Double))
    fields.append(QgsField("lixel_len", QVariant.Double))
    fields.append(QgsField("density", QVariant.Double))
    provider.addAttributes(fields)
    layer.updateFields()

    edge_lookup = _edge_geometry_lookup(bundle.edge_records)
    lixel_length = float(getattr(result, "lixel_length", 0.0) or 0.0)
    half_length = lixel_length / 2.0
    segment_starts = getattr(result, "segment_start_n1", None)
    segment_ends = getattr(result, "segment_end_n1", None)
    features = []
    for index in range(len(result.edge_ids)):
        edge_id = int(result.edge_ids[index])
        line = edge_lookup.get(edge_id)
        if line is None:
            continue

        line_length = float(line.length())
        center_offset = float(result.offsets_n1[index])
        if segment_starts is not None and segment_ends is not None:
            start_offset = max(0.0, float(segment_starts[index]))
            end_offset = min(line_length, float(segment_ends[index]))
        else:
            start_offset = max(0.0, center_offset - half_length)
            end_offset = min(line_length, center_offset + half_length)
        if end_offset <= start_offset:
            continue

        segment = line.constGet().curveSubstring(start_offset, end_offset)
        if segment is None or segment.isEmpty():
            continue
        lixel_geometry = QgsGeometry(segment)

        feature = QgsFeature(layer.fields())
        feature.setGeometry(lixel_geometry)
        feature.setAttributes(
            [
                edge_id,
                float(start_offset),
                float(end_offset),
                float(result.offsets_n1[index]),
                float(result.offsets_n2[index]),
                float(end_offset - start_offset),
                float(result.density[index]),
            ]
        )
        features.append(feature)

    provider.addFeatures(features)
    layer.updateExtents()

    if apply_style:
        apply_density_style(layer)

    return layer


def kfunction_result_to_table_or_csv(result, output_path):
    """Write a K-function result to CSV and return the output path."""
    field_names = ["r", "k_obs", "k_theo", "k_lo", "k_hi"]

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(field_names)
        for index, distance in enumerate(result.r):
            writer.writerow(
                [
                    float(distance),
                    float(result.k_obs[index]),
                    float(result.k_theo[index]) if result.k_theo is not None else "",
                    float(result.k_lo[index]) if result.k_lo is not None else "",
                    float(result.k_hi[index]) if result.k_hi is not None else "",
                ]
            )

    return output_path


def kfunction_result_to_qgs_table(result, *, spatiotemporal=False):
    """Create a temporary no-geometry result table without requiring CSV export."""
    layer = QgsVectorLayer(
        "None", "FastNSA ST K-function" if spatiotemporal else "FastNSA K-function", "memory"
    )
    fields = QgsFields()
    numeric_names = ("s", "t", "k_obs", "k_lo", "k_hi") if spatiotemporal else (
        "r", "k_obs", "k_theo", "k_lo", "k_hi"
    )
    for name in numeric_names:
        fields.append(QgsField(name, QVariant.Double))
    if spatiotemporal:
        for name in ("status", "time_unit", "time_origin", "time_mode"):
            fields.append(QgsField(name, QVariant.String))
    provider = layer.dataProvider()
    if not provider.addAttributes(fields):
        raise RuntimeError("Could not create the result table fields.")
    layer.updateFields()

    def features():
        if spatiotemporal:
            for i, s in enumerate(result.s):
                for j, t in enumerate(result.t):
                    observed = float(result.k_obs[i, j])
                    low = float(result.k_lo[i, j]) if result.k_lo is not None else None
                    high = float(result.k_hi[i, j]) if result.k_hi is not None else None
                    status = "unbounded"
                    if high is not None and observed > high:
                        status = "above envelope"
                    elif low is not None and observed < low:
                        status = "below envelope"
                    elif low is not None and high is not None:
                        status = "within envelope"
                    feature = QgsFeature(layer.fields())
                    feature.setAttributes([
                        float(s), float(t), observed, low, high, status,
                        result.time_unit or "", result.time_origin or "", result.time_mode or "",
                    ])
                    yield feature
        else:
            for i, distance in enumerate(result.r):
                feature = QgsFeature(layer.fields())
                feature.setAttributes([
                    float(distance), float(result.k_obs[i]),
                    float(result.k_theo[i]) if result.k_theo is not None else None,
                    float(result.k_lo[i]) if result.k_lo is not None else None,
                    float(result.k_hi[i]) if result.k_hi is not None else None,
                ])
                yield feature

    # Bound the temporary feature list for large ST threshold grids.
    batch = []
    for feature in features():
        batch.append(feature)
        if len(batch) == 1000:
            if not provider.addFeatures(batch)[0]:
                raise RuntimeError("Could not populate the result table.")
            batch = []
    if batch and not provider.addFeatures(batch)[0]:
        raise RuntimeError("Could not populate the result table.")
    return layer


def spatiotemporal_kfunction_result_to_table_or_csv(result, output_path):
    """Write a spatiotemporal K-function result to CSV and return the output path."""
    field_names = [
        "s",
        "t",
        "k_obs",
        "k_lo",
        "k_hi",
        "status",
        "time_unit",
        "time_origin",
        "time_mode",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(field_names)
        for s_index, s_value in enumerate(result.s):
            for t_index, t_value in enumerate(result.t):
                status = "unbounded"
                if result.k_hi is not None and float(result.k_obs[s_index][t_index]) > float(result.k_hi[s_index][t_index]):
                    status = "above envelope"
                elif result.k_lo is not None and float(result.k_obs[s_index][t_index]) < float(result.k_lo[s_index][t_index]):
                    status = "below envelope"
                elif result.k_lo is not None and result.k_hi is not None:
                    status = "within envelope"
                writer.writerow(
                    [
                        float(s_value),
                        float(t_value),
                        float(result.k_obs[s_index][t_index]),
                        float(result.k_lo[s_index][t_index]) if result.k_lo is not None else "",
                        float(result.k_hi[s_index][t_index]) if result.k_hi is not None else "",
                        status,
                        result.time_unit or "",
                        result.time_origin or "",
                        result.time_mode or "",
                    ]
                )

    return output_path
