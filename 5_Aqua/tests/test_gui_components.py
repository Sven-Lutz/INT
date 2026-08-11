from __future__ import annotations

import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from data.models import SystemMeasurement
from gui.charting import PersistentMetricChart
from gui.logging_bridge import configure_runtime_logging
from gui.main_window import ProcessControlWindow


def application() -> QApplication:
    return QApplication.instance() or QApplication([])


def sample_measurement() -> SystemMeasurement:
    return SystemMeasurement(
        timestamp=datetime.now(),
        flow_ml_min=12.5,
        flow_setpoint_ml_min=0.0,
        bronkhorst_temperature_c=22.0,
        bronkhorst_alarm_info=0,
        bronkhorst_control_mode=20,
        valve_output_raw=8_388_607,
        valve_output_raw_percent=50.0,
        valve_position_percent=100.0,
        capacitance_voltage_v=4.2,
        capacitance_value=20.0,
        capacitance_state="DRAINING",
        humidity_voltage_v=5.0,
        humidity_percent=50.0,
        binary_valve_open=True,
        led_on=False,
    )


def test_chart_click_history_and_exact_sample_storage() -> None:
    app = application()
    chart = PersistentMetricChart("flow", window_seconds=10.0)
    activated: list[str] = []
    chart.activated.connect(activated.append)
    chart.resize(500, 300)
    chart.show()
    app.processEvents()

    chart.append_value(1.0, 2.5)
    chart.append_value(20.0, 3.75)

    assert chart.point_count == 2
    assert chart.latest_value == 3.75
    assert chart.series.at(1).x() == 20.0
    assert chart.series.at(1).y() == 3.75
    assert chart.x_axis.min() == 10.0

    chart.set_full_history(True)
    assert chart.x_axis.min() == 0.0
    assert chart.x_axis.max() == 20.0

    QTest.mouseClick(
        chart.viewport(),
        Qt.MouseButton.LeftButton,
        pos=chart.viewport().rect().center(),
    )
    app.processEvents()
    assert activated == ["flow"]
    chart.close()


def test_window_telemetry_focus_and_escape_overview() -> None:
    app = application()
    window = ProcessControlWindow()
    window.show()
    app.processEvents()

    measurement = sample_measurement()
    window.update_measurement(
        measurement,
        elapsed_seconds=5.0,
        total_volume_ml=1.25,
    )

    assert window.metric_charts["flow"].latest_value == measurement.flow_ml_min
    assert window.metric_charts["capacitance"].latest_value == 20.0
    assert "raw: 4.200 V" in window.telemetry_cards[
        "capacitance"
    ].detail_label.text()
    assert "50.0 %" in window.telemetry_cards["humidity"].value_label.text()

    QTest.mouseClick(
        window.telemetry_cards["temperature"],
        Qt.MouseButton.LeftButton,
    )
    app.processEvents()
    assert window._focused_metric == "temperature"
    assert window.metric_charts["temperature"].isVisible()
    assert not window.metric_charts["flow"].isVisible()

    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert window._focused_metric is None
    assert window.metric_charts["flow"].isVisible()
    window.close()


def test_runtime_logging_is_rotating_bounded_and_not_duplicated() -> None:
    app = application()
    with TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "aqua_runtime.log"
        logger, _ = configure_runtime_logging(path)
        logger, qt_handler = configure_runtime_logging(path)
        received: list[tuple[str, str, str]] = []
        qt_handler.emitter.record_received.connect(
            lambda level, source, message: received.append(
                (level, source, message)
            )
        )

        logger.info("single lifecycle message")
        app.processEvents()

        rotating_handlers = [
            handler
            for handler in logger.handlers
            if isinstance(handler, RotatingFileHandler)
        ]
        assert len(logger.handlers) == 3
        assert len(rotating_handlers) == 1
        assert rotating_handlers[0].maxBytes == 2_000_000
        assert rotating_handlers[0].backupCount == 5
        assert received == [
            ("INFO", "aqua", "single lifecycle message")
        ]
        assert "single lifecycle message" in path.read_text(encoding="utf-8")

        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


if __name__ == "__main__":
    test_chart_click_history_and_exact_sample_storage()
    test_window_telemetry_focus_and_escape_overview()
    test_runtime_logging_is_rotating_bounded_and_not_duplicated()
    print("GUI chart interactions: OK")
