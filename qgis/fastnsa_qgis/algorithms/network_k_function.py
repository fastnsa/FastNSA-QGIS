"""Network K-function algorithm backed by the FastNSA adapter layer."""

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from ..adapters.fastnsa_to_qgs import kfunction_result_to_table_or_csv
from ..adapters.qgs_to_fastnsa import (
    format_timings_for_logs,
    qgs_layers_to_kfunction_inputs,
    run_network_k_function,
)
from ..utils.validation import validate_distance_crs, validate_line_layer, validate_point_layer
from ..utils.progress import ProcessingProgress
from ..utils.analysis_options import DEFAULT_K_MAX_DISTANCE, K_METHOD_OPTIONS
from ..utils.processing_outputs import register_csv_for_loading
from ..utils.processing_help import MAPPING_REUSE_HELP, set_parameter_help


class FastNetworkKFunctionAlgorithm(QgsProcessingAlgorithm):
    """Processing entry point for the FastNSA K-function workflow."""

    POINT_LAYER = "POINT_LAYER"
    ROAD_LAYER = "ROAD_LAYER"
    METHOD = "METHOD"
    MIN_DISTANCE = "MIN_DISTANCE"
    MAX_DISTANCE = "MAX_DISTANCE"
    STEP_DISTANCE = "STEP_DISTANCE"
    EPSILON = "EPSILON"
    MONTE_CARLO = "MONTE_CARLO"
    SIMULATIONS = "SIMULATIONS"
    OUTPUT_TABLE = "OUTPUT_TABLE"
    OUTPUT_CSV = "OUTPUT_CSV"
    LOAD_CSV = "LOAD_CSV"
    MESSAGE = "MESSAGE"

    METHOD_OPTIONS = [label for label, _key in K_METHOD_OPTIONS]

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
                self.MIN_DISTANCE,
                "Min distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_DISTANCE,
                "Max distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=DEFAULT_K_MAX_DISTANCE,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.STEP_DISTANCE,
                "Step distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=100.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EPSILON,
                "Epsilon (STARS only)",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.01,
                minValue=0.0001,
                maxValue=1.0,
            )
        )
        self.parameterDefinition(self.EPSILON).setMetadata({
            "widget_wrapper": {
                "class": "fastnsa_qgis.gui.processing_widgets.ApproximationEpsilonWidgetWrapper"
            }
        })
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.MONTE_CARLO,
                "Monte Carlo envelope",
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SIMULATIONS,
                "Number of simulations",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=5,
                minValue=1,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT_TABLE,
                "K-function result table",
            )
        )
        self.addParameter(
            QgsProcessingParameterFileDestination(
                self.OUTPUT_CSV,
                "Output CSV",
                fileFilter="CSV files (*.csv)",
                optional=True,
            )
        )
        self.addOutput(QgsProcessingOutputString(self.MESSAGE, "Result message"))
        self.addParameter(QgsProcessingParameterBoolean(
            self.LOAD_CSV, "Load exported CSV table into QGIS", defaultValue=False
        ))
        set_parameter_help(self, {
            self.POINT_LAYER: MAPPING_REUSE_HELP + " At least two events are required.",
            self.METHOD: "NS is exact. STARS uses source-event sampling and threshold sharing.",
            self.EPSILON: (
                "STARS only; disabled and ignored for NS. Up to ceil(1 / epsilon) "
                "source events are sampled per occupied edge. Smaller epsilon uses "
                "more events; it is not a guaranteed percentage error bound."
            ),
            self.MIN_DISTANCE: "Minimum network-distance threshold in road CRS map units.",
            self.MAX_DISTANCE: "Maximum network-distance threshold in road CRS map units; must exceed the minimum.",
            self.STEP_DISTANCE: "Spacing between distance thresholds, not a simulation count or event sample size.",
        })

    def processAlgorithm(self, parameters, context, feedback):
        point_layer = self.parameterAsVectorLayer(parameters, self.POINT_LAYER, context)
        road_layer = self.parameterAsVectorLayer(parameters, self.ROAD_LAYER, context)
        method = K_METHOD_OPTIONS[self.parameterAsEnum(parameters, self.METHOD, context)][1]
        r_min = self.parameterAsDouble(parameters, self.MIN_DISTANCE, context)
        r_max = self.parameterAsDouble(parameters, self.MAX_DISTANCE, context)
        r_step = self.parameterAsDouble(parameters, self.STEP_DISTANCE, context)
        epsilon = self.parameterAsDouble(parameters, self.EPSILON, context)
        if method != "STARS":
            epsilon = 0.01
        monte_carlo = self.parameterAsBool(parameters, self.MONTE_CARLO, context)
        simulations = self.parameterAsInt(parameters, self.SIMULATIONS, context) if monte_carlo else 0
        output_csv = self.parameterAsOutputLayer(parameters, self.OUTPUT_CSV, context)

        valid, message = validate_point_layer(point_layer)
        if not valid:
            raise QgsProcessingException(message)
        valid, message = validate_line_layer(road_layer)
        if not valid:
            raise QgsProcessingException(message)
        valid, message = validate_distance_crs(road_layer)
        if not valid:
            raise QgsProcessingException(message)
        if r_max <= r_min:
            raise QgsProcessingException("Max distance must be greater than min distance.")

        feedback.pushInfo("Running algorithm: Fast Network K-Function")
        feedback.pushInfo("Converting QGIS layers to FastNSA inputs...")
        progress = ProcessingProgress(feedback)
        progress.stage("Input validation")

        try:
            bundle = qgs_layers_to_kfunction_inputs(
                point_layer,
                road_layer,
                stage_callback=progress.stage,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        for warning in bundle.warnings:
            feedback.pushInfo(f"Warning: {warning}")

        try:
            result = run_network_k_function(
                bundle,
                r_min=r_min,
                r_max=r_max,
                r_step=r_step,
                method=method,
                simulations=simulations,
                return_simulations=monte_carlo,
                epsilon=epsilon,
                progress_callback=progress.native,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        feedback.pushInfo(f"Converted network type: {type(bundle.network).__name__}")
        feedback.pushInfo(f"Converted point data type: {type(bundle.point_data).__name__}")
        feedback.pushInfo(f"Converted pointset type: {type(bundle.pointset).__name__}")
        feedback.pushInfo(
            f"K-function point source: {bundle.point_events_kwargs.get('mapping_method', 'unknown')}"
        )
        feedback.pushInfo(f"Converted road edges: {len(bundle.edge_records)}")
        feedback.pushInfo(f"Converted event points: {len(bundle.point_records)}")
        for line in format_timings_for_logs(bundle.timings, prefix="Adapter timing"):
            feedback.pushInfo(line)
        feedback.pushInfo(f"K-function distance thresholds: {len(result.r)}")

        progress.stage("Output writing")
        fields = QgsFields()
        for name in ("r", "k_obs", "k_theo", "k_lo", "k_hi"):
            fields.append(QgsField(name, QVariant.Double))
        sink, sink_id = self.parameterAsSink(
            parameters,
            self.OUTPUT_TABLE,
            context,
            fields,
            QgsWkbTypes.NoGeometry,
            QgsCoordinateReferenceSystem(),
        )
        if sink is None:
            raise QgsProcessingException("Could not create the K-function result table.")

        for index, distance in enumerate(result.r):
            feature = QgsFeature(fields)
            feature.setAttributes(
                [
                    float(distance),
                    float(result.k_obs[index]),
                    float(result.k_theo[index]) if result.k_theo is not None else None,
                    float(result.k_lo[index]) if result.k_lo is not None else None,
                    float(result.k_hi[index]) if result.k_hi is not None else None,
                ]
            )
            sink.addFeature(feature)

        results = {self.OUTPUT_TABLE: sink_id}
        if output_csv:
            try:
                kfunction_result_to_table_or_csv(result, output_csv)
                results[self.OUTPUT_CSV] = output_csv
                feedback.pushInfo(f"Wrote K-function CSV: {output_csv}")
                if self.parameterAsBool(parameters, self.LOAD_CSV, context):
                    register_csv_for_loading(output_csv, self.OUTPUT_CSV, context, feedback)
            except Exception as exc:
                raise QgsProcessingException(str(exc)) from exc

        results[self.MESSAGE] = "FastNSA K-function completed."
        return results

    def createInstance(self):
        return type(self)()

    def name(self):
        return "fast_network_k_function"

    def displayName(self):
        return "Fast Network K-Function"

    def group(self):
        return "FastNSA"

    def groupId(self):
        return "fastnsa"

    def shortHelpString(self):
        return (
            "<p>Compute a normalized network K-function using NS (exact) or STARS "
            "(approximate). At least two events and a projected road network are required. "
            "Distance thresholds use road CRS map units.</p>"
            "<p><b>Preprocessing:</b> Raw events are matched automatically. Compatible "
            "Matched points reuse edge_id/offset on the same unchanged network; preserve "
            "network_sig.</p>"
            "<p><b>STARS epsilon:</b> Controls source-event sampling per occupied edge, "
            "not an error percentage. Smaller values use more source events. Disabled "
            "and ignored for NS.</p>"
            "<p><b>Monte Carlo:</b> Random events are drawn uniformly by network length. "
            "Their mean estimates k_theo; quantiles provide a nominal 95% pointwise "
            "envelope, not a global significance envelope. Without simulations, k_theo, "
            "k_lo and k_hi are empty. The default 5 simulations is for quick testing.</p>"
            "<p><b>Outputs:</b> A temporary or saved no-geometry table with r, k_obs, "
            "k_theo, k_lo and k_hi, plus an independent optional CSV. Load exported CSV "
            "table adds it to QGIS, not an external application. Run the analysis in "
            "the FastNSA main dialog for interactive charts.</p>"
        )
