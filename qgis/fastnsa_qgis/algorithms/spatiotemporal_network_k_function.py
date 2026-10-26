"""Spatiotemporal network K-function algorithm backed by the FastNSA adapter layer."""

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
    QgsProcessingParameterField,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant

from ..adapters.fastnsa_to_qgs import spatiotemporal_kfunction_result_to_table_or_csv
from ..adapters.qgs_to_fastnsa import (
    format_timings_for_logs,
    qgs_layers_to_kfunction_inputs,
    run_spatiotemporal_network_k_function,
)
from ..utils.validation import validate_distance_crs, validate_line_layer, validate_point_layer
from ..utils.progress import ProcessingProgress
from ..utils.processing_outputs import register_csv_for_loading
from ..utils.analysis_options import DEFAULT_K_MAX_DISTANCE
from ..utils.processing_help import MAPPING_REUSE_HELP, MONTE_CARLO_HELP, set_parameter_help


class FastSpatiotemporalNetworkKFunctionAlgorithm(QgsProcessingAlgorithm):
    """Processing entry point for the FastNSA spatiotemporal K-function workflow."""

    POINT_LAYER = "POINT_LAYER"
    ROAD_LAYER = "ROAD_LAYER"
    TIME_FIELD = "TIME_FIELD"
    TIME_MODE = "TIME_MODE"
    TIME_UNIT = "TIME_UNIT"
    METHOD = "METHOD"
    S_MIN_DISTANCE = "S_MIN_DISTANCE"
    S_MAX_DISTANCE = "S_MAX_DISTANCE"
    S_STEP_DISTANCE = "S_STEP_DISTANCE"
    T_MIN_DISTANCE = "T_MIN_DISTANCE"
    T_MAX_DISTANCE = "T_MAX_DISTANCE"
    T_STEP_DISTANCE = "T_STEP_DISTANCE"
    MONTE_CARLO = "MONTE_CARLO"
    SIMULATIONS = "SIMULATIONS"
    OUTPUT_TABLE = "OUTPUT_TABLE"
    OUTPUT_CSV = "OUTPUT_CSV"
    LOAD_CSV = "LOAD_CSV"
    MESSAGE = "MESSAGE"

    METHOD_OPTIONS = ["EARTH", "MTS", "EAR", "SPS", "RQS"]
    TIME_MODE_OPTIONS = [
        "Auto detect",
        "Date / datetime",
        "Numeric values",
        "Unix timestamp (seconds)",
        "Unix timestamp (milliseconds)",
    ]
    TIME_MODE_VALUES = [
        "auto",
        "datetime",
        "numeric",
        "unix_seconds",
        "unix_milliseconds",
    ]
    TIME_UNIT_OPTIONS = [
        "Auto (days for date/time)",
        "Seconds",
        "Minutes",
        "Hours",
        "Days",
    ]
    TIME_UNIT_VALUES = ["auto", "seconds", "minutes", "hours", "days"]

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
            QgsProcessingParameterField(
                self.TIME_FIELD,
                "Time field",
                parentLayerParameterName=self.POINT_LAYER,
                type=QgsProcessingParameterField.Any,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.TIME_MODE,
                "Time value interpretation",
                self.TIME_MODE_OPTIONS,
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.TIME_UNIT,
                "Temporal analysis unit",
                self.TIME_UNIT_OPTIONS,
                defaultValue=0,
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
                self.S_MIN_DISTANCE,
                "Spatial min distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.S_MAX_DISTANCE,
                "Spatial max distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=DEFAULT_K_MAX_DISTANCE,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.S_STEP_DISTANCE,
                "Spatial step distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=100.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.T_MIN_DISTANCE,
                "Temporal min distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.T_MAX_DISTANCE,
                "Temporal max distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=30.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.T_STEP_DISTANCE,
                "Temporal step distance",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
                minValue=0.0001,
            )
        )
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
                "Spatiotemporal K-function result table",
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
            self.POINT_LAYER: MAPPING_REUSE_HELP + " At least two events with distinct times are required.",
            self.TIME_FIELD: "Non-null date/datetime or finite numeric event times; the observed time span must be positive.",
            self.TIME_MODE: (
                "Auto distinguishes date/time from ordinary numeric values. It does "
                "not infer Unix timestamps from their magnitude; select Unix seconds "
                "or Unix milliseconds explicitly for epoch values."
            ),
            self.TIME_UNIT: (
                "Date/time and explicit Unix timestamps are converted to elapsed "
                "values (Auto uses days). Ordinary numeric values are assumed already "
                "in the selected unit and are not rescaled; Auto retains native units. "
                "The earliest event is the time origin."
            ),
            self.METHOD: "EARTH (default), MTS, EAR, SPS and RQS implement the same ST K estimator using different strategies.",
            self.MONTE_CARLO: MONTE_CARLO_HELP + " Events are drawn uniformly by network length and over the observed time range.",
            self.S_MIN_DISTANCE: "Minimum spatial threshold in road CRS map units.",
            self.S_MAX_DISTANCE: "Maximum spatial threshold in road CRS map units; must exceed the minimum.",
            self.S_STEP_DISTANCE: "Spatial threshold spacing. Smaller steps increase the number of result cells.",
            self.T_MIN_DISTANCE: "Minimum temporal lag in the effective temporal analysis unit.",
            self.T_MAX_DISTANCE: "Maximum temporal lag in the effective temporal analysis unit; must exceed the minimum.",
            self.T_STEP_DISTANCE: "Temporal threshold spacing, in the same unit as the normalized event times.",
        })

    def processAlgorithm(self, parameters, context, feedback):
        point_layer = self.parameterAsVectorLayer(parameters, self.POINT_LAYER, context)
        road_layer = self.parameterAsVectorLayer(parameters, self.ROAD_LAYER, context)
        time_field = self.parameterAsString(parameters, self.TIME_FIELD, context)
        time_mode = self.TIME_MODE_VALUES[
            self.parameterAsEnum(parameters, self.TIME_MODE, context)
        ]
        time_unit = self.TIME_UNIT_VALUES[
            self.parameterAsEnum(parameters, self.TIME_UNIT, context)
        ]
        method_label = self.METHOD_OPTIONS[self.parameterAsEnum(parameters, self.METHOD, context)]
        s_min = self.parameterAsDouble(parameters, self.S_MIN_DISTANCE, context)
        s_max = self.parameterAsDouble(parameters, self.S_MAX_DISTANCE, context)
        s_step = self.parameterAsDouble(parameters, self.S_STEP_DISTANCE, context)
        t_min = self.parameterAsDouble(parameters, self.T_MIN_DISTANCE, context)
        t_max = self.parameterAsDouble(parameters, self.T_MAX_DISTANCE, context)
        t_step = self.parameterAsDouble(parameters, self.T_STEP_DISTANCE, context)
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
        if not time_field:
            raise QgsProcessingException("A time field is required for spatiotemporal network K-function.")
        if s_max <= s_min:
            raise QgsProcessingException("Spatial max distance must exceed the minimum.")
        if t_max <= t_min:
            raise QgsProcessingException("Temporal max distance must exceed the minimum.")

        feedback.pushInfo("Running algorithm: Fast Spatiotemporal Network K-Function")
        feedback.pushInfo("Converting QGIS layers to FastNSA inputs...")
        progress = ProcessingProgress(feedback)
        progress.stage("Input validation")

        try:
            bundle = qgs_layers_to_kfunction_inputs(
                point_layer,
                road_layer,
                time_col=time_field,
                time_mode=time_mode,
                time_unit=time_unit,
                stage_callback=progress.stage,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        for warning in bundle.warnings:
            feedback.pushInfo(f"Warning: {warning}")

        try:
            result = run_spatiotemporal_network_k_function(
                bundle,
                s_min=s_min,
                s_max=s_max,
                s_step=s_step,
                t_min=t_min,
                t_max=t_max,
                t_step=t_step,
                method=method_label,
                simulations=simulations,
                return_simulations=monte_carlo,
                progress_callback=progress.native,
            )
        except Exception as exc:
            raise QgsProcessingException(str(exc)) from exc

        feedback.pushInfo(f"Converted network type: {type(bundle.network).__name__}")
        feedback.pushInfo(f"Converted point data type: {type(bundle.point_data).__name__}")
        feedback.pushInfo(f"Converted pointset type: {type(bundle.pointset).__name__}")
        feedback.pushInfo(
            f"Spatiotemporal K-function point source: {bundle.point_events_kwargs.get('mapping_method', 'unknown')}"
        )
        feedback.pushInfo(f"Converted road edges: {len(bundle.edge_records)}")
        feedback.pushInfo(f"Converted event points: {len(bundle.point_records)}")
        for line in format_timings_for_logs(bundle.timings, prefix="Adapter timing"):
            feedback.pushInfo(line)
        feedback.pushInfo(f"Spatiotemporal K-function shape: {len(result.s)} x {len(result.t)}")
        feedback.pushInfo(
            f"Temporal axis: {result.time_unit or 'unknown'}; "
            f"mode={result.time_mode or 'unknown'}; origin={result.time_origin or 'unknown'}"
        )

        progress.stage("Output writing")
        fields = QgsFields()
        for name in ("s", "t", "k_obs", "k_lo", "k_hi"):
            fields.append(QgsField(name, QVariant.Double))
        fields.append(QgsField("status", QVariant.String))
        fields.append(QgsField("time_unit", QVariant.String))
        fields.append(QgsField("time_origin", QVariant.String))
        fields.append(QgsField("time_mode", QVariant.String))
        sink, sink_id = self.parameterAsSink(
            parameters,
            self.OUTPUT_TABLE,
            context,
            fields,
            QgsWkbTypes.NoGeometry,
            QgsCoordinateReferenceSystem(),
        )
        if sink is None:
            raise QgsProcessingException(
                "Could not create the spatiotemporal K-function result table."
            )

        for s_index, s_value in enumerate(result.s):
            for t_index, t_value in enumerate(result.t):
                observed = float(result.k_obs[s_index][t_index])
                lower = (
                    float(result.k_lo[s_index][t_index])
                    if result.k_lo is not None
                    else None
                )
                upper = (
                    float(result.k_hi[s_index][t_index])
                    if result.k_hi is not None
                    else None
                )
                status = "unbounded"
                if upper is not None and observed > upper:
                    status = "above envelope"
                elif lower is not None and observed < lower:
                    status = "below envelope"
                elif lower is not None and upper is not None:
                    status = "within envelope"

                feature = QgsFeature(fields)
                feature.setAttributes(
                    [
                        float(s_value),
                        float(t_value),
                        observed,
                        lower,
                        upper,
                        status,
                        result.time_unit or "unknown",
                        result.time_origin or "unknown",
                        result.time_mode or "unknown",
                    ]
                )
                sink.addFeature(feature)

        results = {self.OUTPUT_TABLE: sink_id}
        if output_csv:
            try:
                spatiotemporal_kfunction_result_to_table_or_csv(result, output_csv)
                results[self.OUTPUT_CSV] = output_csv
                feedback.pushInfo(f"Wrote spatiotemporal K-function CSV: {output_csv}")
                if self.parameterAsBool(parameters, self.LOAD_CSV, context):
                    register_csv_for_loading(output_csv, self.OUTPUT_CSV, context, feedback)
            except Exception as exc:
                raise QgsProcessingException(str(exc)) from exc

        results[self.MESSAGE] = "FastNSA spatiotemporal network K-function completed."
        return results

    def createInstance(self):
        return type(self)()

    def name(self):
        return "fast_spatiotemporal_network_k_function"

    def displayName(self):
        return "Fast Spatiotemporal Network K-Function"

    def group(self):
        return "FastNSA"

    def groupId(self):
        return "fastnsa"

    def shortHelpString(self):
        return (
            "<p>Compute normalized spatiotemporal network K(s, t) using EARTH (default), "
            "MTS, EAR, SPS or RQS. These are alternative strategies for the same estimator.</p>"
            "<p><b>Inputs:</b> A projected road network and at least two point events with "
            "a non-null time field and positive time span. Raw events are matched "
            "automatically; compatible Matched points reuse their mapping on the same "
            "unchanged network.</p>"
            "<p><b>Units:</b> Spatial thresholds use road CRS map units. Date/time and "
            "explicit Unix timestamps are converted to elapsed analysis units (days in "
            "Auto). Select Unix seconds/milliseconds explicitly. Ordinary numeric values "
            "are not rescaled: they must already use the selected unit; Auto retains "
            "their native unit. Temporal thresholds must use that same unit.</p>"
            "<p><b>Monte Carlo:</b> Simulate events uniformly by network length and over "
            "the observed time range to obtain nominal 95% pointwise quantile bounds. "
            "Five simulations is a quick-test default, not a reliable inference setting.</p>"
            "<p><b>Outputs:</b> A temporary or saved no-geometry table and optional CSV "
            "with s, t, k_obs, k_lo, k_hi, status, time_unit, time_origin and time_mode. "
            "Without simulations, bounds are empty and status is unbounded. Run the "
            "analysis in the FastNSA main dialog for heatmaps and optional Matplotlib 3D.</p>"
        )
