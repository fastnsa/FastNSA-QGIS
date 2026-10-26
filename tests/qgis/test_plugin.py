"""QGIS adapter, Processing, and GUI integration tests."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


try:
    from qgis.PyQt.QtCore import QDateTime, Qt
    from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsVectorLayer

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False


@unittest.skipUnless(QGIS_AVAILABLE, "QGIS Python bindings are unavailable")
class QgisAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.qgis import qgis_test_application

        cls.app = qgis_test_application()

        from fastnsa_qgis.adapters.fastnsa_to_qgs import (
            build_nearest_edge_result_from_pointset,
            nearest_edge_result_to_qgs_layers,
        )
        from fastnsa_qgis.adapters.qgs_to_fastnsa import (
            clear_network_cache,
            normalize_temporal_values,
            qgs_layers_to_kfunction_inputs,
            qgs_layers_to_nearest_edge_inputs,
        )
        from fastnsa_qgis.utils.validation import validate_distance_crs

        cls.build_nearest_result = staticmethod(build_nearest_edge_result_from_pointset)
        cls.nearest_to_layers = staticmethod(nearest_edge_result_to_qgs_layers)
        cls.normalize_times = staticmethod(normalize_temporal_values)
        cls.kfunction_inputs = staticmethod(qgs_layers_to_kfunction_inputs)
        cls.nearest_inputs = staticmethod(qgs_layers_to_nearest_edge_inputs)
        cls.validate_distance_crs = staticmethod(validate_distance_crs)
        cls.clear_network_cache = staticmethod(clear_network_cache)

    @staticmethod
    def _roads(wkt="LINESTRING (0 0, 100 0)"):
        layer = QgsVectorLayer("LineString?crs=EPSG:3857", "roads", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        layer.dataProvider().addFeature(feature)
        layer.updateExtents()
        return layer

    def test_processing_progress_polls_do_not_regress_and_still_cancel(self):
        from fastnsa_qgis.utils.progress import ProcessingProgress

        feedback = MagicMock()
        feedback.isCanceled.return_value = False
        progress = ProcessingProgress(feedback)
        progress.stage("Road network conversion")
        progress.native("backend compute", 3, 4)
        progress.native("backend compute", 0, 1)
        progress.native("backend compute", 4, 4)
        progress.stage("Output writing")
        progress.native("backend compute", 0, 1)
        values = [call.args[0] for call in feedback.setProgress.call_args_list]
        self.assertEqual(values, sorted(values))
        self.assertEqual(values[-1], 94.0)
        feedback.isCanceled.return_value = True
        self.assertTrue(progress.native("backend compute", 0, 1))
        with self.assertRaisesRegex(RuntimeError, "canceled"):
            progress.stage("Output writing")

    @staticmethod
    def _events():
        dates = [
            QDateTime.fromString("2026-01-01T00:00:00Z", Qt.ISODate),
            QDateTime.fromString("2026-01-02T00:00:00Z", Qt.ISODate),
            QDateTime.fromString("2026-01-04T00:00:00Z", Qt.ISODate),
        ]
        layer = QgsVectorLayer(
            "Point?crs=EPSG:3857&field=event_time:datetime",
            "events",
            "memory",
        )
        features = []
        for (x, y), event_time in zip(((10, 1), (40, -1), (80, 2)), dates):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(f"POINT ({x} {y})"))
            feature.setAttributes([event_time])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        return layer, dates

    def test_temporal_modes_and_units(self):
        _, dates = self._events()
        values, metadata, _ = self.normalize_times(dates)
        self.assertEqual(values.tolist(), [0.0, 1.0, 3.0])
        self.assertEqual(metadata.effective_mode, "datetime")
        self.assertEqual(metadata.effective_unit, "days")

        milliseconds = [dates[0].toMSecsSinceEpoch(), dates[1].toMSecsSinceEpoch()]
        values, metadata, _ = self.normalize_times(
            milliseconds,
            mode="unix_milliseconds",
            unit="days",
        )
        self.assertEqual(values.tolist(), [0.0, 1.0])

        values, metadata, _ = self.normalize_times([100.0, 102.5])
        self.assertEqual(values.tolist(), [0.0, 2.5])
        self.assertEqual(metadata.effective_unit, "native")

    def test_datetime_normalization_preserves_milliseconds(self):
        dates = [QDateTime.fromMSecsSinceEpoch(value, Qt.UTC)
                 for value in (1767225600125, 1767225600375)]
        for mode, source in (
            ("datetime", dates),
            ("unix_milliseconds", [value.toMSecsSinceEpoch() for value in dates]),
            ("datetime", [value.toPyDateTime() for value in dates]),
        ):
            with self.subTest(mode=mode, source=type(source[0]).__name__):
                values, metadata, _ = self.normalize_times(
                    source, mode=mode, unit="seconds"
                )
                self.assertEqual(values.tolist(), [0.0, 0.25])
                self.assertEqual(metadata.span, 0.25)

    def test_bootstrap_rejects_python_below_release_baseline(self):
        from fastnsa_qgis.utils import bootstrap

        with patch.object(bootstrap.sys, "version_info", (3, 10, 0)), \
                patch.object(bootstrap, "ensure_fastnsa_import_path") as find_runtime:
            status = bootstrap.check_runtime_dependencies()

        self.assertFalse(status.available)
        self.assertIn("Python 3.11 or newer", status.message)
        self.assertIn("Python 3.10", status.message)
        find_runtime.assert_not_called()

    def test_result_views_are_nonmodal_and_reuse_the_current_result(self):
        from qgis.PyQt.QtWidgets import QDialog, QApplication
        from fastnsa_qgis.gui import main_dialog

        class FakeChart(QDialog):
            def __init__(self, result, parent):
                super().__init__(parent)
                self.result = result

        parent = QDialog()
        parent.last_kfunction_result = object()
        parent.last_spatiotemporal_kfunction_result = object()
        parent._kfunction_chart_dialog = None
        parent._st_kfunction_chart_dialog = None
        parent.show()
        with patch.object(main_dialog, 'KFunctionChartDialog', FakeChart), \
             patch.object(main_dialog, 'SpatiotemporalKFunctionDialog', FakeChart):
            main_dialog.FastNSAMainDialog._show_kfunction_chart(parent)
            view = parent._kfunction_chart_dialog
            self.assertTrue(view.isVisible())
            self.assertIsNone(view.parent())
            self.assertEqual(view.windowModality(), Qt.NonModal)
            self.assertIsNone(QApplication.activeModalWidget())
            main_dialog.FastNSAMainDialog._show_kfunction_chart(parent)
            self.assertIs(parent._kfunction_chart_dialog, view)
            parent.last_kfunction_result = object()
            main_dialog.FastNSAMainDialog._show_kfunction_chart(parent)
            self.assertIsNot(parent._kfunction_chart_dialog, view)
            self.assertFalse(view.isVisible())
            main_dialog.FastNSAMainDialog._show_st_kfunction_chart(parent)
            self.assertIsNone(parent._st_kfunction_chart_dialog.parent())
            self.assertEqual(parent._st_kfunction_chart_dialog.windowModality(), Qt.NonModal)
            self.assertIsNone(QApplication.activeModalWidget())
            main_dialog.FastNSAMainDialog._close_result_viewers(parent)
            self.assertIsNone(parent._kfunction_chart_dialog)
            self.assertIsNone(parent._st_kfunction_chart_dialog)
        parent.close()

    def test_result_viewers_label_threshold_counts_not_samples(self):
        import numpy as np
        from qgis.PyQt.QtWidgets import QLabel, QTextEdit, QWidget
        from fastnsa.core.types import KFunctionResult, SpatiotemporalKFunctionResult
        from fastnsa_qgis.gui.kfunction_chart_dialog import KFunctionChartDialog
        from fastnsa_qgis.gui.st_kfunction_dialog import SpatiotemporalKFunctionDialog

        k_result = KFunctionResult(
            r=np.array([0.0, 100.0, 200.0]),
            k_obs=np.array([0.0, 2.0, 5.0]), n_points=7,
        )
        st_result = SpatiotemporalKFunctionResult(
            s=np.array([0.0, 100.0, 200.0]), t=np.array([0.0, 1.0]),
            k_obs=np.zeros((3, 2)), n_points=7,
        )
        # This is a label regression; avoid initializing an optional 3D backend.
        with patch.object(SpatiotemporalKFunctionDialog, "_build_matplotlib_surface_tab",
                          side_effect=QWidget):
            for viewer, result, header_parts, summary_parts in (
                (KFunctionChartDialog, k_result,
                 ["Distance thresholds: 3"], ["Number of distance thresholds: 3"]),
                (SpatiotemporalKFunctionDialog, st_result,
                 ["Spatial thresholds: 3", "Temporal thresholds: 2"],
                 ["Number of spatial thresholds: 3", "Number of temporal thresholds: 2"]),
            ):
                with self.subTest(viewer=viewer.__name__):
                    dialog = viewer(result)
                    try:
                        meta = next(label.text() for label in dialog.findChildren(QLabel)
                                    if label.text().startswith("Method:"))
                        summary = "\n".join(edit.toPlainText()
                                            for edit in dialog.findChildren(QTextEdit))
                        for text in header_parts:
                            self.assertIn(text, meta)
                        for text in summary_parts:
                            self.assertIn(text, summary)
                        self.assertIn("Points: 7", meta)
                        self.assertNotIn("samples:", meta.casefold())
                        self.assertNotIn("samples:", summary.casefold())
                        self.assertNotIn("sample count:", summary.casefold())
                    finally:
                        dialog.close()
                        dialog.deleteLater()

    def test_distance_analysis_requires_projected_road_crs(self):
        geographic_roads = QgsVectorLayer(
            "LineString?crs=EPSG:4326",
            "geographic_roads",
            "memory",
        )
        feature = QgsFeature(geographic_roads.fields())
        feature.setGeometry(QgsGeometry.fromWkt("LINESTRING (-74 40, -73.99 40.01)"))
        geographic_roads.dataProvider().addFeature(feature)

        valid, message = self.validate_distance_crs(geographic_roads)
        self.assertFalse(valid)
        self.assertIn("Reproject", message)

        events = QgsVectorLayer("Point?crs=EPSG:4326", "events", "memory")
        event = QgsFeature(events.fields())
        event.setGeometry(QgsGeometry.fromWkt("POINT (-74 40)"))
        events.dataProvider().addFeature(event)
        with self.assertRaisesRegex(ValueError, "Reproject the road network"):
            self.nearest_inputs(events, geographic_roads)

    def test_nearest_output_preserves_time_and_validates_network(self):
        roads = self._roads()
        events, _ = self._events()
        bundle = self.nearest_inputs(events, roads)
        result = self.build_nearest_result(bundle, "R-tree")
        matched = self.nearest_to_layers(
            result,
            roads.crs(),
            include_projected_points=False,
            include_lines=False,
        )[0]

        field_names = [field.name() for field in matched.fields()]
        self.assertIn("event_time", field_names)
        self.assertIn("network_sig", field_names)
        self.kfunction_inputs(matched, roads, time_col="event_time")

        changed_roads = self._roads("LINESTRING (0 0, 120 0)")
        with self.assertRaisesRegex(ValueError, "different road network"):
            self.kfunction_inputs(matched, changed_roads)

    def test_chicago_endpoint_mapping_and_legacy_kde_reuse(self):
        import numpy as np
        from fastnsa.stats.network_kde import network_kde
        from fastnsa_qgis.adapters.qgs_to_fastnsa import qgs_layers_to_kde_inputs

        roads = QgsVectorLayer("LineString?crs=EPSG:32616", "Chicago endpoint", "memory")
        geometry = QgsGeometry()
        geometry.fromWkb(bytes.fromhex(
            "01020000000300000008cd5f3e0c711a416f4a78d5f6be51418b2f3ddc0e711a41"
            "246b457404bf514105965d7d11711a41008b042709bf5141"
        ))
        length = geometry.length()
        feature = QgsFeature(roads.fields())
        feature.setGeometry(geometry)
        roads.dataProvider().addFeature(feature)
        events = QgsVectorLayer("Point?crs=EPSG:32616", "events", "memory")
        event = QgsFeature(events.fields())
        event.setGeometry(QgsGeometry.fromWkt("POINT (433210.314706237 4652161.824312044)"))
        events.dataProvider().addFeature(event)

        raw = qgs_layers_to_kde_inputs(events, roads)
        self.addCleanup(raw.pointset.close)
        self.assertTrue(np.all(raw.pointset.offsets_array() <= length))
        result = self.build_nearest_result(raw, "R-tree")
        matched = self.nearest_to_layers(
            result, roads.crs(), include_projected_points=False, include_lines=False
        )[0]
        # Reproduce an endpoint written by a pre-fix matched-points export.
        offset_field = matched.fields().indexFromName("offset")
        self.assertTrue(matched.dataProvider().changeAttributeValues({
            next(matched.getFeatures()).id(): {
                offset_field: float(np.nextafter(length, np.inf))
            }
        }))
        reused = qgs_layers_to_kde_inputs(matched, roads)
        self.addCleanup(reused.pointset.close)
        np.testing.assert_array_equal(reused.pointset.offsets_array(), [length])
        for method in ("ADA", "LION"):
            with self.subTest(method=method):
                direct = network_kde(network=raw.network, points=raw.pointset,
                    bandwidth=30, lixel_length=25, method=method)
                restored = network_kde(network=reused.network, points=reused.pointset,
                    bandwidth=30, lixel_length=25, method=method)
                self.assertTrue(np.isfinite(direct.density).all())
                np.testing.assert_allclose(restored.density, direct.density, atol=1e-12)

    def test_time_controls_are_available_in_both_entry_points(self):
        from fastnsa_qgis.algorithms.spatiotemporal_network_k_function import (
            FastSpatiotemporalNetworkKFunctionAlgorithm,
        )
        from fastnsa_qgis.gui.parameter_panels import (
            NetworkKdePanel,
            SpatiotemporalNetworkKFunctionPanel,
        )

        panel = SpatiotemporalNetworkKFunctionPanel()
        self.assertEqual(panel.time_mode_combo.currentData(), "auto")
        self.assertEqual(panel.time_unit_combo.currentData(), "auto")

        algorithm = FastSpatiotemporalNetworkKFunctionAlgorithm()
        algorithm.initAlgorithm()
        parameter_names = {parameter.name() for parameter in algorithm.parameterDefinitions()}
        self.assertIn(algorithm.TIME_MODE, parameter_names)
        self.assertIn(algorithm.TIME_UNIT, parameter_names)

        kde_panel = NetworkKdePanel()
        self.assertEqual(kde_panel.kernel_combo.count(), 1)
        self.assertEqual(kde_panel.kernel_combo.currentText(), "Epanechnikov")
        self.assertFalse(kde_panel.kernel_combo.isEnabled())

        from fastnsa_qgis.algorithms.network_kde import FastNetworkKdeAlgorithm

        kde_algorithm = FastNetworkKdeAlgorithm()
        kde_algorithm.initAlgorithm()
        kernel_parameter = kde_algorithm.parameterDefinition(kde_algorithm.KERNEL)
        self.assertEqual(kernel_parameter.options(), ["Epanechnikov"])
        parameter_names = {parameter.name() for parameter in kde_algorithm.parameterDefinitions()}
        self.assertIn(kde_algorithm.STYLE_CLASSIFICATION, parameter_names)
        self.assertIn(kde_algorithm.STYLE_CLASSES, parameter_names)
        self.assertIn(kde_algorithm.STYLE_SEPARATE_ZERO, parameter_names)

    def test_method_controls_and_backend_identifiers(self):
        from fastnsa_qgis.gui.parameter_panels import FastNearestEdgePanel, NetworkKFunctionPanel

        panel = NetworkKFunctionPanel()
        self.assertEqual(panel.method_combo.currentData(), "NS")
        self.assertFalse(panel.epsilon_spin.isEnabled())
        self.assertIn("Not used", panel.config()["Epsilon"])
        panel.method_combo.setCurrentIndex(1)
        self.assertEqual(panel.method_combo.currentData(), "STARS")
        self.assertTrue(panel.epsilon_spin.isEnabled())
        self.assertGreater(panel.epsilon_spin.minimum(), 0)
        self.assertIn("STARS only", panel.epsilon_hint.text())
        self.assertLess(len(panel.epsilon_hint.text()), 90)
        panel.epsilon_spin.setValue(0.025)
        panel.method_combo.setCurrentIndex(0)
        panel.method_combo.setCurrentIndex(1)
        self.assertEqual(panel.epsilon_spin.value(), 0.025)

        panel = FastNearestEdgePanel()
        self.assertEqual(panel.method_combo.count(), 3)
        self.assertTrue(panel.grid_options_panel.isHidden())
        self.assertFalse(panel.grid_size_spin.isEnabled())
        self.assertFalse(hasattr(panel, "k_value_spin"))
        for index, method in ((1, "comp_a"), (2, "comp_e")):
            panel.method_combo.setCurrentIndex(index)
            self.assertEqual(panel.method_combo.currentData(), method)
            self.assertFalse(panel.grid_options_panel.isHidden())
            self.assertTrue(panel.grid_size_spin.isEnabled())
        self.assertTrue(panel.output_lines_checkbox.isEnabled())
        self.assertLess(len(panel.grid_hint.text()), 90)

    def test_default_k_distances_match_processing(self):
        from fastnsa_qgis.gui.parameter_panels import (
            NetworkKFunctionPanel, SpatiotemporalNetworkKFunctionPanel,
        )
        from fastnsa_qgis.algorithms.network_k_function import FastNetworkKFunctionAlgorithm
        from fastnsa_qgis.algorithms.spatiotemporal_network_k_function import (
            FastSpatiotemporalNetworkKFunctionAlgorithm,
        )

        for panel, field, algorithm, parameter in (
            (NetworkKFunctionPanel(), "max_distance_spin", FastNetworkKFunctionAlgorithm(), "MAX_DISTANCE"),
            (SpatiotemporalNetworkKFunctionPanel(), "s_max_distance_spin",
             FastSpatiotemporalNetworkKFunctionAlgorithm(), "S_MAX_DISTANCE"),
        ):
            algorithm.initAlgorithm()
            self.assertEqual(getattr(panel, field).value(), 2000)
            self.assertEqual(algorithm.parameterDefinition(parameter).defaultValue(), 2000)

    def test_output_controls_clear_stale_open_state_and_csv_path(self):
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog

        dialog = FastNSAMainDialog(MagicMock())
        try:
            for name in ("Network K-Function", "Spatiotemporal Network K-Function"):
                dialog._on_task_changed(dialog.workflow_tasks.index(name))
                self.assertFalse(dialog.open_output_checkbox.isChecked())
                dialog.save_runtime_report_checkbox.setChecked(True)
                self.assertTrue(dialog.open_output_checkbox.isEnabled())
                dialog.runtime_report_path_edit.setText("previous result.csv")
                dialog.open_output_checkbox.setChecked(True)
                dialog.save_runtime_report_checkbox.setChecked(False)
                self.assertEqual(dialog.runtime_report_path_edit.text(), "")
                self.assertFalse(dialog.open_output_checkbox.isChecked())
                self.assertFalse(dialog.open_output_checkbox.isEnabled())
                dialog.save_runtime_report_checkbox.setChecked(True)
                self.assertFalse(dialog.open_output_checkbox.isChecked())
                self.assertEqual(dialog.runtime_report_path_edit.text(), "")
                dialog.open_output_checkbox.setChecked(True)
                for spatial in ("Network KDE", "Fast Nearest Edge Matching"):
                    dialog._on_task_changed(dialog.workflow_tasks.index(spatial))
                    self.assertTrue(dialog.open_output_checkbox.isHidden())
                    self.assertFalse(dialog.open_output_checkbox.isChecked())
                    dialog.use_temporary_output_checkbox.setChecked(True)
                    self.assertFalse(dialog.open_output_checkbox.isChecked())
                    dialog.use_temporary_output_checkbox.setChecked(False)
                    self.assertFalse(dialog.open_output_checkbox.isEnabled())
                dialog.save_runtime_report_checkbox.setChecked(False)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_temporary_output_clears_paths_without_affecting_inputs_or_other_options(self):
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog

        dialog = FastNSAMainDialog(MagicMock())
        roads, events = self._roads(), self._events()[0]
        dialog.road_layer_combo.setAdditionalLayers([roads])
        dialog.event_layer_combo.setAdditionalLayers([events])
        dialog.road_layer_combo.setLayer(roads)
        dialog.event_layer_combo.setLayer(events)
        try:
            for name in ("Fast Nearest Edge Matching", "Network KDE"):
                dialog._on_task_changed(dialog.workflow_tasks.index(name))
                dialog.use_temporary_output_checkbox.setChecked(False)
                dialog.output_path_edit.setText("previous-spatial-output.gpkg")
                dialog.use_temporary_output_checkbox.setChecked(True)
                self.assertEqual(dialog.output_path_edit.text(), "")
                self.assertFalse(dialog.output_path_edit.isEnabled())
                self.assertFalse(dialog.browse_output_button.isEnabled())
                self.assertNotIn("previous-spatial-output", dialog.build_configuration_summary())
                self.assertFalse(dialog.open_output_checkbox.isChecked())
                dialog.use_temporary_output_checkbox.setChecked(False)
                self.assertEqual(dialog.output_path_edit.text(), "")
                self.assertTrue(dialog.output_path_edit.isEnabled())
                self.assertTrue(dialog.browse_output_button.isEnabled())

                dialog.output_path_edit.setText("active-output.gpkg")
                dialog.add_result_layer_checkbox.toggle()
                dialog.apply_default_style_checkbox.toggle()
                panel = dialog.parameter_panels[name]
                panel.method_combo.setCurrentIndex(1)
                if name == "Fast Nearest Edge Matching":
                    panel.output_projected_checkbox.toggle()
                    panel.output_lines_checkbox.toggle()
                self.assertEqual(dialog.output_path_edit.text(), "active-output.gpkg")
                dialog._on_task_changed(dialog.workflow_tasks.index(name))
                self.assertEqual(dialog.output_path_edit.text(), "active-output.gpkg")
                self.assertIs(dialog.road_layer_combo.currentLayer(), roads)
                self.assertIs(dialog.event_layer_combo.currentLayer(), events)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_output_paths_are_reset_when_task_or_project_changes(self):
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog

        dialog = FastNSAMainDialog(MagicMock())
        try:
            for name in dialog.workflow_tasks:
                dialog._on_task_changed(dialog.workflow_tasks.index(name))
                self.assertEqual(dialog.output_path_edit.text(), "")
                self.assertEqual(dialog.runtime_report_path_edit.text(), "")
                self.assertFalse(dialog.open_output_checkbox.isChecked())
                if dialog._task_output_capabilities()["spatial_output"]:
                    dialog.use_temporary_output_checkbox.setChecked(False)
                    dialog.output_path_edit.setText("previous-task.gpkg")
                else:
                    dialog.save_runtime_report_checkbox.setChecked(True)
                    dialog.runtime_report_path_edit.setText("previous-task.csv")
                    dialog.open_output_checkbox.setChecked(True)
                    dialog.add_result_layer_checkbox.toggle()
                    dialog.parameter_panels[name].envelope_checkbox.toggle()
                    self.assertEqual(dialog.runtime_report_path_edit.text(), "previous-task.csv")
                    dialog._on_task_changed(dialog.workflow_tasks.index(name))
                    self.assertEqual(dialog.runtime_report_path_edit.text(), "previous-task.csv")
                    self.assertTrue(dialog.open_output_checkbox.isChecked())
            dialog._clear_project_results()
            self.assertEqual(dialog.output_path_edit.text(), "")
            self.assertEqual(dialog.runtime_report_path_edit.text(), "")
            self.assertFalse(dialog.open_output_checkbox.isChecked())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_canceling_file_selection_keeps_the_active_output_path(self):
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog

        dialog = FastNSAMainDialog(MagicMock())
        try:
            dialog.use_temporary_output_checkbox.setChecked(False)
            dialog.output_path_edit.setText("active.gpkg")
            with patch("fastnsa_qgis.gui.main_dialog.QFileDialog.getSaveFileName", return_value=("", "")):
                dialog._browse_output_path()
            self.assertEqual(dialog.output_path_edit.text(), "active.gpkg")
            dialog._on_task_changed(dialog.workflow_tasks.index("Network K-Function"))
            dialog.save_runtime_report_checkbox.setChecked(True)
            dialog.runtime_report_path_edit.setText("active.csv")
            with patch("fastnsa_qgis.gui.main_dialog.QFileDialog.getSaveFileName", return_value=("", "")):
                dialog._browse_report_path()
            self.assertEqual(dialog.runtime_report_path_edit.text(), "active.csv")
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_processing_temporary_destinations_replace_previous_file_paths(self):
        from qgis.PyQt.QtWidgets import QLineEdit
        from qgis.core import QgsProcessing, QgsProcessingContext, QgsProcessingOutputLayerDefinition
        from qgis.gui import QgsGui, QgsProcessingGui
        from fastnsa_qgis.algorithms.nearest_edge import FastNearestEdgeMatchingAlgorithm
        from fastnsa_qgis.algorithms.network_kde import FastNetworkKdeAlgorithm
        from fastnsa_qgis.algorithms.network_k_function import FastNetworkKFunctionAlgorithm
        from fastnsa_qgis.algorithms.spatiotemporal_network_k_function import (
            FastSpatiotemporalNetworkKFunctionAlgorithm,
        )

        for cls in (FastNearestEdgeMatchingAlgorithm, FastNetworkKdeAlgorithm,
                    FastNetworkKFunctionAlgorithm, FastSpatiotemporalNetworkKFunctionAlgorithm):
            algorithm = cls()
            algorithm.initAlgorithm()
            context = QgsProcessingContext()
            for parameter in algorithm.destinationParameterDefinitions():
                with self.subTest(algorithm=algorithm.name(), output=parameter.name()):
                    wrapper = QgsGui.processingGuiRegistry().createParameterWidgetWrapper(
                        parameter, QgsProcessingGui.Standard
                    )
                    widget = wrapper.createWrappedWidget(context)
                    extension = "csv" if parameter.name() == "OUTPUT_CSV" else "gpkg"
                    path = str(Path(tempfile.gettempdir()) / f"previous-output.{extension}")
                    wrapper.setParameterValue(path, context)
                    wrapper.setParameterValue(QgsProcessing.TEMPORARY_OUTPUT, context)
                    value = wrapper.parameterValue()
                    if isinstance(value, QgsProcessingOutputLayerDefinition):
                        value = value.sink.staticValue()
                    self.assertEqual(value, QgsProcessing.TEMPORARY_OUTPUT)
                    for edit in widget.findChildren(QLineEdit):
                        self.assertNotIn("previous-output", edit.text())

    def test_saved_spatial_layers_use_output_filename_without_opening_gpkg(self):
        from qgis.core import QgsProject
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog
        from fastnsa_qgis.utils.layer_utils import snapshot_layer

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        dialog = FastNSAMainDialog(MagicMock())
        roads = self._roads()
        events, _ = self._events()
        snapshots = (snapshot_layer(events), snapshot_layer(roads), roads.crs(),
                     QgsProject.instance().transformContext())
        task = MagicMock()
        task.isCanceled.return_value = False
        task.progress.return_value = 0.0

        def run(_description, worker, finish):
            finish(worker(task))

        try:
            for name, runner, stem in (
                ("Fast Nearest Edge Matching", dialog._run_nearest_edge_workflow, "matched result"),
                ("Network KDE", dialog._run_kde_workflow, "density result"),
            ):
                dialog._on_task_changed(dialog.workflow_tasks.index(name))
                panel = dialog.parameter_panels[name]
                if name == "Fast Nearest Edge Matching":
                    panel.output_projected_checkbox.setChecked(True)
                    panel.output_lines_checkbox.setChecked(True)
                path = Path(directory.name) / f"{stem}.gpkg"
                dialog.output_path_edit.setText(str(path))
                dialog.use_temporary_output_checkbox.setChecked(False)
                # Even an injected stale checked state must not launch a GeoPackage.
                dialog.open_output_checkbox.setChecked(True)
                with patch.object(dialog, "_analysis_source_snapshots", return_value=snapshots), \
                        patch.object(dialog, "_start_background_task", side_effect=run), \
                        patch("fastnsa_qgis.gui.main_dialog.add_layers_to_project") as add, \
                        patch.object(dialog, "_open_exported_file") as open_file:
                    runner(panel)
                    layers = add.call_args.args[0]
                    self.assertTrue(path.is_file())
                    self.assertEqual(layers[0].name(), stem)
                    self.assertIn(stem.replace(" ", "_"), layers[0].source())
                    self.assertEqual(layers[0].providerType(), "ogr")
                    if name == "Fast Nearest Edge Matching":
                        self.assertEqual([layer.name() for layer in layers], [
                            stem, f"{stem}_projected_points", f"{stem}_point_to_edge_lines",
                        ])
                        self.assertIn("network_sig", layers[0].fields().names())
                    open_file.assert_not_called()
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_processing_method_dependent_widgets(self):
        from qgis.PyQt.QtWidgets import QDialog
        from qgis.core import QgsProcessingContext
        from fastnsa_qgis.algorithms.network_k_function import FastNetworkKFunctionAlgorithm
        from fastnsa_qgis.algorithms.nearest_edge import FastNearestEdgeMatchingAlgorithm

        plugin_path = str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins")
        with patch.object(sys, "path", sys.path + [plugin_path]):
            from processing.gui.wrappers import WidgetWrapperFactory

            for cls, dependency in (
                (FastNetworkKFunctionAlgorithm, "EPSILON"),
                (FastNearestEdgeMatchingAlgorithm, "GRID_SIZE"),
            ):
                algorithm = cls()
                algorithm.initAlgorithm()
                dialog = QDialog()
                method = WidgetWrapperFactory.create_wrapper(
                    algorithm.parameterDefinition("METHOD"), dialog
                )
                method_widget = method.createWrappedWidget(QgsProcessingContext())
                dependent = WidgetWrapperFactory.create_wrapper(
                    algorithm.parameterDefinition(dependency), dialog
                )
                dependent.postInitialize([method, dependent])
                method.setParameterValue(0, QgsProcessingContext())
                self.assertFalse(dependent.widget.isEnabled())
                method.setParameterValue(1, QgsProcessingContext())
                self.assertTrue(dependent.widget.isEnabled())
                method.setParameterValue(0, QgsProcessingContext())
                self.assertFalse(dependent.widget.isEnabled())
                self.assertIsNotNone(method_widget)

    def test_main_k_workflows_add_temporary_tables_without_csv(self):
        from qgis.core import QgsProject
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog
        from fastnsa_qgis.utils.layer_utils import snapshot_layer

        dialog = FastNSAMainDialog(MagicMock())
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        roads = self._roads()
        events, _ = self._events()
        snapshots = (snapshot_layer(events), snapshot_layer(roads), roads.crs(),
                     QgsProject.instance().transformContext())
        task = MagicMock()
        task.isCanceled.return_value = False
        task.progress.return_value = 0.0

        def run(_description, worker, finish):
            finish(worker(task))

        for name, runner in (
            ("Network K-Function", dialog._run_k_function_workflow),
            ("Spatiotemporal Network K-Function", dialog._run_spatiotemporal_k_function_workflow),
        ):
            dialog._on_task_changed(dialog.workflow_tasks.index(name))
            panel = dialog.parameter_panels[name]
            panel.envelope_checkbox.setChecked(False)
            if name.startswith("Spatiotemporal"):
                panel.time_field_combo.setLayer(events)
                panel.time_field_combo.setField("event_time")
            self.assertFalse(dialog.add_result_layer_checkbox.isHidden())
            self.assertIn("table", dialog.add_result_layer_checkbox.text())
            self.assertTrue(dialog.apply_default_style_checkbox.isHidden())
            self.assertFalse(dialog.open_output_checkbox.isEnabled())
            with patch.object(dialog, "_analysis_source_snapshots", return_value=snapshots), \
                    patch.object(dialog, "_start_background_task", side_effect=run), \
                    patch("fastnsa_qgis.gui.main_dialog.add_layers_to_project") as add:
                runner(panel)
                table = add.call_args.args[0][0]
                self.assertTrue(table.isValid())
                self.assertGreater(table.featureCount(), 0)
                self.assertIn("k_obs", table.fields().names())
                if name.startswith("Spatiotemporal"):
                    self.assertIn("time_unit", table.fields().names())
                    self.assertEqual(next(table.getFeatures())["time_unit"], "days")
            dialog.save_runtime_report_checkbox.setChecked(True)
            self.assertTrue(dialog.open_output_checkbox.isEnabled())
            self.assertFalse(dialog.open_output_checkbox.isChecked())
            path = Path(directory.name) / f"{name} result.csv"
            dialog.runtime_report_path_edit.setText(str(path))
            with patch.object(dialog, "_analysis_source_snapshots", return_value=snapshots), \
                    patch.object(dialog, "_start_background_task", side_effect=run), \
                    patch("fastnsa_qgis.gui.main_dialog.add_layers_to_project") as add:
                runner(panel)
                self.assertEqual(add.call_args.args[0][0].name(), path.stem)
                self.assertTrue(path.is_file())
            dialog.save_runtime_report_checkbox.setChecked(False)
            self.assertEqual(dialog.runtime_report_path_edit.text(), "")
        dialog.close()
        dialog.deleteLater()

    def test_open_export_uses_local_url_and_handles_missing_files(self):
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog

        dialog = FastNSAMainDialog(MagicMock())
        with tempfile.TemporaryDirectory() as directory, \
                patch("fastnsa_qgis.gui.main_dialog.QDesktopServices.openUrl", return_value=True) as open_url:
            path = Path(directory) / "result with spaces.csv"
            path.touch()
            dialog._open_exported_file(path)
            self.assertEqual(open_url.call_args.args[0].toLocalFile(), str(path))
            dialog._open_exported_file(Path(directory) / "missing.csv")
            self.assertEqual(open_url.call_count, 1)
        dialog.close()
        dialog.deleteLater()

    def test_density_style_quantiles_and_zero_class(self):
        from fastnsa_qgis.adapters.fastnsa_to_qgs import apply_density_style
        from fastnsa_qgis.utils.density_style import calculate_density_ranges

        ranges = calculate_density_ranges([0, 1, 2, 3, 100], "quantile", 3)
        self.assertEqual(len(ranges), 3)
        self.assertEqual(ranges[0][0], 1.0)
        self.assertEqual(ranges[-1][1], 100.0)

        layer = QgsVectorLayer(
            "LineString?crs=EPSG:3857&field=density:double",
            "density",
            "memory",
        )
        features = []
        for index, value in enumerate((-1e-12, 0.0, 1.0, 2.0, 3.0, 100.0)):
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromWkt(f"LINESTRING ({index} 0, {index + 1} 0)"))
            feature.setAttributes([value])
            features.append(feature)
        layer.dataProvider().addFeatures(features)
        self.assertTrue(apply_density_style(layer, classification="quantile", classes=3))
        self.assertEqual(len(layer.renderer().ranges()), 4)
        self.assertEqual(layer.renderer().ranges()[0].lowerValue(), -1e-12)
        self.assertIn("Non-positive", layer.renderer().ranges()[0].label())

        zero_layer = QgsVectorLayer(
            "LineString?crs=EPSG:3857&field=density:double",
            "zero-density",
            "memory",
        )
        zero_feature = QgsFeature(zero_layer.fields())
        zero_feature.setGeometry(QgsGeometry.fromWkt("LINESTRING (0 0, 1 0)"))
        zero_feature.setAttributes([0.0])
        zero_layer.dataProvider().addFeature(zero_feature)
        self.assertTrue(apply_density_style(zero_layer))
        self.assertEqual(zero_layer.renderer().symbol().color().name(), "#30123b")

    def test_main_window_and_progress_can_hide_and_restore(self):
        from fastnsa_qgis.gui.main_dialog import FastNSAMainDialog, _TaskProgressDialog

        class StatusBar:
            def __init__(self):
                self.widget = None

            def addPermanentWidget(self, widget):
                self.widget = widget

            def removeWidget(self, widget):
                if self.widget is widget:
                    self.widget = None

        class Iface:
            def __init__(self):
                self.status_bar = StatusBar()

            def statusBarIface(self):
                return self.status_bar

        iface = Iface()
        dialog = FastNSAMainDialog(iface)
        progress = _TaskProgressDialog()
        dialog._progress_dialog = progress
        dialog._install_task_status_widget("Test task")
        dialog.show()
        progress.show()
        self.app.processEvents()

        self.assertIsNone(dialog.parent())
        dialog._send_active_task_to_background()
        self.app.processEvents()
        self.assertFalse(dialog.isVisible())
        self.assertFalse(progress.isVisible())
        self.assertIsNotNone(iface.status_bar.widget)

        dialog._update_task_status_stage("backend compute")
        dialog._update_task_status_progress(42.0)
        self.assertEqual(dialog._task_status_label.text(), "FastNSA: backend compute")
        self.assertEqual(dialog._task_status_bar.value(), 42)

        dialog.show_active_task()
        self.app.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertTrue(progress.isVisible())

        dialog._progress_dialog = None
        progress.finish()
        dialog._remove_task_status_widget()
        self.assertIsNone(iface.status_bar.widget)
        dialog.close()
        dialog.deleteLater()

    def test_native_network_cache_hits_and_invalidates_after_edit(self):
        from fastnsa_qgis.utils.layer_utils import snapshot_layer

        self.clear_network_cache()
        roads = self._roads()
        events, _ = self._events()
        first = self.nearest_inputs(snapshot_layer(events), snapshot_layer(roads))
        second = self.nearest_inputs(snapshot_layer(events), snapshot_layer(roads))
        self.assertIs(first.network, second.network)
        self.assertEqual(second.timings["network.cache_hit"], 1.0)

        roads.startEditing()
        road_feature = next(roads.getFeatures())
        roads.changeGeometry(road_feature.id(), QgsGeometry.fromWkt("LINESTRING (0 0, 120 0)"))
        changed = self.nearest_inputs(snapshot_layer(events), snapshot_layer(roads))
        roads.rollBack()
        self.assertIsNot(first.network, changed.network)
        self.assertEqual(changed.timings["network.cache_hit"], 0.0)
        self.assertTrue(any("invalidated" in warning for warning in changed.warnings))

    def test_spatiotemporal_processing_entry_point(self):
        from qgis.core import (
            QgsProcessing, QgsProcessingContext, QgsProcessingFeedback,
            QgsProcessingOutputLayerDefinition, QgsProject,
        )

        from fastnsa_qgis.algorithms.spatiotemporal_network_k_function import (
            FastSpatiotemporalNetworkKFunctionAlgorithm,
        )

        roads = self._roads()
        events, _ = self._events()
        algorithm = FastSpatiotemporalNetworkKFunctionAlgorithm()
        algorithm.initAlgorithm()
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = QgsProcessingFeedback()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        csv_path = str(Path(directory.name) / "st result.csv")
        parameters = {
            algorithm.POINT_LAYER: events,
            algorithm.ROAD_LAYER: roads,
            algorithm.TIME_FIELD: "event_time",
            algorithm.TIME_MODE: 0,
            algorithm.TIME_UNIT: 0,
            algorithm.METHOD: 0,
            algorithm.S_MIN_DISTANCE: 0.0,
            algorithm.S_MAX_DISTANCE: 20.0,
            algorithm.S_STEP_DISTANCE: 10.0,
            algorithm.T_MIN_DISTANCE: 0.0,
            algorithm.T_MAX_DISTANCE: 3.0,
            algorithm.T_STEP_DISTANCE: 1.0,
            algorithm.MONTE_CARLO: True,
            algorithm.SIMULATIONS: 2,
            algorithm.OUTPUT_TABLE: QgsProcessingOutputLayerDefinition(
                QgsProcessing.TEMPORARY_OUTPUT, QgsProject.instance()
            ),
            algorithm.OUTPUT_CSV: csv_path,
            algorithm.LOAD_CSV: True,
        }
        result = algorithm.processAlgorithm(parameters, context, feedback)
        output_id = result[algorithm.OUTPUT_TABLE]
        output_layer = context.getMapLayer(output_id)
        self.assertIsNotNone(output_layer)
        self.assertEqual(output_layer.featureCount(), 12)
        self.assertTrue(context.willLoadLayerOnCompletion(output_id))
        self.assertTrue(context.willLoadLayerOnCompletion(csv_path))
        self.assertTrue(Path(csv_path).is_file())
        csv_layer = QgsVectorLayer(csv_path, "exported ST table", "ogr")
        self.assertTrue(csv_layer.isValid())
        self.assertEqual(csv_layer.featureCount(), 12)
        output_fields = [field.name() for field in output_layer.fields()]
        self.assertIn("time_unit", output_fields)
        self.assertIn("time_origin", output_fields)
        self.assertIn("time_mode", output_fields)
        first_feature = next(output_layer.getFeatures())
        self.assertIsNotNone(first_feature["k_lo"])
        self.assertIsNotNone(first_feature["k_hi"])

    def test_processing_help_matches_release_contract(self):
        from qgis.PyQt.QtGui import QTextDocument
        from fastnsa_qgis.algorithms.nearest_edge import FastNearestEdgeMatchingAlgorithm
        from fastnsa_qgis.algorithms.network_kde import FastNetworkKdeAlgorithm
        from fastnsa_qgis.algorithms.network_k_function import FastNetworkKFunctionAlgorithm
        from fastnsa_qgis.algorithms.spatiotemporal_network_k_function import (
            FastSpatiotemporalNetworkKFunctionAlgorithm,
        )

        for algorithm_class, expected in (
            (FastNearestEdgeMatchingAlgorithm,
             ("source locations", "offset", "network_sig", "map units", "legacy alias")),
            (FastNetworkKdeAlgorithm,
             ("line segment", "lion", "ada", "epanechnikov", "not applied to an unloaded sink")),
            (FastNetworkKFunctionAlgorithm,
             ("ns (exact)", "stars", "95% pointwise", "without simulations", "k_theo")),
            (FastSpatiotemporalNetworkKFunctionAlgorithm,
             ("not rescaled", "unix seconds/milliseconds", "time_origin", "unbounded")),
        ):
            with self.subTest(algorithm=algorithm_class.__name__):
                algorithm = algorithm_class()
                algorithm.initAlgorithm()
                document = QTextDocument()
                document.setHtml(algorithm.shortHelpString())
                text = document.toPlainText().casefold()
                for phrase in expected:
                    self.assertIn(phrase, text)
                for stale in ("dummy", "placeholder", "framework is working", "pointevents"):
                    self.assertNotIn(stale, text)
                for parameter in algorithm.parameterDefinitions():
                    with self.subTest(parameter=parameter.name()):
                        self.assertTrue(parameter.help().strip())
                self.assertEqual(algorithm.outputDefinition("MESSAGE").description(), "Result message")
                if algorithm.parameterDefinition("SIMULATIONS") is not None:
                    help_text = algorithm.parameterDefinition("SIMULATIONS").help()
                    self.assertIn("only when Monte Carlo", help_text)
                    self.assertIn("default 5", help_text)
                if algorithm.parameterDefinition("LOAD_CSV") is not None:
                    self.assertIn("external application", algorithm.parameterDefinition("LOAD_CSV").help())

    def test_nearest_kde_and_k_processing_entry_points(self):
        from qgis.core import (
            QgsProcessing, QgsProcessingContext, QgsProcessingFeedback,
            QgsProcessingOutputLayerDefinition, QgsProject,
        )

        from fastnsa_qgis.algorithms.nearest_edge import (
            FastNearestEdgeMatchingAlgorithm,
        )
        from fastnsa_qgis.algorithms.network_k_function import (
            FastNetworkKFunctionAlgorithm,
        )
        from fastnsa_qgis.algorithms.network_kde import FastNetworkKdeAlgorithm

        roads = self._roads()
        events, _ = self._events()

        nearest = FastNearestEdgeMatchingAlgorithm()
        nearest.initAlgorithm()
        nearest_context = QgsProcessingContext()
        nearest_result = nearest.processAlgorithm(
            {
                nearest.POINT_LAYER: events,
                nearest.ROAD_LAYER: roads,
                nearest.METHOD: 0,
                nearest.GRID_SIZE: 25.0,
                nearest.THREADS: 1,
                nearest.INCLUDE_PROJECTED_POINTS: True,
                nearest.INCLUDE_LINES: True,
                nearest.MATCHED_POINTS: QgsProcessingOutputLayerDefinition(
                    QgsProcessing.TEMPORARY_OUTPUT, QgsProject.instance()
                ),
                nearest.PROJECTED_POINTS: QgsProcessing.TEMPORARY_OUTPUT,
                nearest.POINT_TO_EDGE_LINES: QgsProcessing.TEMPORARY_OUTPUT,
            },
            nearest_context,
            QgsProcessingFeedback(),
        )
        matched = nearest_context.getMapLayer(nearest_result[nearest.MATCHED_POINTS])
        self.assertEqual(nearest_result[nearest.MESSAGE], "FastNSA nearest-edge matching completed.")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.featureCount(), 3)
        self.assertTrue(nearest_context.willLoadLayerOnCompletion(matched.id()))
        self.assertIn("network_sig", [field.name() for field in matched.fields()])

        kde = FastNetworkKdeAlgorithm()
        kde.initAlgorithm()
        kde_context = QgsProcessingContext()
        kde_result = kde.processAlgorithm(
            {
                kde.POINT_LAYER: matched,
                kde.ROAD_LAYER: roads,
                kde.BANDWIDTH: 30.0,
                kde.METHOD: 1,
                kde.KERNEL: 0,
                kde.SEGMENT_RESOLUTION: 10.0,
                kde.NORMALIZE: True,
                kde.APPLY_STYLE: False,
                kde.DENSITY_POINTS: QgsProcessingOutputLayerDefinition(
                    QgsProcessing.TEMPORARY_OUTPUT, QgsProject.instance()
                ),
            },
            kde_context,
            QgsProcessingFeedback(),
        )
        density = kde_context.getMapLayer(kde_result[kde.DENSITY_POINTS])
        self.assertIsNotNone(density)
        self.assertEqual(density.featureCount(), 10)
        self.assertTrue(kde_context.willLoadLayerOnCompletion(density.id()))
        density_integral = sum(
            float(feature["density"]) * float(feature["lixel_len"])
            for feature in density.getFeatures()
        )
        self.assertAlmostEqual(density_integral, 1.0)

        k_function = FastNetworkKFunctionAlgorithm()
        k_function.initAlgorithm()
        k_context = QgsProcessingContext()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        csv_path = str(Path(directory.name) / "k result.csv")
        k_result = k_function.processAlgorithm(
            {
                k_function.POINT_LAYER: matched,
                k_function.ROAD_LAYER: roads,
                k_function.METHOD: 0,
                k_function.MIN_DISTANCE: 0.0,
                k_function.MAX_DISTANCE: 20.0,
                k_function.STEP_DISTANCE: 10.0,
                k_function.EPSILON: 0.1,
                k_function.MONTE_CARLO: True,
                k_function.SIMULATIONS: 2,
                k_function.OUTPUT_TABLE: QgsProcessingOutputLayerDefinition(
                    QgsProcessing.TEMPORARY_OUTPUT, QgsProject.instance()
                ),
                k_function.OUTPUT_CSV: QgsProcessingOutputLayerDefinition(csv_path, QgsProject.instance()),
            },
            k_context,
            QgsProcessingFeedback(),
        )
        table = k_context.getMapLayer(k_result[k_function.OUTPUT_TABLE])
        self.assertIsNotNone(table)
        self.assertEqual(table.featureCount(), 3)
        self.assertTrue(k_context.willLoadLayerOnCompletion(table.id()))
        self.assertTrue(k_context.willLoadLayerOnCompletion(csv_path))
        self.assertTrue(Path(csv_path).is_file())
        self.assertIn("k_lo", [field.name() for field in table.fields()])


if __name__ == "__main__":
    unittest.main()
