"""Helpers for working with QGIS layers inside the FastNSA plugin."""

from pathlib import Path

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeatureSource,
    QgsFields,
    QgsProject,
    QgsVectorLayer,
    QgsVectorLayerFeatureSource,
    QgsVectorFileWriter,
    QgsWkbTypes,
)


_LAYER_REVISIONS = {}
_TRACKED_LAYER_IDS = set()


def _layer_provider_timestamp(layer):
    try:
        timestamp = layer.dataProvider().dataTimestamp()
        return timestamp.toString("yyyy-MM-ddTHH:mm:ss.zzz") if timestamp.isValid() else ""
    except Exception:
        return ""


def _track_layer_revision(layer: QgsVectorLayer):
    """Track edits on a live layer so snapshots can invalidate native caches."""
    layer_id = layer.id()
    _LAYER_REVISIONS.setdefault(layer_id, 0)
    if layer_id in _TRACKED_LAYER_IDS:
        return

    def changed(*_args, tracked_id=layer_id):
        _LAYER_REVISIONS[tracked_id] = _LAYER_REVISIONS.get(tracked_id, 0) + 1

    for signal_name in (
        "featureAdded",
        "featureDeleted",
        "geometryChanged",
        "dataChanged",
        "editingStopped",
    ):
        signal = getattr(layer, signal_name, None)
        if signal is not None:
            signal.connect(changed)
    _TRACKED_LAYER_IDS.add(layer_id)


class LayerFeatureSourceSnapshot:
    """Thread-safe feature source with copied vector-layer metadata."""

    def __init__(self, layer: QgsVectorLayer):
        _track_layer_revision(layer)
        self._source = QgsVectorLayerFeatureSource(layer)
        self._fields = QgsFields(layer.fields())
        self._crs = QgsCoordinateReferenceSystem(layer.crs())
        self._wkb_type = layer.wkbType()
        self._feature_count = int(layer.featureCount())
        self._cache_identity = (
            layer.id(),
            layer.source(),
            self._crs.authid(),
            _LAYER_REVISIONS.get(layer.id(), 0),
            self._feature_count,
            _layer_provider_timestamp(layer),
        )

    def getFeatures(self, request=None):
        if request is None:
            return self._source.getFeatures()
        return self._source.getFeatures(request)

    def fields(self):
        return self._fields

    def crs(self):
        return self._crs

    def wkbType(self):
        return self._wkb_type

    def featureCount(self):
        return self._feature_count

    def fastnsaCacheIdentity(self):
        return self._cache_identity


def selected_layer(combo_box) -> QgsVectorLayer | None:
    """Return the currently selected layer from a combo box-like widget."""
    if combo_box is None:
        return None
    return combo_box.currentLayer()


def snapshot_layer(layer: QgsVectorLayer) -> LayerFeatureSourceSnapshot:
    """Capture a vector layer for safe read-only use in a background task."""
    return LayerFeatureSourceSnapshot(layer)


def selected_layer_name(combo_box, fallback: str = "None") -> str:
    """Return a safe user-facing layer name."""
    layer = selected_layer(combo_box)
    return layer.name() if layer is not None else fallback


def get_field_names(layer: QgsFeatureSource | None) -> list[str]:
    """Return field names for a vector layer-like object."""
    if layer is None or not hasattr(layer, "fields"):
        return []
    return [field.name() for field in layer.fields()]


def get_layer_geometry_type_name(layer: QgsFeatureSource | None) -> str:
    """Return a readable geometry type name for a layer-like object."""
    if layer is None or not hasattr(layer, "wkbType"):
        return "Unknown"
    return QgsWkbTypes.displayString(layer.wkbType())


def get_feature_count(layer: QgsFeatureSource | None) -> int:
    """Return a count, or cheaply detect content for feature-source snapshots."""
    if layer is None:
        return 0
    if hasattr(layer, "featureCount"):
        return int(layer.featureCount())
    if not hasattr(layer, "getFeatures"):
        return 0

    iterator = layer.getFeatures()
    try:
        next(iterator)
    except StopIteration:
        return 0
    return 1


def safe_layer_name(name: str) -> str:
    """Normalize a layer name for output display."""
    cleaned = (name or "").strip()
    if not cleaned:
        return "fastnsa_output"
    return "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in cleaned)


def add_layers_to_project(layers: list[QgsVectorLayer]) -> list[QgsVectorLayer]:
    """Add valid layers to the active QGIS project and return the ones added."""
    project = QgsProject.instance()
    added = []
    for layer in layers:
        if layer is not None and layer.isValid():
            project.addMapLayer(layer)
            added.append(layer)
    return added


def write_layers_to_geopackage(
    layers: list[QgsVectorLayer],
    gpkg_path: str,
    layer_names: list[str] | None = None,
) -> list[str]:
    """Write memory layers to a GeoPackage and return written layer names."""
    if not gpkg_path.strip():
        raise ValueError("GeoPackage output path is required.")

    written_names = []
    transform_context = QgsProject.instance().transformContext()

    for index, layer in enumerate(layers):
        if layer is None or not layer.isValid():
            continue

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = (
            layer_names[index]
            if layer_names is not None and index < len(layer_names)
            else safe_layer_name(layer.name())
        )
        options.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer
            if Path(gpkg_path).exists() or index > 0
            else QgsVectorFileWriter.CreateOrOverwriteFile
        )

        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            gpkg_path,
            transform_context,
            options,
        )
        error_code = result[0]
        error_message = result[1] if len(result) > 1 else ""
        if error_code != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"Failed to write layer {options.layerName}: {error_message}")

        written_names.append(options.layerName)

    return written_names


def load_geopackage_layers(gpkg_path: str, layer_names: list[str]) -> list[QgsVectorLayer]:
    """Load named GeoPackage layers so project results use persistent providers."""
    layers = []
    for layer_name in layer_names:
        source = f"{gpkg_path}|layername={layer_name}"
        layer = QgsVectorLayer(source, layer_name, "ogr")
        if not layer.isValid():
            raise RuntimeError(f"Could not load GeoPackage layer: {layer_name}")
        layers.append(layer)
    return layers
