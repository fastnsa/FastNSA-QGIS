"""Validation helpers for the FastNSA plugin."""

from qgis.core import QgsCoordinateReferenceSystem, QgsFeatureSource, QgsMapLayer, QgsWkbTypes

from .layer_utils import get_feature_count, selected_layer


def validate_required_layer(combo_box, label: str) -> list[str]:
    """Validate that a required QGIS layer has been selected."""
    if selected_layer(combo_box) is None:
        return [f"{label} is required."]
    return []


def validate_text_required(value: str, label: str) -> list[str]:
    """Validate that a text field contains a non-empty value."""
    if not value.strip():
        return [f"{label} is required."]
    return []


def validate_vector_layer(layer: QgsMapLayer | QgsFeatureSource | None) -> tuple[bool, str]:
    """Validate that the input is a non-empty vector layer-like object."""
    if layer is None:
        return False, "Layer is required."
    if hasattr(layer, "isValid") and not layer.isValid():
        return False, "Layer is invalid."
    if not hasattr(layer, "getFeatures") or not hasattr(layer, "fields"):
        return False, "Layer is not a vector layer."
    if get_feature_count(layer) == 0:
        return False, "Layer is empty."
    return True, ""


def validate_line_layer(layer: QgsMapLayer | QgsFeatureSource | None) -> tuple[bool, str]:
    """Validate that the layer contains line geometries."""
    valid, message = validate_vector_layer(layer)
    if not valid:
        return valid, message
    geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
    if geometry_type != QgsWkbTypes.LineGeometry:
        return False, "Layer must use line geometry."
    return True, ""


def validate_point_layer(layer: QgsMapLayer | QgsFeatureSource | None) -> tuple[bool, str]:
    """Validate that the layer contains point geometries."""
    valid, message = validate_vector_layer(layer)
    if not valid:
        return valid, message
    geometry_type = QgsWkbTypes.geometryType(layer.wkbType())
    if geometry_type != QgsWkbTypes.PointGeometry:
        return False, "Layer must use point geometry."
    return True, ""


def validate_same_crs(
    layer_a: QgsMapLayer | QgsFeatureSource | None,
    layer_b: QgsMapLayer | QgsFeatureSource | None,
) -> tuple[bool, str]:
    """Validate that two layers share the same CRS."""
    if layer_a is None or layer_b is None:
        return False, "Both layers are required."
    crs_a = layer_a.sourceCrs() if hasattr(layer_a, "sourceCrs") else layer_a.crs()
    crs_b = layer_b.sourceCrs() if hasattr(layer_b, "sourceCrs") else layer_b.crs()
    if not crs_a.isValid() or not crs_b.isValid():
        return False, "Both layers must have a valid CRS."
    if crs_a != crs_b:
        return False, f"CRS mismatch: {crs_a.authid()} vs {crs_b.authid()}."
    return True, ""


def validate_projected_crs(layer: QgsMapLayer | QgsFeatureSource | None) -> tuple[bool, str]:
    """Warn when the layer uses a geographic CRS."""
    if layer is None:
        return False, "Layer is required."
    crs = layer.sourceCrs() if hasattr(layer, "sourceCrs") else layer.crs()
    if not isinstance(crs, QgsCoordinateReferenceSystem) or not crs.isValid():
        return False, "Layer CRS is invalid."
    if not crs.isGeographic():
        return True, ""
    return False, f"Layer CRS {crs.authid()} is geographic; projected CRS is recommended."


def validate_distance_crs(
    layer: QgsMapLayer | QgsFeatureSource | None,
) -> tuple[bool, str]:
    """Require a projected road CRS for algorithms whose parameters are distances."""
    valid, message = validate_projected_crs(layer)
    if valid:
        return True, ""
    if "invalid" in message.lower() or "required" in message.lower():
        return False, message
    crs = layer.sourceCrs() if hasattr(layer, "sourceCrs") else layer.crs()
    return False, (
        f"Road network CRS {crs.authid()} is geographic. Reproject the road network "
        "to a suitable projected CRS before running distance-based analysis."
    )


def validate_required_fields(
    layer: QgsMapLayer | QgsFeatureSource | None,
    fields: list[str],
) -> tuple[bool, str]:
    """Validate that a layer contains all required fields."""
    valid, message = validate_vector_layer(layer)
    if not valid:
        return valid, message
    layer_fields = {field.name() for field in layer.fields()}
    missing = [field for field in fields if field not in layer_fields]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}."
    return True, ""
