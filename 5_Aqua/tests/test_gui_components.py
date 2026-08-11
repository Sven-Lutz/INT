from __future__ import annotations

import os
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QToolTip

from data.models import SystemMeasurement
from gui.charting import PersistentMetricChart
from gui.logging_bridge import configure_runtime_logging
from gui.main_window import CHART_ORDER, ProcessControlWindow
from gui.runtime import ProcessRuntime
from tests.test_controller_reuse import build_fake_controller


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
    assert chart.chart().backgroundBrush().color().name() == "#ffffff"
    assert chart.chart().plotAreaBackgroundBrush().color().name() == "#ffffff"

    chart._show_hover_tooltip(QPointF(1.0, 2.5), True)
    assert "2.50 ml/min" in QToolTip.text()
    assert "t = 1.0 s" in QToolTip.text()
    chart._show_hover_tooltip(QPointF(), False)

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
    assert window.windowTitle() == "Process Control"
    assert set(window.metric_charts) == set(CHART_ORDER)
    assert set(window.metric_toggle_buttons) == set(CHART_ORDER)
    assert " V" not in window.telemetry_cards["capacitance"].value_label.text()
    assert "raw: 4.200 V" in window.telemetry_cards[
        "capacitance"
    ].detail_label.text()
    assert "50.0 %" in window.telemetry_cards["humidity"].value_label.text()
    assert window.led_state_label.text() == "LED: OFF"
    assert window.telemetry_status_label.text() == "●"
    assert window.telemetry_status_label.property("status") == "live"
    assert "Telemetry current" in window.telemetry_status_label.toolTip()

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

    window.focus_metric_chart("temperature")
    QTest.mouseClick(window.overview_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window._focused_metric is None

    window.metric_toggle_buttons["volume"].setChecked(True)
    app.processEvents()
    assert window.metric_charts["volume"].isVisible()
    window.full_history_check.setChecked(True)
    assert all(
        chart._show_full_history
        for chart in window.metric_charts.values()
    )

    window._last_telemetry_monotonic = time.monotonic() - 3.0
    window._update_freshness()
    assert "STALE" in window.telemetry_status_label.text()
    assert window.telemetry_status_label.property("status") == "stale"

    window.set_process_state("READY")
    assert window.state_label.text() == "State: READY"
    assert not window.connect_button.isEnabled()
    assert window.disconnect_button.isEnabled()
    assert not window.stop_button.isEnabled()
    QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    assert window._start_pending
    assert not window.start_button.isEnabled()
    window.set_start_pending(False)
    assert window.start_button.isEnabled()
    window.close()


def test_light_ui_preserves_operator_diagnostics_and_controls() -> None:
    app = application()
    window = ProcessControlWindow()
    window.show()
    app.processEvents()

    visible_labels = [label.text() for label in window.findChildren(QLabel)]
    assert all("AQUA" not in text.upper() for text in visible_labels)
    assert "LIVE" not in visible_labels
    assert window.led_on_button.objectName() == "ledOnButton"
    assert window.led_off_button.objectName() == "ledOffButton"
    assert window.start_button.text() == "Start draining"
    assert window.stop_button.text() == "STOP"

    led_requests: list[bool] = []
    stop_requests: list[bool] = []
    window.led_requested.connect(led_requests.append)
    window.stop_requested.connect(lambda: stop_requests.append(True))
    window.set_process_state("READY")
    QTest.mouseClick(window.led_on_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.led_off_button, Qt.MouseButton.LeftButton)
    assert led_requests == [True, False]

    window.set_process_state("RUNNING")
    assert not window.start_button.isEnabled()
    assert not window.disconnect_button.isEnabled()
    assert window.stop_button.isEnabled()
    assert not window.led_on_button.isEnabled()
    assert not window.led_off_button.isEnabled()
    QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    assert stop_requests == [True]

    tabs = window.findChild(QTabWidget)
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Operator Log",
        "Developer Insights",
    ]
    assert window.log_output.document().maximumBlockCount() == 1200
    assert [
        window.log_level_filter.itemText(index)
        for index in range(window.log_level_filter.count())
    ] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    window.log_level_filter.setCurrentText("DEBUG")
    window.append_log("diagnostic detail", "DEBUG", source="aqua.test")
    window.append_log("operator fault", "ERROR", source="aqua.test")
    assert "diagnostic detail" in window.log_output.toPlainText()
    assert "operator fault" in window.log_output.toPlainText()
    window.log_level_filter.setCurrentText("ERROR")
    assert "diagnostic detail" not in window.log_output.toPlainText()
    assert "operator fault" in window.log_output.toPlainText()

    window.update_developer_snapshot(
        {"measurement": {"capacitance_value": 20.0}}
    )
    QTest.mouseClick(
        window.copy_developer_button,
        Qt.MouseButton.LeftButton,
    )
    assert "capacitance_value" in QApplication.clipboard().text()
    assert window.developer_output.isReadOnly()
    window.close()


def test_runtime_coalesces_duplicate_start_but_allows_later_run() -> None:
    app = application()
    with TemporaryDirectory() as temporary_directory:
        controller, analog = build_fake_controller(Path(temporary_directory))
        controller.connect()
        runtime = ProcessRuntime(controller)
        failures: list[tuple[str, str]] = []
        runtime.operation_failed.connect(
            lambda title, message: failures.append((title, message))
        )
        QTest.qWait(20)

        runtime.start_process(100.0, True, 2.0)
        runtime.start_process(100.0, True, 2.0)

        deadline = time.monotonic() + 2.0
        while runtime._start_in_flight and time.monotonic() < deadline:
            QTest.qWait(10)
            app.processEvents()

        assert not runtime._start_in_flight
        assert analog.calls == 1
        assert failures == [
            ("Start blocked", "A start request is already pending or running.")
        ]

        runtime.start_process(100.0, True, 2.0)
        deadline = time.monotonic() + 2.0
        while runtime._start_in_flight and time.monotonic() < deadline:
            QTest.qWait(10)
            app.processEvents()

        assert not runtime._start_in_flight
        assert analog.calls == 2
        runtime.shutdown()


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
    test_light_ui_preserves_operator_diagnostics_and_controls()
    test_runtime_coalesces_duplicate_start_but_allows_later_run()
    test_runtime_logging_is_rotating_bounded_and_not_duplicated()
    print("GUI chart interactions: OK")
