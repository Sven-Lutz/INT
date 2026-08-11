from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PySide6.QtCharts import (
    QChart,
    QChartView,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter

from config import CAPACITANCE_FULL_VALUE


@dataclass(frozen=True)
class MetricConfig:
    """Axis and formatting rules for one physical quantity.

    Every measured quantity has its own unit and its own sensible range.
    A single generic autoscaling rule produced misleading plots — a
    humidity in percent must not share an axis definition with a
    capacitance reading.
    """

    key: str
    label: str
    unit: str
    y_minimum: float
    # ``None`` means the upper bound follows the data.
    y_maximum: float | None
    decimals: int = 2
    # Headroom applied above the observed maximum on dynamic axes.
    dynamic_headroom: float = 1.15
    # Smallest upper bound a dynamic axis may fall back to.
    minimum_dynamic_maximum: float = 1.0

    @property
    def axis_title(self) -> str:
        if not self.unit:
            return self.label
        return f"{self.label} [{self.unit}]"

    def format_value(self, value: float | None) -> str:
        if value is None:
            return "—"

        text = f"{value:.{self.decimals}f}"

        if not self.unit:
            return text

        return f"{text} {self.unit}"

    def axis_range(
        self,
        observed_maximum: float | None,
    ) -> tuple[float, float]:
        if self.y_maximum is not None:
            return self.y_minimum, self.y_maximum

        if observed_maximum is None:
            return (
                self.y_minimum,
                self.y_minimum + self.minimum_dynamic_maximum,
            )

        upper = observed_maximum * self.dynamic_headroom

        return (
            self.y_minimum,
            max(
                upper,
                self.y_minimum + self.minimum_dynamic_maximum,
            ),
        )


# Central metric definition used by both the charts and the telemetry
# cards, so a value and its plot can never disagree about the unit.
METRIC_CONFIG: dict[str, MetricConfig] = {
    "flow": MetricConfig(
        key="flow",
        label="Flow",
        unit="ml/min",
        y_minimum=0.0,
        # Starts at zero and follows the data upwards.
        y_maximum=None,
        decimals=2,
        minimum_dynamic_maximum=10.0,
    ),
    "capacitance": MetricConfig(
        key="capacitance",
        label="Capacitance",
        unit="",
        y_minimum=0.0,
        # Roughly 25 when filled, roughly 0 when empty. Not a percentage.
        y_maximum=CAPACITANCE_FULL_VALUE * 1.2,
        decimals=2,
    ),
    "humidity": MetricConfig(
        key="humidity",
        label="Humidity",
        unit="%",
        y_minimum=0.0,
        y_maximum=100.0,
        decimals=1,
    ),
    "valve_position": MetricConfig(
        key="valve_position",
        label="Valve Position",
        unit="%",
        y_minimum=0.0,
        y_maximum=100.0,
        decimals=1,
    ),
    "volume": MetricConfig(
        key="volume",
        label="Drained Volume",
        unit="ml",
        y_minimum=0.0,
        y_maximum=None,
        decimals=1,
        minimum_dynamic_maximum=10.0,
    ),
    "temperature": MetricConfig(
        key="temperature",
        label="Temperature",
        unit="°C",
        y_minimum=0.0,
        y_maximum=50.0,
        decimals=1,
    ),
}


def metric(key: str) -> MetricConfig:
    try:
        return METRIC_CONFIG[key]
    except KeyError:
        raise KeyError(
            f"Unknown metric {key!r}. Known metrics: "
            f"{sorted(METRIC_CONFIG)}"
        ) from None


def format_metric(key: str, value: float | None) -> str:
    return metric(key).format_value(value)


class LiveLineChart(QChartView):
    """Rolling time-series plot for exactly one metric."""

    def __init__(
        self,
        metric_key: str,
        *,
        window_seconds: float = 60.0,
        maximum_points: int = 600,
    ) -> None:
        super().__init__()

        self.metric = metric(metric_key)
        self.window_seconds = window_seconds

        self._x: deque[float] = deque(maxlen=maximum_points)
        self._y: deque[float] = deque(maxlen=maximum_points)

        self.series = QLineSeries()
        self.series.setName(self.metric.label)

        chart = QChart()
        chart.addSeries(self.series)
        chart.setTitle(self.metric.label)
        chart.legend().hide()

        self.x_axis = QValueAxis()
        self.x_axis.setTitleText("Time [s]")
        self.x_axis.setRange(0.0, window_seconds)

        self.y_axis = QValueAxis()
        self.y_axis.setTitleText(self.metric.axis_title)
        self.y_axis.setLabelFormat(
            f"%.{self.metric.decimals}f"
        )

        minimum, maximum = self.metric.axis_range(None)
        self.y_axis.setRange(minimum, maximum)

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
        self.setMinimumHeight(200)

    def clear(self) -> None:
        self._x.clear()
        self._y.clear()
        self.series.clear()

        self.x_axis.setRange(0.0, self.window_seconds)

        minimum, maximum = self.metric.axis_range(None)
        self.y_axis.setRange(minimum, maximum)

    def append_value(
        self,
        elapsed_seconds: float,
        value: float | None,
    ) -> None:
        if value is None:
            return

        self._x.append(elapsed_seconds)
        self._y.append(value)

        self.series.replace(
            [
                QPointF(x, y)
                for x, y in zip(self._x, self._y)
            ]
        )

        self.x_axis.setRange(
            max(0.0, elapsed_seconds - self.window_seconds),
            max(self.window_seconds, elapsed_seconds),
        )

        minimum, maximum = self.metric.axis_range(max(self._y))
        self.y_axis.setRange(minimum, maximum)
