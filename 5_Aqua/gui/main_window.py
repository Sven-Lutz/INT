from __future__ import annotations

import html
import pprint
import time
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QToolButton,
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
DEFAULT_VISIBLE_CHARTS = {
    "flow",
    "capacitance",
    "humidity",
    "valve_position",
}


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
        layout.setContentsMargins(11, 9, 11, 9)
        layout.setSpacing(2)

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
        self.setWindowTitle("Aqua Process Control")
        self.resize(1540, 940)
        self.setMinimumSize(1180, 720)

        self._state_name = "DISCONNECTED"
        self._last_telemetry_monotonic: float | None = None
        self._focused_metric: str | None = None
        self._log_entries: deque[tuple[str, str, str, str]] = deque(
            maxlen=1500
        )
        self._developer_snapshot: dict[str, object] = {}

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(9)

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
        layout.setContentsMargins(15, 10, 15, 10)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("AQUA · Process Control")
        title.setObjectName("appTitle")
        subtitle = QLabel(
            "Gravity drain · capacitance empty detection · live instrumentation"
        )
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.state_label = QLabel("DISCONNECTED")
        self.state_label.setProperty("statusChip", True)
        self.telemetry_status_label = QLabel("TELEMETRY —")
        self.telemetry_status_label.setProperty("statusChip", True)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.disconnect_button = QPushButton("Disconnect")

        layout.addLayout(title_box)
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
        layout.setContentsMargins(0, 0, 5, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_process_group())
        layout.addWidget(self._build_telemetry_group())
        layout.addWidget(self._build_output_group())
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

        self.auto_empty_stop = QCheckBox("Stop automatically when empty")
        self.auto_empty_stop.setChecked(CAPACITANCE_EMPTY_STOP_ENABLED)

        self.empty_threshold = QDoubleSpinBox()
        self.empty_threshold.setRange(0.0, 100.0)
        self.empty_threshold.setDecimals(2)
        self.empty_threshold.setSingleStep(0.25)
        self.empty_threshold.setValue(CAPACITANCE_EMPTY_THRESHOLD)

        self.threshold_hint = QLabel()
        self.threshold_hint.setWordWrap(True)
        self.threshold_hint.setObjectName("appSubtitle")

        self.start_button = QPushButton("START DRAINING")
        self.start_button.setObjectName("primaryButton")
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
        group = QGroupBox("Live Telemetry")
        layout = QGridLayout(group)
        layout.setSpacing(6)

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
            layout.addWidget(card, index // 2, index % 2)
        return group

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Manual Output")
        layout = QHBoxLayout(group)
        self.led_on_button = QPushButton("LED on")
        self.led_off_button = QPushButton("LED off")
        layout.addWidget(self.led_on_button)
        layout.addWidget(self.led_off_button)
        return group

    def _build_right_panel(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_chart_group())
        splitter.addWidget(self._build_diagnostics_tabs())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([650, 250])
        return splitter

    def _build_chart_group(self) -> QGroupBox:
        group = QGroupBox("Live Charts")
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
        self.log_auto_scroll = QCheckBox("Auto-scroll")
        self.log_auto_scroll.setChecked(True)
        self.clear_log_button = QPushButton("Clear view")
        log_toolbar.addWidget(self.log_level_filter)
        log_toolbar.addStretch()
        log_toolbar.addWidget(self.log_auto_scroll)
        log_toolbar.addWidget(self.clear_log_button)
        log_layout.addLayout(log_toolbar)

        self.log_output = QTextBrowser()
        self.log_output.document().setMaximumBlockCount(1200)
        log_layout.addWidget(self.log_output, 1)
        tabs.addTab(log_tab, "Operator Log")

        developer_tab = QWidget()
        developer_layout = QVBoxLayout(developer_tab)
        developer_toolbar = QHBoxLayout()
        developer_toolbar.addWidget(
            QLabel("Raw acquisition, controller and logging state")
        )
        developer_toolbar.addStretch()
        self.copy_developer_button = QPushButton("Copy snapshot")
        developer_toolbar.addWidget(self.copy_developer_button)
        developer_layout.addLayout(developer_toolbar)
        self.developer_output = QPlainTextEdit()
        self.developer_output.setReadOnly(True)
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
        self.clear_log_button.clicked.connect(self._clear_log_view)
        self.copy_developer_button.clicked.connect(self._copy_developer_snapshot)

    def _emit_start_requested(self) -> None:
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
        self.state_label.setText(state_name)

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

        disconnected = state_name == "DISCONNECTED"
        connected_idle = state_name in {"READY", "STOPPED"}
        running = state_name == "RUNNING"
        stopping = state_name == "STOPPING"
        fault = state_name in {"FAULT", "CONFIG ERROR"}

        self.connect_button.setEnabled(disconnected)
        self.disconnect_button.setEnabled(connected_idle or fault)
        self.start_button.setEnabled(connected_idle)
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

    def mark_run_started(self) -> None:
        self.clear_charts()
        self.set_process_state("RUNNING")
        self.telemetry_cards["volume"].set_value(format_metric("volume", 0.0))

    def show_run_summary(self, summary: ProcessSummary) -> None:
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

        self.telemetry_cards["flow"].set_value(
            format_metric("flow", measurement.flow_ml_min),
            detail="measured process telemetry",
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
        if self._last_telemetry_monotonic is None:
            self.telemetry_status_label.setText("TELEMETRY —")
            set_dynamic_property(self.telemetry_status_label, "status", "muted")
            return

        age = max(0.0, time.monotonic() - self._last_telemetry_monotonic)
        if age <= 2.5:
            self.telemetry_status_label.setText(f"LIVE · {age:.1f}s")
            set_dynamic_property(self.telemetry_status_label, "status", "live")
        else:
            self.telemetry_status_label.setText(f"STALE · {age:.1f}s")
            set_dynamic_property(self.telemetry_status_label, "status", "stale")

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
            2,
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
        colors = {
            "DEBUG": "#71879a",
            "INFO": "#cbd8e3",
            "WARNING": "#ffc96b",
            "ERROR": "#ff7d8d",
            "CRITICAL": "#ff5c70",
        }
        lines: list[str] = []
        for timestamp, level, source, message in self._log_entries:
            if self._level_number(level) < minimum:
                continue
            color = colors.get(level, "#cbd8e3")
            lines.append(
                f'<span style="color:#71879a">{html.escape(timestamp)}</span> '
                f'<span style="color:{color};font-weight:600">{html.escape(level):<8}</span> '
                f'<span style="color:#6fa6bf">{html.escape(source)}</span> '
                f'<span style="color:{color}">{html.escape(message)}</span>'
            )

        scrollbar = self.log_output.verticalScrollBar()
        previous = scrollbar.value()
        self.log_output.setHtml("<br>".join(lines))
        if self.log_auto_scroll.isChecked():
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(previous, scrollbar.maximum()))

    def _clear_log_view(self) -> None:
        self._log_entries.clear()
        self.log_output.clear()

    # ------------------------------------------------------------------
    # Developer diagnostics
    # ------------------------------------------------------------------

    def update_developer_snapshot(self, snapshot: dict[str, object]) -> None:
        self._developer_snapshot = snapshot
        text = pprint.pformat(
            snapshot,
            width=110,
            sort_dicts=False,
            compact=False,
        )
        self.developer_output.setPlainText(text)

    def _copy_developer_snapshot(self) -> None:
        self.developer_output.selectAll()
        self.developer_output.copy()
        cursor = self.developer_output.textCursor()
        cursor.clearSelection()
        self.developer_output.setTextCursor(cursor)
