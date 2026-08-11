from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

import pytest

from config import CAPACITANCE_EMPTY_THRESHOLD
from control.empty_detection import EmptyDetectionSettings
from control.run_configuration import ControlMode, RunConfiguration
from control.safety import SafetyLimits, SafetyMonitor
from control.water_process import WaterProcessController, WaterProcessError
from data.models import SystemMeasurement
from tests.test_controller_reuse import (
    FakeBronkhorst,
    FakeLed,
    build_fake_controller,
)


def measurement(
    timestamp: datetime,
    *,
    flow_ml_min: float,
    capacitance_value: float = 25.0,
    valve_position_percent: float = 0.0,
    led_on: bool = False,
) -> SystemMeasurement:
    return SystemMeasurement(
        timestamp=timestamp,
        flow_ml_min=flow_ml_min,
        flow_setpoint_ml_min=0.0,
        bronkhorst_temperature_c=22.0,
        bronkhorst_alarm_info=0,
        bronkhorst_control_mode=20,
        valve_output_raw=0,
        valve_output_raw_percent=0.0,
        valve_position_percent=valve_position_percent,
        capacitance_voltage_v=capacitance_value,
        capacitance_value=capacitance_value,
        capacitance_state="DRAINING",
        humidity_voltage_v=5.0,
        humidity_percent=50.0,
        binary_valve_open=True,
        led_on=led_on,
    )


class MeasurementSequence:
    def __init__(self, values: list[SystemMeasurement]) -> None:
        self.values = list(values)

    def __call__(self) -> SystemMeasurement:
        if not self.values:
            raise AssertionError("run did not stop before measurements ended")
        return self.values.pop(0)


def configure_sequence(
    controller: WaterProcessController,
    *,
    flow_ml_min: float,
    interval_seconds: float,
    sample_count: int = 2,
    capacitance_value: float = 25.0,
) -> None:
    started = datetime(2026, 1, 1, 12, 0, 0)
    controller.measure = MeasurementSequence(  # type: ignore[method-assign]
        [
            measurement(
                started + timedelta(seconds=index * interval_seconds),
                flow_ml_min=flow_ml_min,
                capacitance_value=capacitance_value,
            )
            for index in range(sample_count)
        ]
    )
    controller.safety_monitor = SafetyMonitor(
        SafetyLimits(maximum_flow_ml_min=1_000.0)
    )


def event_types(controller: WaterProcessController) -> list[str]:
    return [
        event.event_type
        for event in controller.repository.recent_events()
    ]


def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert predicate()


def start_background_run(
    controller: WaterProcessController,
    configuration: RunConfiguration,
    *,
    measurements: list[SystemMeasurement] | None = None,
    command_errors: list[tuple[str, str]] | None = None,
) -> tuple[threading.Thread, threading.Event, list[object]]:
    started = threading.Event()
    results: list[object] = []

    def run() -> None:
        try:
            results.append(
                controller.start(
                    configuration=configuration,
                    on_started=started.set,
                    on_measurement=(
                        measurements.append
                        if measurements is not None
                        else None
                    ),
                    on_command_error=(
                        lambda title, message: command_errors.append(
                            (title, message)
                        )
                        if command_errors is not None
                        else None
                    ),
                )
            )
        except Exception as exc:
            results.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert started.wait(timeout=2.0)
    return thread, started, results


def test_default_empty_threshold_is_five_scaled_units() -> None:
    assert CAPACITANCE_EMPTY_THRESHOLD == 5.0
    assert EmptyDetectionSettings().empty_threshold == 5.0
    assert RunConfiguration().empty_threshold == 5.0
    with pytest.raises(ValueError, match="greater than zero"):
        RunConfiguration(
            target_volume_enabled=True,
            target_volume_ml=0.0,
        )


def test_valve_position_sixty_with_target_volume_five_hundred() -> None:
    with TemporaryDirectory() as temporary_directory:
        bronkhorst = FakeBronkhorst()
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            bronkhorst=bronkhorst,
        )
        controller.connect()
        configure_sequence(
            controller,
            flow_ml_min=250.0,
            interval_seconds=120.0,
        )

        summary = controller.start(
            configuration=RunConfiguration(
                control_mode=ControlMode.VALVE_POSITION,
                valve_position_percent=60.0,
                empty_stop_enabled=False,
                target_volume_enabled=True,
                target_volume_ml=500.0,
            )
        )

        assert bronkhorst.direct_commands == [60.0]
        assert not bronkhorst.flow_commands
        assert summary.completed_successfully
        assert summary.total_volume_ml == 500.0
        assert "VOLUME_STOP" in event_types(controller)
        controller.disconnect()


def test_flow_target_mode_with_independent_target_volume() -> None:
    with TemporaryDirectory() as temporary_directory:
        bronkhorst = FakeBronkhorst()
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            bronkhorst=bronkhorst,
        )
        controller.connect()
        configure_sequence(
            controller,
            flow_ml_min=100.0,
            interval_seconds=300.0,
        )

        summary = controller.start(
            configuration=RunConfiguration(
                control_mode=ControlMode.FLOW_TARGET,
                flow_target_ml_min=100.0,
                empty_stop_enabled=False,
                target_volume_enabled=True,
                target_volume_ml=500.0,
            )
        )

        assert bronkhorst.flow_commands == [100.0]
        assert not bronkhorst.direct_commands
        assert summary.completed_successfully
        assert summary.total_volume_ml == 500.0
        assert "VOLUME_STOP" in event_types(controller)
        controller.disconnect()


def test_empty_detection_can_stop_before_target_volume() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(Path(temporary_directory))
        controller.connect()
        configure_sequence(
            controller,
            flow_ml_min=10.0,
            interval_seconds=1.0,
            sample_count=1,
            capacitance_value=0.0,
        )
        summary = controller.start(
            configuration=RunConfiguration(
                empty_stop_enabled=True,
                empty_threshold=5.0,
                target_volume_enabled=True,
                target_volume_ml=500.0,
            )
        )
        assert summary.completed_successfully
        assert "EMPTY_STOP" in event_types(controller)
        assert "VOLUME_STOP" not in event_types(controller)
        controller.disconnect()


def test_target_volume_can_stop_before_empty_detection() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(Path(temporary_directory))
        controller.connect()
        configure_sequence(
            controller,
            flow_ml_min=10.0,
            interval_seconds=60.0,
        )
        summary = controller.start(
            configuration=RunConfiguration(
                empty_stop_enabled=True,
                empty_threshold=5.0,
                target_volume_enabled=True,
                target_volume_ml=10.0,
            )
        )
        assert summary.completed_successfully
        assert "VOLUME_STOP" in event_types(controller)
        assert "EMPTY_STOP" not in event_types(controller)
        controller.disconnect()


def test_safety_fault_preempts_target_volume_completion() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(Path(temporary_directory))
        controller.connect()
        started = datetime(2026, 1, 1, 12, 0, 0)
        controller.measure = MeasurementSequence(  # type: ignore[method-assign]
            [measurement(started, flow_ml_min=250.0)]
        )
        summary = controller.start(
            configuration=RunConfiguration(
                empty_stop_enabled=False,
                target_volume_enabled=True,
                target_volume_ml=0.1,
            )
        )
        assert not summary.completed_successfully
        assert controller.state.name == "FAULT"
        assert "SAFETY_FAULT" in event_types(controller)
        assert "VOLUME_STOP" not in event_types(controller)
        controller.disconnect()


def test_run_volume_resets_but_session_total_accumulates() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(Path(temporary_directory))
        controller.connect()

        configure_sequence(
            controller,
            flow_ml_min=250.0,
            interval_seconds=60.0,
        )
        first = controller.start(
            configuration=RunConfiguration(
                empty_stop_enabled=False,
                target_volume_enabled=True,
                target_volume_ml=250.0,
            )
        )
        assert first.total_volume_ml == 250.0
        assert controller.session_total_volume_ml == 250.0

        configure_sequence(
            controller,
            flow_ml_min=175.0,
            interval_seconds=60.0,
        )
        second = controller.start(
            configuration=RunConfiguration(
                empty_stop_enabled=False,
                target_volume_enabled=True,
                target_volume_ml=175.0,
            )
        )
        assert second.total_volume_ml == 175.0
        assert controller.run_volume_ml == 175.0
        assert controller.session_total_volume_ml == 425.0
        controller.disconnect()


def test_live_valve_and_led_commands_execute_only_in_run_thread() -> None:
    with TemporaryDirectory() as temporary_directory:
        bronkhorst = FakeBronkhorst()
        led = FakeLed()
        controller, analog = build_fake_controller(
            Path(temporary_directory),
            capacitance_value=25.0,
            bronkhorst=bronkhorst,
            led=led,
        )
        controller.connect()
        received: list[SystemMeasurement] = []
        configuration = RunConfiguration(
            control_mode=ControlMode.VALVE_POSITION,
            valve_position_percent=100.0,
            empty_stop_enabled=False,
        )
        run_thread, _, results = start_background_run(
            controller,
            configuration,
            measurements=received,
        )
        wait_until(lambda: analog.calls > 0)
        main_thread_id = threading.get_ident()

        controller.request_valve_position(60.0)
        controller.request_led_change(True)
        wait_until(
            lambda: bronkhorst.direct_commands == [100.0, 60.0]
            and led.on_state
        )
        wait_until(
            lambda: any(
                item.valve_position_percent == 60.0 and item.led_on
                for item in received
            )
        )

        assert bronkhorst.command_thread_ids[-1] == run_thread.ident
        assert led.command_thread_ids[-1] == run_thread.ident
        assert bronkhorst.command_thread_ids[-1] != main_thread_id
        assert led.command_thread_ids[-1] != main_thread_id
        assert bronkhorst.direct_commands.count(60.0) == 1

        controller.request_stop("live command test complete")
        run_thread.join(timeout=2.0)
        assert not run_thread.is_alive()
        assert controller.pending_live_command_count == 0
        assert results and not isinstance(results[0], Exception)
        assert "VALVE_SETPOINT_CHANGED" in event_types(controller)
        assert "LED_CHANGED" in event_types(controller)
        controller.disconnect()


def test_live_flow_target_applies_and_mode_cannot_switch() -> None:
    with TemporaryDirectory() as temporary_directory:
        bronkhorst = FakeBronkhorst()
        controller, analog = build_fake_controller(
            Path(temporary_directory),
            capacitance_value=25.0,
            bronkhorst=bronkhorst,
        )
        controller.connect()
        received: list[SystemMeasurement] = []
        run_thread, _, _ = start_background_run(
            controller,
            RunConfiguration(
                control_mode=ControlMode.FLOW_TARGET,
                flow_target_ml_min=100.0,
                empty_stop_enabled=False,
            ),
            measurements=received,
        )
        wait_until(lambda: analog.calls > 0)

        with pytest.raises(WaterProcessError, match="active mode"):
            controller.request_valve_position(60.0)
        controller.request_flow_target(80.0)
        wait_until(lambda: bronkhorst.flow_commands == [100.0, 80.0])
        wait_until(
            lambda: any(
                item.flow_setpoint_ml_min == 80.0
                for item in received
            )
        )
        assert controller.active_flow_target_ml_min == 80.0
        assert "FLOW_SETPOINT_CHANGED" in event_types(controller)

        controller.request_stop("flow update test complete")
        run_thread.join(timeout=2.0)
        assert not run_thread.is_alive()
        controller.disconnect()


def test_failed_live_led_write_is_reported_without_false_state_or_fault() -> None:
    with TemporaryDirectory() as temporary_directory:
        led = FakeLed(fail_write=True)
        controller, analog = build_fake_controller(
            Path(temporary_directory),
            capacitance_value=25.0,
            led=led,
        )
        controller.connect()
        errors: list[tuple[str, str]] = []
        run_thread, _, _ = start_background_run(
            controller,
            RunConfiguration(empty_stop_enabled=False),
            command_errors=errors,
        )
        wait_until(lambda: analog.calls > 0)

        controller.request_led_change(True)
        wait_until(lambda: bool(errors))
        assert not led.on_state
        assert run_thread.is_alive()
        assert controller.state.name == "RUNNING"
        assert "LED_CHANGE_FAILED" in event_types(controller)

        controller.request_stop("LED failure test complete")
        run_thread.join(timeout=2.0)
        assert not run_thread.is_alive()
        controller.disconnect()


def test_stopping_rejects_new_live_commands_and_clears_queue() -> None:
    with TemporaryDirectory() as temporary_directory:
        led = FakeLed()
        controller, analog = build_fake_controller(
            Path(temporary_directory),
            capacitance_value=25.0,
            led=led,
        )
        controller.sample_interval_seconds = 1.0
        controller.connect()
        run_thread, _, _ = start_background_run(
            controller,
            RunConfiguration(empty_stop_enabled=False),
        )
        wait_until(lambda: analog.calls > 0)
        controller.request_led_change(True)
        assert controller.pending_live_command_count == 1
        controller.request_stop("stop now")
        assert controller.pending_live_command_count == 0
        with pytest.raises(WaterProcessError, match="not accepting"):
            controller.request_led_change(True)
        run_thread.join(timeout=2.0)
        assert not run_thread.is_alive()
        assert controller.pending_live_command_count == 0
        assert led.write_count == 0
        assert not led.on_state
        controller.disconnect()
