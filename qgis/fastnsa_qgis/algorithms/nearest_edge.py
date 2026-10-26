"""Nearest edge matching algorithm backed by the FastNSA adapter layer."""

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
)

from ..adapters.fastnsa_to_qgs import (
    build_nearest_edge_result_from_pointset,
    build_temporary_nearest_edge_result,
    nearest_edge_result_to_qgs_layers,
)
from ..adapters.qgs_to_fastnsa import format_timings_for_logs, qgs_layers_to_nearest_edge_inputs
from ..utils.validation import validate_distance_crs, validate_line_layer, validate_point_layer
from ..utils.progress import ProcessingProgress
from ..utils.analysis_options import GRID_HELP, NEAREST_PROCESSING_OPTIONS
from ..utils.processing_help import set_parameter_help


class FastNearestEdgeMatchingAlgorithm(QgsProcessingAlgorithm):
    """Processing entry point for the FastNSA nearest-edge adapter workflow."""

    POINT_LAYER = "POINT_LAYER"
    ROAD_LAYER = "ROAD_LAYER"
    METHOD = "METHOD"
    GRID_SIZE = "GRID_SIZE"
    THREADS = "THREADS"
    INCLUDE_PROJECTED_POINTS = "INCLUDE_PROJECTED_POINTS"
    INCLUDE_LINES = "INCLUDE_LINES"
    MATCHED_POINTS = "MATCHED_POINTS"
    PROJECTED_POINTS = "PROJECTED_POINTS"
    POINT_TO_EDGE_LINES = "POINT_TO_EDGE_LINES"
    MESSAGE = "MESSAGE"

    # Keep Processing indices stable for previously saved models.
    METHOD_OPTIONS = [label for label, _key in NEAREST_PROCESSING_OPTIONS]

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.POINT_LAYER,
                "Point event layer",
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.ROAD_LAYER,
                "Road network layer",
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.METHOD,
                "Method",
                self.METHOD_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRID_SIZE,
                "Compression tolerance (grid methods only)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=25.0,
                minValue=0.0001,
            )
        )
        self.parameterDefinition(self.GRID_SIZE).setMetadata({
            "widget_wrapper": {
                "class": "fastnsa_qgis.gui.processing_widgets.GridToleranceWidgetWrapper"
            }
        })
        self.addParameter(
            QgsProcessingParameterNumber(
                self.THREADS,
                "Number of threads",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=0,
                minValue=0,
                maxValue=32,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_PROJECTED_POINTS,
                "Output projected points",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.INCLUDE_LINES,
                "Output point-to-edge lines",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.MATCHED_POINTS,
                "Matched points",
                type=QgsProcessing.TypeVectorPoint,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.PROJECTED_POINTS,
                "Projected points",
                type=QgsProcessing.TypeVectorPoint,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.POINT_TO_EDGE_LINES,
                "Point-to-edge lines",
                type=QgsProcessing.TypeVectorLine,
                optional=True,
            )
        )
        self.addOutput(QgsProcessingOutputString(self.MESSAGE, "Result message"))
        set_parameter_help(self, {
            self.METHOD: (
                "R-tree matches against the original road geometry. Grid compression "
                "offers approximate and refined matching. The legacy Grid-ENN "
                "selection is an alias of refined matching for saved models."
            ),
            self.GRID_SIZE: GRID_HELP,
            self.THREADS: (
                "0 selects automatic parallelism with up to 8 workers. Explicit "
                "values are bounded by CPU availability, workload size, and the "
                "backend safety limit (32 by default)."
            ),
            self.INCLUDE_PROJECTED_POINTS: "Also write points located on their matched road edges.",
            self.INCLUDE_LINES: "Also write connector lines from each event to its road projection.",
            self.MATCHED_POINTS: (
                "Source event locations in the road CRS, with edge_id, offset, "
                "distance, method, network_sig and non-conflicting source attributes. "
                "Reuse this layer in the FastNSA analysis tools."
            ),
            self.PROJECTED_POINTS: "Road projections; written only when Output projected points is enabled.",
            self.POINT_TO_EDGE_LINES: "Displacement connectors; written only when Output point-to-edge lines is enabled.",
        })

    def processAlgorithm(self, parameters, context, feedback):
        point_layer = self.parameterAsVectorLayer(parameters, self.POINT_LAYER, context)
        road_layer = self.parameterAsVectorLayer(parameters, self.ROAD_LAYER, context)
        method_label, mapping_method = NEAREST_PROCESSING_OPTIONS[
            self.parameterAsEnum(parameters, self.METHOD, context)
        ]
        grid_size = self.parameterAsDouble(parameters, self.GRID_SIZE, context)
        threads = self.parameterAsInt(parameters, self.THREADS, context)
        include_projected_points = self.parameterAsBool(parameters, self.INCLUDE_PROJECTED_POINTS, context)
        include_lines = self.parameterAsBool(parameters, self.INCLUDE_LINES, context)

        valid, message = validate_point_layer(point_layer)
        if not valid:
            raise QgsProcessingException(message)
        valid, message = validate_line_layer(road_layer)
        if not valid:
            raise QgsProcessingException(message)
        valid, message = validate_distance_crs(road_layer)
        if not valid:
            raise QgsProcessingException(message)

        feedback.pushInfo("Running algorithm: Fast Nearest Edge Matching")
        feedback.pushInfo("Converting QGIS layers to FastNSA inputs...")
        progress = ProcessingProgress(feedback)
        progress.stage("Input validation")

        try:
            bundle = qgs_layers_to_nearest_edge_inputs(
                point_layer,
                road_layer,
                mapping_method=mapping_method,
                comp_eps=grid_size,
                n_threads=threads,
                stage_callback=progress.stage,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        for warning in bundle.warnings:
            feedback.pushInfo(f"Warning: {warning}")

        pointset = bundle.point_events_kwargs["pointset"]
        feedback.pushInfo(f"Converted network type: {type(bundle.network).__name__}")
        feedback.pushInfo(f"Converted point data type: {type(bundle.point_data).__name__}")
        feedback.pushInfo(f"Converted pointset type: {type(pointset).__name__}")
        feedback.pushInfo(f"Converted road edges: {len(bundle.edge_records)}")
        feedback.pushInfo(f"Converted event points: {len(bundle.point_records)}")
        for line in format_timings_for_logs(bundle.timings, prefix="Adapter timing"):
            feedback.pushInfo(line)
        try:
            result = build_nearest_edge_result_from_pointset(bundle, method_label)
            feedback.pushInfo("Built nearest-edge outputs from native event mappings.")
        except Exception as exc:
            feedback.pushInfo(f"Falling back to temporary nearest-edge wrapper: {exc}")
            result = build_temporary_nearest_edge_result(bundle, point_layer, road_layer, method_label)
        progress.stage("Output writing")
        output_layers = nearest_edge_result_to_qgs_layers(
            result,
            road_layer.crs(),
            include_projected_points=include_projected_points,
            include_lines=include_lines,
        )

        results = {}
        matched_dest_id = self._write_output_layer(
            parameters,
            context,
            output_layers[0],
            self.MATCHED_POINTS,
        )
        results[self.MATCHED_POINTS] = matched_dest_id

        next_index = 1
        if include_projected_points and len(output_layers) > next_index:
            results[self.PROJECTED_POINTS] = self._write_output_layer(
                parameters,
                context,
                output_layers[next_index],
                self.PROJECTED_POINTS,
            )
            next_index += 1

        line_index = 2 if include_projected_points else 1
        if include_lines and len(output_layers) > line_index:
            line_layer = output_layers[line_index]
            results[self.POINT_TO_EDGE_LINES] = self._write_output_layer(
                parameters,
                context,
                line_layer,
                self.POINT_TO_EDGE_LINES,
            )

        message_text = "FastNSA nearest-edge matching completed."
        feedback.pushInfo(message_text)
        results[self.MESSAGE] = message_text
        return results

    def _write_output_layer(self, parameters, context, layer, output_name):
        sink, dest_id = self.parameterAsSink(
            parameters,
            output_name,
            context,
            layer.fields(),
            layer.wkbType(),
            layer.crs(),
        )
        if sink is None:
            raise QgsProcessingException(f"Could not create output sink for {output_name}.")

        features = [QgsFeature(feature) for feature in layer.getFeatures()]
        sink.addFeatures(features, QgsFeatureSink.FastInsert)
        return dest_id

    def createInstance(self):
        return type(self)()

    def name(self):
        return "fast_nearest_edge_matching"

    def displayName(self):
        return "Fast Nearest Edge Matching"

    def group(self):
        return "FastNSA"

    def groupId(self):
        return "fastnsa"

    def shortHelpString(self):
        return (
            "<p>Match point events to road edges and prepare reusable inputs for network "
            "density, network K-function and spatiotemporal network K-function.</p>"
            "<p><b>Inputs and units:</b> The road layer must use a projected CRS. Event "
            "coordinates are transformed to it when needed. Distances and compression "
            "tolerance use road CRS map units, not necessarily metres.</p>"
            "<p><b>Methods:</b> R-tree, grid compression (approximate), and grid compression "
            "(refined). Compression tolerance is ignored by R-tree. The fourth selection "
            "is a legacy alias of refined matching.</p>"
            "<p><b>Outputs:</b> Matched points keep source locations and attributes, adding "
            "edge_id, offset, distance, method and network_sig. Offset is distance along "
            "the edge from its start; distance is event-to-projection displacement. "
            "Edge IDs are internal IDs, not road feature IDs. Optional projected points "
            "and connector lines support visual checks.</p>"
            "<p><b>Reuse:</b> Keep the mapping fields and network_sig unchanged and select "
            "the same road network for subsequent analyses.</p>"
        )
