from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QToolTip

from config import CAPACITANCE_FULL_VALUE


@dataclass(frozen=True)
class MetricConfig:
    """Display rules for one physical quantity."""

    key: str
    label: str
    unit: str
    color: str
    y_minimum: float
    y_maximum: float | None
    decimals: int = 2
    dynamic_headroom: float = 1.15
    minimum_dynamic_maximum: float = 1.0

    @property
    def axis_title(self) -> str:
        return (
            self.label
            if not self.unit
            else f"{self.label} [{self.unit}]"
        )

    def format_value(self, value: float | None) -> str:
        if value is None:
            return "—"

        text = f"{value:.{self.decimals}f}"
        return text if not self.unit else f"{text} {self.unit}"

    def axis_range(
        self,
        observed_maximum: float | None,
    ) -> tuple[float, float]:
        if self.y_maximum is not None:
            return self.y_minimum, self.y_maximum

        if observed_maximum is None:
            maximum = self.y_minimum + self.minimum_dynamic_maximum
            return self.y_minimum, maximum

        maximum = max(
            observed_maximum * self.dynamic_headroom,
            self.y_minimum + self.minimum_dynamic_maximum,
        )
        return self.y_minimum, maximum


METRIC_CONFIG: dict[str, MetricConfig] = {
    "flow": MetricConfig(
        key="flow",
        label="Flow",
        unit="ml/min",
        color="#65d9ff",
        y_minimum=0.0,
        y_maximum=None,
        decimals=2,
        minimum_dynamic_maximum=10.0,
    ),
    "capacitance": MetricConfig(
        key="capacitance",
        label="Capacitance",
        unit="scaled",
        color="#b49cff",
        y_minimum=0.0,
        y_maximum=CAPACITANCE_FULL_VALUE * 1.2,
        decimals=2,
    ),
    "humidity": MetricConfig(
        key="humidity",
        label="Humidity",
        unit="%",
        color="#72e0a1",
        y_minimum=0.0,
        y_maximum=100.0,
        decimals=1,
    ),
    "valve_position": MetricConfig(
        key="valve_position",
        label="Valve Position",
        unit="%",
        color="#ffc96b",
        y_minimum=0.0,
        y_maximum=100.0,
        decimals=1,
    ),
    "volume": MetricConfig(
        key="volume",
        label="Drained Volume",
        unit="ml",
        color="#ff9f73",
        y_minimum=0.0,
        y_maximum=None,
        decimals=1,
        minimum_dynamic_maximum=10.0,
    ),
    "temperature": MetricConfig(
        key="temperature",
        label="Temperature",
        unit="°C",
        color="#f48fb1",
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


class PersistentMetricChart(QChartView):
    """Interactive chart retaining the run history in memory.

    The default view follows the last ``window_seconds``. Users can
    switch to the complete run history, hover samples for exact values,
    and click the chart to focus it in the GUI.
    """

    activated = Signal(str)

    def __init__(
        self,
        metric_key: str,
        *,
        window_seconds: float = 60.0,
        maximum_points: int = 20_000,
    ) -> None:
        super().__init__()

        self.metric_key = metric_key
        self.metric_config = metric(metric_key)
        self.window_seconds = window_seconds
        self._show_full_history = False
        self._press_position: QPoint | None = None

        self._x: deque[float] = deque(maxlen=maximum_points)
        self._y: deque[float] = deque(maxlen=maximum_points)

        self.series = QLineSeries()
        self.series.setName(self.metric_config.label)
        self.series.setPen(
            QPen(QColor(self.metric_config.color), 2.0)
        )
        self.series.hovered.connect(self._show_hover_tooltip)

        chart = QChart()
        chart.addSeries(self.series)
        chart.setTitle(self.metric_config.label)
        chart.legend().hide()
        chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        chart.setBackgroundBrush(QColor("#0c141e"))
        chart.setPlotAreaBackgroundVisible(True)
        chart.setPlotAreaBackgroundBrush(QColor("#0a1119"))
        chart.setTitleBrush(QColor("#dce7f2"))

        self.x_axis = QValueAxis()
        self.x_axis.setTitleText("Time [s]")
        self.x_axis.setRange(0.0, window_seconds)
        self.x_axis.setLabelFormat("%.0f")
        self.x_axis.setTickCount(7)

        self.y_axis = QValueAxis()
        self.y_axis.setTitleText(self.metric_config.axis_title)
        self.y_axis.setLabelFormat(
            f"%.{self.metric_config.decimals}f"
        )
        self.y_axis.setTickCount(6)

        for axis in (self.x_axis, self.y_axis):
            axis.setLabelsColor(QColor("#8ea2b5"))
            axis.setTitleBrush(QColor("#8ea2b5"))
            axis.setGridLineColor(QColor("#223141"))
            axis.setLinePenColor(QColor("#34495d"))

        minimum, maximum = self.metric_config.axis_range(None)
        self.y_axis.setRange(minimum, maximum)

        chart.addAxis(self.x_axis, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(self.y_axis, Qt.AlignmentFlag.AlignLeft)
        self.series.attachAxis(self.x_axis)
        self.series.attachAxis(self.y_axis)

        self.setChart(chart)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            "Click to focus • hover the curve for an exact value"
        )

    @property
    def point_count(self) -> int:
        return len(self._x)

    @property
    def latest_value(self) -> float | None:
        return self._y[-1] if self._y else None

    def clear(self) -> None:
        self._x.clear()
        self._y.clear()
        self.series.clear()
        self.x_axis.setRange(0.0, self.window_seconds)

        minimum, maximum = self.metric_config.axis_range(None)
        self.y_axis.setRange(minimum, maximum)

    def set_full_history(self, enabled: bool) -> None:
        self._show_full_history = enabled
        self._update_axes()

    def append_value(
        self,
        elapsed_seconds: float,
        value: float | None,
    ) -> None:
        if value is None:
            return

        self._x.append(float(elapsed_seconds))
        self._y.append(float(value))
        self.series.replace(
            [
                QPointF(x, y)
                for x, y in zip(self._x, self._y)
            ]
        )
        self._update_axes()

    def _update_axes(self) -> None:
        if not self._x:
            return

        newest = self._x[-1]

        if self._show_full_history:
            left = min(0.0, self._x[0])
            right = max(self.window_seconds, newest)
            visible_y = list(self._y)
        else:
            left = max(0.0, newest - self.window_seconds)
            right = max(self.window_seconds, newest)
            visible_y = [
                y
                for x, y in zip(self._x, self._y)
                if x >= left
            ]

        if right <= left:
            right = left + self.window_seconds

        self.x_axis.setRange(left, right)

        observed_maximum = (
            max(visible_y)
            if visible_y
            else None
        )
        minimum, maximum = self.metric_config.axis_range(
            observed_maximum
        )
        self.y_axis.setRange(minimum, maximum)

    def _show_hover_tooltip(
        self,
        point: QPointF,
        hovered: bool,
    ) -> None:
        if not hovered:
            QToolTip.hideText()
            return

        QToolTip.showText(
            QCursor.pos(),
            (
                f"{self.metric_config.label}\n"
                f"{self.metric_config.format_value(point.y())}\n"
                f"t = {point.x():.1f} s"
            ),
            self,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        super().mouseReleaseEvent(event)

        if (
            event.button() != Qt.MouseButton.LeftButton
            or self._press_position is None
        ):
            return

        released = event.position().toPoint()
        movement = (released - self._press_position).manhattanLength()
        self._press_position = None

        if movement <= 5:
            self.activated.emit(self.metric_key)


# Backward-compatible name used by the current GUI and external imports.
LiveLineChart = PersistentMetricChart
