from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

import devices.lucid_do as lucid_do
from control.water_process import LucidDigitalConfigurationError
from devices.lucid_do import (
    BinaryValve,
    LedController,
    LucidControlError,
    LucidDigitalOutput,
    LucidTransientCommunicationError,
)
from tests.test_controller_reuse import (
    FakeBinaryValve,
    FakeLed,
    build_fake_controller,
)


def result(
    returncode: int,
    stdout: str = "",
    stderr: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class ScriptedRunner:
    def __init__(self, *results: SimpleNamespace) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_: object) -> SimpleNamespace:
        self.commands.append(command)
        if not self.results:
            raise AssertionError(f"unexpected LucidIoCtrl call: {command}")
        return self.results.pop(0)


def driver(
    monkeypatch: pytest.MonkeyPatch,
    runner: ScriptedRunner,
    *,
    read_attempts: int = 3,
) -> LucidDigitalOutput:
    monkeypatch.setattr(lucid_do.subprocess, "run", runner)
    return LucidDigitalOutput(
        executable=Path(__file__),
        port="COM4",
        read_attempts=read_attempts,
        retry_delay_seconds=0,
    )


def write_commands(runner: ScriptedRunner) -> list[list[str]]:
    return [
        command
        for command in runner.commands
        if any(argument.startswith("-w") for argument in command)
    ]


def read_commands(runner: ScriptedRunner) -> list[list[str]]:
    return [command for command in runner.commands if "-r" in command]


@pytest.mark.parametrize(
    ("channel", "output", "expected"),
    ((0, "CH0:00", 0), (1, "CH1:01", 1)),
)
def test_exit_code_one_logical_reads_succeed(
    monkeypatch: pytest.MonkeyPatch,
    channel: int,
    output: str,
    expected: int,
) -> None:
    output_driver = driver(monkeypatch, ScriptedRunner(result(1, output)))
    assert output_driver.read_channel(channel) == expected


def test_exit_code_one_mode_read_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1, "outDiMode=reflect")),
    )
    assert output_driver.read_output_mode(0) == "reflect"


def test_exit_code_zero_remains_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(monkeypatch, ScriptedRunner(result(0, "CH0:00")))
    assert output_driver.read_channel(0) == 0


@pytest.mark.parametrize(
    "message",
    (
        "(0x10) Internal I/O read error",
        "(0x11) Invalid number of bytes received",
    ),
)
def test_known_text_errors_raise_transient_error(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(-1, message)),
        read_attempts=1,
    )
    with pytest.raises(LucidTransientCommunicationError) as exc_info:
        output_driver.read_channel(0)
    message = str(exc_info.value)
    assert "COM4 CH0" in message
    assert "operation=read logical state" in message
    assert "exit=-1" in message


def test_textual_error_is_authoritative_even_with_accepted_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1, "(0x20) Device configuration error")),
    )
    with pytest.raises(LucidControlError):
        output_driver.read_channel(0)


def test_textual_error_in_stderr_is_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(
            result(1, "CH0:00", "(0x10) Internal I/O read error")
        ),
        read_attempts=1,
    )
    with pytest.raises(LucidTransientCommunicationError):
        output_driver.read_channel(0)


def test_malformed_logical_read_raises_with_response_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1, "unexpected output")),
    )
    with pytest.raises(LucidControlError) as exc_info:
        output_driver.read_channel(0)
    assert "Malformed" in str(exc_info.value)
    assert "stdout='unexpected output'" in str(exc_info.value)


@pytest.mark.parametrize("failures", (1, 2))
def test_transient_reads_retry_then_succeed(
    monkeypatch: pytest.MonkeyPatch,
    failures: int,
) -> None:
    responses = [
        result(-1, "(0x11) Invalid number of bytes received")
        for _ in range(failures)
    ]
    responses.append(result(1, "CH0:00"))
    runner = ScriptedRunner(*responses)
    output_driver = driver(monkeypatch, runner)
    assert output_driver.read_channel(0) == 0
    assert len(runner.commands) == failures + 1


def test_transient_read_retries_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(
        *[
            result(-1, "(0x10) Internal I/O read error")
            for _ in range(3)
        ]
    )
    output_driver = driver(monkeypatch, runner)
    with pytest.raises(LucidTransientCommunicationError) as exc_info:
        output_driver.read_channel(0)
    assert len(runner.commands) == 3
    assert "after 3 attempts" in str(exc_info.value)


def test_write_once_with_matching_readback_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(result(1), result(1, "CH1:01"))
    output_driver = driver(monkeypatch, runner)
    output_driver.write_channel(1, 1)
    assert len(write_commands(runner)) == 1
    assert len(read_commands(runner)) == 1


def test_write_once_with_mismatch_raises_without_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(result(1), result(1, "CH0:00"))
    output_driver = driver(monkeypatch, runner)
    with pytest.raises(LucidControlError):
        output_driver.write_channel(0, 1)
    assert len(write_commands(runner)) == 1


def test_transient_read_after_write_retries_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(
        result(1),
        result(-1, "(0x11) Invalid number of bytes received"),
        result(1, "CH1:01"),
    )
    output_driver = driver(monkeypatch, runner)
    output_driver.write_channel(1, 1)
    assert len(write_commands(runner)) == 1
    assert len(read_commands(runner)) == 2


def test_transient_write_response_with_matching_readback_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(
        result(-1, "(0x10) Internal I/O read error"),
        result(1, "CH1:01"),
    )
    output_driver = driver(monkeypatch, runner)
    output_driver.write_channel(1, 1)
    assert len(write_commands(runner)) == 1
    assert len(read_commands(runner)) == 1


def test_transient_write_response_with_opposite_readback_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(
        result(-1, "(0x11) Invalid number of bytes received"),
        result(1, "CH1:00"),
    )
    output_driver = driver(monkeypatch, runner)
    with pytest.raises(LucidControlError):
        output_driver.write_channel(1, 1)
    assert len(write_commands(runner)) == 1


@pytest.mark.parametrize("mode", ("reflect", "inactive"))
def test_output_mode_parsing(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1, f"outDiMode={mode}")),
    )
    assert output_driver.read_output_mode(0) == mode


@pytest.mark.parametrize(("text", "expected"), (("off", False), ("on", True)))
def test_output_inverted_parsing(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected: bool,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1, f"outDiInverted={text}")),
    )
    assert output_driver.read_output_inverted(0) is expected


def test_output_value_parsing_is_diagnostic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1, "outDiValue=1")),
    )
    assert output_driver.read_output_value(0) == 1


def test_inspection_keeps_logical_readback_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(
        result(1, "outDiMode=reflect"),
        result(1, "outDiInverted=off"),
        result(1, "CH0:00"),
        result(1, "outDiValue=1"),
    )
    output_driver = driver(monkeypatch, runner)
    details = output_driver.inspect_channel(0, role="Binary Valve")
    assert details["actual_logical_state"] == 0
    assert details["internal_output_value"] == 1
    assert not write_commands(runner)


def test_optional_output_value_transient_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ScriptedRunner(
        result(1, "outDiMode=reflect"),
        result(1, "outDiInverted=off"),
        result(1, "CH0:00"),
        *[
            result(-1, "(0x11) Invalid number of bytes received")
            for _ in range(3)
        ],
    )
    output_driver = driver(monkeypatch, runner)
    details = output_driver.inspect_channel(0, role="Binary Valve")
    assert details["actual_logical_state"] == 0
    assert details["internal_output_value"] is None
    assert "after 3 attempts" in str(details["optional_diagnostic_error"])


class ConfigurableBinaryValve(FakeBinaryValve):
    def __init__(
        self,
        *,
        mode: str = "reflect",
        inverted: bool = False,
        critical_error: bool = False,
        optional_error: bool = False,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.inverted = inverted
        self.critical_error = critical_error
        self.optional_error = optional_error

    def preflight(self) -> dict[str, object]:
        if self.critical_error:
            raise LucidControlError("COM4 CH0 critical read failed")
        details = super().preflight()
        details["port"] = "COM4"
        details["reported_mode"] = self.mode
        details["inverted"] = self.inverted
        if self.optional_error:
            details["optional_diagnostic_error"] = (
                "Unavailable / transient communication error"
            )
        return details


class ConfigurableLed(FakeLed):
    def __init__(
        self,
        *,
        mode: str = "reflect",
        inverted: bool = False,
    ) -> None:
        super().__init__()
        self.mode = mode
        self.inverted = inverted

    def preflight(self) -> dict[str, object]:
        details = super().preflight()
        details["port"] = "COM4"
        details["reported_mode"] = self.mode
        details["inverted"] = self.inverted
        return details


class UnsafeReadbackBinaryValve(ConfigurableBinaryValve):
    def close(self) -> None:
        self.close_attempted = True
        self.open_state = True

    def verify_closed(self) -> None:
        raise LucidControlError(
            "Binary Valve safe-state verification failed: actual OPEN (1)."
        )


def test_preflight_passes_with_both_channels_reflect_and_not_inverted() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(Path(temporary_directory))
        controller.connect()
        diagnostics = controller.lucid_digital_diagnostics
        assert controller.state.name == "READY"
        assert diagnostics["status"] == "OK"
        assert diagnostics["preflight"] == "PASS"
        controller.disconnect()


@pytest.mark.parametrize(
    ("binary", "led", "expected_channel"),
    (
        (ConfigurableBinaryValve(mode="inactive"), ConfigurableLed(), "CH0"),
        (ConfigurableBinaryValve(), ConfigurableLed(mode="inactive"), "CH1"),
    ),
)
def test_inactive_mode_prevents_ready(
    binary: ConfigurableBinaryValve,
    led: ConfigurableLed,
    expected_channel: str,
) -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            binary_valve=binary,
            led=led,
        )
        with pytest.raises(LucidDigitalConfigurationError) as exc_info:
            controller.connect()
        assert expected_channel in str(exc_info.value)
        assert "outDiMode=inactive" in str(exc_info.value)
        assert controller.state.name == "DISCONNECTED"
        assert controller.lucid_digital_diagnostics["status"] == "CONFIG ERROR"
        assert controller.bronkhorst.close_attempted
        assert not controller.bronkhorst.is_connected


def test_unexpected_inversion_prevents_ready() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            binary_valve=ConfigurableBinaryValve(inverted=True),
            led=ConfigurableLed(),
        )
        with pytest.raises(LucidDigitalConfigurationError):
            controller.connect()
        diagnostics = controller.lucid_digital_diagnostics
        assert diagnostics["status"] == "CONFIG ERROR"
        assert "outDiInverted=on" in str(diagnostics["preflight_error"])


def test_critical_preflight_read_failure_prevents_ready() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            binary_valve=ConfigurableBinaryValve(critical_error=True),
            led=ConfigurableLed(),
        )
        with pytest.raises(LucidControlError):
            controller.connect()
        assert controller.state.name == "DISCONNECTED"
        assert controller.lucid_digital_diagnostics["status"] == "COMM ERROR"


def test_optional_output_value_failure_does_not_prevent_ready() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            binary_valve=ConfigurableBinaryValve(optional_error=True),
            led=ConfigurableLed(),
        )
        controller.connect()
        diagnostics = controller.lucid_digital_diagnostics
        assert controller.state.name == "READY"
        assert diagnostics["status"] == "OK"
        binary = diagnostics["channels"]["binary_valve"]
        assert binary["optional_diagnostic_error"]
        controller.disconnect()


def test_unsafe_ch0_readback_prevents_ready() -> None:
    with TemporaryDirectory() as temporary_directory:
        controller, _ = build_fake_controller(
            Path(temporary_directory),
            binary_valve=UnsafeReadbackBinaryValve(),
            led=ConfigurableLed(),
        )
        with pytest.raises(LucidControlError):
            controller.connect()
        assert controller.state.name == "DISCONNECTED"
        assert controller.lucid_digital_diagnostics["status"] == "COMM ERROR"


def test_verified_write_updates_binary_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1), result(1, "CH0:01")),
    )
    valve = BinaryValve(output_driver, 0)
    valve.open()
    assert valve.last_known_state == 1
    assert valve.is_open(refresh=False)


def test_failed_write_does_not_update_binary_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(
            result(1),
            result(1, "CH0:01"),
            result(1),
            result(1, "CH0:01"),
        ),
    )
    valve = BinaryValve(output_driver, 0)
    valve.open()
    with pytest.raises(LucidControlError):
        valve.close()
    assert valve.last_known_state == 1


def test_refresh_true_overrides_verified_cache_with_logical_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(
            result(1),
            result(1, "CH0:01"),
            result(1, "CH0:00"),
        ),
    )
    valve = BinaryValve(output_driver, 0)
    valve.open()
    assert valve.is_open(refresh=False)
    assert not valve.is_open(refresh=True)
    assert valve.last_known_state == 0


def test_high_level_led_mismatch_uses_actuator_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_driver = driver(
        monkeypatch,
        ScriptedRunner(result(1), result(1, "CH1:00")),
    )
    led = LedController(output_driver, 1)
    with pytest.raises(LucidControlError) as exc_info:
        led.on()
    assert "LED verification failed" in str(exc_info.value)
    assert "requested ON (1)" in str(exc_info.value)
    assert "actual read-back OFF (0)" in str(exc_info.value)
