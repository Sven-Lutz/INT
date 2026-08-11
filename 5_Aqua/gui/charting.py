from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from PySide6.QtCharts import (
    QChart,
    QChartView,
    QLineSeries,
    QScatterSeries,
    QValueAxis,
)
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from config import CAPACITANCE_FULL_VALUE


# Selectable time windows for the live plots. ``None`` shows the whole
# run instead of a rolling window.
TIME_WINDOWS: tuple[tuple[str, float | None], ...] = (
    ("10 s", 10.0),
    ("30 s", 30.0),
    ("1 min", 60.0),
    ("2 min", 120.0),
    ("5 min", 300.0),
    ("10 min", 600.0),
    ("Full run", None),
)

DEFAULT_TIME_WINDOW_INDEX = 2


@dataclass(frozen=True)
class MetricConfig:
    """Axis and formatting rules for one physical quantity.

    Every measured quantity has its own unit and its own sensible range.
    A single generic autoscaling rule produced misleading plots — a
    humidity in percent must not share an axis definition with a
    capacitance reading in volts.
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
        unit="V",
        y_minimum=0.0,
        # Roughly 25 V when filled, roughly 0 V when empty.
        # A voltage, not a percentage — the axis stays in volts.
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
    """Rolling time-series plot for exactly one metric.

    Interaction:
      * click a point to read off its exact value and timestamp
      * drag to zoom into a region
      * double-click to reset the zoom and resume following live data
    """

    point_selected = Signal(float, float)

    # A press/release pair within this many pixels counts as a click
    # rather than a zoom drag.
    CLICK_TOLERANCE_PX = 4

    def __init__(
        self,
        metric_key: str,
        *,
        window_seconds: float | None = 60.0,
        maximum_points: int = 20_000,
    ) -> None:
        super().__init__()

        self.metric = metric(metric_key)
        self.window_seconds = window_seconds

        # The full run is kept so a longer window can look back.
        self._x: deque[float] = deque(maxlen=maximum_points)
        self._y: deque[float] = deque(maxlen=maximum_points)

        self._follow = True
        self._press_position = None

        self.series = QLineSeries()
        self.series.setName(self.metric.label)

        self.marker = QScatterSeries()
        self.marker.setMarkerSize(11.0)
        self.marker.setName("Selection")

        chart = QChart()
        chart.addSeries(self.series)
        chart.addSeries(self.marker)
        chart.setTitle(self.metric.label)
        chart.legend().hide()

        self.x_axis = QValueAxis()
        self.x_axis.setTitleText("Time [s]")
        self.x_axis.setRange(0.0, window_seconds or 60.0)

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

        for series in (self.series, self.marker):
            series.attachAxis(self.x_axis)
            series.attachAxis(self.y_axis)

        self.setChart(chart)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRubberBand(
            QChartView.RubberBand.RectangleRubberBand
        )
        self.setMinimumHeight(190)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip(
            "Click a point to read its value, drag to zoom, "
            "double-click to reset."
        )

    # -------------------------------------------------------------
    # Data
    # -------------------------------------------------------------

    @property
    def is_following(self) -> bool:
        return self._follow

    def clear(self) -> None:
        self._x.clear()
        self._y.clear()
        self.series.clear()
        self.marker.clear()

        self._follow = True
        self.chart().zoomReset()

        self.x_axis.setRange(
            0.0,
            self.window_seconds or 60.0,
        )

        minimum, maximum = self.metric.axis_range(None)
        self.y_axis.setRange(minimum, maximum)

    def set_window_seconds(
        self,
        window_seconds: float | None,
    ) -> None:
        self.window_seconds = window_seconds
        self._follow = True
        self.chart().zoomReset()
        self._refresh_axes()

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

        self._refresh_axes()

    def _visible_points(
        self,
    ) -> tuple[list[float], list[float]]:
        if self.window_seconds is None or not self._x:
            return list(self._x), list(self._y)

        lower = self._x[-1] - self.window_seconds

        pairs = [
            (x, y)
            for x, y in zip(self._x, self._y)
            if x >= lower
        ]

        if not pairs:
            return list(self._x), list(self._y)

        return (
            [x for x, _ in pairs],
            [y for _, y in pairs],
        )

    def _refresh_axes(self) -> None:
        # While the operator is zoomed in or inspecting a point, the
        # axes must stay where they were put.
        if not self._follow or not self._x:
            return

        latest = self._x[-1]

        if self.window_seconds is None:
            self.x_axis.setRange(0.0, max(1.0, latest))
        else:
            self.x_axis.setRange(
                max(0.0, latest - self.window_seconds),
                max(self.window_seconds, latest),
            )

        _, visible_y = self._visible_points()

        minimum, maximum = self.metric.axis_range(
            max(visible_y) if visible_y else None
        )
        self.y_axis.setRange(minimum, maximum)

    # -------------------------------------------------------------
    # Interaction
    # -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        self._press_position = event.position()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        press = self._press_position
        self._press_position = None

        if press is not None:
            travelled = (
                event.position() - press
            ).manhattanLength()

            if travelled <= self.CLICK_TOLERANCE_PX:
                # A click inspects a point instead of zooming into a
                # zero-width rectangle.
                self._select_nearest_point(event.position())
                return

            # A real drag zooms, which also stops following live data.
            self._follow = False

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.chart().zoomReset()
        self.marker.clear()
        self._follow = True
        self._refresh_axes()
        super().mouseDoubleClickEvent(event)

    def _select_nearest_point(self, position) -> None:
        if not self._x:
            return

        scene_position = self.mapToScene(position.toPoint())
        chart_position = self.chart().mapFromScene(
            scene_position
        )
        value = self.chart().mapToValue(chart_position)

        span = (
            self.x_axis.max() - self.x_axis.min()
        ) or 1.0

        candidates = [
            (abs(x - value.x()), x, y)
            for x, y in zip(self._x, self._y)
            if self.x_axis.min() <= x <= self.x_axis.max()
        ]

        if not candidates:
            return

        distance, x, y = min(candidates)

        # Ignore clicks far away from any recorded sample.
        if distance > span * 0.05:
            return

        self.marker.replace([QPointF(x, y)])
        self.point_selected.emit(x, y)


class ChartPanel(QWidget):
    """A live chart plus the readout of the point last clicked."""

    def __init__(self, metric_key: str) -> None:
        super().__init__()

        self.chart = LiveLineChart(metric_key)
        self.metric = self.chart.metric

        self.readout = QLabel(
            "Click a point to inspect it."
        )
        self.readout.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.chart, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(6, 0, 6, 0)
        footer.addWidget(self.readout)
        footer.addStretch()
        layout.addLayout(footer)

        self.chart.point_selected.connect(
            self._show_selected_point
        )

    def _show_selected_point(
        self,
        elapsed_seconds: float,
        value: float,
    ) -> None:
        self.readout.setEnabled(True)
        self.readout.setText(
            f"t = {elapsed_seconds:.1f} s    "
            f"{self.metric.label} = "
            f"{self.metric.format_value(value)}"
        )

    def set_window_seconds(
        self,
        window_seconds: float | None,
    ) -> None:
        self.chart.set_window_seconds(window_seconds)

    def append_value(
        self,
        elapsed_seconds: float,
        value: float | None,
    ) -> None:
        self.chart.append_value(elapsed_seconds, value)

    def clear(self) -> None:
        self.chart.clear()
        self.readout.setEnabled(False)
        self.readout.setText("Click a point to inspect it.")
