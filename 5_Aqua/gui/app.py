from __future__ import annotations

import sys
from collections import deque
from datetime import datetime

from PySide6.QtCharts import (
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class TelemetryCard(QFrame):
    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.title = QLabel(title.upper())
        self.value = QLabel(value)
        self.value.setFont(
            QFont("Segoe UI", 18, QFont.Weight.Bold)
        )
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class LiveLineChart(QChartView):
    def __init__(
        self,
        title: str,
        y_axis_title: str,
        maximum_points: int = 120,
    ) -> None:
        super().__init__()
        self._x = deque(maxlen=maximum_points)
        self._y = deque(maxlen=maximum_points)

        self.series = QLineSeries()
        chart = QChart()
        chart.addSeries(self.series)
        chart.setTitle(title)
        chart.legend().hide()

        self.x_axis = QValueAxis()
        self.y_axis = QValueAxis()
        self.x_axis.setTitleText("Time [s]")
        self.y_axis.setTitleText(y_axis_title)

        chart.addAxis(
            self.x_axis,
            Qt.AlignmentFlag.AlignBottom,
        )
        chart.addAxis(
            self.y_axis,
            Qt.AlignmentFlag.AlignLeft,
        )
        self.series.attachAxis(self.x_axis)
        self.series.attachAxis(self.y_axis)

        self.setChart(chart)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)

    def append_value(
        self,
        elapsed_seconds: float,
        value: float,
    ) -> None:
        self._x.append(elapsed_seconds)
        self._y.append(value)

        self.series.replace(
            [
                QPointF(x, y)
                for x, y in zip(self._x, self._y)
            ]
        )

        self.x_axis.setRange(
            max(0.0, elapsed_seconds - 60.0),
            max(60.0, elapsed_seconds),
        )

        minimum = min(self._y)
        maximum = max(self._y)
        padding = max((maximum - minimum) * 0.15, 1.0)
        self.y_axis.setRange(
            minimum - padding,
            maximum + padding,
        )


class ProcessControlWindow(QMainWindow):
    connect_requested = Signal()
    disconnect_requested = Signal()
    start_requested = Signal(float, str, float)
    stop_requested = Signal()
    led_requested = Signal(bool)
    capacitance_limit_changed = Signal(float, bool, str)

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Process Control")
        self.resize(1350, 850)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

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
        root.addLayout(header)

        columns = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()

        water = QGroupBox("Water Control")
        water_layout = QGridLayout(water)

        self.flow_input = QDoubleSpinBox()
        self.flow_input.setRange(0.1, 200.0)
        self.flow_input.setValue(100.0)
        self.flow_input.setSuffix(" ml/min")

        self.stop_mode = QComboBox()
        self.stop_mode.addItems(
            ("Duration", "Target volume", "Manual / capacitance")
        )

        self.stop_value = QDoubleSpinBox()
        self.stop_value.setRange(1.0, 86_400.0)
        self.stop_value.setValue(60.0)
        self.stop_value.setSuffix(" s")

        self.start_button = QPushButton("Start water")
        self.stop_button = QPushButton("Stop water")

        water_layout.addWidget(QLabel("Target flow"), 0, 0)
        water_layout.addWidget(self.flow_input, 0, 1)
        water_layout.addWidget(QLabel("Stop condition"), 1, 0)
        water_layout.addWidget(self.stop_mode, 1, 1)
        water_layout.addWidget(self.stop_value, 2, 0, 1, 2)
        water_layout.addWidget(self.start_button, 3, 0)
        water_layout.addWidget(self.stop_button, 3, 1)
        left.addWidget(water)

        telemetry = QGroupBox("Live Telemetry")
        telemetry_layout = QGridLayout(telemetry)

        self.flow_card = TelemetryCard("Flow")
        self.volume_card = TelemetryCard("Drained volume")
        self.cap_card = TelemetryCard("Capacitance")
        self.humidity_card = TelemetryCard("Humidity")
        self.temperature_card = TelemetryCard("Temperature")
        self.alarm_card = TelemetryCard("Alarm")

        for index, card in enumerate(
            (
                self.flow_card,
                self.volume_card,
                self.cap_card,
                self.humidity_card,
                self.temperature_card,
                self.alarm_card,
            )
        ):
            telemetry_layout.addWidget(
                card,
                index // 2,
                index % 2,
            )

        left.addWidget(telemetry)

        cap_group = QGroupBox("Capacitance Control")
        cap_layout = QGridLayout(cap_group)
        self.critical_capacitance = QDoubleSpinBox()
        self.critical_capacitance.setDecimals(5)
        self.critical_capacitance.setSuffix(" V")
        self.auto_stop = QCheckBox("Enable automatic stop")
        self.comparison = QComboBox()
        self.comparison.addItems(("Above limit", "Below limit"))
        cap_layout.addWidget(QLabel("Critical value"), 0, 0)
        cap_layout.addWidget(self.critical_capacitance, 0, 1)
        cap_layout.addWidget(self.comparison, 1, 0, 1, 2)
        cap_layout.addWidget(self.auto_stop, 2, 0, 1, 2)
        left.addWidget(cap_group)

        led_group = QGroupBox("LED Control")
        led_layout = QHBoxLayout(led_group)
        self.led_on_button = QPushButton("LED on")
        self.led_off_button = QPushButton("LED off")
        led_layout.addWidget(self.led_on_button)
        led_layout.addWidget(self.led_off_button)
        left.addWidget(led_group)

        charts = QGroupBox("Live Charts")
        charts_layout = QVBoxLayout(charts)
        self.flow_chart = LiveLineChart(
            "Flow",
            "Flow [ml/min]",
        )
        self.cap_chart = LiveLineChart(
            "Capacitance",
            "Voltage [V]",
        )
        charts_layout.addWidget(self.flow_chart)
        charts_layout.addWidget(self.cap_chart)
        right.addWidget(charts)

        logging = QGroupBox("Logging")
        logging_layout = QVBoxLayout(logging)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        logging_layout.addWidget(self.log_output)
        right.addWidget(logging)

        columns.addLayout(left, 5)
        columns.addLayout(right, 7)
        root.addLayout(columns)

        self.connect_button.clicked.connect(
            self.connect_requested.emit
        )
        self.disconnect_button.clicked.connect(
            self.disconnect_requested.emit
        )
        self.start_button.clicked.connect(
            lambda: self.start_requested.emit(
                self.flow_input.value(),
                self.stop_mode.currentText(),
                self.stop_value.value(),
            )
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

    def append_log(
        self,
        message: str,
        level: str = "INFO",
    ) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.append(
            f"{timestamp} | {level:<7} | {message}"
        )


def main() -> int:
    application = QApplication(sys.argv)
    window = ProcessControlWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
