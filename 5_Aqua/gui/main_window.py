from __future__ import annotations

from datetime import datetime
from html import escape

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import (
    BRONKHORST_BAUDRATE,
    BRONKHORST_NODE_ADDRESS,
    BRONKHORST_PORT,
    CAPACITANCE_CHANNEL,
    CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES,
    CAPACITANCE_EMPTY_STOP_ENABLED,
    CAPACITANCE_EMPTY_THRESHOLD,
    DEFAULT_VALVE_POSITION_PERCENT,
    GUI_LEFT_PANEL_MINIMUM_WIDTH,
    GUI_SPLITTER_SIZES,
    HUMIDITY_CHANNEL,
    LUCID_AI_PORT,
    LUCID_DO_PORT,
    SAMPLE_INTERVAL_SECONDS,
)
from control.empty_detection import CapacitanceState
from control.state_machine import ProcessState
from data.models import ProcessSummary, SystemMeasurement
from gui.charting import (
    DEFAULT_TIME_WINDOW_INDEX,
    TIME_WINDOWS,
    ChartPanel,
    format_metric,
)
from gui.colors import (
    alarm_color,
    bold_color_style,
    capacitance_state_color,
    log_level_color,
    process_state_color,
)
from gui.worker import ProcessWorker, describe_summary


class TelemetryCard(QFrame):
    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        self.title = QLabel(title.upper())
        self.value = QLabel(value)
        self.value.setFont(
            QFont("Segoe UI", 15, QFont.Weight.Bold)
        )
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(
        self,
        value: str,
        color: str = "",
    ) -> None:
        self.value.setText(value)
        self.value.setStyleSheet(bold_color_style(color))


class ProcessControlWindow(QMainWindow):
    """Operator window for the gravity-fed drain process.

    The valve opening is the only manipulated variable and defaults to
    100 %. Draining ends when the capacitance sensor reports an empty
    vessel or when the operator stops the run.
    """

    _connect_requested = Signal()
    _disconnect_requested = Signal()
    _start_requested = Signal(float, bool, float)
    _led_requested = Signal(bool)

    def __init__(self, controller_factory) -> None:
        super().__init__()

        self.setWindowTitle("Process Control")
        self.resize(1480, 900)

        self._connected = False
        self._state = ProcessState.DISCONNECTED
        self._sample_count = 0
        self._last_sample_timestamp: datetime | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())

        # The control panel opens at roughly one third of the window
        # and cannot be collapsed away entirely.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes(list(GUI_SPLITTER_SIZES))
        splitter.setCollapsible(0, False)
        splitter.setChildrenCollapsible(False)

        root.addWidget(splitter, 1)

        self._start_worker(controller_factory)
        self._connect_signals()
        self._update_threshold_hint()
        self._apply_state(ProcessState.DISCONNECTED)

        self.append_log(
            "Ready. Press Connect to open the devices.",
        )

    # -------------------------------------------------------------
    # Worker
    # -------------------------------------------------------------

    def _start_worker(self, controller_factory) -> None:
        self.worker_thread = QThread(self)
        self.worker = ProcessWorker(controller_factory)
        self.worker.moveToThread(self.worker_thread)

        self._connect_requested.connect(
            self.worker.connect_devices
        )
        self._disconnect_requested.connect(
            self.worker.disconnect_devices
        )
        self._start_requested.connect(
            self.worker.start_process
        )
        self._led_requested.connect(self.worker.set_led)

        self.worker.log_message.connect(self.append_log)
        self.worker.state_changed.connect(self._apply_state)
        self.worker.connection_changed.connect(
            self._apply_connection
        )
        self.worker.measurement_ready.connect(
            self._apply_measurement
        )
        self.worker.run_finished.connect(
            self._apply_run_finished
        )
        self.worker.failed.connect(self._show_failure)

        self.worker_thread.start()

    # -------------------------------------------------------------
    # Layout
    # -------------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()

        title = QLabel("Process Control")
        title.setFont(
            QFont("Segoe UI", 18, QFont.Weight.Bold)
        )

        self.state_label = QLabel("DISCONNECTED")
        self.state_label.setFont(
            QFont("Segoe UI", 12, QFont.Weight.Bold)
        )

        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("State"))
        header.addWidget(self.state_label)
        header.addSpacing(16)
        header.addWidget(self.connect_button)
        header.addWidget(self.disconnect_button)

        return header

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._build_process_group())
        layout.addWidget(self._build_capacitance_group())
        layout.addWidget(self._build_telemetry_group())
        layout.addWidget(self._build_led_group())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(GUI_LEFT_PANEL_MINIMUM_WIDTH)

        return scroll

    def _build_process_group(self) -> QGroupBox:
        group = QGroupBox("Process Control")
        layout = QGridLayout(group)

        self.valve_position = QDoubleSpinBox()
        self.valve_position.setRange(0.0, 100.0)
        self.valve_position.setDecimals(0)
        self.valve_position.setSingleStep(5.0)
        self.valve_position.setValue(
            DEFAULT_VALVE_POSITION_PERCENT
        )
        self.valve_position.setSuffix(" %")

        valve_hint = QLabel(
            f"Default: {DEFAULT_VALVE_POSITION_PERCENT:.0f} %"
        )
        valve_hint.setEnabled(False)

        self.auto_empty_stop = QCheckBox(
            "Automatic empty stop"
        )
        self.auto_empty_stop.setChecked(
            CAPACITANCE_EMPTY_STOP_ENABLED
        )

        self.empty_threshold = QDoubleSpinBox()
        self.empty_threshold.setRange(0.0, 100.0)
        self.empty_threshold.setDecimals(2)
        self.empty_threshold.setSingleStep(0.5)
        self.empty_threshold.setValue(
            CAPACITANCE_EMPTY_THRESHOLD
        )
        self.empty_threshold.setSuffix(" V")

        self.threshold_hint = QLabel()
        self.threshold_hint.setEnabled(False)
        self.threshold_hint.setWordWrap(True)

        self.start_button = QPushButton("Start draining")
        self.stop_button = QPushButton("Stop")

        layout.addWidget(QLabel("Valve opening"), 0, 0)
        layout.addWidget(self.valve_position, 0, 1)
        layout.addWidget(valve_hint, 1, 0, 1, 2)
        layout.addWidget(self.auto_empty_stop, 2, 0, 1, 2)
        layout.addWidget(QLabel("Empty threshold"), 3, 0)
        layout.addWidget(self.empty_threshold, 3, 1)
        layout.addWidget(self.threshold_hint, 4, 0, 1, 2)
        layout.addWidget(self.start_button, 5, 0)
        layout.addWidget(self.stop_button, 5, 1)

        return group

    def _build_capacitance_group(self) -> QGroupBox:
        group = QGroupBox("Capacitance")
        layout = QGridLayout(group)

        self.capacitance_value_label = QLabel("—")
        self.capacitance_value_label.setFont(
            QFont("Segoe UI", 15, QFont.Weight.Bold)
        )

        self.capacitance_state_label = QLabel(
            CapacitanceState.UNKNOWN.value
        )
        self.capacitance_state_label.setFont(
            QFont("Segoe UI", 12, QFont.Weight.Bold)
        )
        self.capacitance_state_label.setStyleSheet(
            bold_color_style(
                capacitance_state_color(
                    CapacitanceState.UNKNOWN.value
                )
            )
        )

        self.empty_stop_status_label = QLabel("ARMED")

        layout.addWidget(QLabel("Sensor value"), 0, 0)
        layout.addWidget(self.capacitance_value_label, 0, 1)
        layout.addWidget(QLabel("State"), 1, 0)
        layout.addWidget(self.capacitance_state_label, 1, 1)
        layout.addWidget(QLabel("Automatic empty stop"), 2, 0)
        layout.addWidget(self.empty_stop_status_label, 2, 1)

        return group

    def _build_telemetry_group(self) -> QGroupBox:
        group = QGroupBox("Live Telemetry")
        layout = QGridLayout(group)

        self.flow_card = TelemetryCard("Flow")
        self.volume_card = TelemetryCard("Drained volume")
        self.valve_card = TelemetryCard("Valve position")
        self.humidity_card = TelemetryCard("Humidity")
        self.temperature_card = TelemetryCard("Temperature")
        self.alarm_card = TelemetryCard("Alarm")

        cards = (
            self.flow_card,
            self.volume_card,
            self.valve_card,
            self.humidity_card,
            self.temperature_card,
            self.alarm_card,
        )

        for index, card in enumerate(cards):
            layout.addWidget(
                card,
                index // 2,
                index % 2,
            )

        return group

    def _build_led_group(self) -> QGroupBox:
        group = QGroupBox("LED Control")
        layout = QHBoxLayout(group)

        self.led_on_button = QPushButton("LED on")
        self.led_off_button = QPushButton("LED off")

        self.led_state_label = QLabel("OFF")
        self.led_state_label.setFont(
            QFont("Segoe UI", 12, QFont.Weight.Bold)
        )

        layout.addWidget(self.led_on_button)
        layout.addWidget(self.led_off_button)
        layout.addStretch()
        layout.addWidget(self.led_state_label)

        return group

    def _build_right_panel(self) -> QWidget:
        charts = QGroupBox("Live Charts")
        charts_layout = QVBoxLayout(charts)

        self.time_window = QComboBox()
        for label, _ in TIME_WINDOWS:
            self.time_window.addItem(label)
        self.time_window.setCurrentIndex(
            DEFAULT_TIME_WINDOW_INDEX
        )

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Time window"))
        controls.addWidget(self.time_window)
        controls.addStretch()

        hint = QLabel(
            "Click a point to read it · drag to zoom · "
            "double-click to reset"
        )
        hint.setEnabled(False)
        controls.addWidget(hint)

        charts_layout.addLayout(controls)

        grid = QGridLayout()
        self.flow_chart = ChartPanel("flow")
        self.capacitance_chart = ChartPanel("capacitance")
        self.humidity_chart = ChartPanel("humidity")
        self.valve_chart = ChartPanel("valve_position")

        grid.addWidget(self.flow_chart, 0, 0)
        grid.addWidget(self.capacitance_chart, 0, 1)
        grid.addWidget(self.humidity_chart, 1, 0)
        grid.addWidget(self.valve_chart, 1, 1)

        charts_layout.addLayout(grid, 1)

        tabs = QTabWidget()
        tabs.addTab(self._build_log_tab(), "Logging")
        tabs.addTab(
            self._build_insights_tab(),
            "Developer Insights",
        )

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(charts)
        splitter.addWidget(tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 260])
        splitter.setChildrenCollapsible(False)

        return splitter

    def _build_log_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        controls = QHBoxLayout()
        self.show_debug = QCheckBox("Show debug output")
        self.clear_log_button = QPushButton("Clear log")
        controls.addWidget(self.show_debug)
        controls.addStretch()
        controls.addWidget(self.clear_log_button)
        layout.addLayout(controls)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )
        self.log_output.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_output)

        return page

    def _build_insights_tab(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)

        self.insight_labels: dict[str, QLabel] = {}

        connection_form = QFormLayout()
        self._add_insight(
            connection_form,
            "bronkhorst",
            "Bronkhorst",
            f"{BRONKHORST_PORT} · node "
            f"{BRONKHORST_NODE_ADDRESS} · "
            f"{BRONKHORST_BAUDRATE} baud",
        )
        self._add_insight(
            connection_form,
            "lucid_do",
            "LucidControl DO",
            LUCID_DO_PORT,
        )
        self._add_insight(
            connection_form,
            "lucid_ai",
            "LucidControl AI4",
            f"{LUCID_AI_PORT} · capacitance CH"
            f"{CAPACITANCE_CHANNEL} · humidity CH"
            f"{HUMIDITY_CHANNEL}",
        )
        self._add_insight(
            connection_form,
            "control_mode",
            "Control mode",
        )
        self._add_insight(
            connection_form,
            "alarm_info",
            "Alarm info (raw)",
        )
        self._add_insight(
            connection_form,
            "binary_valve",
            "Binary valve",
        )

        signal_form = QFormLayout()
        self._add_insight(
            signal_form,
            "capacitance_voltage",
            "Capacitance raw",
        )
        self._add_insight(
            signal_form,
            "capacitance_value",
            "Capacitance value",
        )
        self._add_insight(
            signal_form,
            "humidity_voltage",
            "Humidity raw",
        )
        self._add_insight(
            signal_form,
            "humidity_percent",
            "Humidity converted",
        )
        self._add_insight(
            signal_form,
            "valve_raw",
            "Valve output (raw)",
        )
        self._add_insight(
            signal_form,
            "flow_setpoint",
            "Flow setpoint (device)",
        )

        timing_form = QFormLayout()
        self._add_insight(
            timing_form,
            "samples",
            "Samples this run",
            "0",
        )
        self._add_insight(
            timing_form,
            "interval",
            "Sample interval",
            f"configured {SAMPLE_INTERVAL_SECONDS:.2f} s",
        )
        self._add_insight(
            timing_form,
            "elapsed",
            "Elapsed",
        )
        self._add_insight(
            timing_form,
            "volume",
            "Integrated volume",
        )
        self._add_insight(
            timing_form,
            "last_summary",
            "Last run",
        )
        self._add_insight(
            timing_form,
            "last_error",
            "Last error",
            "none",
        )

        for form in (
            connection_form,
            signal_form,
            timing_form,
        ):
            container = QWidget()
            container.setLayout(form)
            layout.addWidget(container)

        layout.addStretch()

        return page

    def _add_insight(
        self,
        form: QFormLayout,
        key: str,
        label: str,
        initial: str = "—",
    ) -> None:
        value_label = QLabel(initial)
        value_label.setFont(QFont("Consolas", 9))
        value_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.insight_labels[key] = value_label
        form.addRow(f"{label}:", value_label)

    def _set_insight(self, key: str, value: str) -> None:
        label = self.insight_labels.get(key)

        if label is not None:
            label.setText(value)

    # -------------------------------------------------------------
    # Signals
    # -------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.connect_button.clicked.connect(
            self._on_connect_clicked
        )
        self.disconnect_button.clicked.connect(
            self._on_disconnect_clicked
        )
        self.start_button.clicked.connect(
            self._on_start_clicked
        )
        self.stop_button.clicked.connect(
            self._on_stop_clicked
        )
        self.led_on_button.clicked.connect(
            lambda: self._on_led_clicked(True)
        )
        self.led_off_button.clicked.connect(
            lambda: self._on_led_clicked(False)
        )
        self.auto_empty_stop.toggled.connect(
            self._update_threshold_hint
        )
        self.empty_threshold.valueChanged.connect(
            self._update_threshold_hint
        )
        self.time_window.currentIndexChanged.connect(
            self._on_time_window_changed
        )
        self.clear_log_button.clicked.connect(
            self.log_output.clear
        )

    def _on_connect_clicked(self) -> None:
        self.connect_button.setEnabled(False)
        self.append_log("Connect requested.")
        self._connect_requested.emit()

    def _on_disconnect_clicked(self) -> None:
        self.disconnect_button.setEnabled(False)
        self.append_log("Disconnect requested.")
        self._disconnect_requested.emit()

    def _on_start_clicked(self) -> None:
        self._sample_count = 0
        self._last_sample_timestamp = None
        self._set_insight("samples", "0")
        self._set_insight("last_error", "none")
        self.clear_charts()
        self.empty_stop_status_label.setText(
            "ARMED"
            if self.auto_empty_stop.isChecked()
            else "OFF"
        )

        self.start_button.setEnabled(False)
        self._start_requested.emit(
            self.valve_position.value(),
            self.auto_empty_stop.isChecked(),
            self.empty_threshold.value(),
        )

    def _on_stop_clicked(self) -> None:
        self.stop_button.setEnabled(False)
        self.append_log("Stop requested.", "WARNING")

        # Thread-safe: only sets an event, no serial traffic.
        self.worker.request_stop()

    def _on_led_clicked(self, enabled: bool) -> None:
        self.led_state_label.setText(
            "ON" if enabled else "OFF"
        )
        self.led_state_label.setStyleSheet(
            bold_color_style(
                "#CA8A04" if enabled else ""
            )
        )
        self._led_requested.emit(enabled)

    def _on_time_window_changed(self, index: int) -> None:
        _, window_seconds = TIME_WINDOWS[index]

        for chart in self._charts():
            chart.set_window_seconds(window_seconds)

    def _charts(self) -> tuple[ChartPanel, ...]:
        return (
            self.flow_chart,
            self.capacitance_chart,
            self.humidity_chart,
            self.valve_chart,
        )

    def _update_threshold_hint(self) -> None:
        if not self.auto_empty_stop.isChecked():
            self.threshold_hint.setText(
                "Automatic empty stop is off — the run has to be "
                "stopped manually."
            )
            self.empty_stop_status_label.setText("OFF")
            return

        self.threshold_hint.setText(
            "Stop when capacitance ≤ "
            f"{self.empty_threshold.value():g} V for "
            f"{CAPACITANCE_EMPTY_CONSECUTIVE_SAMPLES} consecutive "
            "samples."
        )
        self.empty_stop_status_label.setText("ARMED")

    # -------------------------------------------------------------
    # View updates
    # -------------------------------------------------------------

    @Slot(object)
    def _apply_state(self, state: ProcessState) -> None:
        self._state = state

        self.state_label.setText(state.name)
        self.state_label.setStyleSheet(
            bold_color_style(process_state_color(state))
        )

        running = state == ProcessState.RUNNING

        self.connect_button.setEnabled(not self._connected)
        self.disconnect_button.setEnabled(
            self._connected and not running
        )
        self.start_button.setEnabled(
            self._connected and not running
        )
        self.stop_button.setEnabled(running)

        self.led_on_button.setEnabled(
            self._connected and not running
        )
        self.led_off_button.setEnabled(
            self._connected and not running
        )

        self.valve_position.setEnabled(not running)
        self.auto_empty_stop.setEnabled(not running)
        self.empty_threshold.setEnabled(not running)

    @Slot(bool)
    def _apply_connection(self, connected: bool) -> None:
        self._connected = connected
        self._apply_state(self._state)

    @Slot(str)
    def _show_failure(self, message: str) -> None:
        self._set_insight(
            "last_error",
            message.splitlines()[-1],
        )
        QMessageBox.critical(self, "Process Control", message)

    @Slot(object)
    def _apply_run_finished(
        self,
        summary: ProcessSummary,
    ) -> None:
        self._set_insight(
            "last_summary",
            describe_summary(summary),
        )

        if "empty" in summary.stop_reason.lower():
            self.empty_stop_status_label.setText("TRIGGERED")

    def clear_charts(self) -> None:
        for chart in self._charts():
            chart.clear()

    @Slot(object, float, float)
    def _apply_measurement(
        self,
        measurement: SystemMeasurement,
        elapsed_seconds: float,
        total_volume_ml: float,
    ) -> None:
        self.update_measurement(
            measurement,
            elapsed_seconds=elapsed_seconds,
            total_volume_ml=total_volume_ml,
        )
        self._update_insights(
            measurement,
            elapsed_seconds,
            total_volume_ml,
        )

    def update_measurement(
        self,
        measurement: SystemMeasurement,
        *,
        elapsed_seconds: float,
        total_volume_ml: float | None = None,
    ) -> None:
        """Feeds one measurement into cards and charts.

        Values are formatted through the same metric definitions the
        charts use, so a number and its plot always share one unit.
        """

        self.flow_card.set_value(
            format_metric("flow", measurement.flow_ml_min)
        )
        self.valve_card.set_value(
            format_metric(
                "valve_position",
                measurement.valve_position_percent,
            )
        )
        self.humidity_card.set_value(
            format_metric(
                "humidity",
                measurement.humidity_percent,
            )
        )
        self.temperature_card.set_value(
            format_metric(
                "temperature",
                measurement.bronkhorst_temperature_c,
            )
        )
        self.alarm_card.set_value(
            "OK"
            if measurement.bronkhorst_alarm_info == 0
            else f"ALARM {measurement.bronkhorst_alarm_info}",
            alarm_color(measurement.bronkhorst_alarm_info),
        )

        if total_volume_ml is not None:
            self.volume_card.set_value(
                format_metric("volume", total_volume_ml)
            )

        self.capacitance_value_label.setText(
            format_metric(
                "capacitance",
                measurement.capacitance_value,
            )
        )
        self.capacitance_state_label.setText(
            measurement.capacitance_state
        )
        self.capacitance_state_label.setStyleSheet(
            bold_color_style(
                capacitance_state_color(
                    measurement.capacitance_state
                )
            )
        )

        self.led_state_label.setText(
            "ON" if measurement.led_on else "OFF"
        )
        self.led_state_label.setStyleSheet(
            bold_color_style(
                "#CA8A04" if measurement.led_on else ""
            )
        )

        self.flow_chart.append_value(
            elapsed_seconds,
            measurement.flow_ml_min,
        )
        self.capacitance_chart.append_value(
            elapsed_seconds,
            measurement.capacitance_value,
        )
        self.humidity_chart.append_value(
            elapsed_seconds,
            measurement.humidity_percent,
        )
        self.valve_chart.append_value(
            elapsed_seconds,
            measurement.valve_position_percent,
        )

    def _update_insights(
        self,
        measurement: SystemMeasurement,
        elapsed_seconds: float,
        total_volume_ml: float,
    ) -> None:
        self._sample_count += 1

        measured_interval = ""
        if self._last_sample_timestamp is not None:
            delta = (
                measurement.timestamp
                - self._last_sample_timestamp
            ).total_seconds()
            measured_interval = f" · measured {delta:.2f} s"
        self._last_sample_timestamp = measurement.timestamp

        self._set_insight(
            "control_mode",
            str(measurement.bronkhorst_control_mode),
        )
        self._set_insight(
            "alarm_info",
            str(measurement.bronkhorst_alarm_info),
        )
        self._set_insight(
            "binary_valve",
            "open" if measurement.binary_valve_open else "closed",
        )
        self._set_insight(
            "capacitance_voltage",
            _format_optional(
                measurement.capacitance_voltage_v,
                "V",
                5,
            ),
        )
        self._set_insight(
            "capacitance_value",
            f"{_format_optional(measurement.capacitance_value, 'V', 3)}"
            f"  ({measurement.capacitance_state})",
        )
        self._set_insight(
            "humidity_voltage",
            _format_optional(
                measurement.humidity_voltage_v,
                "V",
                5,
            ),
        )
        self._set_insight(
            "humidity_percent",
            _format_optional(
                measurement.humidity_percent,
                "%",
                2,
            ),
        )
        self._set_insight(
            "valve_raw",
            f"{measurement.valve_output_raw} "
            f"({measurement.valve_output_raw_percent:.2f} %)",
        )
        self._set_insight(
            "flow_setpoint",
            f"{measurement.flow_setpoint_ml_min:.3f} ml/min",
        )
        self._set_insight(
            "samples",
            str(self._sample_count),
        )
        self._set_insight(
            "interval",
            f"configured {SAMPLE_INTERVAL_SECONDS:.2f} s"
            f"{measured_interval}",
        )
        self._set_insight(
            "elapsed",
            f"{elapsed_seconds:.1f} s",
        )
        self._set_insight(
            "volume",
            f"{total_volume_ml:.2f} ml",
        )

    @Slot(str, str)
    def append_log(
        self,
        message: str,
        level: str = "INFO",
    ) -> None:
        level = level.upper()

        if level == "DEBUG" and not self.show_debug.isChecked():
            return

        timestamp = datetime.now().strftime("%H:%M:%S")
        color = log_level_color(level)

        # Multi-line entries such as tracebacks must keep their line
        # breaks; QTextEdit.append() would otherwise collapse them.
        text = escape(
            f"{timestamp} | {level:<7} | {message}"
        ).replace("\n", "<br>")

        style = "white-space: pre;"
        if color:
            style = f"color:{color};{style}"

        self.log_output.append(
            f'<span style="{style}">{text}</span>'
        )

        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # -------------------------------------------------------------
    # Shutdown
    # -------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.worker.request_stop()

        self.worker_thread.quit()

        if not self.worker_thread.wait(5_000):
            self.worker_thread.terminate()
            self.worker_thread.wait()

        self.worker.shutdown()

        super().closeEvent(event)


def _format_optional(
    value: float | None,
    unit: str,
    decimals: int,
) -> str:
    if value is None:
        return "—"

    return f"{value:.{decimals}f} {unit}"
