"""Main workflow dialog for the FastNSA plugin."""

from pathlib import Path

from qgis.PyQt.QtCore import Qt, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QGridLayout,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsApplication,
    QgsCoordinateTransformContext,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsTask,
)
from qgis.gui import QgsMapLayerComboBox

from ..adapters.fastnsa_to_qgs import (
    apply_density_style,
    build_nearest_edge_result_from_pointset,
    build_temporary_nearest_edge_result,
    density_result_to_qgs_layer,
    kfunction_result_to_table_or_csv,
    kfunction_result_to_qgs_table,
    nearest_edge_result_to_qgs_layers,
    spatiotemporal_kfunction_result_to_table_or_csv,
)
from ..adapters.qgs_to_fastnsa import (
    format_timings_for_logs,
    qgs_layers_to_kfunction_inputs,
    qgs_layers_to_kde_inputs,
    qgs_layers_to_nearest_edge_inputs,
    run_network_kde,
    run_network_k_function,
    run_spatiotemporal_network_k_function,
)
from ..utils.layer_utils import (
    add_layers_to_project,
    load_geopackage_layers,
    safe_layer_name,
    selected_layer,
    selected_layer_name,
    snapshot_layer,
    write_layers_to_geopackage,
)
from ..utils.validation import (
    validate_distance_crs,
    validate_line_layer,
    validate_point_layer,
    validate_required_layer,
    validate_text_required,
)
from .parameter_panels import (
    FastNearestEdgePanel,
    NetworkKdePanel,
    NetworkKFunctionPanel,
    SpatiotemporalNetworkKFunctionPanel,
)
from .kfunction_chart_dialog import KFunctionChartDialog
from .st_kfunction_dialog import SpatiotemporalKFunctionDialog


class _TaskProgressDialog(QDialog):
    """Non-modal task progress with separate background and cancel actions."""

    canceled = pyqtSignal()
    backgroundRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._finished = False
        self.setWindowTitle("FastNSA")
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        self._label = QLabel("Validating inputs...")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        background_button = QPushButton("Hide Windows && Run in Background")
        self._cancel_button = QPushButton("Cancel")
        background_button.clicked.connect(self.backgroundRequested.emit)
        self._cancel_button.clicked.connect(self._request_cancel)
        buttons.addWidget(background_button)
        buttons.addWidget(self._cancel_button)
        layout.addLayout(buttons)

    def setLabelText(self, text):
        self._label.setText(text)

    def setValue(self, value):
        self._bar.setValue(max(self._bar.value(), int(value)))

    def _request_cancel(self):
        self._cancel_button.setEnabled(False)
        self._label.setText("Cancellation requested. Waiting for the current backend step...")
        self.canceled.emit()

    def finish(self):
        self._finished = True
        self._bar.setValue(100)
        self.close()
        self.deleteLater()

    def reject(self):
        if self._finished:
            super().reject()
        else:
            self.hide()


class FastNSAMainDialog(QDialog):
    """Workflow-oriented main dialog for the FastNSA plugin."""

    taskStageChanged = pyqtSignal(str)

    PREPROCESS_TASKS = [
        "Fast Nearest Edge Matching",
    ]

    ANALYSIS_TASKS = [
        "Network KDE",
        "Network K-Function",
        "Spatiotemporal Network K-Function",
    ]

    def __init__(self, iface, parent=None):
        # Keep this as an independent top-level window so it can move behind
        # the QGIS map instead of remaining stacked above its parent.
        super().__init__(parent)
        self.iface = iface

        self.setWindowTitle("FastNSA: Fast Network Spatial Analysis")
        self.setMinimumSize(980, 720)
        self.setModal(False)

        self.task_button_group = QButtonGroup(self)
        self.task_cards = {}
        self.preprocess_cards = {}
        self.preprocess_parameter_panels = {}
        self.analysis_parameter_panels = {}
        self.parameter_panels = {}
        self.last_kfunction_result = None
        self.last_spatiotemporal_kfunction_result = None
        self._kfunction_chart_dialog = None
        self._st_kfunction_chart_dialog = None
        self._active_task = None
        self._progress_dialog = None
        self._task_status_widget = None
        self._task_status_label = None
        self._task_status_bar = None
        self._project_generation = 0
        self.workflow_tasks = self.PREPROCESS_TASKS + self.ANALYSIS_TASKS
        self.current_task_name = self.workflow_tasks[0]
        self._right_panel_visible = True
        self._build_ui()
        self._connect_signals()
        self._sync_event_layer_fields()
        self._sync_task_output_controls()
        self.update_summary()
        self.log_message("FastNSA UI initialized.")
        self.update_status("Ready.")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(14)

        self.setStyleSheet(
            "QDialog { background: #f4f8fb; }"
            "QGroupBox { font-weight: 600; color: #17384d; border: 1px solid #d7e2e9; "
            "border-radius: 14px; margin-top: 12px; padding-top: 12px; background: #fcfeff; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 4px; }"
            "QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { "
            "border: 1px solid #c9d7e0; border-radius: 9px; padding: 6px 8px; background: #ffffff; color: #17384d; }"
            "QTextEdit:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { "
            "border: 1px solid #4f8fb4; background: #ffffff; }"
            "QPushButton { background: #16384c; color: white; border: 1px solid #16384c; "
            "border-radius: 10px; padding: 8px 14px; font-weight: 600; }"
            "QPushButton:disabled { background: #aab9c3; border-color: #aab9c3; color: #edf3f7; }"
            "QPushButton:hover:!disabled { background: #204e67; border-color: #204e67; }"
            "QPushButton#secondaryButton { background: #ffffff; color: #24475d; border: 1px solid #c9d7e0; }"
            "QPushButton#secondaryButton:hover:!disabled { background: #f5fafc; border-color: #9fbaca; }"
            "QPushButton#runButton { background: #0f5c78; border-color: #0f5c78; padding-left: 18px; padding-right: 18px; }"
            "QPushButton#runButton:hover:!disabled { background: #147192; border-color: #147192; }"
            "QPushButton#dangerButton { background: #fff8f4; color: #9a4f1f; border: 1px solid #efcfbb; }"
            "QPushButton#dangerButton:hover:!disabled { background: #fff1e7; border-color: #e6b595; }"
            "QCheckBox, QLabel { color: #274355; }"
            "QScrollArea { background: transparent; border: none; }"
            "QSplitter::handle { background: transparent; width: 10px; }"
            "QWidget#leftWorkspace, QWidget#rightWorkspace { background: transparent; }"
        )

        header = QLabel("FastNSA: Fast Network Spatial Analysis")
        header.setObjectName("fastnsaHeader")
        header.setStyleSheet(
            "#fastnsaHeader { font-size: 20px; font-weight: 700; color: #153243; }"
        )
        layout.addWidget(header)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        subtitle = QLabel("Prepare data, choose an analysis, and inspect results from a single workspace.")
        subtitle.setStyleSheet("color: #52606d; font-size: 12px;")
        header_row.addWidget(subtitle, 1)

        self.toggle_right_panel_button = QPushButton("Hide Report Pane")
        self.toggle_right_panel_button.setObjectName("secondaryButton")
        self.toggle_right_panel_button.setMinimumWidth(132)
        header_row.addWidget(self.toggle_right_panel_button, 0, Qt.AlignRight)
        layout.addLayout(header_row)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_container = QWidget()
        left_container.setObjectName("leftWorkspace")
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 10, 0)
        left_layout.setSpacing(12)
        left_layout.setAlignment(Qt.AlignTop)
        # left_layout.addWidget(self._build_workflow_overview())
        left_layout.addWidget(
            self._build_collapsible_panel(
                "Data Setup",
                self._build_data_tab(),
                expanded=True,
                card_style=True,
            )
        )
        left_layout.addWidget(
            self._build_collapsible_panel(
                "Data Preprocess",
                self._build_preprocess_tab(),
                expanded=False,
                card_style=True,
            )
        )
        left_layout.addWidget(
            self._build_collapsible_panel(
                "Analysis Setup",
                self._build_analysis_tab(),
                expanded=False,
                card_style=True,
            )
        )
        left_layout.addWidget(
            self._build_collapsible_panel(
                "Output Setup",
                self._build_output_tab(),
                expanded=False,
                card_style=True,
            )
        )
        left_layout.addStretch(1)
        left_scroll.setWidget(left_container)

        self.right_container = QWidget()
        self.right_container.setObjectName("rightWorkspace")
        right_layout = QVBoxLayout(self.right_container)
        right_layout.setContentsMargins(10, 0, 0, 0)
        right_layout.setSpacing(12)
        right_layout.setAlignment(Qt.AlignTop)
        right_layout.addWidget(self._build_summary_panel(), 0)
        right_layout.addWidget(self._build_log_tab(), 1)

        self.main_splitter.addWidget(left_scroll)
        self.main_splitter.addWidget(self.right_container)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 2)
        layout.addWidget(self.main_splitter, 1)

        footer_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Ready.")
        self.status_label.setObjectName("statusPill")
        self.status_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.status_label.setStyleSheet(
            "#statusPill { background: #ffffff; color: #365468; border: 1px solid #d6e1e8; "
            "border-radius: 12px; padding: 8px 12px; font-weight: 600; }"
        )
        footer_layout.addWidget(self.status_label, 0)
        footer_layout.addStretch(1)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("runButton")
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("secondaryButton")
        self.run_button.setMinimumWidth(78)
        self.close_button.setMinimumWidth(78)

        footer_layout.addWidget(self.run_button)
        footer_layout.addWidget(self.close_button)
        layout.addLayout(footer_layout)

    def _build_data_tab(self):
        tab = QWidget()
        tab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        network_section = QWidget()
        network_layout = QVBoxLayout(network_section)
        network_layout.setContentsMargins(0, 0, 0, 0)
        network_layout.setSpacing(10)

        self.existing_network_section = QGroupBox("Road Network Layer")
        existing_form = QFormLayout(self.existing_network_section)
        self.road_layer_combo = QgsMapLayerComboBox()
        self.road_layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.refresh_road_layers_button = QPushButton("Refresh layer list")
        self.validate_road_button = QPushButton("Validate road network")
        road_button_row = self._button_row(
            self.refresh_road_layers_button,
            self.validate_road_button,
        )
        existing_form.addRow("Road network layer", self.road_layer_combo)
        existing_form.addRow("", road_button_row)
        network_layout.addWidget(self.existing_network_section)

        event_section = QWidget()
        event_form = QFormLayout(event_section)
        event_form.setContentsMargins(0, 0, 0, 0)
        self.event_layer_combo = QgsMapLayerComboBox()
        self.event_layer_combo.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.refresh_event_layers_button = QPushButton("Refresh layer list")
        self.validate_event_button = QPushButton("Validate point layer")
        event_button_row = self._button_row(
            self.refresh_event_layers_button,
            self.validate_event_button,
        )
        event_form.addRow("Point event layer", self.event_layer_combo)
        event_form.addRow("", event_button_row)

        layout.insertWidget(
            layout.count() - 1,
            self._build_collapsible_panel(
                "Road Network Layer",
                network_section,
                expanded=True,
            )
        )
        layout.insertWidget(
            layout.count() - 1,
            self._build_collapsible_panel(
                "Point Event Layer",
                event_section,
                expanded=False,
            )
        )
        return tab

    def _build_analysis_tab(self):
        tab = QWidget()
        tab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        task_section = QWidget()
        task_layout = QVBoxLayout(task_section)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(10)
        task_grid = QGridLayout()
        task_grid.setHorizontalSpacing(10)
        task_grid.setVerticalSpacing(10)

        for index, task_name in enumerate(self.ANALYSIS_TASKS):
            button = self._build_task_card(task_name)
            self.task_button_group.addButton(button, len(self.PREPROCESS_TASKS) + index)
            self.task_cards[task_name] = button
            task_grid.addWidget(button, index // 2, index % 2)

        task_layout.addLayout(task_grid)
        self.task_description_label = QLabel()
        self.task_description_label.setWordWrap(True)
        self.task_description_label.setStyleSheet("color: #52606d;")
        task_layout.addWidget(self.task_description_label)
        layout.insertWidget(
            layout.count() - 1,
            self._build_collapsible_panel(
                "Analysis Task",
                task_section,
                expanded=True,
            )
        )

        panel_section = QWidget()
        panel_section.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        panel_layout = QVBoxLayout(panel_section)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setAlignment(Qt.AlignTop)
        self.analysis_parameter_stack = QStackedWidget()
        self.analysis_parameter_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        kde_panel = NetworkKdePanel()
        k_function_panel = NetworkKFunctionPanel()
        spatiotemporal_k_function_panel = SpatiotemporalNetworkKFunctionPanel()

        self.analysis_parameter_panels = {
            "Network KDE": kde_panel,
            "Network K-Function": k_function_panel,
            "Spatiotemporal Network K-Function": spatiotemporal_k_function_panel,
        }

        for task_name in self.ANALYSIS_TASKS:
            self.analysis_parameter_stack.addWidget(self.analysis_parameter_panels[task_name])

        panel_layout.addWidget(self.analysis_parameter_stack)
        self.parameter_panels = {}
        self.parameter_panels.update(self.preprocess_parameter_panels)
        self.parameter_panels.update(self.analysis_parameter_panels)
        layout.insertWidget(
            layout.count() - 1,
            self._build_collapsible_panel(
                "Task Parameters",
                panel_section,
                expanded=False,
            ),
        )
        self._update_task_description()
        return tab

    def _build_preprocess_tab(self):
        tab = QWidget()
        tab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        task_section = QWidget()
        task_layout = QVBoxLayout(task_section)
        task_layout.setContentsMargins(0, 0, 0, 0)
        task_layout.setSpacing(10)

        self.preprocess_cards = {}
        for index, task_name in enumerate(self.PREPROCESS_TASKS):
            button = self._build_task_card(task_name)
            button.setChecked(index == 0)
            self.task_button_group.addButton(button, index)
            self.preprocess_cards[task_name] = button
            task_layout.addWidget(button)

        self.preprocess_description_label = QLabel()
        self.preprocess_description_label.setWordWrap(True)
        self.preprocess_description_label.setStyleSheet("color: #52606d;")
        task_layout.addWidget(self.preprocess_description_label)
        layout.insertWidget(
            layout.count() - 1,
            self._build_collapsible_panel(
                "Preprocess Task",
                task_section,
                expanded=True,
            )
        )

        panel_section = QWidget()
        panel_section.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        panel_layout = QVBoxLayout(panel_section)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setAlignment(Qt.AlignTop)
        self.preprocess_parameter_stack = QStackedWidget()
        self.preprocess_parameter_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        nearest_edge_panel = FastNearestEdgePanel()
        self.preprocess_parameter_panels = {
            "Fast Nearest Edge Matching": nearest_edge_panel,
        }
        for task_name in self.PREPROCESS_TASKS:
            self.preprocess_parameter_stack.addWidget(self.preprocess_parameter_panels[task_name])

        panel_layout.addWidget(self.preprocess_parameter_stack)
        layout.insertWidget(
            layout.count() - 1,
            self._build_collapsible_panel(
                "Preprocess Parameters",
                panel_section,
                expanded=False,
            )
        )

        self._update_task_description()
        return tab

    def _build_output_tab(self):
        tab = QWidget()
        tab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(tab)
        layout.setSpacing(14)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)

        output_section = QWidget()
        output_form = QFormLayout(output_section)
        output_form.setContentsMargins(0, 0, 0, 0)
        self.output_path_edit = QLineEdit()
        self.browse_output_button = QPushButton("Browse")
        self.browse_output_button.setObjectName("secondaryButton")
        self.browse_output_button.setMinimumWidth(88)
        self.use_temporary_output_checkbox = QCheckBox("Use temporary output")
        self.output_path_row = self._button_row(self.output_path_edit, self.browse_output_button)
        self.output_path_label = QLabel("Output GeoPackage path")
        output_form.addRow(self.output_path_label, self.output_path_row)
        output_form.addRow("", self.use_temporary_output_checkbox)
        self.output_path_panel = self._build_collapsible_panel(
            "Output Path",
            output_section,
            expanded=True,
        )
        layout.insertWidget(
            layout.count() - 1,
            self.output_path_panel,
        )

        result_section = QWidget()
        result_form = QFormLayout(result_section)
        result_form.setContentsMargins(0, 0, 0, 0)
        self.add_result_layer_checkbox = QCheckBox("Add result layer to QGIS")
        self.add_result_layer_checkbox.setChecked(True)
        self.apply_default_style_checkbox = QCheckBox("Apply default FastNSA style")
        self.apply_default_style_checkbox.setChecked(True)
        self.apply_default_style_checkbox.setToolTip(
            "Apply FastNSA styling to outputs which provide a default renderer."
        )
        self.save_runtime_report_checkbox = QCheckBox("Save result table (CSV)")
        self.open_output_checkbox = QCheckBox("Open exported file after completion")
        self.open_output_checkbox.setChecked(False)
        self.open_output_checkbox.setToolTip(
            "Open the saved CSV with the operating system's default application."
        )
        self.runtime_report_path_edit = QLineEdit()
        self.browse_report_button = QPushButton("Browse CSV path")
        self.browse_report_button.setObjectName("secondaryButton")
        self.report_row = self._button_row(self.runtime_report_path_edit, self.browse_report_button)
        self.report_path_label = QLabel("Result CSV path")
        result_form.addRow("", self.add_result_layer_checkbox)
        result_form.addRow("", self.apply_default_style_checkbox)
        result_form.addRow("", self.save_runtime_report_checkbox)
        result_form.addRow(self.report_path_label, self.report_row)
        result_form.addRow("", self.open_output_checkbox)
        self.result_options_panel = self._build_collapsible_panel(
            "Result Options",
            result_section,
            expanded=False,
        )
        layout.insertWidget(
            layout.count() - 1,
            self.result_options_panel,
        )

        return tab

    def _build_summary_panel(self):
        group = QGroupBox("Run Summary")
        layout = QVBoxLayout(group)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.summary_input_card = self._build_info_card("Inputs")
        self.summary_task_card = self._build_info_card("Task")
        self.summary_output_card = self._build_info_card("Output")
        self.summary_state_card = self._build_info_card("Status")

        grid.addWidget(self.summary_input_card["frame"], 0, 0)
        grid.addWidget(self.summary_task_card["frame"], 0, 1)
        grid.addWidget(self.summary_output_card["frame"], 1, 0)
        grid.addWidget(self.summary_state_card["frame"], 1, 1)
        layout.addLayout(grid)

        self.summary_text = QTextEdit()
        self.summary_text.setObjectName("summarySnapshot")
        self.summary_text.setReadOnly(True)
        self.summary_text.setMinimumHeight(132)
        self.summary_text.setMaximumHeight(170)
        self.summary_text.setStyleSheet(
            "QTextEdit#summarySnapshot { background: #fbfdff; border: 1px solid #d9e4eb; "
            "border-radius: 12px; color: #355266; padding: 8px; font-family: monospace; }"
        )
        layout.addWidget(self.summary_text)
        return group

    def _build_log_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        title = QLabel("Activity & Results")
        title.setStyleSheet("font-size: 15px; font-weight: 600; color: #153243;")
        layout.addWidget(title)
        self.log_text = QTextEdit()
        self.log_text.setObjectName("activityLog")
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "QTextEdit#activityLog { background: #ffffff; border: 1px solid #d8e4eb; "
            "border-radius: 12px; color: #2f4a5d; padding: 8px; }"
        )
        layout.addWidget(self.log_text, 1)

        buttons_layout = QHBoxLayout()
        self.clear_log_button = QPushButton("Clear log")
        self.copy_log_button = QPushButton("Copy log")
        self.show_kfunction_chart_button = QPushButton("Show K-function Chart")
        self.show_kfunction_chart_button.setObjectName("secondaryButton")
        self.show_kfunction_chart_button.setEnabled(False)
        self.show_st_kfunction_button = QPushButton("Show ST K-function View")
        self.show_st_kfunction_button.setObjectName("secondaryButton")
        self.show_st_kfunction_button.setEnabled(False)
        self.show_kfunction_chart_button.hide()
        self.show_st_kfunction_button.hide()
        self.clear_log_button.setObjectName("secondaryButton")
        self.copy_log_button.setObjectName("secondaryButton")
        self.clear_log_button.setMinimumWidth(92)
        self.copy_log_button.setMinimumWidth(92)
        buttons_layout.addStretch(1)
        buttons_layout.addWidget(self.show_st_kfunction_button)
        buttons_layout.addWidget(self.show_kfunction_chart_button)
        buttons_layout.addWidget(self.clear_log_button)
        buttons_layout.addWidget(self.copy_log_button)
        layout.addLayout(buttons_layout)
        return tab

    def _connect_signals(self):
        self.refresh_road_layers_button.clicked.connect(
            lambda: self._refresh_layer_list("Road network layer list refreshed.")
        )
        self.refresh_event_layers_button.clicked.connect(
            lambda: self._refresh_layer_list("Point event layer list refreshed.")
        )
        self.validate_road_button.clicked.connect(self._validate_road_layer)
        self.validate_event_button.clicked.connect(self._validate_event_layer)
        self.task_button_group.idClicked.connect(self._on_task_changed)

        self.use_temporary_output_checkbox.toggled.connect(self._sync_output_controls)
        self.browse_output_button.clicked.connect(self._browse_output_path)
        self.browse_report_button.clicked.connect(self._browse_report_path)
        self.save_runtime_report_checkbox.toggled.connect(self._sync_output_controls)

        self.run_button.clicked.connect(self._run_task)
        self.close_button.clicked.connect(self.close)
        self.clear_log_button.clicked.connect(self.log_text.clear)
        self.copy_log_button.clicked.connect(self._copy_log)
        self.show_kfunction_chart_button.clicked.connect(self._show_kfunction_chart)
        self.show_st_kfunction_button.clicked.connect(self._show_st_kfunction_chart)
        self.toggle_right_panel_button.clicked.connect(self._toggle_right_panel)

        summary_triggers = [
            self.output_path_edit.textChanged,
            self.use_temporary_output_checkbox.toggled,
            self.save_runtime_report_checkbox.toggled,
            self.runtime_report_path_edit.textChanged,
            self.add_result_layer_checkbox.toggled,
            self.apply_default_style_checkbox.toggled,
            self.open_output_checkbox.toggled,
        ]

        for signal in summary_triggers:
            signal.connect(self.update_summary)

        for combo in [self.road_layer_combo, self.event_layer_combo]:
            combo.layerChanged.connect(self.update_summary)
        self.event_layer_combo.layerChanged.connect(self._sync_event_layer_fields)
        QgsProject.instance().cleared.connect(self._clear_project_results)
        self.taskStageChanged.connect(self._update_task_status_stage)

        for panel in self.parameter_panels.values():
            for widget in panel.findChildren(QWidget):
                if hasattr(widget, "toggled"):
                    widget.toggled.connect(self.update_summary)
                if hasattr(widget, "valueChanged"):
                    widget.valueChanged.connect(self.update_summary)
                if hasattr(widget, "currentTextChanged"):
                    widget.currentTextChanged.connect(self.update_summary)

    def _clear_project_results(self):
        """Drop results tied to the previous QGIS project."""
        self._project_generation += 1
        self._clear_output_paths()
        self.last_kfunction_result = None
        self.last_spatiotemporal_kfunction_result = None
        self._close_result_viewers()
        self._update_result_buttons()
        if self._active_task is not None:
            self._active_task.cancel()
            self.log_message("Project changed; canceling the FastNSA task tied to the previous project.")

    def _close_result_viewers(self):
        """Close independently owned result windows."""
        for name in ("_kfunction_chart_dialog", "_st_kfunction_chart_dialog"):
            dialog = getattr(self, name)
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
                setattr(self, name, None)

    def _sync_event_layer_fields(self, layer=None):
        """Keep field-based analysis parameters aligned with the event layer."""
        if layer is None:
            layer = selected_layer(self.event_layer_combo)
        panel = self.analysis_parameter_panels.get("Spatiotemporal Network K-Function")
        if panel is not None:
            panel.time_field_combo.setLayer(layer)
        self.update_summary()

    def _button_row(self, left_widget, right_widget):
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(left_widget, 1)
        layout.addWidget(right_widget)
        return container

    def _clear_output_paths(self):
        """Do not carry output destinations into a different task or project."""
        self.output_path_edit.clear()
        self.runtime_report_path_edit.clear()
        self.open_output_checkbox.setChecked(False)

    def _sync_output_controls(self):
        capabilities = self._task_output_capabilities()
        use_temp = self.use_temporary_output_checkbox.isChecked()
        spatial_output = capabilities["spatial_output"]
        save_spatial = spatial_output and not use_temp
        if not save_spatial:
            self.output_path_edit.clear()
        self.output_path_edit.setEnabled(save_spatial)
        self.browse_output_button.setEnabled(save_spatial)

        save_report = self.save_runtime_report_checkbox.isChecked()
        result_table = capabilities["result_table"]
        save_csv = result_table and save_report
        if not save_csv:
            self.runtime_report_path_edit.clear()
        self.runtime_report_path_edit.setEnabled(save_csv)
        self.browse_report_button.setEnabled(save_csv)
        can_open_export = save_csv
        if not can_open_export:
            self.open_output_checkbox.setChecked(False)
        self.open_output_checkbox.setVisible(result_table)
        self.open_output_checkbox.setEnabled(can_open_export)
        self.update_summary()

    def _task_output_capabilities(self):
        task_name = self.current_task_name
        return {
            "spatial_output": task_name in {"Fast Nearest Edge Matching", "Network KDE"},
            "add_layer": task_name in {
                "Fast Nearest Edge Matching", "Network KDE", "Network K-Function",
                "Spatiotemporal Network K-Function",
            },
            "density_style": task_name == "Network KDE",
            "result_table": task_name
            in {"Network K-Function", "Spatiotemporal Network K-Function"},
        }

    def _sync_task_output_controls(self):
        capabilities = self._task_output_capabilities()
        spatial_output = capabilities["spatial_output"]
        result_table = capabilities["result_table"]

        self.output_path_panel.setVisible(spatial_output)
        self.output_path_label.setVisible(spatial_output)
        self.output_path_row.setVisible(spatial_output)
        self.use_temporary_output_checkbox.setVisible(spatial_output)

        self.add_result_layer_checkbox.setVisible(capabilities["add_layer"])
        self.add_result_layer_checkbox.setText(
            "Add temporary result table to QGIS" if result_table else "Add result layer to QGIS"
        )
        self.apply_default_style_checkbox.setVisible(capabilities["density_style"])
        self.save_runtime_report_checkbox.setVisible(result_table)
        self.report_path_label.setVisible(result_table)
        self.report_row.setVisible(result_table)
        self.result_options_panel.setVisible(
            capabilities["add_layer"] or capabilities["density_style"] or result_table
        )
        self._sync_output_controls()

    def _refresh_layer_list(self, message: str):
        self.road_layer_combo.setFilters(QgsMapLayerProxyModel.LineLayer)
        self.event_layer_combo.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.log_message(message)
        self.update_status("Layer lists refreshed.")

    def _validate_road_layer(self):
        errors = validate_required_layer(self.road_layer_combo, "Road network layer")
        if errors:
            self.log_message(f"Validation failed: {errors[0]}")
            self.update_status("Road network validation failed.")
            return

        self.log_message(f"Validated road network layer: {selected_layer_name(self.road_layer_combo)}")
        self.update_status("Road network layer is valid.")

    def _validate_event_layer(self):
        errors = validate_required_layer(self.event_layer_combo, "Point event layer")
        if errors:
            self.log_message(f"Validation failed: {errors[0]}")
            self.update_status("Point layer validation failed.")
            return

        self.log_message(f"Validated point event layer: {selected_layer_name(self.event_layer_combo)}")
        self.update_status("Point event layer is valid.")

    def _on_task_changed(self, index: int):
        previous_task = self.current_task_name
        self.current_task_name = self.workflow_tasks[index]
        if self.current_task_name != previous_task:
            self._clear_output_paths()
        if self.current_task_name in self.preprocess_parameter_panels:
            preprocess_index = self.PREPROCESS_TASKS.index(self.current_task_name)
            self.preprocess_parameter_stack.setCurrentIndex(preprocess_index)
        if self.current_task_name in self.analysis_parameter_panels:
            analysis_index = self.ANALYSIS_TASKS.index(self.current_task_name)
            self.analysis_parameter_stack.setCurrentIndex(analysis_index)
        task_name = self.current_task_name
        self._update_task_description()
        self._update_result_buttons()
        self._sync_task_output_controls()
        self.log_message(f"Selected task changed to: {task_name}.")
        self.update_summary()

    def _build_workflow_overview(self):
        frame = QFrame()
        frame.setObjectName("workflowCard")
        frame.setStyleSheet(
            "QFrame#workflowCard { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fbfeff, stop:0.55 #f1f8fb, stop:1 #e8f2f8); "
            "border: 1px solid #d6e3ea; border-radius: 16px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        title = QLabel("Workflow")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #153243; letter-spacing: 0.3px;")
        blurb = QLabel(
            "1. Select event and network layers.\n"
            "2. Optionally preprocess with nearest-edge matching.\n"
            "3. Run KDE or K-function analysis.\n"
            "4. Review charts, heatmaps, layers, and exports."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color: #475569;")
        layout.addWidget(title)
        layout.addWidget(blurb)
        return frame

    def _build_collapsible_panel(
        self,
        title: str,
        content: QWidget,
        *,
        expanded: bool = True,
        card_style: bool = False,
    ):
        wrapper = QFrame()
        wrapper.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        wrapper_layout = QVBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(6)

        toggle = QToolButton()
        toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        toggle.setText(title)
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        toggle.setStyleSheet(
            "QToolButton { font-weight: 700; color: #17384d; background: #edf5f8; "
            "border: 1px solid #d5e1e8; border-radius: 12px; padding: 10px 14px; text-align: left; }"
            "QToolButton:hover { background: #e5f0f5; border-color: #bfcfd9; }"
            "QToolButton:checked { background: #e8f2f7; border-color: #b8ccd9; }"
        )
        wrapper_layout.addWidget(toggle)

        body = content
        content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        if card_style:
            body_frame = QFrame()
            body_frame.setObjectName("sectionBodyCard")
            body_frame.setStyleSheet(
                "QFrame#sectionBodyCard { background: #ffffff; border: 1px solid #d8e5ec; border-radius: 14px; }"
            )
            body_frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            body_layout = QVBoxLayout(body_frame)
            body_layout.setContentsMargins(14, 14, 14, 14)
            body_layout.addWidget(content)
            body = body_frame

        body.setVisible(expanded)
        wrapper_layout.addWidget(body)

        def _sync(checked: bool):
            body.setVisible(checked)
            toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

        toggle.toggled.connect(_sync)

        return wrapper

    def _update_task_description(self):
        descriptions = {
            "Fast Nearest Edge Matching": "Project points onto the road network and build reusable edge_id/offset mappings.",
            "Network KDE": "Estimate density along the network using lixel segmentation and kernel smoothing.",
            "Network K-Function": "Measure spatial interaction across network distances and compare against CSR simulations.",
            "Spatiotemporal Network K-Function": "Measure joint spatial-temporal interaction across network and time thresholds.",
        }
        text = descriptions.get(self.current_task_name, "")
        if hasattr(self, "task_description_label"):
            self.task_description_label.setText(text if self.current_task_name in self.ANALYSIS_TASKS else "")
        if hasattr(self, "preprocess_description_label"):
            self.preprocess_description_label.setText(text if self.current_task_name in self.PREPROCESS_TASKS else "")

    def _build_info_card(self, title: str):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #5b7383; letter-spacing: 0.6px; padding-left: 2px;"
        )

        body = QWidget()
        body.setObjectName("summaryCardBody")
        body.setStyleSheet(
            "QWidget#summaryCardBody { background: #f8fbfd; border: none; border-radius: 10px; }"
        )
        body.setMinimumHeight(78)
        frame_layout = QVBoxLayout(body)
        frame_layout.setContentsMargins(12, 9, 12, 9)
        frame_layout.setSpacing(6)

        value_label = QLabel("-")
        value_label.setWordWrap(True)
        value_label.setStyleSheet("color: #274355; font-weight: 600; line-height: 1.3em;")
        value_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        layout.addWidget(title_label)
        frame_layout.addWidget(value_label)
        layout.addWidget(body)
        return {"frame": wrapper, "title": title_label, "value": value_label, "body": body}

    def _toggle_right_panel(self):
        self._right_panel_visible = not self._right_panel_visible
        self.right_container.setVisible(self._right_panel_visible)
        self.toggle_right_panel_button.setText(
            "Hide Report Pane" if self._right_panel_visible else "Show Report Pane"
        )
        if self._right_panel_visible:
            total_width = max(self.main_splitter.size().width(), 1)
            left_width = int(total_width * 0.6)
            right_width = max(total_width - left_width, 240)
            self.main_splitter.setSizes([left_width, right_width])
        else:
            total_width = max(self.main_splitter.size().width(), 1)
            self.main_splitter.setSizes([total_width, 0])

    def _build_task_card(self, task_name: str):
        button = QPushButton(task_name)
        button.setCheckable(True)
        button.setMinimumHeight(70)
        button.setStyleSheet(
            "QPushButton { text-align: left; padding: 12px 14px; background: #ffffff; color: #17384d; "
            "border: 1px solid #cfdbe3; border-radius: 14px; font-weight: 700; }"
            "QPushButton:hover:!checked { background: #f4f9fc; border-color: #93b9cd; color: #17384d; }"
            "QPushButton:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #16384c, stop:1 #24576f); "
            "color: white; border-color: #16384c; }"
        )
        return button

    def _update_result_buttons(self):
        show_k = self.current_task_name == "Network K-Function" and self.last_kfunction_result is not None
        show_st = (
            self.current_task_name == "Spatiotemporal Network K-Function"
            and self.last_spatiotemporal_kfunction_result is not None
        )

        self.show_kfunction_chart_button.setVisible(show_k)
        self.show_kfunction_chart_button.setEnabled(show_k)
        self.show_st_kfunction_button.setVisible(show_st)
        self.show_st_kfunction_button.setEnabled(show_st)

    def _browse_output_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output GeoPackage",
            "",
            "GeoPackage (*.gpkg);;All files (*)",
        )
        if path:
            self.output_path_edit.setText(path)

    def _browse_report_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Result CSV Path",
            "",
            "CSV files (*.csv);;All files (*)",
        )
        if path:
            self.runtime_report_path_edit.setText(path)

    def current_parameter_panel(self):
        return self.parameter_panels[self.current_task_name]

    def _start_background_task(self, description: str, worker, on_success):
        if self._active_task is not None:
            QMessageBox.information(self, "FastNSA", "Another FastNSA task is already running.")
            return

        progress = _TaskProgressDialog()
        progress.setValue(0)
        progress.show()
        self._install_task_status_widget(description)
        project_generation = self._project_generation

        self.run_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.update_status(f"Running: {description}")

        def run(task):
            task.setProgress(5)
            return worker(task)

        def finished(exception, result=None):
            self._active_task = None
            self.run_button.setEnabled(True)
            self.close_button.setEnabled(True)

            canceled = task.isCanceled() or (exception is not None and "canceled" in str(exception).lower())
            project_changed = project_generation != self._project_generation
            if canceled or project_changed:
                self.log_message(f"{description} canceled by user.")
                self.update_status(f"{description} canceled.")
                self._close_task_progress()
                return

            if exception is not None:
                message = str(exception)
                self.log_message(f"{description} failed: {message}")
                self.update_status(f"{description} failed.")
                QMessageBox.warning(self, "FastNSA", message)
                self._close_task_progress()
                return

            if result is None:
                self.log_message(f"{description} did not return a result.")
                self.update_status(f"{description} stopped without output.")
                self._close_task_progress()
                return

            try:
                progress.setLabelText("Writing outputs and applying styles...")
                progress.setValue(95)
                on_success(result)
            except Exception as exc:
                self.log_message(f"Failed to finalize {description}: {exc}")
                self.update_status(f"{description} output failed.")
                QMessageBox.warning(self, "FastNSA", str(exc))
            finally:
                self._close_task_progress()

        task = QgsTask.fromFunction(description, run, on_finished=finished)
        task._fastnsa_base_description = description
        task.setDescription(f"{description}: queued (use FastNSA toolbar to restore details)")
        task.progressChanged.connect(lambda value: progress.setValue(int(round(value))))
        task.progressChanged.connect(self._update_task_status_progress)
        self.taskStageChanged.connect(progress.setLabelText)
        progress.canceled.connect(task.cancel)
        progress.backgroundRequested.connect(self._send_active_task_to_background)
        self._active_task = task
        self._progress_dialog = progress
        QgsApplication.taskManager().addTask(task)

    def _set_task_stage(self, task, label: str, progress: float):
        if task.isCanceled():
            raise RuntimeError("FastNSA operation canceled.")
        self.taskStageChanged.emit(label)
        self._set_task_description(task, label)
        task.setProgress(progress)

    @staticmethod
    def _set_task_description(task, stage: str):
        base = getattr(task, "_fastnsa_base_description", "FastNSA")
        task.setDescription(f"{base}: {stage} (FastNSA toolbar restores details)")

    def _send_active_task_to_background(self):
        if self._progress_dialog is not None:
            self._progress_dialog.hide()
        self.hide()

    def _install_task_status_widget(self, description: str):
        self._remove_task_status_widget()
        widget = QFrame()
        widget.setStyleSheet(
            "QFrame { background: #edf5f8; border: 1px solid #9dbdcb; border-radius: 5px; }"
            "QLabel { border: none; color: #17384d; padding: 0 4px; }"
            "QPushButton { padding: 2px 8px; }"
        )
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(5, 2, 5, 2)
        layout.setSpacing(5)
        label = QLabel(f"FastNSA: {description}")
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setFixedWidth(130)
        show_button = QPushButton("Show")
        show_button.clicked.connect(self.show_active_task)
        layout.addWidget(label)
        layout.addWidget(bar)
        layout.addWidget(show_button)
        self.iface.statusBarIface().addPermanentWidget(widget)
        self._task_status_widget = widget
        self._task_status_label = label
        self._task_status_bar = bar

    def _update_task_status_stage(self, stage: str):
        if self._task_status_label is not None:
            self._task_status_label.setText(f"FastNSA: {stage}")

    def _update_task_status_progress(self, value: float):
        if self._task_status_bar is not None:
            self._task_status_bar.setValue(int(round(value)))

    def _remove_task_status_widget(self):
        if self._task_status_widget is not None:
            self.iface.statusBarIface().removeWidget(self._task_status_widget)
            self._task_status_widget.deleteLater()
        self._task_status_widget = None
        self._task_status_label = None
        self._task_status_bar = None

    def _close_task_progress(self):
        if self._progress_dialog is not None:
            self._progress_dialog.finish()
            self._progress_dialog = None
        self._remove_task_status_widget()

    def _notify_completion(self, message: str):
        if self.isVisible():
            QMessageBox.information(self, "FastNSA", message)
        else:
            self.iface.messageBar().pushMessage("FastNSA", message, duration=6)

    def show_active_task(self):
        """Restore the workspace and its active progress window."""
        self.show()
        self.raise_()
        self.activateWindow()
        if self._progress_dialog is not None:
            self._progress_dialog.show()
            self._progress_dialog.raise_()
            self._progress_dialog.activateWindow()

    def _native_progress_callback(self, task, start=55.0, end=92.0):
        last_stage = [None]

        def callback(stage, completed, total):
            if stage != last_stage[0]:
                self.taskStageChanged.emit(stage)
                self._set_task_description(task, stage)
                last_stage[0] = stage
            fraction = completed / total if total > 0 else 0.0
            native_progress = start + (end - start) * max(0.0, min(1.0, fraction))
            task.setProgress(max(task.progress(), native_progress))
            return task.isCanceled()

        return callback

    def _adapter_stage_callback(self, task):
        stages = {
            "Road network conversion": 15.0,
            "Event mapping": 38.0,
            "Reusing preprocessed event mappings": 38.0,
        }

        def callback(stage):
            self._set_task_stage(task, stage, stages.get(stage, 15.0))

        return callback

    def _log_bundle(self, bundle):
        """Write consistent adapter diagnostics after a background conversion."""
        self.log_message(f"Converted network type: {type(bundle.network).__name__}")
        self.log_message(f"Converted point data type: {type(bundle.point_data).__name__}")
        self.log_message(f"Converted pointset type: {type(bundle.pointset).__name__}")
        self.log_message(
            f"Analysis point source: {bundle.point_events_kwargs.get('mapping_method', 'unknown')}"
        )
        self.log_message(f"Converted road edges: {len(bundle.edge_records)}")
        self.log_message(f"Converted event points: {len(bundle.point_records)}")
        for line in format_timings_for_logs(bundle.timings, prefix="Adapter timing"):
            self.log_message(line)
        for warning in bundle.warnings:
            self.log_message(f"Warning: {warning}")

    def _analysis_source_snapshots(self):
        point_layer = selected_layer(self.event_layer_combo)
        road_layer = selected_layer(self.road_layer_combo)

        valid, message = validate_point_layer(point_layer)
        if not valid:
            raise ValueError(message)
        valid, message = validate_line_layer(road_layer)
        if not valid:
            raise ValueError(message)

        return (
            snapshot_layer(point_layer),
            snapshot_layer(road_layer),
            road_layer.crs(),
            QgsCoordinateTransformContext(QgsProject.instance().transformContext()),
        )

    def _run_task(self):
        self.log_message("Validating input layers...")
        errors = self._validate_run_inputs()
        if errors:
            for error in errors:
                self.log_message(f"Validation failed: {error}")
            self.update_status("Validation failed.")
            QMessageBox.warning(self, "FastNSA", "\n".join(errors))
            return

        panel = self.current_parameter_panel()
        config_summary = self.build_configuration_summary()
        for line in config_summary.splitlines():
            self.log_message(line)

        if panel.task_name == "Fast Nearest Edge Matching":
            self._run_nearest_edge_workflow(panel)
            return
        if panel.task_name == "Network K-Function":
            self._run_k_function_workflow(panel)
            return
        if panel.task_name == "Spatiotemporal Network K-Function":
            self._run_spatiotemporal_k_function_workflow(panel)
            return
        if panel.task_name == "Network KDE":
            self._run_kde_workflow(panel)
            return

        message = f"Unsupported analysis task: {panel.task_name}"
        self.log_message(message)
        self.update_status("Unsupported task.")
        QMessageBox.warning(self, "FastNSA", message)

    def _run_nearest_edge_workflow(self, panel):
        try:
            point_source, road_source, road_crs, transform_context = self._analysis_source_snapshots()
        except ValueError as exc:
            self.log_message(f"Validation failed: {exc}")
            self.update_status("Validation failed.")
            QMessageBox.warning(self, "FastNSA", str(exc))
            return

        method_label = panel.method_combo.currentText()

        include_projected = panel.output_projected_checkbox.isChecked()
        include_lines = panel.output_lines_checkbox.isChecked()
        mapping_method = panel.method_combo.currentData()
        comp_eps = float(panel.grid_size_spin.value())
        n_threads = panel.thread_spin.value()
        use_temporary_output = self.use_temporary_output_checkbox.isChecked()
        output_path = self.output_path_edit.text().strip()
        add_to_project = self.add_result_layer_checkbox.isChecked()

        def worker(task):
            task.setProgress(10)
            bundle = qgs_layers_to_nearest_edge_inputs(
                point_source,
                road_source,
                mapping_method=mapping_method,
                comp_eps=comp_eps,
                n_threads=n_threads,
                transform_context=transform_context,
                stage_callback=self._adapter_stage_callback(task),
            )
            task.setProgress(80)
            try:
                result = build_nearest_edge_result_from_pointset(bundle, method_label)
                used_fallback = False
            except Exception:
                result = build_temporary_nearest_edge_result(bundle, None, None, method_label)
                used_fallback = True
            task.setProgress(100)
            return bundle, result, used_fallback

        def finish(payload):
            bundle, result, used_fallback = payload
            self._log_bundle(bundle)
            if used_fallback:
                self.log_message("Used the temporary nearest-edge result reconstruction fallback.")
            else:
                self.log_message("Built nearest-edge outputs from real FastNSA PointEvents mappings.")

            output_layers = nearest_edge_result_to_qgs_layers(
                result,
                road_crs,
                include_projected_points=include_projected,
                include_lines=include_lines,
            )

            if not use_temporary_output:
                stem = Path(output_path).stem
                display_names = [stem]
                if include_projected:
                    display_names.append(f"{stem}_projected_points")
                if include_lines:
                    display_names.append(f"{stem}_point_to_edge_lines")
                written_names = write_layers_to_geopackage(
                    output_layers,
                    output_path,
                    [safe_layer_name(name) for name in display_names],
                )
                self.log_message(f"Wrote nearest-edge outputs to GeoPackage layers: {', '.join(written_names)}")

            project_layers = output_layers
            if not use_temporary_output:
                project_layers = load_geopackage_layers(
                    output_path,
                    written_names,
                )
                for layer, name in zip(project_layers, display_names):
                    layer.setName(name)

            if add_to_project:
                added_layers = add_layers_to_project(project_layers)
                self.log_message(f"Added {len(added_layers)} result layer(s) to the project.")
            else:
                self.log_message("Result layers were created but not added to the project.")

            self.log_message("FastNSA nearest-edge adapter workflow completed.")
            self._notify_completion("Fast Nearest Edge Matching completed successfully.")
            self.update_status("Finished nearest-edge run.")

        self.log_message("Selected task: Fast Nearest Edge Matching")
        self.log_message("Queued layer conversion and nearest-edge matching in the background.")
        self._start_background_task("Fast Nearest Edge Matching", worker, finish)

    def _run_k_function_workflow(self, panel):
        try:
            point_source, road_source, _road_crs, transform_context = self._analysis_source_snapshots()
        except ValueError as exc:
            QMessageBox.warning(self, "FastNSA", str(exc))
            return

        simulations = panel.simulation_spin.value() if panel.envelope_checkbox.isChecked() else 0
        r_min = float(panel.min_distance_spin.value())
        r_max = float(panel.max_distance_spin.value())
        r_step = int(panel.step_distance_spin.value())
        method = panel.method_combo.currentData()
        return_simulations = panel.envelope_checkbox.isChecked()
        epsilon = float(panel.epsilon_spin.value())
        save_report = self.save_runtime_report_checkbox.isChecked()
        report_path = self.runtime_report_path_edit.text().strip()
        add_to_project = self.add_result_layer_checkbox.isChecked()
        open_output = self.open_output_checkbox.isChecked() and save_report

        if r_max <= r_min:
            QMessageBox.warning(self, "FastNSA", "Maximum distance must be greater than minimum distance.")
            return

        def worker(task):
            task.setProgress(10)
            bundle = qgs_layers_to_kfunction_inputs(
                point_source,
                road_source,
                transform_context=transform_context,
                stage_callback=self._adapter_stage_callback(task),
            )
            task.setProgress(55)
            result = run_network_k_function(
                bundle,
                r_min=r_min,
                r_max=r_max,
                r_step=r_step,
                method=method,
                simulations=simulations,
                return_simulations=return_simulations,
                epsilon=epsilon,
                progress_callback=self._native_progress_callback(task),
            )
            task.setProgress(100)
            return bundle, result

        def finish(payload):
            bundle, result = payload
            self._log_bundle(bundle)

            self.log_message("Network K-function backend finished successfully.")
            self.log_message(f"K-function samples: {len(result.r)}")
            self.log_message(f"K-function method: {result.method}")
            self.last_kfunction_result = result
            self._update_result_buttons()

            if save_report and report_path:
                kfunction_result_to_table_or_csv(result, report_path)
                self.log_message(f"Wrote K-function result table to: {report_path}")
                if open_output:
                    self._open_exported_file(report_path)
            if add_to_project:
                table = kfunction_result_to_qgs_table(result)
                if save_report and report_path:
                    table.setName(Path(report_path).stem)
                add_layers_to_project([table])
                self.log_message("Added a temporary K-function result table to the project.")

            self.log_message("FastNSA K-function workflow completed.")
            self.update_status("Finished K-function run.")
            if self.isVisible():
                QTimer.singleShot(0, self._show_kfunction_chart)
            else:
                self.iface.messageBar().pushMessage(
                    "FastNSA",
                    "Network K-Function finished. Open FastNSA to view the chart.",
                    duration=6,
                )

        self.log_message("Queued Network K-Function in the background.")
        self._start_background_task("Network K-Function", worker, finish)

    def _run_kde_workflow(self, panel):
        try:
            point_source, road_source, road_crs, transform_context = self._analysis_source_snapshots()
        except ValueError as exc:
            QMessageBox.warning(self, "FastNSA", str(exc))
            return

        bandwidth = float(panel.bandwidth_spin.value())
        lixel_length = float(panel.segment_resolution_spin.value())
        kernel = panel.kernel_combo.currentText().upper()
        method = panel.method_combo.currentText().upper()
        normalize = panel.normalize_checkbox.isChecked()
        style_classification = str(panel.style_classification_combo.currentData())
        style_classes = panel.style_classes_spin.value()
        style_separate_zero = panel.style_separate_zero_checkbox.isChecked()
        apply_style = self.apply_default_style_checkbox.isChecked()
        use_temporary_output = self.use_temporary_output_checkbox.isChecked()
        output_path = self.output_path_edit.text().strip()
        add_to_project = self.add_result_layer_checkbox.isChecked()
        output_layer_name = (
            safe_layer_name(Path(output_path).stem)
            if not use_temporary_output
            else "fastnsa_kde_lixels"
        )

        if kernel != "EPANECHNIKOV":
            QMessageBox.warning(
                self,
                "FastNSA",
                "The current NKDV backend only supports the Epanechnikov kernel.",
            )
            return

        def worker(task):
            task.setProgress(10)
            bundle = qgs_layers_to_kde_inputs(
                point_source,
                road_source,
                transform_context=transform_context,
                stage_callback=self._adapter_stage_callback(task),
            )
            task.setProgress(55)
            result = run_network_kde(
                bundle,
                bandwidth=bandwidth,
                lixel_length=lixel_length,
                kernel=kernel,
                method=method,
                normalize=normalize,
                progress_callback=self._native_progress_callback(task),
            )
            task.setProgress(100)
            return bundle, result

        def finish(payload):
            bundle, result = payload
            self._log_bundle(bundle)
            density_layer = density_result_to_qgs_layer(
                bundle,
                result,
                road_crs,
                apply_style=False,
            )
            if apply_style:
                apply_density_style(
                    density_layer,
                    classification=style_classification,
                    classes=style_classes,
                    separate_zero=style_separate_zero,
                )

            if not use_temporary_output:
                written_names = write_layers_to_geopackage(
                    [density_layer],
                    output_path,
                    [output_layer_name],
                )
                self.log_message(f"Wrote KDE output to GeoPackage layer: {', '.join(written_names)}")

            project_layers = [density_layer]
            if not use_temporary_output:
                project_layers = load_geopackage_layers(
                    output_path,
                    written_names,
                )
                project_layers[0].setName(Path(output_path).stem)
                if apply_style:
                    apply_density_style(
                        project_layers[0],
                        classification=style_classification,
                        classes=style_classes,
                        separate_zero=style_separate_zero,
                    )

            if add_to_project:
                added_layers = add_layers_to_project(project_layers)
                self.log_message(f"Added {len(added_layers)} KDE result layer(s) to the project.")
            else:
                self.log_message("KDE result layer was created but not added to the project.")

            self.log_message("Network KDE backend finished successfully.")
            self.log_message(f"KDE lixels: {len(result.edge_ids)}")
            self.log_message(f"KDE method: {result.method}")
            self.log_message(f"KDE kernel: {result.kernel}")
            self._notify_completion("Network KDE completed using the FastNSA backend.")
            self.update_status("Finished KDE run.")

        self.log_message("Queued Network KDE in the background.")
        self._start_background_task("Network KDE", worker, finish)

    def _run_spatiotemporal_k_function_workflow(self, panel):
        time_field = panel.time_field_combo.currentField().strip()
        if not time_field:
            self.log_message("Spatiotemporal K-function requires a time field.")
            self.update_status("Time field is required.")
            QMessageBox.warning(self, "FastNSA", "Please provide a time field for spatiotemporal network K-function.")
            return

        time_mode = str(panel.time_mode_combo.currentData())
        time_unit = str(panel.time_unit_combo.currentData())

        try:
            point_source, road_source, _road_crs, transform_context = self._analysis_source_snapshots()
        except ValueError as exc:
            QMessageBox.warning(self, "FastNSA", str(exc))
            return

        simulations = panel.simulation_spin.value() if panel.envelope_checkbox.isChecked() else 0
        s_min = float(panel.s_min_distance_spin.value())
        s_max = float(panel.s_max_distance_spin.value())
        s_step = int(panel.s_step_distance_spin.value())
        t_min = float(panel.t_min_distance_spin.value())
        t_max = float(panel.t_max_distance_spin.value())
        t_step = float(panel.t_step_distance_spin.value())
        method = panel.method_combo.currentText()
        return_simulations = panel.envelope_checkbox.isChecked()
        save_report = self.save_runtime_report_checkbox.isChecked()
        report_path = self.runtime_report_path_edit.text().strip()
        add_to_project = self.add_result_layer_checkbox.isChecked()
        open_output = self.open_output_checkbox.isChecked() and save_report

        if s_max <= s_min:
            QMessageBox.warning(self, "FastNSA", "Maximum spatial distance must exceed the minimum.")
            return
        if t_max <= t_min:
            QMessageBox.warning(self, "FastNSA", "Maximum temporal distance must exceed the minimum.")
            return

        def worker(task):
            task.setProgress(10)
            bundle = qgs_layers_to_kfunction_inputs(
                point_source,
                road_source,
                time_col=time_field,
                time_mode=time_mode,
                time_unit=time_unit,
                transform_context=transform_context,
                stage_callback=self._adapter_stage_callback(task),
            )
            task.setProgress(55)
            result = run_spatiotemporal_network_k_function(
                bundle,
                s_min=s_min,
                s_max=s_max,
                s_step=s_step,
                t_min=t_min,
                t_max=t_max,
                t_step=t_step,
                method=method,
                simulations=simulations,
                return_simulations=return_simulations,
                progress_callback=self._native_progress_callback(task),
            )
            task.setProgress(100)
            return bundle, result

        def finish(payload):
            bundle, result = payload
            self._log_bundle(bundle)
            self.log_message("Spatiotemporal Network K-function backend finished successfully.")
            self.log_message(f"Spatiotemporal K-function shape: {len(result.s)} x {len(result.t)}")
            self.log_message(f"Spatiotemporal K-function method: {result.method}")
            self.log_message(
                f"Temporal axis: {result.time_unit or 'unknown'}; "
                f"mode={result.time_mode or 'unknown'}; origin={result.time_origin or 'unknown'}"
            )
            self.last_spatiotemporal_kfunction_result = result
            self._update_result_buttons()

            if save_report and report_path:
                spatiotemporal_kfunction_result_to_table_or_csv(result, report_path)
                self.log_message(f"Wrote spatiotemporal K-function result table to: {report_path}")
                if open_output:
                    self._open_exported_file(report_path)
            if add_to_project:
                table = kfunction_result_to_qgs_table(result, spatiotemporal=True)
                if save_report and report_path:
                    table.setName(Path(report_path).stem)
                add_layers_to_project([table])
                self.log_message("Added a temporary ST K-function result table to the project.")

            self.log_message("FastNSA spatiotemporal K-function workflow completed.")
            self.update_status("Finished spatiotemporal K-function run.")
            if self.isVisible():
                QTimer.singleShot(0, self._show_st_kfunction_chart)
            else:
                self.iface.messageBar().pushMessage(
                    "FastNSA",
                    "Spatiotemporal K-Function finished. Open FastNSA to view the result.",
                    duration=6,
                )

        self.log_message("Queued Spatiotemporal Network K-Function in the background.")
        self._start_background_task("Spatiotemporal Network K-Function", worker, finish)

    def _open_exported_file(self, output_path):
        """Open an existing export on the GUI thread without failing the analysis."""
        try:
            path = Path(output_path).resolve()
            opened = path.is_file() and QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:
            self.log_message(f"Output was saved, but could not be opened: {exc}")
            return
        if not opened:
            self.log_message(
                f"Output could not be opened automatically. Open it manually: {path}"
            )

    def _copy_log(self):
        QApplication.clipboard().setText(self.log_text.toPlainText())
        self.log_message("Log copied to clipboard.")

    def closeEvent(self, event):
        if self._active_task is not None:
            QMessageBox.information(
                self,
                "FastNSA",
                "A FastNSA analysis is still running. Please wait for it to finish before closing this window.",
            )
            event.ignore()
            return
        self._close_result_viewers()
        super().closeEvent(event)

    def _show_kfunction_chart(self):
        if self.last_kfunction_result is None:
            QMessageBox.information(
                self,
                "FastNSA",
                "No K-function result is available yet.",
            )
            return

        dialog = self._kfunction_chart_dialog
        if dialog is None or dialog.result is not self.last_kfunction_result:
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            # Keep result viewers independent from the workspace. A parented
            # QDialog is always stacked above its parent on some window
            # managers, which made switching among the viewer, workspace and
            # QGIS map unreliable even though the dialog was non-modal.
            dialog = KFunctionChartDialog(self.last_kfunction_result, None)
            dialog.setWindowModality(Qt.NonModal)
            self._kfunction_chart_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _show_st_kfunction_chart(self):
        if self.last_spatiotemporal_kfunction_result is None:
            QMessageBox.information(
                self,
                "FastNSA",
                "No spatiotemporal K-function result is available yet.",
            )
            return

        dialog = self._st_kfunction_chart_dialog
        if dialog is None or dialog.result is not self.last_spatiotemporal_kfunction_result:
            if dialog is not None:
                dialog.close()
                dialog.deleteLater()
            dialog = SpatiotemporalKFunctionDialog(
                self.last_spatiotemporal_kfunction_result,
                None,
            )
            dialog.setWindowModality(Qt.NonModal)
            self._st_kfunction_chart_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _validate_run_inputs(self):
        errors = validate_required_layer(self.event_layer_combo, "Point event layer")
        errors.extend(validate_required_layer(self.road_layer_combo, "Road network layer"))
        road_layer = selected_layer(self.road_layer_combo)
        if road_layer is not None:
            valid, message = validate_distance_crs(road_layer)
            if not valid:
                errors.append(message)
        capabilities = self._task_output_capabilities()

        if capabilities["spatial_output"] and not self.use_temporary_output_checkbox.isChecked():
            errors.extend(validate_text_required(self.output_path_edit.text(), "Output GeoPackage path"))

        if capabilities["result_table"] and self.save_runtime_report_checkbox.isChecked():
            errors.extend(validate_text_required(self.runtime_report_path_edit.text(), "Result CSV path"))

        return errors

    def build_configuration_summary(self):
        panel = self.current_parameter_panel()
        lines = [
            f"Road network source: {self._network_source_summary()}",
            f"Road network layer: {selected_layer_name(self.road_layer_combo)}",
            f"Point event layer: {selected_layer_name(self.event_layer_combo)}",
            f"Selected task: {panel.task_name}",
        ]

        for key, value in panel.config().items():
            lines.append(f"{key}: {value}")

        capabilities = self._task_output_capabilities()
        if capabilities["spatial_output"]:
            lines.append(
                f"Output: {'temporary layer' if self.use_temporary_output_checkbox.isChecked() else self.output_path_edit.text().strip() or 'not set'}"
            )
        if capabilities["add_layer"]:
            lines.append(f"Add result layer to QGIS: {self.add_result_layer_checkbox.isChecked()}")
        if self.open_output_checkbox.isEnabled():
            lines.append(f"Open exported file: {self.open_output_checkbox.isChecked()}")
        if capabilities["density_style"]:
            lines.append(f"Apply default FastNSA style: {self.apply_default_style_checkbox.isChecked()}")
        if capabilities["result_table"]:
            lines.append(f"Save result table: {self.save_runtime_report_checkbox.isChecked()}")
            lines.append(
                f"Result CSV path: {self.runtime_report_path_edit.text().strip() or 'not set'}"
            )
        return "\n".join(lines)

    def update_summary(self):
        task_briefs = {
            "Fast Nearest Edge Matching": "Map points to reusable edge_id/offset values.",
            "Network KDE": "Estimate density along network segments.",
            "Network K-Function": "Measure network clustering against simulations.",
            "Spatiotemporal Network K-Function": "Measure joint space-time clustering.",
        }

        self.summary_input_card["value"].setText(
            "\n".join(
                [
                    f"Road: {selected_layer_name(self.road_layer_combo)}",
                    f"Events: {selected_layer_name(self.event_layer_combo)}",
                    f"Source: {self._network_source_summary()}",
                ]
            )
        )
        self.summary_task_card["value"].setText(
            "\n".join(
                [
                    self.current_parameter_panel().task_name,
                    task_briefs.get(self.current_parameter_panel().task_name, ""),
                ]
            )
        )
        capabilities = self._task_output_capabilities()
        output_lines = []
        if capabilities["spatial_output"]:
            output_lines.append(
                "Temporary layer"
                if self.use_temporary_output_checkbox.isChecked()
                else (self.output_path_edit.text().strip() or "Output path not set")
            )
        if capabilities["add_layer"]:
            output_lines.append(f"Add to QGIS: {self.add_result_layer_checkbox.isChecked()}")
        if capabilities["density_style"]:
            output_lines.append(f"Style: {self.apply_default_style_checkbox.isChecked()}")
        if capabilities["result_table"]:
            result_csv = "disabled"
            if self.save_runtime_report_checkbox.isChecked():
                result_csv = self.runtime_report_path_edit.text().strip() or "path not set"
            output_lines.append(f"Result CSV: {result_csv}")
        self.summary_output_card["value"].setText("\n".join(output_lines) or "No file output")
        self.summary_state_card["value"].setText(
            self.status_label.text().replace("Status: ", "")
        )
        self.summary_text.setPlainText(self.build_configuration_summary())

    def _network_source_summary(self):
        return "existing layer"

    def log_message(self, message: str):
        self.log_text.append(message)

    def update_status(self, status: str):
        self.status_label.setText(f"Status: {status}")
