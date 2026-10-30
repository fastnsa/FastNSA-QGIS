"""Network KDE algorithm backed by the FastNSA adapter layer."""

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
)

from ..adapters.fastnsa_to_qgs import apply_density_style, density_result_to_qgs_layer
from ..adapters.qgs_to_fastnsa import (
    format_timings_for_logs,
    qgs_layers_to_kde_inputs,
    run_network_kde,
)
from ..utils.validation import validate_distance_crs, validate_line_layer, validate_point_layer
from ..utils.density_style import (
    DEFAULT_DENSITY_CLASSES,
    DEFAULT_SEPARATE_ZERO,
    DENSITY_CLASSIFICATION_OPTIONS,
)
from ..utils.progress import ProcessingProgress
from ..utils.processing_help import MAPPING_REUSE_HELP, set_parameter_help


class _DensityStylePostProcessor(QgsProcessingLayerPostProcessorInterface):
    """Apply and persist the renderer after Processing loads the destination."""

    _live_instances = set()

    def __init__(self, classification, classes, separate_zero):
        super().__init__()
        self.classification = classification
        self.classes = classes
        self.separate_zero = separate_zero
        # SIP transfers C++ ownership, but the Python subclass must remain alive
        # for its virtual postProcessLayer implementation to be called.
        self._live_instances.add(self)

    def postProcessLayer(self, layer, context, feedback):
        del context
        try:
            feedback.pushInfo("Stage: Style application")
            feedback.setProgress(98.0)
            if not apply_density_style(
                layer,
                classification=self.classification,
                classes=self.classes,
                separate_zero=self.separate_zero,
            ):
                feedback.reportError(
                    "FastNSA density style was not applied because the output has no usable density values."
                )
                return

            source_path = layer.source().split("|", 1)[0].lower()
            if layer.providerType() == "ogr" and source_path.endswith(".gpkg"):
                error = layer.saveStyleToDatabase(
                    "FastNSA density",
                    "FastNSA Turbo density renderer",
                    True,
                    "",
                )
                if error:
                    feedback.reportError(f"Could not persist the density style: {error}")
            feedback.pushInfo("Applied the FastNSA density style to the loaded output layer.")
        finally:
            self._live_instances.discard(self)


class FastNetworkKdeAlgorithm(QgsProcessingAlgorithm):
    """Processing entry point for the FastNSA KDE adapter workflow."""

    POINT_LAYER = "POINT_LAYER"
    ROAD_LAYER = "ROAD_LAYER"
    BANDWIDTH = "BANDWIDTH"
    KERNEL = "KERNEL"
    SEGMENT_RESOLUTION = "SEGMENT_RESOLUTION"
    METHOD = "METHOD"
    NORMALIZE = "NORMALIZE"
    APPLY_STYLE = "APPLY_STYLE"
    STYLE_CLASSIFICATION = "STYLE_CLASSIFICATION"
    STYLE_CLASSES = "STYLE_CLASSES"
    STYLE_SEPARATE_ZERO = "STYLE_SEPARATE_ZERO"
    DENSITY_POINTS = "DENSITY_POINTS"
    MESSAGE = "MESSAGE"

    METHOD_OPTIONS = ["LION", "ADA"]
    KERNEL_OPTIONS = ["Epanechnikov"]

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
            QgsProcessingParameterNumber(
                self.BANDWIDTH,
                "Bandwidth",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=500.0,
                minValue=1.0,
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
            QgsProcessingParameterEnum(
                self.KERNEL,
                "Kernel type",
                self.KERNEL_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEGMENT_RESOLUTION,
                "Segment resolution",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=50.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.NORMALIZE,
                "Normalize density",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.STYLE_CLASSIFICATION,
                "Density classification",
                [label for label, _key in DENSITY_CLASSIFICATION_OPTIONS],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STYLE_CLASSES,
                "Density classes",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=DEFAULT_DENSITY_CLASSES,
                minValue=3,
                maxValue=30,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.STYLE_SEPARATE_ZERO,
                "Show zero density as a separate class",
                defaultValue=DEFAULT_SEPARATE_ZERO,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.APPLY_STYLE,
                "Apply density style",
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.DENSITY_POINTS,
                "KDE lixel segments",
                type=QgsProcessing.TypeVectorLine,
            )
        )
        self.addOutput(QgsProcessingOutputString(self.MESSAGE, "Result message"))
        set_parameter_help(self, {
            self.POINT_LAYER: MAPPING_REUSE_HELP,
            self.METHOD: "LION is the default accelerated method; ADA is the alternative supported method.",
            self.KERNEL: "Only the Epanechnikov kernel is supported in this release.",
            self.BANDWIDTH: "Network-distance smoothing radius in road CRS map units.",
            self.SEGMENT_RESOLUTION: (
                "Target lixel line length in road CRS map units. Final segments can "
                "be shorter. Smaller values increase computation and output size."
            ),
            self.NORMALIZE: (
                "Scale density so its nonzero network integral (density times actual "
                "segment length) is 1. All-zero results remain zero. This occurs "
                "before styling and is not a simple sum-of-values normalization."
            ),
            self.APPLY_STYLE: (
                "Apply a Turbo graduated renderer after Processing loads the result "
                "layer. Enable output loading to see it. For a loaded GeoPackage "
                "output, also attempt to save the style in the database."
            ),
            self.STYLE_CLASSIFICATION: (
                "Quantile uses equal-count classes; Equal interval uses equal numeric "
                "widths. These options only affect styling, not computed density."
            ),
            self.STYLE_CLASSES: "Requested number of density classes (default 12); tied values may reduce the count.",
            self.STYLE_SEPARATE_ZERO: "Give zero/non-positive density a separate lowest class when styling.",
            self.DENSITY_POINTS: "Lixel line segments with density and actual segment length, not a point layer.",
        })

    def processAlgorithm(self, parameters, context, feedback):
        point_layer = self.parameterAsVectorLayer(parameters, self.POINT_LAYER, context)
        road_layer = self.parameterAsVectorLayer(parameters, self.ROAD_LAYER, context)
        bandwidth = self.parameterAsDouble(parameters, self.BANDWIDTH, context)
        method_index = self.parameterAsEnum(parameters, self.METHOD, context)
        kernel_index = self.parameterAsEnum(parameters, self.KERNEL, context)
        if method_index < 0 or method_index >= len(self.METHOD_OPTIONS):
            raise QgsProcessingException("Unsupported NKDV method selection.")
        if kernel_index < 0 or kernel_index >= len(self.KERNEL_OPTIONS):
            raise QgsProcessingException(
                "This saved configuration selects an unavailable NKDV kernel. "
                "Select Epanechnikov and run it again."
            )
        method_label = self.METHOD_OPTIONS[method_index]
        kernel_label = self.KERNEL_OPTIONS[kernel_index]
        lixel_length = self.parameterAsDouble(parameters, self.SEGMENT_RESOLUTION, context)
        normalize = self.parameterAsBool(parameters, self.NORMALIZE, context)
        apply_style = self.parameterAsBool(parameters, self.APPLY_STYLE, context)
        style_index = self.parameterAsEnum(parameters, self.STYLE_CLASSIFICATION, context)
        if style_index < 0 or style_index >= len(DENSITY_CLASSIFICATION_OPTIONS):
            raise QgsProcessingException("Unsupported density classification selection.")
        style_classification = DENSITY_CLASSIFICATION_OPTIONS[style_index][1]
        style_classes = self.parameterAsInt(parameters, self.STYLE_CLASSES, context)
        style_separate_zero = self.parameterAsBool(parameters, self.STYLE_SEPARATE_ZERO, context)

        if kernel_label != "Epanechnikov":
            raise QgsProcessingException(
                "The current NKDV backend only supports the Epanechnikov kernel."
            )

        valid, message = validate_point_layer(point_layer)
        if not valid:
            raise QgsProcessingException(message)
        valid, message = validate_line_layer(road_layer)
        if not valid:
            raise QgsProcessingException(message)
        valid, message = validate_distance_crs(road_layer)
        if not valid:
            raise QgsProcessingException(message)

        feedback.pushInfo("Running algorithm: Fast Network KDE")
        feedback.pushInfo("Converting QGIS layers to FastNSA inputs...")
        progress = ProcessingProgress(feedback)
        progress.stage("Input validation")

        try:
            bundle = qgs_layers_to_kde_inputs(
                point_layer,
                road_layer,
                stage_callback=progress.stage,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        for warning in bundle.warnings:
            feedback.pushInfo(f"Warning: {warning}")

        feedback.pushInfo(f"Converted network type: {type(bundle.network).__name__}")
        feedback.pushInfo(f"Converted point data type: {type(bundle.point_data).__name__}")
        feedback.pushInfo(f"Converted pointset type: {type(bundle.pointset).__name__}")
        feedback.pushInfo(f"Converted road edges: {len(bundle.edge_records)}")
        feedback.pushInfo(f"Converted event points: {len(bundle.point_records)}")
        for line in format_timings_for_logs(bundle.timings, prefix="Adapter timing"):
            feedback.pushInfo(line)

        try:
            result = run_network_kde(
                bundle,
                bandwidth=bandwidth,
                lixel_length=lixel_length,
                kernel=kernel_label.upper(),
                method=method_label.upper(),
                normalize=normalize,
                progress_callback=progress.native,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        progress.stage("Output writing")
        density_layer = density_result_to_qgs_layer(
            bundle,
            result,
            road_layer.crs(),
            apply_style=False,
        )
        density_dest_id = self._write_output_layer(
            parameters,
            context,
            density_layer,
            self.DENSITY_POINTS,
        )
        if apply_style and context.willLoadLayerOnCompletion(density_dest_id):
            processor = _DensityStylePostProcessor(
                style_classification,
                style_classes,
                style_separate_zero,
            )
            details = context.layerToLoadOnCompletionDetails(density_dest_id)
            details.setPostProcessor(processor)

        feedback.pushInfo(f"KDE lixels: {len(result.edge_ids)}")
        feedback.pushInfo(f"KDE method: {result.method}")
        feedback.pushInfo(f"KDE kernel: {result.kernel}")

        return {
            self.DENSITY_POINTS: density_dest_id,
            self.MESSAGE: "FastNSA network KDE completed.",
        }

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
        return "fast_network_kde"

    def displayName(self):
        return "Fast Network KDE"

    def group(self):
        return "FastNSA"

    def groupId(self):
        return "fastnsa"

    def shortHelpString(self):
        return (
            "<p>Map event density along roads using LION or ADA with the Epanechnikov "
            "kernel. The result is a <b>line segment</b> layer: each short road segment "
            "(lixel) has a density value.</p>"
            "<p><b>Inputs:</b> Use a projected road CRS. Raw events are matched automatically; "
            "compatible Matched points reuse edge_id/offset and network_sig on the same "
            "unchanged network.</p>"
            "<p><b>Parameters:</b> Bandwidth is the smoothing radius; segment resolution "
            "is the target lixel length, with shorter final segments. Both use road CRS "
            "map units. Smaller segments increase output size.</p>"
            "<p><b>Colors and normalization:</b> Use the Turbo color ramp with Quantile "
            "or Equal interval classes; the default is 12 classes. Zero-density segments "
            "can have their own color. Add the result to QGIS to see the style. "
            "If normalization is enabled, density is scaled so its integral along the "
            "network is 1 (unless all values are zero), before colors are assigned.</p>"
        )
