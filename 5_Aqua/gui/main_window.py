from __future__ import annotations

import pprint
import time
from collections import deque
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import (
    CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES,
    CAPACITANCE_EMPTY_STOP_ENABLED,
    CAPACITANCE_EMPTY_THRESHOLD,
    DEFAULT_VALVE_POSITION_PERCENT,
    GUI_LEFT_PANEL_MINIMUM_WIDTH,
    GUI_SPLITTER_SIZES,
    SAMPLE_INTERVAL_SECONDS,
)
from data.models import ProcessSummary, SystemMeasurement
from gui.charting import METRIC_CONFIG, PersistentMetricChart, format_metric
from gui.theme import set_dynamic_property


CHART_ORDER = (
    "flow",
    "capacitance",
    "humidity",
    "valve_position",
    "volume",
    "temperature",
)
DEFAULT_VISIBLE_CHARTS = frozenset(CHART_ORDER)


class TelemetryCard(QFrame):
    clicked = Signal(str)

    def __init__(
        self,
        title: str,
        value: str = "—",
        *,
        metric_key: str | None = None,
        detail: str = "",
    ) -> None:
        super().__init__()
        self.metric_key = metric_key
        self.setObjectName("telemetryCard")
        self.setProperty("metricClickable", metric_key is not None)
        self.setProperty("severity", "normal")
        if metric_key is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(1)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("telemetryTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("telemetryValue")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("telemetryDetail")
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_value(
        self,
        value: str,
        *,
        detail: str | None = None,
        severity: str = "normal",
    ) -> None:
        self.value_label.setText(value)
        if detail is not None:
            self.detail_label.setText(detail)
        set_dynamic_property(self, "severity", severity)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if (
            self.metric_key is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.clicked.emit(self.metric_key)


class ProcessControlWindow(QMainWindow):
    """Operator UI for the gravity-fed Aqua drain process."""

    connect_requested = Signal()
    disconnect_requested = Signal()
    start_requested = Signal(float, bool, float)
    stop_requested = Signal()
    led_requested = Signal(bool)
    empty_detection_changed = Signal(bool, float)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Process Control")
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        self._state_name = "DISCONNECTED"
        self._start_pending = False
        self._last_telemetry_monotonic: float | None = None
        self._latest_measurement: SystemMeasurement | None = None
        self._focused_metric: str | None = None
        self._log_entries: deque[tuple[str, str, str, str]] = deque(
            maxlen=1500
        )
        self._selected_log_entry: tuple[str, str, str, str] | None = None
        self._developer_snapshot: dict[str, object] = {}
        self._developer_sections: dict[str, QTreeWidgetItem] = {}
        self._developer_items: dict[tuple[str, str], QTreeWidgetItem] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addWidget(self._build_header())

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(self._build_left_panel())
        main_splitter.addWidget(self._build_right_panel())
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes(list(GUI_SPLITTER_SIZES))
        main_splitter.setCollapsible(0, False)
        main_splitter.setChildrenCollapsible(False)
        root.addWidget(main_splitter, 1)

        self._connect_local_signals()
        self._update_threshold_hint()
        self.set_process_state("DISCONNECTED")

        self._freshness_timer = QTimer(self)
        self._freshness_timer.setInterval(500)
        self._freshness_timer.timeout.connect(self._update_freshness)
        self._freshness_timer.start()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_header(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("headerFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 7, 10, 7)

        title = QLabel("Process Control")
        title.setObjectName("appTitle")

        self.state_label = QLabel("State: DISCONNECTED")
        self.state_label.setProperty("stateDisplay", True)
        self.telemetry_status_label = QLabel("●")
        self.telemetry_status_label.setProperty("telemetryIndicator", True)
        self.telemetry_status_label.setToolTip("Telemetry unavailable")

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.disconnect_button = QPushButton("Disconnect")

        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.telemetry_status_label)
        layout.addWidget(self.state_label)
        layout.addSpacing(6)
        layout.addWidget(self.connect_button)
        layout.addWidget(self.disconnect_button)
        return frame

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(5)
        layout.addWidget(self._build_process_group())
        layout.addWidget(self._build_telemetry_group())
        layout.addWidget(self._build_output_group())
        layout.addWidget(self._build_system_status_group())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(GUI_LEFT_PANEL_MINIMUM_WIDTH)
        return scroll

    def _build_process_group(self) -> QGroupBox:
        group = QGroupBox("Drain Control")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)

        self.valve_position = QDoubleSpinBox()
        self.valve_position.setRange(0.0, 100.0)
        self.valve_position.setDecimals(0)
        self.valve_position.setSingleStep(5.0)
        self.valve_position.setValue(DEFAULT_VALVE_POSITION_PERCENT)
        self.valve_position.setSuffix(" %")
        self.valve_position.setMinimumHeight(27)
        self.valve_position.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )

        self.auto_empty_stop = QCheckBox("Stop automatically when empty")
        self.auto_empty_stop.setChecked(CAPACITANCE_EMPTY_STOP_ENABLED)

        self.empty_threshold = QDoubleSpinBox()
        self.empty_threshold.setRange(0.0, 100.0)
        self.empty_threshold.setDecimals(2)
        self.empty_threshold.setSingleStep(0.25)
        self.empty_threshold.setValue(CAPACITANCE_EMPTY_THRESHOLD)
        self.empty_threshold.setMinimumHeight(27)
        self.empty_threshold.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.UpDownArrows
        )

        self.threshold_hint = QLabel()
        self.threshold_hint.setWordWrap(True)
        self.threshold_hint.setObjectName("secondaryText")

        self.start_button = QPushButton("Start draining")
        self.start_button.setObjectName("startButton")
        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("dangerButton")

        layout.addWidget(QLabel("Valve opening"), 0, 0)
        layout.addWidget(self.valve_position, 0, 1)
        layout.addWidget(self.auto_empty_stop, 1, 0, 1, 2)
        layout.addWidget(QLabel("Empty threshold (scaled)"), 2, 0)
        layout.addWidget(self.empty_threshold, 2, 1)
        layout.addWidget(self.threshold_hint, 3, 0, 1, 2)
        layout.addWidget(self.start_button, 4, 0)
        layout.addWidget(self.stop_button, 4, 1)
        return group

    def _build_telemetry_group(self) -> QGroupBox:
        group = QGroupBox("Telemetry")
        layout = QGridLayout(group)
        layout.setSpacing(4)

        self.telemetry_context_label = QLabel("No current sample")
        self.telemetry_context_label.setObjectName("secondaryText")
        self.telemetry_context_label.setProperty("sampleContext", True)
        layout.addWidget(self.telemetry_context_label, 0, 0, 1, 2)

        self.telemetry_cards: dict[str, TelemetryCard] = {
            "flow": TelemetryCard("Flow", metric_key="flow"),
            "capacitance": TelemetryCard(
                "Capacitance",
                metric_key="capacitance",
                detail="state: UNKNOWN",
            ),
            "humidity": TelemetryCard("Humidity", metric_key="humidity"),
            "valve_position": TelemetryCard(
                "Valve position",
                metric_key="valve_position",
            ),
            "volume": TelemetryCard(
                "Drained volume",
                metric_key="volume",
            ),
            "temperature": TelemetryCard(
                "Temperature",
                metric_key="temperature",
            ),
        }
        self.alarm_card = TelemetryCard("Bronkhorst alarm", "—")
        self.io_card = TelemetryCard("Digital I/O", "—", detail="Valve / LED")

        cards = [
            self.telemetry_cards["flow"],
            self.telemetry_cards["capacitance"],
            self.telemetry_cards["humidity"],
            self.telemetry_cards["valve_position"],
            self.telemetry_cards["volume"],
            self.telemetry_cards["temperature"],
            self.alarm_card,
            self.io_card,
        ]
        for index, card in enumerate(cards):
            layout.addWidget(card, index // 2 + 1, index % 2)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("LED")
        layout = QHBoxLayout(group)
        self.led_on_button = QPushButton("LED ON")
        self.led_on_button.setObjectName("ledOnButton")
        self.led_off_button = QPushButton("LED OFF")
        self.led_off_button.setObjectName("ledOffButton")
        self.led_state_label = QLabel("LED: —")
        self.led_state_label.setObjectName("ledState")
        self.led_state_label.setProperty("ledState", "unknown")
        layout.addWidget(self.led_on_button)
        layout.addWidget(self.led_off_button)
        layout.addStretch()
        layout.addWidget(self.led_state_label)
        return group

    def _build_system_status_group(self) -> QGroupBox:
        group = QGroupBox("System Status")
        layout = QGridLayout(group)
        layout.setColumnStretch(1, 1)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(3)

        self.system_controller_status = self._new_system_status_label()
        self.system_lucid_status = self._new_system_status_label()
        self.system_telemetry_status = self._new_system_status_label()
        self.system_sampling_status = self._new_system_status_label()
        self.system_logger_status = self._new_system_status_label()
        self.system_latest_run = self._new_system_status_label()
        self.system_latest_run.setWordWrap(True)

        self.system_sampling_status.setText(
            f"{SAMPLE_INTERVAL_SECONDS:g} s configured"
        )
        set_dynamic_property(
            self.system_sampling_status,
            "status",
            "muted",
        )

        rows = (
            ("Controller", self.system_controller_status),
            ("Lucid Digital", self.system_lucid_status),
            ("Telemetry", self.system_telemetry_status),
            ("Sampling", self.system_sampling_status),
            ("Run logger", self.system_logger_status),
            ("Latest run", self.system_latest_run),
        )
        for row, (title, value) in enumerate(rows):
            title_label = QLabel(title)
            title_label.setObjectName("statusTitle")
            layout.addWidget(title_label, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(value, row, 1)

        self.system_latest_run.setText("No completed run")
        self.system_logger_status.setText("Idle")
        self.system_lucid_status.setText("DISCONNECTED")
        return group

    @staticmethod
    def _new_system_status_label() -> QLabel:
        label = QLabel("—")
        label.setProperty("systemStatus", True)
        label.setProperty("status", "muted")
        return label

    def _build_right_panel(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_chart_group())
        splitter.addWidget(self._build_diagnostics_tabs())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 240])
        return splitter

    def _build_chart_group(self) -> QGroupBox:
        group = QGroupBox("Charts")
        outer = QVBoxLayout(group)

        toolbar = QHBoxLayout()
        self.metric_toggle_buttons: dict[str, QToolButton] = {}
        for metric_key in CHART_ORDER:
            config = METRIC_CONFIG[metric_key]
            button = QToolButton()
            button.setText(config.label)
            button.setCheckable(True)
            button.setChecked(metric_key in DEFAULT_VISIBLE_CHARTS)
            button.toggled.connect(self._apply_chart_visibility)
            self.metric_toggle_buttons[metric_key] = button
            toolbar.addWidget(button)

        toolbar.addStretch()
        self.full_history_check = QCheckBox("Full run")
        self.overview_button = QPushButton("Overview")
        self.overview_button.setVisible(False)
        toolbar.addWidget(self.full_history_check)
        toolbar.addWidget(self.overview_button)
        outer.addLayout(toolbar)

        self.chart_container = QWidget()
        self.chart_layout = QGridLayout(self.chart_container)
        self.chart_layout.setContentsMargins(0, 0, 0, 0)
        self.chart_layout.setSpacing(7)
        self.chart_layout.setColumnStretch(0, 1)
        self.chart_layout.setColumnStretch(1, 1)
        outer.addWidget(self.chart_container, 1)

        self.metric_charts: dict[str, PersistentMetricChart] = {
            key: PersistentMetricChart(key)
            for key in CHART_ORDER
        }
        for chart in self.metric_charts.values():
            chart.activated.connect(self.focus_metric_chart)

        self._restore_chart_grid()
        return group

    def _build_diagnostics_tabs(self) -> QTabWidget:
        tabs = QTabWidget()

        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("Minimum level"))
        self.log_level_filter = QComboBox()
        self.log_level_filter.addItems(
            ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        )
        self.log_level_filter.setCurrentText("INFO")
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Search log")
        self.log_search.setClearButtonEnabled(True)
        self.log_auto_scroll = QCheckBox("Auto-scroll")
        self.log_auto_scroll.setChecked(True)
        self.clear_log_button = QPushButton("Clear view")
        log_toolbar.addWidget(self.log_level_filter)
        log_toolbar.addWidget(self.log_search, 1)
        log_toolbar.addStretch()
        log_toolbar.addWidget(self.log_auto_scroll)
        log_toolbar.addWidget(self.clear_log_button)
        log_layout.addLayout(log_toolbar)

        self.log_output = QTableWidget(0, 4)
        self.log_output.setObjectName("operatorLog")
        self.log_output.setHorizontalHeaderLabels(
            ("Time", "Level", "Source", "Message")
        )
        self.log_output.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.log_output.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.log_output.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.log_output.setAlternatingRowColors(True)
        self.log_output.setShowGrid(False)
        self.log_output.setWordWrap(False)
        self.log_output.verticalHeader().setVisible(False)
        log_header = self.log_output.horizontalHeader()
        for column in range(3):
            log_header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        log_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        log_layout.addWidget(self.log_output, 1)

        self.log_detail = QPlainTextEdit()
        self.log_detail.setObjectName("logDetail")
        self.log_detail.setReadOnly(True)
        self.log_detail.setMaximumHeight(86)
        self.log_detail.setVisible(False)
        log_layout.addWidget(self.log_detail)
        tabs.addTab(log_tab, "Operator Log")

        developer_tab = QWidget()
        developer_layout = QVBoxLayout(developer_tab)
        developer_toolbar = QHBoxLayout()
        developer_toolbar.addWidget(
            QLabel("Structured acquisition, controller and logging state")
        )
        developer_toolbar.addStretch()
        self.raw_snapshot_button = QPushButton("Raw snapshot")
        self.raw_snapshot_button.setCheckable(True)
        self.copy_developer_button = QPushButton("Copy diagnostics")
        developer_toolbar.addWidget(self.raw_snapshot_button)
        developer_toolbar.addWidget(self.copy_developer_button)
        developer_layout.addLayout(developer_toolbar)

        self.developer_tree = QTreeWidget()
        self.developer_tree.setObjectName("developerTree")
        self.developer_tree.setColumnCount(2)
        self.developer_tree.setHeaderLabels(("Diagnostic", "Value"))
        self.developer_tree.setAlternatingRowColors(True)
        self.developer_tree.header().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.developer_tree.header().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        developer_layout.addWidget(self.developer_tree, 1)

        self.developer_output = QPlainTextEdit()
        self.developer_output.setObjectName("rawSnapshot")
        self.developer_output.setReadOnly(True)
        self.developer_output.setVisible(False)
        developer_layout.addWidget(self.developer_output, 1)
        tabs.addTab(developer_tab, "Developer Insights")
        return tabs

    # ------------------------------------------------------------------
    # Signals and local interaction
    # ------------------------------------------------------------------

    def _connect_local_signals(self) -> None:
        self.connect_button.clicked.connect(self.connect_requested.emit)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.start_button.clicked.connect(self._emit_start_requested)
        self.stop_button.clicked.connect(self.stop_requested.emit)
        self.led_on_button.clicked.connect(lambda: self.led_requested.emit(True))
        self.led_off_button.clicked.connect(lambda: self.led_requested.emit(False))
        self.auto_empty_stop.toggled.connect(self._emit_empty_detection_changed)
        self.empty_threshold.valueChanged.connect(self._emit_empty_detection_changed)

        for card in self.telemetry_cards.values():
            card.clicked.connect(self.focus_metric_chart)

        self.full_history_check.toggled.connect(self._set_full_history)
        self.overview_button.clicked.connect(self.show_chart_overview)
        self.log_level_filter.currentTextChanged.connect(self._render_log)
        self.log_search.textChanged.connect(self._render_log)
        self.log_output.itemSelectionChanged.connect(
            self._show_selected_log_detail
        )
        self.clear_log_button.clicked.connect(self._clear_log_view)
        self.raw_snapshot_button.toggled.connect(
            self.developer_output.setVisible
        )
        self.copy_developer_button.clicked.connect(self._copy_developer_snapshot)

    def _emit_start_requested(self) -> None:
        if self._start_pending:
            return
        self._start_pending = True
        self.start_button.setEnabled(False)
        self.start_requested.emit(
            self.valve_position.value(),
            self.auto_empty_stop.isChecked(),
            self.empty_threshold.value(),
        )

    def _emit_empty_detection_changed(self) -> None:
        self._update_threshold_hint()
        self.empty_detection_changed.emit(
            self.auto_empty_stop.isChecked(),
            self.empty_threshold.value(),
        )

    def _update_threshold_hint(self) -> None:
        self.empty_threshold.setEnabled(self.auto_empty_stop.isChecked())
        if self.auto_empty_stop.isChecked():
            self.threshold_hint.setText(
                "Stop at capacitance ≤ "
                f"{self.empty_threshold.value():g} scaled units for "
                f"{CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES} consecutive samples."
            )
        else:
            self.threshold_hint.setText(
                "Automatic empty stop is disabled; use STOP to end the run."
            )

    # ------------------------------------------------------------------
    # Process state / controls
    # ------------------------------------------------------------------

    def set_process_state(self, state_name: str) -> None:
        state_name = state_name.upper()
        self._state_name = state_name
        self.state_label.setText(f"State: {state_name}")

        status_map = {
            "DISCONNECTED": "disconnected",
            "READY": "ready",
            "RUNNING": "running",
            "STOPPING": "warning",
            "STOPPED": "ready",
            "FAULT": "fault",
            "CONFIG ERROR": "error",
        }
        set_dynamic_property(
            self.state_label,
            "status",
            status_map.get(state_name, "muted"),
        )

        controller_display = {
            "DISCONNECTED": ("Disconnected", "muted"),
            "READY": ("Connected · ready", "ok"),
            "RUNNING": ("Connected · running", "live"),
            "STOPPING": ("Connected · stopping", "warning"),
            "STOPPED": ("Connected · stopped", "ok"),
            "FAULT": ("Fault", "error"),
            "CONFIG ERROR": ("Configuration error", "error"),
        }
        controller_text, controller_status = controller_display.get(
            state_name,
            (state_name.title(), "muted"),
        )
        self.system_controller_status.setText(controller_text)
        set_dynamic_property(
            self.system_controller_status,
            "status",
            controller_status,
        )

        disconnected = state_name == "DISCONNECTED"
        connected_idle = state_name in {"READY", "STOPPED"}
        running = state_name == "RUNNING"
        stopping = state_name == "STOPPING"
        fault = state_name in {"FAULT", "CONFIG ERROR"}

        self.connect_button.setEnabled(disconnected)
        self.disconnect_button.setEnabled(connected_idle or fault)
        self.start_button.setEnabled(connected_idle and not self._start_pending)
        self.stop_button.setEnabled(running or stopping)
        self.valve_position.setEnabled(connected_idle)
        self.auto_empty_stop.setEnabled(connected_idle)
        self.empty_threshold.setEnabled(
            connected_idle and self.auto_empty_stop.isChecked()
        )
        self.led_on_button.setEnabled(connected_idle)
        self.led_off_button.setEnabled(connected_idle)

        if disconnected or fault:
            self._last_telemetry_monotonic = None
        self._update_freshness()

    def set_configuration_error(self, message: str) -> None:
        self.set_process_state("CONFIG ERROR")
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.append_log(message, "ERROR", source="aqua.config")

    def set_start_pending(self, pending: bool) -> None:
        self._start_pending = pending
        connected_idle = self._state_name in {"READY", "STOPPED"}
        self.start_button.setEnabled(connected_idle and not pending)

    def mark_run_started(self) -> None:
        self.clear_charts()
        self.set_process_state("RUNNING")
        self.telemetry_cards["volume"].set_value(format_metric("volume", 0.0))

    def show_run_summary(self, summary: ProcessSummary) -> None:
        self.system_latest_run.setText(
            f"{summary.total_volume_ml:.1f} ml · "
            f"{summary.duration_seconds:.1f} s\n"
            f"{summary.stop_reason}"
        )
        set_dynamic_property(
            self.system_latest_run,
            "status",
            "ok" if summary.completed_successfully else "error",
        )
        if "empty" in summary.stop_reason.lower():
            self.telemetry_cards["capacitance"].set_value(
                format_metric("capacitance", summary.final_capacitance_value),
                detail="state: EMPTY · automatic stop triggered",
                severity="ok",
            )

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def update_measurement(
        self,
        measurement: SystemMeasurement,
        *,
        elapsed_seconds: float,
        total_volume_ml: float | None = None,
        append_to_charts: bool = True,
    ) -> None:
        self._last_telemetry_monotonic = time.monotonic()
        self._latest_measurement = measurement

        self.telemetry_cards["flow"].set_value(
            format_metric("flow", measurement.flow_ml_min),
            detail="",
        )
        cap_severity = "ok" if measurement.capacitance_state == "FILLED" else "normal"
        if measurement.capacitance_state == "EMPTY":
            cap_severity = "warning"
        capacitance_raw = (
            "raw: —"
            if measurement.capacitance_voltage_v is None
            else f"raw: {measurement.capacitance_voltage_v:.3f} V"
        )
        self.telemetry_cards["capacitance"].set_value(
            format_metric("capacitance", measurement.capacitance_value),
            detail=f"state: {measurement.capacitance_state} · {capacitance_raw}",
            severity=cap_severity,
        )
        self.telemetry_cards["humidity"].set_value(
            format_metric("humidity", measurement.humidity_percent),
            detail=(
                "raw: —"
                if measurement.humidity_voltage_v is None
                else f"raw: {measurement.humidity_voltage_v:.3f} V"
            ),
        )
        self.telemetry_cards["valve_position"].set_value(
            format_metric("valve_position", measurement.valve_position_percent),
            detail=f"Bronkhorst output: {measurement.valve_output_raw_percent:.1f} %",
        )
        self.telemetry_cards["temperature"].set_value(
            format_metric("temperature", measurement.bronkhorst_temperature_c),
            detail=f"control mode: {measurement.bronkhorst_control_mode}",
        )

        if total_volume_ml is not None:
            self.telemetry_cards["volume"].set_value(
                format_metric("volume", total_volume_ml)
            )

        alarm = measurement.bronkhorst_alarm_info
        self.alarm_card.set_value(
            "OK" if alarm == 0 else f"ALARM {alarm}",
            detail="device alarm register",
            severity="ok" if alarm == 0 else "error",
        )
        self.io_card.set_value(
            "VALVE OPEN" if measurement.binary_valve_open else "VALVE CLOSED",
            detail=f"LED {'ON' if measurement.led_on else 'OFF'}",
            severity="ok" if measurement.binary_valve_open else "normal",
        )
        self.led_state_label.setText(
            f"LED: {'ON' if measurement.led_on else 'OFF'}"
        )
        set_dynamic_property(
            self.led_state_label,
            "ledState",
            "on" if measurement.led_on else "off",
        )

        if append_to_charts:
            chart_values = {
                "flow": measurement.flow_ml_min,
                "capacitance": measurement.capacitance_value,
                "humidity": measurement.humidity_percent,
                "valve_position": measurement.valve_position_percent,
                "volume": total_volume_ml,
                "temperature": measurement.bronkhorst_temperature_c,
            }
            for key, value in chart_values.items():
                self.metric_charts[key].append_value(elapsed_seconds, value)

        self._update_freshness()

    def _update_freshness(self) -> None:
        measurement_is_historical = (
            self._latest_measurement is not None
            and (
                self._last_telemetry_monotonic is None
                or self._state_name
                in {"DISCONNECTED", "FAULT", "CONFIG ERROR"}
            )
        )
        if measurement_is_historical:
            self.telemetry_status_label.setText("●")
            self.telemetry_status_label.setToolTip(
                "Latest telemetry is historical and does not represent "
                "current hardware state"
            )
            set_dynamic_property(self.telemetry_status_label, "status", "muted")
            self.telemetry_context_label.setText(
                "Historical sample — not current hardware state"
            )
            set_dynamic_property(
                self.telemetry_context_label,
                "status",
                "historical",
            )
            self.system_telemetry_status.setText("Historical sample")
            set_dynamic_property(
                self.system_telemetry_status,
                "status",
                "muted",
            )
            self._mark_latest_measurement_historical()
            if self._developer_snapshot:
                self._render_developer_snapshot()
            return

        if self._last_telemetry_monotonic is None:
            self.telemetry_status_label.setText("●")
            self.telemetry_status_label.setToolTip("Telemetry unavailable")
            set_dynamic_property(self.telemetry_status_label, "status", "muted")
            self.telemetry_context_label.setText("No current sample")
            set_dynamic_property(
                self.telemetry_context_label,
                "status",
                "muted",
            )
            self.system_telemetry_status.setText("Unavailable")
            set_dynamic_property(
                self.system_telemetry_status,
                "status",
                "muted",
            )
            if self._developer_snapshot:
                self._render_developer_snapshot()
            return

        age = max(0.0, time.monotonic() - self._last_telemetry_monotonic)
        if age <= 2.5:
            self.telemetry_status_label.setText("●")
            self.telemetry_status_label.setToolTip(
                f"Telemetry current ({age:.1f} s old)"
            )
            set_dynamic_property(self.telemetry_status_label, "status", "live")
            self.telemetry_context_label.setText("Current sample")
            set_dynamic_property(
                self.telemetry_context_label,
                "status",
                "live",
            )
            self.system_telemetry_status.setText(f"Current · {age:.1f} s")
            set_dynamic_property(
                self.system_telemetry_status,
                "status",
                "ok",
            )
        else:
            self.telemetry_status_label.setText(f"● STALE {age:.1f} s")
            self.telemetry_status_label.setToolTip(
                f"Telemetry stale ({age:.1f} s old)"
            )
            set_dynamic_property(self.telemetry_status_label, "status", "stale")
            self.telemetry_context_label.setText(f"STALE · {age:.1f} s old")
            set_dynamic_property(
                self.telemetry_context_label,
                "status",
                "stale",
            )
            self.system_telemetry_status.setText(f"Stale · {age:.1f} s")
            set_dynamic_property(
                self.system_telemetry_status,
                "status",
                "warning",
            )

        if self._developer_snapshot:
            self._render_developer_snapshot()

    def _mark_latest_measurement_historical(self) -> None:
        measurement = self._latest_measurement
        if measurement is None:
            return
        alarm = measurement.bronkhorst_alarm_info
        self.alarm_card.set_value(
            "OK" if alarm == 0 else f"ALARM {alarm}",
            detail="device alarm register · historical sample",
            severity="normal",
        )
        self.io_card.set_value(
            "VALVE OPEN" if measurement.binary_valve_open else "VALVE CLOSED",
            detail=(
                f"LED {'ON' if measurement.led_on else 'OFF'} · "
                "historical sample"
            ),
            severity="normal",
        )
        self.led_state_label.setText(
            f"LED: {'ON' if measurement.led_on else 'OFF'} (last sample)"
        )
        set_dynamic_property(
            self.led_state_label,
            "ledState",
            "unknown",
        )

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------

    def clear_charts(self) -> None:
        for chart in self.metric_charts.values():
            chart.clear()

    def _set_full_history(self, enabled: bool) -> None:
        for chart in self.metric_charts.values():
            chart.set_full_history(enabled)

    def _apply_chart_visibility(self) -> None:
        if self._focused_metric is not None:
            return
        self._restore_chart_grid()

    def focus_metric_chart(self, metric_key: str) -> None:
        if metric_key not in self.metric_charts:
            return
        self._focused_metric = metric_key
        self.overview_button.setVisible(True)
        for key, chart in self.metric_charts.items():
            chart.setVisible(key == metric_key)
        self.chart_layout.addWidget(
            self.metric_charts[metric_key],
            0,
            0,
            3,
            2,
        )

    def show_chart_overview(self) -> None:
        self._focused_metric = None
        self.overview_button.setVisible(False)
        self._restore_chart_grid()

    def _restore_chart_grid(self) -> None:
        visible_keys = [
            key
            for key in CHART_ORDER
            if self.metric_toggle_buttons[key].isChecked()
        ]
        if not visible_keys:
            # Never leave the operator with a completely empty chart area.
            self.metric_toggle_buttons["flow"].setChecked(True)
            visible_keys = ["flow"]

        for chart in self.metric_charts.values():
            chart.setVisible(False)

        for row in range(3):
            self.chart_layout.setRowStretch(row, 0)
        visible_row_count = max(1, (len(visible_keys) + 1) // 2)
        for row in range(visible_row_count):
            self.chart_layout.setRowStretch(row, 1)

        for index, key in enumerate(visible_keys):
            chart = self.metric_charts[key]
            self.chart_layout.addWidget(chart, index // 2, index % 2)
            chart.setVisible(True)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape and self._focused_metric is not None:
            self.show_chart_overview()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def append_log(
        self,
        message: str,
        level: str = "INFO",
        *,
        source: str = "aqua",
    ) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_entries.append((timestamp, level.upper(), source, message))
        self._render_log()

    def append_runtime_log(self, level: str, source: str, message: str) -> None:
        self.append_log(message, level, source=source)

    @staticmethod
    def _level_number(level: str) -> int:
        return {
            "DEBUG": 10,
            "INFO": 20,
            "WARNING": 30,
            "ERROR": 40,
            "CRITICAL": 50,
        }.get(level.upper(), 20)

    def _render_log(self) -> None:
        minimum = self._level_number(self.log_level_filter.currentText())
        search = self.log_search.text().strip().casefold()
        colors = {
            "DEBUG": "#737b84",
            "INFO": "#252a30",
            "WARNING": "#9a5900",
            "ERROR": "#b42318",
            "CRITICAL": "#8a1024",
        }
        visible_entries: list[tuple[str, str, str, str]] = []
        for timestamp, level, source, message in self._log_entries:
            if self._level_number(level) < minimum:
                continue
            entry = (timestamp, level, source, message)
            if search and search not in " ".join(entry).casefold():
                continue
            visible_entries.append(entry)

        self.log_output.setUpdatesEnabled(False)
        self.log_output.setRowCount(len(visible_entries))
        selected_row = -1
        for row, entry in enumerate(visible_entries):
            timestamp, level, source, message = entry
            display_message = message.splitlines()[0] if message else ""
            items = (
                QTableWidgetItem(timestamp),
                QTableWidgetItem(level),
                QTableWidgetItem(source),
                QTableWidgetItem(display_message),
            )
            color = QBrush(QColor(colors.get(level, "#252a30")))
            items[1].setForeground(color)
            if level in {"WARNING", "ERROR", "CRITICAL"}:
                items[3].setForeground(color)
            items[3].setData(Qt.ItemDataRole.UserRole, entry)
            items[3].setToolTip(message)
            for column, item in enumerate(items):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter
                )
                self.log_output.setItem(row, column, item)
            if entry == self._selected_log_entry:
                selected_row = row

        self.log_output.setUpdatesEnabled(True)
        if selected_row >= 0:
            self.log_output.selectRow(selected_row)
        else:
            self._selected_log_entry = None
            self.log_detail.clear()
            self.log_detail.setVisible(False)

        if self.log_auto_scroll.isChecked():
            self.log_output.scrollToBottom()

    def _show_selected_log_detail(self) -> None:
        row = self.log_output.currentRow()
        item = self.log_output.item(row, 3) if row >= 0 else None
        entry = (
            item.data(Qt.ItemDataRole.UserRole)
            if item is not None
            else None
        )
        if not isinstance(entry, tuple) or len(entry) != 4:
            self._selected_log_entry = None
            self.log_detail.clear()
            self.log_detail.setVisible(False)
            return
        self._selected_log_entry = entry
        self.log_detail.setPlainText(str(entry[3]))
        self.log_detail.setVisible(True)

    def _clear_log_view(self) -> None:
        self._log_entries.clear()
        self._selected_log_entry = None
        self.log_output.setRowCount(0)
        self.log_detail.clear()
        self.log_detail.setVisible(False)

    # ------------------------------------------------------------------
    # Developer diagnostics
    # ------------------------------------------------------------------

    def update_developer_snapshot(self, snapshot: dict[str, object]) -> None:
        self._developer_snapshot = dict(snapshot)
        text = pprint.pformat(
            snapshot,
            width=110,
            sort_dicts=False,
            compact=False,
        )
        self.developer_output.setPlainText(text)
        self._render_developer_snapshot()

        logging_active = bool(snapshot.get("logging_run_active", False))
        self.system_logger_status.setText(
            "Run active" if logging_active else "Idle"
        )
        set_dynamic_property(
            self.system_logger_status,
            "status",
            "ok" if logging_active else "muted",
        )
        sample_interval = snapshot.get("sample_interval_seconds")
        if isinstance(sample_interval, (int, float)):
            self.system_sampling_status.setText(
                f"{sample_interval:g} s configured"
            )

        lucid_value = snapshot.get("lucid_digital")
        lucid = lucid_value if isinstance(lucid_value, dict) else {}
        lucid_status = str(lucid.get("status", "DISCONNECTED")).upper()
        self.system_lucid_status.setText(lucid_status)
        set_dynamic_property(
            self.system_lucid_status,
            "status",
            {
                "OK": "ok",
                "CONFIG ERROR": "error",
                "COMM ERROR": "error",
                "CHECKING": "warning",
                "DISCONNECTED": "muted",
            }.get(lucid_status, "muted"),
        )

    def _render_developer_snapshot(self) -> None:
        snapshot = self._developer_snapshot
        process_state = self._state_name
        measurement_value = snapshot.get("measurement")
        measurement = (
            measurement_value
            if isinstance(measurement_value, dict)
            else {}
        )
        timestamp_text, measurement_age = self._measurement_timestamp_and_age(
            measurement.get("timestamp")
        )
        measurement_status = self._measurement_status(
            process_state,
            measurement,
            measurement_age,
        )
        age_text = (
            f"{measurement_age:.1f} s"
            if measurement_age is not None
            else "—"
        )
        connected_states = {"READY", "RUNNING", "STOPPING", "STOPPED"}
        connection_text = (
            "Connected"
            if process_state in connected_states
            else "Disconnected / not confirmed"
        )
        context_text = {
            "LIVE": "Current sample from connected controller",
            "STALE": "Sample is old; current hardware state is uncertain",
            "HISTORICAL": (
                "Historical sample only; not current hardware state"
            ),
            "NO DATA": "No measurement available",
        }[measurement_status]

        self._add_developer_section(
            "CURRENT CONTROLLER STATE",
            (
                ("Process state", process_state),
                ("Connection", connection_text),
            ),
        )
        self._add_developer_section(
            "LATEST MEASUREMENT",
            (
                ("Timestamp", timestamp_text),
                ("Age", age_text),
                ("Status", measurement_status),
                ("Context", context_text),
            ),
        )
        self._color_developer_status(measurement_status)

        self._add_developer_section(
            "ACQUISITION",
            (
                (
                    "Capacitance raw AI4",
                    self._format_number(
                        measurement.get("capacitance_voltage_v"),
                        3,
                        " V",
                    ),
                ),
                (
                    "Capacitance scaled",
                    self._format_number(
                        measurement.get("capacitance_value"),
                        2,
                        " scaled",
                    ),
                ),
                (
                    "Capacitance state",
                    str(measurement.get("capacitance_state", "—")),
                ),
                (
                    "Humidity raw AI4",
                    self._format_number(
                        measurement.get("humidity_voltage_v"),
                        3,
                        " V",
                    ),
                ),
                (
                    "Humidity",
                    self._format_number(
                        measurement.get("humidity_percent"),
                        1,
                        " % RH",
                    ),
                ),
            ),
        )

        historical_suffix = (
            " (historical sample)"
            if measurement_status == "HISTORICAL"
            else ""
        )
        self._add_developer_section(
            "BRONKHORST",
            (
                (
                    "Measured flow",
                    self._format_number(
                        measurement.get("flow_ml_min"),
                        2,
                        " ml/min",
                    ),
                ),
                (
                    "Flow setpoint readback",
                    self._format_number(
                        measurement.get("flow_setpoint_ml_min"),
                        2,
                        " ml/min",
                    ),
                ),
                (
                    "Temperature",
                    self._format_number(
                        measurement.get("bronkhorst_temperature_c"),
                        1,
                        " °C",
                    ),
                ),
                ("Alarm", str(measurement.get("bronkhorst_alarm_info", "—"))),
                (
                    "Control mode",
                    str(measurement.get("bronkhorst_control_mode", "—")),
                ),
                (
                    "Commanded valve position",
                    self._format_number(
                        measurement.get("valve_position_percent"),
                        1,
                        " %" + historical_suffix,
                    ),
                ),
                (
                    "Raw valve output",
                    str(measurement.get("valve_output_raw", "—"))
                    + historical_suffix,
                ),
                (
                    "Valve output",
                    self._format_number(
                        measurement.get("valve_output_raw_percent"),
                        1,
                        " %" + historical_suffix,
                    ),
                ),
            ),
        )

        binary_state = self._format_boolean_state(
            measurement.get("binary_valve_open"),
            "OPEN",
            "CLOSED",
        )
        led_state = self._format_boolean_state(
            measurement.get("led_on"),
            "ON",
            "OFF",
        )
        if measurement:
            binary_state += historical_suffix
            led_state += historical_suffix
        self._add_developer_section(
            "DIGITAL I/O",
            (
                ("Downstream binary valve", binary_state),
                ("LED", led_state),
            ),
        )

        lucid_value = snapshot.get("lucid_digital")
        lucid = lucid_value if isinstance(lucid_value, dict) else {}
        lucid_channels_value = lucid.get("channels")
        lucid_channels = (
            lucid_channels_value
            if isinstance(lucid_channels_value, dict)
            else {}
        )
        binary_value = lucid_channels.get("binary_valve")
        binary = binary_value if isinstance(binary_value, dict) else {}
        led_value = lucid_channels.get("led")
        led = led_value if isinstance(led_value, dict) else {}
        binary_prefix = f"Binary Valve / CH{binary.get('channel', '?')}"
        led_prefix = f"LED / CH{led.get('channel', '?')}"

        def lucid_state(
            value: object,
            active_text: str,
            inactive_text: str,
        ) -> str:
            if value == 1:
                return f"{active_text} (1)"
            if value == 0:
                return f"{inactive_text} (0)"
            return "—"

        def lucid_inverted(value: object) -> str:
            if value is True:
                return "on"
            if value is False:
                return "off"
            return "—"

        def optional_value(channel: dict[str, object]) -> str:
            if channel.get("optional_diagnostic_error"):
                return "Unavailable / transient communication error"
            value = channel.get("internal_output_value")
            return "—" if value is None else str(value)

        self._add_developer_section(
            "LUCID DIGITAL",
            (
                ("Port", str(lucid.get("port", "—"))),
                ("Status", str(lucid.get("status", "DISCONNECTED"))),
                ("Preflight", str(lucid.get("preflight", "NOT RUN"))),
                (
                    "Preflight error",
                    str(lucid.get("preflight_error") or "—"),
                ),
                (
                    f"{binary_prefix} expected mode",
                    str(binary.get("expected_mode", "reflect")),
                ),
                (
                    f"{binary_prefix} reported mode",
                    str(binary.get("reported_mode") or "—"),
                ),
                (f"{binary_prefix} expected inverted", "off"),
                (
                    f"{binary_prefix} reported inverted",
                    lucid_inverted(binary.get("inverted")),
                ),
                (
                    f"{binary_prefix} actual logical read-back",
                    lucid_state(
                        binary.get("actual_logical_state"),
                        "OPEN",
                        "CLOSED",
                    ),
                ),
                (
                    f"{binary_prefix} cached application state",
                    lucid_state(
                        binary.get("cached_application_state"),
                        "OPEN",
                        "CLOSED",
                    ),
                ),
                (
                    f"{binary_prefix} internal/configured outDiValue",
                    optional_value(binary),
                ),
                (
                    f"{led_prefix} expected mode",
                    str(led.get("expected_mode", "reflect")),
                ),
                (
                    f"{led_prefix} reported mode",
                    str(led.get("reported_mode") or "—"),
                ),
                (f"{led_prefix} expected inverted", "off"),
                (
                    f"{led_prefix} reported inverted",
                    lucid_inverted(led.get("inverted")),
                ),
                (
                    f"{led_prefix} actual logical read-back",
                    lucid_state(
                        led.get("actual_logical_state"),
                        "ON",
                        "OFF",
                    ),
                ),
                (
                    f"{led_prefix} cached application state",
                    lucid_state(
                        led.get("cached_application_state"),
                        "ON",
                        "OFF",
                    ),
                ),
                (
                    f"{led_prefix} internal/configured outDiValue",
                    optional_value(led),
                ),
                (
                    "Last communication error",
                    str(lucid.get("last_communication_error") or "—"),
                ),
            ),
        )

        empty_details_value = snapshot.get("empty_detector_details")
        empty_details = (
            empty_details_value
            if isinstance(empty_details_value, dict)
            else {}
        )
        self._add_developer_section(
            "EMPTY DETECTOR",
            (
                (
                    "Current semantic state",
                    str(
                        empty_details.get(
                            "state",
                            measurement.get("capacitance_state", "—"),
                        )
                    ),
                ),
                ("Enabled", self._format_enabled(empty_details.get("enabled"))),
                (
                    "Empty threshold",
                    self._format_number(
                        empty_details.get("empty_threshold"),
                        2,
                        " scaled",
                    ),
                ),
                (
                    "Consecutive count",
                    str(empty_details.get("consecutive_count", "—")),
                ),
                (
                    "Required consecutive count",
                    str(empty_details.get("required_consecutive_count", "—")),
                ),
                ("Description", str(snapshot.get("empty_detector", "—"))),
            ),
        )

        self._add_developer_section(
            "DATA / LOGGING",
            (
                (
                    "Repository measurements",
                    str(snapshot.get("repository_measurements", "—")),
                ),
                (
                    "Repository events",
                    str(snapshot.get("repository_events", "—")),
                ),
                (
                    "Run logging",
                    "ACTIVE"
                    if snapshot.get("logging_run_active")
                    else "INACTIVE",
                ),
                ("Measurement CSV", str(snapshot.get("measurement_csv", "—"))),
                ("Event CSV", str(snapshot.get("event_csv", "—"))),
                ("Summary CSV", str(snapshot.get("summary_csv", "—"))),
                ("Runtime log", str(snapshot.get("runtime_log", "—"))),
            ),
        )

    def _add_developer_section(
        self,
        title: str,
        rows: tuple[tuple[str, str], ...],
    ) -> None:
        root = self._developer_sections.get(title)
        if root is None:
            root = QTreeWidgetItem((title, ""))
            root_font = root.font(0)
            root_font.setBold(True)
            root.setFont(0, root_font)
            self.developer_tree.addTopLevelItem(root)
            self._developer_sections[title] = root
            root.setExpanded(True)
        for field, value in rows:
            item = self._developer_items.get((title, field))
            if item is None:
                item = QTreeWidgetItem((field, value))
                root.addChild(item)
                self._developer_items[(title, field)] = item
            else:
                item.setText(1, value)

    def _color_developer_status(self, status: str) -> None:
        item = self._developer_items.get(("LATEST MEASUREMENT", "Status"))
        if item is None:
            return
        color = {
            "LIVE": "#236b3d",
            "STALE": "#9a5900",
            "HISTORICAL": "#69717a",
            "NO DATA": "#69717a",
        }.get(status, "#252a30")
        item.setForeground(1, QBrush(QColor(color)))

    def _measurement_status(
        self,
        process_state: str,
        measurement: dict[str, Any],
        age: float | None,
    ) -> str:
        if not measurement:
            return "NO DATA"
        connected_states = {"READY", "RUNNING", "STOPPING", "STOPPED"}
        if (
            process_state not in connected_states
            or self._state_name not in connected_states
        ):
            return "HISTORICAL"
        if age is None or age > 2.5:
            return "STALE"
        return "LIVE"

    @staticmethod
    def _measurement_timestamp_and_age(
        value: object,
    ) -> tuple[str, float | None]:
        timestamp: datetime | None = None
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, str):
            try:
                timestamp = datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                )
            except ValueError:
                return value, None
        if timestamp is None:
            return "—", None
        now = (
            datetime.now(timestamp.tzinfo)
            if timestamp.tzinfo is not None
            else datetime.now()
        )
        age = max(0.0, (now - timestamp).total_seconds())
        return timestamp.isoformat(timespec="milliseconds"), age

    @staticmethod
    def _format_number(
        value: object,
        decimals: int,
        suffix: str,
    ) -> str:
        if value is None:
            return "—"
        try:
            return f"{float(value):.{decimals}f}{suffix}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _format_boolean_state(
        value: object,
        true_text: str,
        false_text: str,
    ) -> str:
        if value is True:
            return true_text
        if value is False:
            return false_text
        return "—"

    @staticmethod
    def _format_enabled(value: object) -> str:
        if value is True:
            return "ENABLED"
        if value is False:
            return "DISABLED"
        return "—"

    def _copy_developer_snapshot(self) -> None:
        QApplication.clipboard().setText(self.developer_output.toPlainText())
