from __future__ import annotations

from typing import Any

import pytest

from devices import bronkhorst as bronkhorst_module
from devices.bronkhorst import BronkhorstError, BronkhorstFlowController


class FakeMaster:
    def __init__(self) -> None:
        self.running = True
        self.start_calls = 0
        self.stop_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        self.running = True

    def stop(self) -> None:
        self.stop_calls += 1
        self.running = False


class FakeInstrument:
    def __init__(self) -> None:
        self.master = FakeMaster()
        self.fail_reads = False
        self.read_calls: list[int] = []
        self.values: dict[int, Any] = {
            BronkhorstFlowController.PARAM_CONTROL_MODE: (
                BronkhorstFlowController.MODE_VALVE_STEERING
            ),
            BronkhorstFlowController.PARAM_FLOW: 12.5,
        }

    def readParameter(self, parameter: int) -> Any:
        self.read_calls.append(parameter)
        if not self.master.running:
            raise RuntimeError("master is stopped")
        if self.fail_reads:
            raise RuntimeError("communication failed")
        return self.values.get(parameter, 0)


class FakeInstrumentFactory:
    def __init__(self, instrument: FakeInstrument) -> None:
        self.instrument = instrument
        self.calls: list[tuple[str, int, int]] = []

    def __call__(
        self,
        port: str,
        node_address: int,
        *,
        baudrate: int,
    ) -> FakeInstrument:
        self.calls.append((port, node_address, baudrate))
        return self.instrument


def build_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    BronkhorstFlowController,
    FakeInstrument,
    FakeInstrumentFactory,
]:
    instrument = FakeInstrument()
    factory = FakeInstrumentFactory(instrument)
    monkeypatch.setattr(bronkhorst_module.propar, "instrument", factory)
    controller = BronkhorstFlowController(
        port="COM_TEST",
        node_address=3,
        baudrate=38_400,
    )
    return controller, instrument, factory


def test_connect_disconnect_and_reconnect_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, instrument, factory = build_controller(monkeypatch)

    controller.connect()

    assert controller.is_connected
    assert factory.calls == [("COM_TEST", 3, 38_400)]
    assert instrument.master.start_calls == 0
    assert instrument.read_calls == [controller.PARAM_CONTROL_MODE]
    assert controller.read_flow_ml_min() == 12.5

    controller.disconnect()

    assert not controller.is_connected
    assert instrument.master.stop_calls == 1
    assert not hasattr(instrument.master, "close")
    with pytest.raises(BronkhorstError, match="not connected"):
        controller.read_flow_ml_min()
    with pytest.raises(BronkhorstError, match="not connected"):
        controller.set_direct_valve_position(50.0)

    controller.disconnect()
    assert instrument.master.stop_calls == 1

    controller.connect()

    assert controller.is_connected
    assert factory.calls == [("COM_TEST", 3, 38_400)]
    assert instrument.master.start_calls == 1
    assert instrument.read_calls.count(controller.PARAM_CONTROL_MODE) == 2
    assert controller.read_flow_ml_min() == 12.5

    controller.disconnect()
    assert not controller.is_connected
    assert instrument.master.stop_calls == 2


def test_failed_reconnect_stops_master_and_stays_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, instrument, _ = build_controller(monkeypatch)
    controller.connect()
    controller.disconnect()
    instrument.fail_reads = True

    with pytest.raises(BronkhorstError) as error:
        controller.connect()

    assert isinstance(error.value.__cause__, RuntimeError)
    assert not controller.is_connected
    assert instrument.master.start_calls == 1
    assert instrument.master.stop_calls == 2
    with pytest.raises(BronkhorstError, match="not connected"):
        controller.read_control_mode()


def test_failed_first_connect_retains_instrument_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, instrument, factory = build_controller(monkeypatch)
    instrument.fail_reads = True

    with pytest.raises(BronkhorstError) as error:
        controller.connect()

    assert isinstance(error.value.__cause__, RuntimeError)
    assert not controller.is_connected
    assert instrument.master.stop_calls == 1

    instrument.fail_reads = False
    controller.connect()

    assert controller.is_connected
    assert factory.calls == [("COM_TEST", 3, 38_400)]
    assert instrument.master.start_calls == 1
    controller.disconnect()
