from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
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
from control.empty_detection import CapacitanceState
from data.models import SystemMeasurement
from gui.charting import LiveLineChart, format_metric


class TelemetryCard(QFrame):
    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        self.title = QLabel(title.upper())
        self.value = QLabel(value)
        self.value.setFont(
            QFont("Segoe UI", 16, QFont.Weight.Bold)
        )
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class ProcessControlWindow(QMainWindow):
    """Operator window for the gravity-fed drain process.

    The valve opening is the only manipulated variable and defaults to
    100 %. Draining ends when the capacitance sensor reports an empty
    vessel or when the operator stops the run.
    """

    connect_requested = Signal()
    disconnect_requested = Signal()

    # valve opening [%], automatic empty stop enabled, empty threshold
    start_requested = Signal(float, bool, float)
    stop_requested = Signal()
    led_requested = Signal(bool)

    # automatic empty stop enabled, empty threshold
    empty_detection_changed = Signal(bool, float)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Process Control")
        self.resize(1440, 880)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())

        # The control panel used to start as a narrow strip. It now
        # opens at roughly one third of the window and cannot be
        # collapsed away entirely.
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes(list(GUI_SPLITTER_SIZES))
        splitter.setCollapsible(0, False)
        splitter.setChildrenCollapsible(False)

        root.addWidget(splitter, 1)

        self._connect_signals()
        self._update_threshold_hint()

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
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disconnect")

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.state_label)
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
            QFont("Segoe UI", 16, QFont.Weight.Bold)
        )

        self.capacitance_state_label = QLabel(
            CapacitanceState.UNKNOWN.value
        )
        self.capacitance_state_label.setFont(
            QFont("Segoe UI", 12, QFont.Weight.Bold)
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

        layout.addWidget(self.led_on_button)
        layout.addWidget(self.led_off_button)

        return group

    def _build_right_panel(self) -> QWidget:
        charts = QGroupBox("Live Charts")
        charts_layout = QGridLayout(charts)

        self.flow_chart = LiveLineChart("flow")
        self.capacitance_chart = LiveLineChart("capacitance")
        self.humidity_chart = LiveLineChart("humidity")
        self.valve_chart = LiveLineChart("valve_position")

        charts_layout.addWidget(self.flow_chart, 0, 0)
        charts_layout.addWidget(self.capacitance_chart, 0, 1)
        charts_layout.addWidget(self.humidity_chart, 1, 0)
        charts_layout.addWidget(self.valve_chart, 1, 1)

        logging_group = QGroupBox("Logging")
        logging_layout = QVBoxLayout(logging_group)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        logging_layout.addWidget(self.log_output)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(charts)
        splitter.addWidget(logging_group)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([660, 220])
        splitter.setChildrenCollapsible(False)

        return splitter

    # -------------------------------------------------------------
    # Signals
    # -------------------------------------------------------------

    def _connect_signals(self) -> None:
        self.connect_button.clicked.connect(
            self.connect_requested.emit
        )
        self.disconnect_button.clicked.connect(
            self.disconnect_requested.emit
        )
        self.start_button.clicked.connect(
            self._emit_start_requested
        )
        self.stop_button.clicked.connect(
            self.stop_requested.emit
        )
        self.led_on_button.clicked.connect(
            lambda: self.led_requested.emit(True)
        )
        self.led_off_button.clicked.connect(
            lambda: self.led_requested.emit(False)
        )
        self.auto_empty_stop.toggled.connect(
            self._emit_empty_detection_changed
        )
        self.empty_threshold.valueChanged.connect(
            self._emit_empty_detection_changed
        )

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

    def set_process_state(self, state_name: str) -> None:
        self.state_label.setText(state_name)

    def mark_empty_stop_triggered(self) -> None:
        self.empty_stop_status_label.setText("TRIGGERED")

    def clear_charts(self) -> None:
        for chart in (
            self.flow_chart,
            self.capacitance_chart,
            self.humidity_chart,
            self.valve_chart,
        ):
            chart.clear()

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
            else f"ALARM {measurement.bronkhorst_alarm_info}"
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

    def append_log(
        self,
        message: str,
        level: str = "INFO",
    ) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(
            f"{timestamp} | {level:<7} | {message}"
        )
