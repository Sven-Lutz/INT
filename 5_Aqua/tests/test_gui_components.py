from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLabel,
    QTabWidget,
    QToolTip,
)

from config import (
    CAPACITANCE_EMPTY_THRESHOLD,
    DEFAULT_FLOW_SETPOINT_ML_MIN,
    DEFAULT_TARGET_VOLUME_ML,
    DEFAULT_VALVE_POSITION_PERCENT,
)
from control.run_configuration import ControlMode, RunConfiguration
from data.models import SystemMeasurement
from gui.charting import PersistentMetricChart
from gui.logging_bridge import configure_runtime_logging
from gui.main_window import (
    CHART_ORDER,
    CHART_TIME_WINDOWS,
    ProcessControlWindow,
)
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


def sample_developer_snapshot(
    *,
    process_state: str = "READY",
    measurement: SystemMeasurement | None = None,
) -> dict[str, object]:
    current_measurement = measurement or sample_measurement()
    lucid_status = "DISCONNECTED" if process_state == "DISCONNECTED" else "OK"
    return {
        "process_state": process_state,
        "sample_interval_seconds": 0.5,
        "repository_measurements": 12,
        "repository_events": 3,
        "logging_run_active": False,
        "measurement_csv": "C:/data/measurements.csv",
        "event_csv": "C:/data/events.csv",
        "summary_csv": "C:/data/summaries.csv",
        "runtime_log": "C:/data/aqua_runtime.log",
        "run_configuration": {
            "control_mode": "VALVE_POSITION",
            "run_volume_ml": 175.0,
            "session_total_volume_ml": 425.0,
            "pending_live_commands": 0,
        },
        "lucid_digital": {
            "port": "COM4",
            "status": lucid_status,
            "preflight": "PASS",
            "preflight_error": None,
            "last_communication_error": None,
            "channels": {
                "binary_valve": {
                    "channel": 0,
                    "expected_mode": "reflect",
                    "reported_mode": "reflect",
                    "inverted": False,
                    "actual_logical_state": 0,
                    "cached_application_state": 0,
                    "internal_output_value": 1,
                    "optional_diagnostic_error": None,
                },
                "led": {
                    "channel": 1,
                    "expected_mode": "reflect",
                    "reported_mode": "reflect",
                    "inverted": False,
                    "actual_logical_state": 1,
                    "cached_application_state": 1,
                    "internal_output_value": None,
                    "optional_diagnostic_error": (
                        "Unavailable / transient communication error"
                    ),
                },
            },
        },
        "empty_detector": (
            "Capacitance DRAINING "
            "(0/3 samples at or below 5 scaled units)"
        ),
        "empty_detector_details": {
            "state": "DRAINING",
            "enabled": True,
            "empty_threshold": 5.0,
            "consecutive_count": 0,
            "required_consecutive_count": 3,
        },
        "measurement": asdict(current_measurement),
    }


def chart_grid_position(
    window: ProcessControlWindow,
    metric_key: str,
) -> tuple[int, int, int, int]:
    index = window.chart_layout.indexOf(window.metric_charts[metric_key])
    return window.chart_layout.getItemPosition(index)


def developer_value(
    window: ProcessControlWindow,
    section: str,
    field: str,
) -> str:
    return window._developer_items[(section, field)].text(1)


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
    assert chart.chart().title() == "Flow [ml/min]"
    assert chart.y_axis.titleText() == "[ml/min]"
    assert chart.minimumHeight() == 130

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


def test_six_chart_overview_focus_and_custom_toggles() -> None:
    app = application()
    window = ProcessControlWindow()
    window.set_process_state("READY")
    window.show()
    app.processEvents()

    assert all(
        button.isChecked()
        for button in window.metric_toggle_buttons.values()
    )
    assert all(chart.isVisible() for chart in window.metric_charts.values())
    assert {
        key: chart_grid_position(window, key)
        for key in CHART_ORDER
    } == {
        "flow": (0, 0, 1, 1),
        "capacitance": (0, 1, 1, 1),
        "humidity": (1, 0, 1, 1),
        "valve_position": (1, 1, 1, 1),
        "volume": (2, 0, 1, 1),
        "temperature": (2, 1, 1, 1),
    }

    window.update_measurement(
        sample_measurement(),
        elapsed_seconds=1.0,
        total_volume_ml=0.2,
    )
    history_counts = {
        key: chart.point_count
        for key, chart in window.metric_charts.items()
    }
    assert all(count == 1 for count in history_counts.values())

    window.metric_toggle_buttons["temperature"].setChecked(False)
    app.processEvents()
    assert not window.metric_charts["temperature"].isVisible()
    assert all(
        window.metric_charts[key].isVisible()
        for key in CHART_ORDER
        if key != "temperature"
    )

    window.focus_metric_chart("volume")
    app.processEvents()
    assert window._focused_metric == "volume"
    assert window.metric_charts["volume"].isVisible()
    assert all(
        not chart.isVisible()
        for key, chart in window.metric_charts.items()
        if key != "volume"
    )
    window.metric_toggle_buttons["humidity"].setChecked(False)
    app.processEvents()
    assert window._focused_metric == "volume"
    assert window.metric_charts["volume"].isVisible()

    QTest.mouseClick(window.overview_button, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert window._focused_metric is None
    assert not window.metric_charts["temperature"].isVisible()
    assert not window.metric_charts["humidity"].isVisible()
    assert chart_grid_position(window, "volume") == (1, 1, 1, 1)

    window.focus_metric_chart("flow")
    QTest.keyClick(window, Qt.Key.Key_Escape)
    app.processEvents()
    assert window._focused_metric is None
    assert not window.metric_toggle_buttons["temperature"].isChecked()
    assert not window.metric_toggle_buttons["humidity"].isChecked()
    assert not window.metric_charts["temperature"].isVisible()
    assert not window.metric_charts["humidity"].isVisible()
    assert {
        key: chart.point_count
        for key, chart in window.metric_charts.items()
    } == history_counts
    window.close()


def test_window_telemetry_focus_and_escape_overview() -> None:
    app = application()
    window = ProcessControlWindow()
    window.set_process_state("READY")
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
    assert window.telemetry_context_label.text() == "Current sample"

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

    assert window.metric_charts["volume"].isVisible()
    window.chart_window_selector.setCurrentText("Full session")
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


def test_numeric_inputs_preserve_ranges_steps_and_process_state() -> None:
    window = ProcessControlWindow()

    assert window.valve_position.minimum() == 0.0
    assert window.valve_position.maximum() == 100.0
    assert window.valve_position.value() == DEFAULT_VALVE_POSITION_PERCENT
    assert window.valve_position.singleStep() == 5.0
    assert window.valve_position.suffix() == " %"
    assert window.valve_position.buttonSymbols() == (
        QAbstractSpinBox.ButtonSymbols.UpDownArrows
    )

    assert window.empty_threshold.minimum() == 0.0
    assert window.empty_threshold.maximum() == 100.0
    assert window.empty_threshold.value() == CAPACITANCE_EMPTY_THRESHOLD
    assert window.empty_threshold.singleStep() == 0.25
    assert window.empty_threshold.suffix() == ""
    assert window.empty_threshold.buttonSymbols() == (
        QAbstractSpinBox.ButtonSymbols.UpDownArrows
    )

    window.set_process_state("READY")
    assert window.valve_position.isEnabled()
    assert window.empty_threshold.isEnabled()
    window.valve_position.stepDown()
    assert window.valve_position.value() == 95.0
    window.valve_position.stepUp()
    assert window.valve_position.value() == 100.0
    window.empty_threshold.stepUp()
    assert window.empty_threshold.value() == 5.25
    window.empty_threshold.stepDown()
    assert window.empty_threshold.value() == 5.0

    window.set_process_state("RUNNING")
    assert window.valve_position.isEnabled()
    assert not window.empty_threshold.isEnabled()
    window.set_process_state("STOPPED")
    assert window.valve_position.isEnabled()
    assert window.empty_threshold.isEnabled()
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
    assert window.led_on_button.isEnabled()
    assert window.led_off_button.isEnabled()
    QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
    assert stop_requests == [True]

    tabs = window.findChild(QTabWidget)
    assert tabs is not None
    assert [tabs.tabText(index) for index in range(tabs.count())] == [
        "Operator Log",
        "Developer Insights",
    ]
    assert [
        window.log_output.horizontalHeaderItem(column).text()
        for column in range(window.log_output.columnCount())
    ] == ["Time", "Level", "Source", "Message"]
    assert [
        window.log_level_filter.itemText(index)
        for index in range(window.log_level_filter.count())
    ] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    window.log_level_filter.setCurrentText("DEBUG")
    window.append_log("diagnostic detail", "DEBUG", source="aqua.test")
    window.append_log(
        "operator fault\nTraceback: sample detail",
        "ERROR",
        source="aqua.test",
    )
    assert window.log_output.rowCount() == 2
    assert window.log_output.item(0, 3).text() == "diagnostic detail"
    assert window.log_output.item(1, 0).text()
    assert window.log_output.item(1, 1).text() == "ERROR"
    assert window.log_output.item(1, 2).text() == "aqua.test"
    assert window.log_output.item(1, 3).text() == "operator fault"
    window.log_output.selectRow(1)
    app.processEvents()
    assert "Traceback: sample detail" in window.log_detail.toPlainText()

    window.log_level_filter.setCurrentText("ERROR")
    assert window.log_output.rowCount() == 1
    assert window.log_output.item(0, 3).text() == "operator fault"
    window.log_search.setText("not present")
    assert window.log_output.rowCount() == 0
    window.log_search.setText("fault")
    assert window.log_output.rowCount() == 1

    window.log_search.clear()
    window.log_level_filter.setCurrentText("DEBUG")
    window._log_entries.extend(
        ("12:00:00", "INFO", "aqua.bound", f"message {index}")
        for index in range(1600)
    )
    window._render_log()
    assert len(window._log_entries) == 1500
    assert window.log_output.rowCount() == 1500

    measurement = sample_measurement()
    window.set_process_state("READY")
    window.update_measurement(
        measurement,
        elapsed_seconds=1.0,
        total_volume_ml=0.2,
    )
    window.set_process_state("DISCONNECTED")
    window.update_developer_snapshot(
        sample_developer_snapshot(
            process_state="DISCONNECTED",
            measurement=measurement,
        )
    )
    assert developer_value(
        window,
        "CURRENT CONTROLLER STATE",
        "Process state",
    ) == "DISCONNECTED"
    assert developer_value(
        window,
        "LATEST MEASUREMENT",
        "Status",
    ) == "HISTORICAL"
    assert developer_value(
        window,
        "CURRENT CONTROLLER STATE",
        "Session total volume",
    ) == "425.0 ml"
    assert "not current hardware state" in developer_value(
        window,
        "LATEST MEASUREMENT",
        "Context",
    )
    assert "historical sample" in developer_value(
        window,
        "DIGITAL I/O",
        "Downstream binary valve",
    )
    assert "historical sample" in developer_value(
        window,
        "BRONKHORST",
        "Valve output",
    )
    assert window.telemetry_context_label.property("status") == "historical"
    assert "last sample" in window.led_state_label.text()
    assert window.system_controller_status.text() == "Disconnected"
    assert window.system_lucid_status.text() == "DISCONNECTED"
    assert window.system_telemetry_status.text() == "Historical sample"
    assert developer_value(
        window,
        "EMPTY DETECTOR",
        "Required consecutive count",
    ) == "3"
    assert developer_value(
        window,
        "DATA / LOGGING",
        "Runtime log",
    ) == "C:/data/aqua_runtime.log"
    assert developer_value(window, "LUCID DIGITAL", "Port") == "COM4"
    assert developer_value(window, "LUCID DIGITAL", "Preflight") == "PASS"
    assert developer_value(
        window,
        "LUCID DIGITAL",
        "Binary Valve / CH0 actual logical read-back",
    ) == "CLOSED (0)"
    assert developer_value(
        window,
        "LUCID DIGITAL",
        "Binary Valve / CH0 internal/configured outDiValue",
    ) == "1"
    assert developer_value(
        window,
        "LUCID DIGITAL",
        "LED / CH1 internal/configured outDiValue",
    ) == "Unavailable / transient communication error"

    tabs.setCurrentIndex(1)
    app.processEvents()
    QTest.mouseClick(
        window.raw_snapshot_button,
        Qt.MouseButton.LeftButton,
    )
    assert window.developer_output.isVisible()
    assert "capacitance_value" in window.developer_output.toPlainText()
    QTest.mouseClick(
        window.copy_developer_button,
        Qt.MouseButton.LeftButton,
    )
    assert "capacitance_value" in QApplication.clipboard().text()
    assert window.developer_output.isReadOnly()

    window.set_process_state("READY")
    window.update_developer_snapshot(sample_developer_snapshot())
    assert developer_value(
        window,
        "LATEST MEASUREMENT",
        "Status",
    ) == "LIVE"
    assert developer_value(
        window,
        "ACQUISITION",
        "Capacitance raw AI4",
    ) == "4.200 V"
    assert developer_value(
        window,
        "ACQUISITION",
        "Capacitance scaled",
    ) == "20.00 scaled"
    assert developer_value(
        window,
        "ACQUISITION",
        "Humidity",
    ) == "50.0 % RH"
    assert developer_value(
        window,
        "BRONKHORST",
        "Measured flow",
    ) == "12.50 ml/min"

    config_error_snapshot = sample_developer_snapshot()
    lucid = config_error_snapshot["lucid_digital"]
    assert isinstance(lucid, dict)
    lucid["status"] = "CONFIG ERROR"
    lucid["preflight"] = "FAIL"
    window.update_developer_snapshot(config_error_snapshot)
    assert window.system_lucid_status.text() == "CONFIG ERROR"
    assert window.system_lucid_status.property("status") == "error"
    assert developer_value(window, "LUCID DIGITAL", "Preflight") == "FAIL"
    window.close()


def test_control_configuration_and_gui_state_rules() -> None:
    app = application()
    window = ProcessControlWindow()

    assert window.control_mode.currentText() == "Valve Position"
    assert window.valve_position.isVisibleTo(window)
    assert not window.flow_target.isVisibleTo(window)
    assert window.flow_target.value() == DEFAULT_FLOW_SETPOINT_ML_MIN
    assert window.target_volume.value() == DEFAULT_TARGET_VOLUME_ML
    assert window.empty_threshold.value() == 5.0
    assert not window.control_mode.isEnabled()
    assert not window.led_on_button.isEnabled()

    window.set_process_state("READY")
    window.show()
    app.processEvents()
    assert window.control_mode.isEnabled()
    assert window.valve_position.isEnabled()
    assert not window.apply_setpoint_button.isVisible()
    assert window.auto_empty_stop.isEnabled()
    assert window.led_on_button.isEnabled()

    window.control_mode.setCurrentIndex(1)
    app.processEvents()
    assert window._selected_control_mode() == ControlMode.FLOW_TARGET
    assert not window.valve_position.isVisible()
    assert window.flow_target.isVisible()
    assert window.flow_target.isEnabled()

    window.target_volume_stop.setChecked(True)
    window.target_volume.setValue(500.0)
    configurations: list[RunConfiguration] = []
    window.start_requested.connect(configurations.append)
    QTest.mouseClick(window.start_button, Qt.MouseButton.LeftButton)
    assert len(configurations) == 1
    configuration = configurations[0]
    assert configuration.control_mode == ControlMode.FLOW_TARGET
    assert configuration.flow_target_ml_min == DEFAULT_FLOW_SETPOINT_ML_MIN
    assert configuration.target_volume_enabled
    assert configuration.target_volume_ml == 500.0
    assert configuration.empty_threshold == 5.0
    assert not window.control_mode.isEnabled()
    assert not window.led_on_button.isEnabled()

    window.set_start_pending(False)
    window.mark_run_started()
    app.processEvents()
    assert not window.control_mode.isEnabled()
    assert window.flow_target.isEnabled()
    assert not window.valve_position.isEnabled()
    assert window.apply_setpoint_button.isEnabled()
    assert window.apply_setpoint_button.isVisible()
    assert not window.auto_empty_stop.isEnabled()
    assert not window.empty_threshold.isEnabled()
    assert not window.target_volume_stop.isEnabled()
    assert not window.target_volume.isEnabled()
    assert window.led_on_button.isEnabled()

    changes: list[tuple[ControlMode, float]] = []
    window.active_setpoint_requested.connect(
        lambda mode, value: changes.append((mode, value))
    )
    window.flow_target.setValue(80.0)
    QTest.mouseClick(
        window.apply_setpoint_button,
        Qt.MouseButton.LeftButton,
    )
    assert changes == [(ControlMode.FLOW_TARGET, 80.0)]

    window.set_process_state("STOPPING")
    assert not window.flow_target.isEnabled()
    assert not window.apply_setpoint_button.isEnabled()
    assert not window.led_on_button.isEnabled()
    window.close()


def test_session_charts_persist_across_runs_with_monotonic_time_and_volume() -> None:
    window = ProcessControlWindow()
    window.set_process_state("READY")
    sample = sample_measurement()

    window.mark_run_started()
    window.update_measurement(
        sample,
        elapsed_seconds=10.0,
        run_volume_ml=250.0,
        session_total_volume_ml=250.0,
    )
    assert window.metric_charts["flow"].point_count == 1

    window.set_process_state("STOPPED")
    window.mark_run_started()
    assert window.metric_charts["flow"].point_count == 1
    window.update_measurement(
        sample,
        elapsed_seconds=70.0,
        run_volume_ml=175.0,
        session_total_volume_ml=425.0,
    )

    window.set_process_state("STOPPED")
    window.mark_run_started()
    window.update_measurement(
        sample,
        elapsed_seconds=105.0,
        run_volume_ml=175.0,
        session_total_volume_ml=600.0,
    )

    flow_chart = window.metric_charts["flow"]
    volume_chart = window.metric_charts["volume"]
    assert flow_chart.point_count == 3
    assert [flow_chart.series.at(index).x() for index in range(3)] == [
        10.0,
        70.0,
        105.0,
    ]
    assert [volume_chart.series.at(index).y() for index in range(3)] == [
        250.0,
        425.0,
        600.0,
    ]
    assert window.telemetry_cards["volume"].value_label.text() == "600.0 ml"
    assert window.telemetry_cards["volume"].detail_label.text() == (
        "run: 175.0 ml"
    )

    window.focus_metric_chart("volume")
    window.show_chart_overview()
    assert flow_chart.point_count == 3
    assert volume_chart.point_count == 3
    window.close()


def test_all_chart_time_windows_change_axes_without_deleting_history() -> None:
    window = ProcessControlWindow()
    chart = window.metric_charts["flow"]
    chart.append_value(0.0, 1.0)
    chart.append_value(700.0, 2.0)
    expected_labels = [label for label, _ in CHART_TIME_WINDOWS]
    assert [
        window.chart_window_selector.itemText(index)
        for index in range(window.chart_window_selector.count())
    ] == expected_labels

    expected_left = {
        "10 s": 690.0,
        "30 s": 670.0,
        "60 s": 640.0,
        "2 min": 580.0,
        "5 min": 400.0,
        "10 min": 100.0,
    }
    for label, left in expected_left.items():
        window.chart_window_selector.setCurrentText(label)
        assert chart.point_count == 2
        assert chart.x_axis.min() == left
        assert chart.x_axis.max() == 700.0

    window.chart_window_selector.setCurrentText("Full session")
    assert chart._show_full_history
    assert chart.x_axis.min() == 0.0
    assert chart.x_axis.max() == 700.0
    assert chart.point_count == 2
    window.close()


def test_runtime_live_requests_are_applied_in_worker_thread() -> None:
    app = application()
    with TemporaryDirectory() as temporary_directory:
        controller, analog = build_fake_controller(
            Path(temporary_directory),
            capacitance_value=25.0,
        )
        controller.connect()
        runtime = ProcessRuntime(controller)
        main_thread_id = threading.get_ident()
        QTest.qWait(20)

        runtime.start_process(
            RunConfiguration(
                control_mode=ControlMode.VALVE_POSITION,
                valve_position_percent=100.0,
                empty_stop_enabled=False,
            )
        )
        deadline = time.monotonic() + 2.0
        while (
            (controller.state.name != "RUNNING" or analog.calls == 0)
            and time.monotonic() < deadline
        ):
            QTest.qWait(5)
            app.processEvents()

        runtime.request_active_setpoint(ControlMode.VALVE_POSITION, 60.0)
        runtime.set_led(True)
        deadline = time.monotonic() + 2.0
        while (
            (
                controller.bronkhorst.direct_commands != [100.0, 60.0]
                or not controller.led.on_state
            )
            and time.monotonic() < deadline
        ):
            QTest.qWait(5)
            app.processEvents()

        assert controller.bronkhorst.direct_commands == [100.0, 60.0]
        assert controller.led.on_state
        assert all(
            thread_id != main_thread_id
            for thread_id in controller.bronkhorst.command_thread_ids
        )
        assert all(
            thread_id != main_thread_id
            for thread_id in controller.led.command_thread_ids
        )

        runtime.stop_process()
        deadline = time.monotonic() + 2.0
        while runtime._start_in_flight and time.monotonic() < deadline:
            QTest.qWait(5)
            app.processEvents()
        assert not runtime._start_in_flight
        runtime.shutdown()


def test_runtime_coalesces_duplicate_start_but_allows_later_run() -> None:
    app = application()
    with TemporaryDirectory() as temporary_directory:
        controller, analog = build_fake_controller(Path(temporary_directory))
        controller.connect()
        runtime = ProcessRuntime(controller)
        failures: list[tuple[str, str]] = []
        snapshots: list[dict[str, object]] = []
        telemetry: list[object] = []
        runtime.operation_failed.connect(
            lambda title, message: failures.append((title, message))
        )
        runtime.developer_snapshot.connect(snapshots.append)
        runtime.telemetry_received.connect(telemetry.append)
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
        assert len(telemetry) >= 2
        assert telemetry[-1].session_elapsed_seconds > (
            telemetry[0].session_elapsed_seconds
        )
        assert snapshots
        assert snapshots[-1]["sample_interval_seconds"] == 0.001
        empty_details = snapshots[-1]["empty_detector_details"]
        assert isinstance(empty_details, dict)
        assert empty_details["required_consecutive_count"] == 1
        run_details = snapshots[-1]["run_configuration"]
        assert isinstance(run_details, dict)
        assert run_details["control_mode"] == "VALVE_POSITION"
        runtime.shutdown()


def test_runtime_logging_is_rotating_bounded_and_not_duplicated() -> None:
    app = application()
    with TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "aqua_runtime.log"
        logger, _ = configure_runtime_logging(path)
        logger, qt_handler = configure_runtime_logging(path)
        received: list[tuple[str, str, str]] = []
        window = ProcessControlWindow()
        qt_handler.emitter.record_received.connect(
            lambda level, source, message: received.append(
                (level, source, message)
            )
        )
        qt_handler.emitter.record_received.connect(window.append_runtime_log)

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
        assert window.log_output.rowCount() == 1
        assert window.log_output.item(0, 3).text() == (
            "single lifecycle message"
        )

        try:
            raise ValueError("trace detail")
        except ValueError:
            logger.exception("runtime operation failed")
        app.processEvents()

        assert len(received) == 2
        assert received[1][0:2] == ("ERROR", "aqua")
        assert "runtime operation failed" in received[1][2]
        assert "Traceback" in received[1][2]
        assert "ValueError: trace detail" in received[1][2]
        assert window.log_output.rowCount() == 2
        window.log_output.selectRow(1)
        app.processEvents()
        assert "Traceback" in window.log_detail.toPlainText()
        assert "single lifecycle message" in path.read_text(encoding="utf-8")
        assert "ValueError: trace detail" in path.read_text(encoding="utf-8")

        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
        window.close()


if __name__ == "__main__":
    test_chart_click_history_and_exact_sample_storage()
    test_six_chart_overview_focus_and_custom_toggles()
    test_window_telemetry_focus_and_escape_overview()
    test_numeric_inputs_preserve_ranges_steps_and_process_state()
    test_light_ui_preserves_operator_diagnostics_and_controls()
    test_runtime_coalesces_duplicate_start_but_allows_later_run()
    test_runtime_logging_is_rotating_bounded_and_not_duplicated()
    print("GUI chart interactions: OK")
