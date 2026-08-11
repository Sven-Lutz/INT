from __future__ import annotations

import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from control.empty_detection import EmptyDetectionSettings, EmptyDetector
from control.water_process import WaterProcessController, WaterProcessError
from data.logger import CsvDataLogger
from data.repository import MeasurementRepository


class FakeBronkhorst:
    VALVE_OUTPUT_FULL_SCALE = 16_777_215

    def __init__(self, *, fail_close: bool = False) -> None:
        self.is_connected = False
        self.valve_percent = 0.0
        self.fail_close = fail_close
        self.close_attempted = False

    def connect(self) -> None:
        self.is_connected = True

    def disconnect(self) -> None:
        self.is_connected = False

    def force_valve_closed(self) -> None:
        self.close_attempted = True
        if self.fail_close:
            raise RuntimeError("proportional valve close failed")
        self.valve_percent = 0.0

    def set_direct_valve_position(self, percent: float) -> None:
        self.valve_percent = percent

    def set_flow_ml_min(self, value: float) -> None:
        self.valve_percent = 50.0

    def read_flow_ml_min(self) -> float:
        return 10.0

    def read_flow_setpoint_ml_min(self) -> float:
        return 0.0

    def read_temperature_c(self) -> float:
        return 22.5

    def read_alarm_info(self) -> int:
        return 0

    def read_control_mode(self) -> int:
        return 20

    def read_valve_output_raw(self) -> int:
        return int(
            self.valve_percent / 100.0 * self.VALVE_OUTPUT_FULL_SCALE
        )


class FakeAnalogInputs:
    def __init__(self, *, capacitance_value: float = 0.0) -> None:
        self.calls = 0
        self.capacitance_value = capacitance_value

    def read_channel_voltages(self, channels: tuple[int, ...]):
        self.calls += 1
        values = {channels[0]: self.capacitance_value, channels[1]: 5.0}
        return tuple(
            SimpleNamespace(channel=channel, voltage_v=values[channel])
            for channel in channels
        )


class FakeBinaryValve:
    def __init__(self, *, fail_close: bool = False) -> None:
        self.open_state = False
        self.fail_close = fail_close
        self.close_attempted = False

    def open(self) -> None:
        self.open_state = True

    def close(self) -> None:
        self.close_attempted = True
        if self.fail_close:
            raise RuntimeError("binary valve close failed")
        self.open_state = False

    def is_open(self, *, refresh: bool = True) -> bool:
        return self.open_state


class FakeLed:
    def __init__(self) -> None:
        self.on_state = False

    def on(self) -> None:
        self.on_state = True

    def off(self) -> None:
        self.on_state = False

    def is_on(self, *, refresh: bool = True) -> bool:
        return self.on_state


def build_fake_controller(
    directory: Path,
    *,
    capacitance_value: float = 0.0,
    bronkhorst: FakeBronkhorst | None = None,
    binary_valve: FakeBinaryValve | None = None,
) -> tuple[WaterProcessController, FakeAnalogInputs]:
    analog = FakeAnalogInputs(capacitance_value=capacitance_value)
    controller = WaterProcessController(
        bronkhorst=bronkhorst or FakeBronkhorst(),
        binary_valve=binary_valve or FakeBinaryValve(),
        led=FakeLed(),
        analog_inputs=analog,
        logger=CsvDataLogger(directory),
        repository=MeasurementRepository(),
        empty_detector=EmptyDetector(
            EmptyDetectionSettings(
                empty_threshold=2.0,
                filled_threshold=12.5,
                consecutive_samples=1,
                enabled=True,
            )
        ),
        sample_interval_seconds=0.001,
        capacitance_channel=0,
        humidity_channel=1,
    )
    return controller, analog


def test_controller_can_run_twice_without_reconnect() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, analog = build_fake_controller(Path(temporary_directory))

        controller.connect()
        first = controller.start()
        second = controller.start()

        assert first.completed_successfully
        assert second.completed_successfully
        assert analog.calls == 2
        assert controller.state.name == "STOPPED"
        controller.disconnect()


def test_stop_request_is_immediate_and_persisted_by_worker() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, analog = build_fake_controller(
            Path(temporary_directory),
            capacitance_value=25.0,
        )
        controller.connect()
        result: list[object] = []

        run_thread = threading.Thread(
            target=lambda: result.append(controller.start()),
            daemon=True,
        )
        run_thread.start()

        deadline = time.monotonic() + 2.0
        while analog.calls == 0 and time.monotonic() < deadline:
            time.sleep(0.001)

        controller.request_stop("test stop")
        run_thread.join(timeout=2.0)

        assert not run_thread.is_alive()
        assert result and result[0].completed_successfully
        assert result[0].stop_reason == "test stop"
        event_types = {
            event.event_type
            for event in controller.repository.recent_events()
        }
        assert "STOP_REQUESTED" in event_types
        assert "PROCESS_STOPPED" in event_types
        controller.disconnect()


def test_safe_state_attempts_both_valve_closures() -> None:
    with TemporaryDirectory() as temporary_directory:
        bronkhorst = FakeBronkhorst(fail_close=True)
        binary_valve = FakeBinaryValve(fail_close=True)
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            bronkhorst=bronkhorst,
            binary_valve=binary_valve,
        )
        bronkhorst.is_connected = True

        try:
            controller._apply_safe_state()
        except WaterProcessError:
            pass
        else:
            raise AssertionError("an incomplete safe state must fail")

        assert bronkhorst.close_attempted
        assert binary_valve.close_attempted


if __name__ == "__main__":
    test_controller_can_run_twice_without_reconnect()
    test_stop_request_is_immediate_and_persisted_by_worker()
    test_safe_state_attempts_both_valve_closures()
    print("controller reuse, stop and safe state: OK")
