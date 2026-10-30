"""Task-specific parameter panels for the FastNSA dialog."""

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QToolButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsFieldComboBox
from ..utils.analysis_options import (
    DEFAULT_K_MAX_DISTANCE, EPSILON_HELP, GRID_HELP, K_METHOD_OPTIONS, NEAREST_METHOD_OPTIONS,
)

from ..utils.density_style import (
    DEFAULT_DENSITY_CLASSES,
    DEFAULT_DENSITY_CLASSIFICATION,
    DEFAULT_SEPARATE_ZERO,
    DENSITY_CLASSIFICATION_OPTIONS,
)


class _BaseParameterPanel(QWidget):
    """Shared helpers for task-specific parameter widgets."""

    task_name = ""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(12)
        self.root_layout.setAlignment(Qt.AlignTop)

    def config(self):
        raise NotImplementedError

    def _add_section(self, title: str, *, collapsible: bool = False, expanded: bool = True) -> QFormLayout:
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(6)
        container_layout.setAlignment(Qt.AlignTop)

        if collapsible:
            toggle = QToolButton()
            toggle.setText(title)
            toggle.setCheckable(True)
            toggle.setChecked(expanded)
            toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            toggle.setStyleSheet(
                "QToolButton { font-weight: 700; color: #17384d; background: #edf5f8; "
                "border: 1px solid #d5e1e8; border-radius: 10px; padding: 9px 12px; text-align: left; }"
                "QToolButton:hover { background: #e5f0f5; border-color: #bfd0da; }"
                "QToolButton:checked { background: #e8f2f7; border-color: #b7cad6; }"
            )
            container_layout.addWidget(toggle)
        else:
            toggle = None

        group = QGroupBox("" if collapsible else title)
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        group.setStyleSheet(
            "QGroupBox { font-weight: 600; color: #17384d; border: 1px solid #d7e2e9; "
            "border-radius: 12px; margin-top: 10px; padding-top: 12px; background: #ffffff; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }"
        )
        group.setVisible(expanded)
        layout = QFormLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(11)
        container_layout.addWidget(group)

        if toggle is not None:
            def _sync(checked: bool):
                group.setVisible(checked)
                toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

            toggle.toggled.connect(_sync)

        self.root_layout.addWidget(container)
        return layout


class FastNearestEdgePanel(_BaseParameterPanel):
    task_name = "Fast Nearest Edge Matching"

    def __init__(self, parent=None):
        super().__init__(parent)
        core_layout = self._add_section("Core Parameters")
        advanced_layout = self._add_section("Grid Options", collapsible=True, expanded=False)
        self.grid_options_panel = advanced_layout.parentWidget().parentWidget()
        output_layout = self._add_section("Output Geometry", collapsible=True, expanded=False)

        self.method_combo = QComboBox()
        for label, key in NEAREST_METHOD_OPTIONS:
            self.method_combo.addItem(label, key)

        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(1, 100000)
        self.grid_size_spin.setValue(25)
        self.grid_size_spin.setSuffix(" m")
        self.grid_size_spin.setToolTip(GRID_HELP)
        self.grid_hint = QLabel(GRID_HELP)
        self.grid_hint.setWordWrap(True)

        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(0, 32)
        self.thread_spin.setValue(0)
        self.thread_spin.setSpecialValueText("0 (auto)")
        self.thread_spin.setToolTip(
            "Auto uses up to 8 workers. Explicit values are bounded by CPU "
            "availability and the amount of work."
        )

        self.output_projected_checkbox = QCheckBox("Output projected points")
        self.output_lines_checkbox = QCheckBox("Output point-to-edge lines")

        core_layout.addRow("Method", self.method_combo)
        core_layout.addRow("Number of threads", self.thread_spin)
        advanced_layout.addRow("Compression tolerance", self.grid_size_spin)
        advanced_layout.addRow(self.grid_hint)
        output_layout.addRow("", self.output_projected_checkbox)
        output_layout.addRow("", self.output_lines_checkbox)
        self.method_combo.currentIndexChanged.connect(self._sync_grid_options)
        self._sync_grid_options()

    def _sync_grid_options(self):
        uses_grid = self.method_combo.currentData() != "R-tree"
        self.grid_options_panel.setVisible(uses_grid)
        self.grid_size_spin.setEnabled(uses_grid)

    def config(self):
        return {
            "Method": self.method_combo.currentText(),
            "Compression tolerance": (
                f"{self.grid_size_spin.value()} m"
                if self.method_combo.currentData() != "R-tree" else "Not used"
            ),
            "Threads": self.thread_spin.value(),
            "Output projected points": self.output_projected_checkbox.isChecked(),
            "Output point-to-edge lines": self.output_lines_checkbox.isChecked(),
        }


class NetworkKdePanel(_BaseParameterPanel):
    task_name = "Network KDE"

    def __init__(self, parent=None):
        super().__init__(parent)
        core_layout = self._add_section("Core Parameters")
        advanced_layout = self._add_section("Advanced Options", collapsible=True, expanded=False)

        self.bandwidth_spin = QSpinBox()
        self.bandwidth_spin.setRange(1, 1000000)
        self.bandwidth_spin.setValue(500)
        self.bandwidth_spin.setSuffix(" m")

        self.method_combo = QComboBox()
        self.method_combo.addItems(["LION", "ADA"])

        self.kernel_combo = QComboBox()
        self.kernel_combo.addItem("Epanechnikov")
        self.kernel_combo.setEnabled(False)
        self.kernel_combo.setToolTip(
            "FastNSA 0.1 currently exposes only the validated Epanechnikov kernel."
        )

        self.segment_resolution_spin = QSpinBox()
        self.segment_resolution_spin.setRange(1, 100000)
        self.segment_resolution_spin.setValue(50)
        self.segment_resolution_spin.setSuffix(" m")

        self.normalize_checkbox = QCheckBox("Normalize density")

        self.style_classification_combo = QComboBox()
        for label, key in DENSITY_CLASSIFICATION_OPTIONS:
            self.style_classification_combo.addItem(label, key)
        self.style_classification_combo.setCurrentIndex(
            self.style_classification_combo.findData(DEFAULT_DENSITY_CLASSIFICATION)
        )

        self.style_classes_spin = QSpinBox()
        self.style_classes_spin.setRange(3, 30)
        self.style_classes_spin.setValue(DEFAULT_DENSITY_CLASSES)

        self.style_separate_zero_checkbox = QCheckBox("Show zero density as a separate class")
        self.style_separate_zero_checkbox.setChecked(DEFAULT_SEPARATE_ZERO)

        self.method_combo.currentTextChanged.connect(self._sync_kernel_options)
        self._sync_kernel_options(self.method_combo.currentText())

        core_layout.addRow("Bandwidth", self.bandwidth_spin)
        core_layout.addRow("Method", self.method_combo)
        core_layout.addRow("Kernel type", self.kernel_combo)
        core_layout.addRow("Segment resolution", self.segment_resolution_spin)
        advanced_layout.addRow("", self.normalize_checkbox)
        advanced_layout.addRow("Style classification", self.style_classification_combo)
        advanced_layout.addRow("Style classes", self.style_classes_spin)
        advanced_layout.addRow("", self.style_separate_zero_checkbox)

    def config(self):
        return {
            "Bandwidth": f"{self.bandwidth_spin.value()} m",
            "Method": self.method_combo.currentText(),
            "Kernel type": self.kernel_combo.currentText(),
            "Segment resolution": f"{self.segment_resolution_spin.value()} m",
            "Normalize density": self.normalize_checkbox.isChecked(),
            "Style classification": self.style_classification_combo.currentText(),
            "Style classes": self.style_classes_spin.value(),
            "Separate zero density": self.style_separate_zero_checkbox.isChecked(),
        }

    def _sync_kernel_options(self, method: str):
        del method
        self.kernel_combo.setCurrentText("Epanechnikov")


class NetworkKFunctionPanel(_BaseParameterPanel):
    task_name = "Network K-Function"

    def __init__(self, parent=None):
        super().__init__(parent)
        core_layout = self._add_section("Core Parameters")
        advanced_layout = self._add_section("Advanced Options", collapsible=True, expanded=False)

        self.min_distance_spin = QSpinBox()
        self.min_distance_spin.setRange(0, 1000000)
        self.min_distance_spin.setValue(0)
        self.min_distance_spin.setSuffix(" m")

        self.max_distance_spin = QSpinBox()
        self.max_distance_spin.setRange(1, 1000000)
        self.max_distance_spin.setValue(DEFAULT_K_MAX_DISTANCE)
        self.max_distance_spin.setSuffix(" m")

        self.step_distance_spin = QSpinBox()
        self.step_distance_spin.setRange(1, 100000)
        self.step_distance_spin.setValue(100)
        self.step_distance_spin.setSuffix(" m")

        self.method_combo = QComboBox()
        for label, key in K_METHOD_OPTIONS:
            self.method_combo.addItem(label, key)

        self.epsilon_spin = QDoubleSpinBox()
        self.epsilon_spin.setDecimals(4)
        self.epsilon_spin.setRange(0.0001, 1.0)
        self.epsilon_spin.setSingleStep(0.01)
        self.epsilon_spin.setValue(0.01)
        self.epsilon_spin.setToolTip(EPSILON_HELP)
        self.epsilon_hint = QLabel(EPSILON_HELP)
        self.epsilon_hint.setWordWrap(True)

        self.envelope_checkbox = QCheckBox("Monte Carlo envelope")
        self.envelope_checkbox.setChecked(True)

        self.simulation_spin = QSpinBox()
        self.simulation_spin.setRange(1, 10000)
        self.simulation_spin.setValue(5)
        self.envelope_checkbox.toggled.connect(self.simulation_spin.setEnabled)
        self.simulation_spin.setEnabled(self.envelope_checkbox.isChecked())

        core_layout.addRow("Min distance", self.min_distance_spin)
        core_layout.addRow("Max distance", self.max_distance_spin)
        core_layout.addRow("Step distance", self.step_distance_spin)
        core_layout.addRow("Method", self.method_combo)
        advanced_layout.addRow("Epsilon (STARS only)", self.epsilon_spin)
        advanced_layout.addRow(self.epsilon_hint)
        advanced_layout.addRow("", self.envelope_checkbox)
        advanced_layout.addRow("Number of simulations", self.simulation_spin)
        self.method_combo.currentIndexChanged.connect(self._sync_epsilon)
        self._sync_epsilon()

    def _sync_epsilon(self):
        self.epsilon_spin.setEnabled(self.method_combo.currentData() == "STARS")

    def config(self):
        return {
            "Min distance": f"{self.min_distance_spin.value()} m",
            "Max distance": f"{self.max_distance_spin.value()} m",
            "Step distance": f"{self.step_distance_spin.value()} m",
            "Method": self.method_combo.currentText(),
            "Epsilon": (self.epsilon_spin.value()
                        if self.method_combo.currentData() == "STARS" else "Not used by NS"),
            "Monte Carlo envelope": self.envelope_checkbox.isChecked(),
            "Number of simulations": self.simulation_spin.value(),
        }


class SpatiotemporalNetworkKFunctionPanel(_BaseParameterPanel):
    task_name = "Spatiotemporal Network K-Function"

    TIME_MODE_OPTIONS = [
        ("Auto detect", "auto"),
        ("Date / datetime", "datetime"),
        ("Numeric values", "numeric"),
        ("Unix timestamp (seconds)", "unix_seconds"),
        ("Unix timestamp (milliseconds)", "unix_milliseconds"),
    ]
    TIME_UNIT_OPTIONS = [
        ("Auto (days for date/time)", "auto"),
        ("Seconds", "seconds"),
        ("Minutes", "minutes"),
        ("Hours", "hours"),
        ("Days", "days"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        core_layout = self._add_section("Core Parameters")
        advanced_layout = self._add_section("Advanced Options", collapsible=True, expanded=False)

        self.time_field_combo = QgsFieldComboBox()
        self.time_field_combo.setAllowEmptyFieldName(True)
        self.time_field_combo.setToolTip(
            "Select the event attribute containing numeric or date/time values."
        )

        self.time_mode_combo = QComboBox()
        for label, value in self.TIME_MODE_OPTIONS:
            self.time_mode_combo.addItem(label, value)
        self.time_mode_combo.setToolTip(
            "Auto detects date/time fields and ordinary numeric values. Select a Unix "
            "mode explicitly when a numeric field stores epoch timestamps."
        )

        self.time_unit_combo = QComboBox()
        for label, value in self.TIME_UNIT_OPTIONS:
            self.time_unit_combo.addItem(label, value)
        self.time_unit_combo.setToolTip(
            "Date/time and Unix timestamps are converted to elapsed values in this unit. "
            "Ordinary numeric values are assumed to already use the selected unit."
        )

        self.s_min_distance_spin = QSpinBox()
        self.s_min_distance_spin.setRange(0, 1000000)
        self.s_min_distance_spin.setValue(0)
        self.s_min_distance_spin.setSuffix(" m")

        self.s_max_distance_spin = QSpinBox()
        self.s_max_distance_spin.setRange(1, 1000000)
        self.s_max_distance_spin.setValue(DEFAULT_K_MAX_DISTANCE)
        self.s_max_distance_spin.setSuffix(" m")

        self.s_step_distance_spin = QSpinBox()
        self.s_step_distance_spin.setRange(1, 100000)
        self.s_step_distance_spin.setValue(100)
        self.s_step_distance_spin.setSuffix(" m")

        self.t_min_distance_spin = QDoubleSpinBox()
        self.t_min_distance_spin.setRange(0.0, 1000000.0)
        self.t_min_distance_spin.setDecimals(4)
        self.t_min_distance_spin.setValue(0.0)

        self.t_max_distance_spin = QDoubleSpinBox()
        self.t_max_distance_spin.setRange(0.0001, 1000000.0)
        self.t_max_distance_spin.setDecimals(4)
        self.t_max_distance_spin.setValue(30.0)

        self.t_step_distance_spin = QDoubleSpinBox()
        self.t_step_distance_spin.setRange(0.0001, 1000000.0)
        self.t_step_distance_spin.setDecimals(4)
        self.t_step_distance_spin.setValue(1.0)

        def sync_temporal_suffix():
            unit = self.time_unit_combo.currentData()
            suffixes = {
                "auto": " units",
                "seconds": " s",
                "minutes": " min",
                "hours": " h",
                "days": " days",
            }
            suffix = suffixes.get(unit, " units")
            for spin in (
                self.t_min_distance_spin,
                self.t_max_distance_spin,
                self.t_step_distance_spin,
            ):
                spin.setSuffix(suffix)

        self.time_unit_combo.currentIndexChanged.connect(sync_temporal_suffix)
        sync_temporal_suffix()

        self.method_combo = QComboBox()
        self.method_combo.addItems(["EARTH", "MTS", "EAR", "SPS", "RQS"])

        self.envelope_checkbox = QCheckBox("Monte Carlo envelope")
        self.envelope_checkbox.setChecked(True)

        self.simulation_spin = QSpinBox()
        self.simulation_spin.setRange(1, 10000)
        self.simulation_spin.setValue(5)
        self.envelope_checkbox.toggled.connect(self.simulation_spin.setEnabled)
        self.simulation_spin.setEnabled(self.envelope_checkbox.isChecked())

        core_layout.addRow("Time field", self.time_field_combo)
        core_layout.addRow("Time interpretation", self.time_mode_combo)
        core_layout.addRow("Analysis time unit", self.time_unit_combo)
        core_layout.addRow("Spatial min distance", self.s_min_distance_spin)
        core_layout.addRow("Spatial max distance", self.s_max_distance_spin)
        core_layout.addRow("Spatial step distance", self.s_step_distance_spin)
        core_layout.addRow("Temporal min distance", self.t_min_distance_spin)
        core_layout.addRow("Temporal max distance", self.t_max_distance_spin)
        core_layout.addRow("Temporal step distance", self.t_step_distance_spin)
        core_layout.addRow("Method", self.method_combo)
        advanced_layout.addRow("", self.envelope_checkbox)
        advanced_layout.addRow("Number of simulations", self.simulation_spin)

    def config(self):
        return {
            "Time field": self.time_field_combo.currentField().strip(),
            "Time interpretation": self.time_mode_combo.currentText(),
            "Analysis time unit": self.time_unit_combo.currentText(),
            "Spatial min distance": f"{self.s_min_distance_spin.value()} m",
            "Spatial max distance": f"{self.s_max_distance_spin.value()} m",
            "Spatial step distance": f"{self.s_step_distance_spin.value()} m",
            "Temporal min distance": self.t_min_distance_spin.value(),
            "Temporal max distance": self.t_max_distance_spin.value(),
            "Temporal step distance": self.t_step_distance_spin.value(),
            "Method": self.method_combo.currentText(),
            "Monte Carlo envelope": self.envelope_checkbox.isChecked(),
            "Number of simulations": self.simulation_spin.value(),
        }
