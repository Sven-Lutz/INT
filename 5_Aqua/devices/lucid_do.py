from __future__ import annotations

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar


LOGGER = logging.getLogger("aqua.devices.lucid_do")


class LucidControlError(RuntimeError):
    """Base error for LucidControl communication failures."""


class LucidTransientCommunicationError(LucidControlError):
    """A retryable 0x10/0x11 read/protocol response from LucidIoCtrl."""


class LucidVerificationError(LucidControlError):
    """A write completed without the requested authoritative read-back."""

    def __init__(
        self,
        *,
        port: str,
        channel: int,
        requested: int,
        actual: int | None,
        detail: str = "",
    ) -> None:
        self.port = port
        self.channel = channel
        self.requested = requested
        self.actual = actual
        actual_text = "unavailable" if actual is None else str(actual)
        message = (
            "LucidControl verification failed: "
            f"{port} CH{channel} requested {requested}, "
            f"actual logical read-back {actual_text}."
        )
        if detail:
            message += f" {detail}"
        super().__init__(message)


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str


_T = TypeVar("_T")


class LucidDigitalOutput:
    """Low-level driver for LucidControl digital outputs.

    Logical state from ``-tL -r`` is authoritative. ``outDiValue`` is retained
    only as commissioning diagnostics because physical testing showed that it
    can disagree with the actual logical output state.
    """

    _TEXTUAL_ERROR_PATTERN = re.compile(
        r"(?:\(\s*0x[0-9a-f]+\s*\)[^\r\n]*|"
        r"\b(?:error|failed|failure)\b)",
        flags=re.IGNORECASE,
    )
    _TRANSIENT_ERROR_PATTERN = re.compile(
        r"\(\s*0x(?:10|11)\s*\)",
        flags=re.IGNORECASE,
    )

    def __init__(
        self,
        executable: Path,
        port: str,
        *,
        timeout_seconds: float = 10.0,
        read_attempts: int = 3,
        retry_delay_seconds: float = 0.15,
    ) -> None:
        self.executable = executable
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.read_attempts = read_attempts
        self.retry_delay_seconds = retry_delay_seconds
        self.last_communication_error: str | None = None
        self._last_logical_states: dict[int, int] = {}
        self._last_output_modes: dict[int, str] = {}
        self._last_output_inverted: dict[int, bool] = {}
        self._last_output_values: dict[int, int] = {}
        self._output_value_errors: dict[int, str] = {}

        if not self.executable.is_file():
            raise FileNotFoundError(
                "LucidIoCtrl.exe was not found:\n"
                f"{self.executable}"
            )

        if not self.port:
            raise ValueError("LucidControl port must not be empty.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        if self.read_attempts < 1:
            raise ValueError("read_attempts must be at least one.")
        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative.")

    def _run(
        self,
        *arguments: str,
        operation: str,
        channel: int | None = None,
    ) -> _CommandResult:
        command = [
            str(self.executable),
            f"-d{self.port}",
            *arguments,
        ]

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            error = LucidControlError(
                self._error_context(
                    operation=operation,
                    channel=channel,
                    exit_code="timeout",
                    stdout="",
                    stderr="",
                )
            )
            self.last_communication_error = str(error)
            raise error from exc
        except OSError as exc:
            error = LucidControlError(
                self._error_context(
                    operation=operation,
                    channel=channel,
                    exit_code="not executed",
                    stdout="",
                    stderr=str(exc),
                )
            )
            self.last_communication_error = str(error)
            raise error from exc

        result = _CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        combined_output = "\n".join((result.stdout, result.stderr))
        textual_error = self._TEXTUAL_ERROR_PATTERN.search(combined_output)

        if textual_error is not None:
            error_type: type[LucidControlError] = LucidControlError
            if self._TRANSIENT_ERROR_PATTERN.search(combined_output):
                error_type = LucidTransientCommunicationError
            error = error_type(
                self._error_context(
                    operation=operation,
                    channel=channel,
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
            self.last_communication_error = str(error)
            raise error

        # Physical commissioning confirmed that this LucidIoCtrl build
        # commonly returns 1 for successful reads and writes.
        if result.returncode not in (0, 1):
            error = LucidControlError(
                self._error_context(
                    operation=operation,
                    channel=channel,
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            )
            self.last_communication_error = str(error)
            raise error

        return result

    def _read_with_retries(
        self,
        *,
        operation: str,
        channel: int,
        arguments: tuple[str, ...],
        parser: Callable[[_CommandResult], _T],
    ) -> _T:
        for attempt in range(1, self.read_attempts + 1):
            try:
                result = self._run(
                    *arguments,
                    operation=operation,
                    channel=channel,
                )
                return parser(result)
            except LucidTransientCommunicationError as exc:
                if attempt >= self.read_attempts:
                    error = LucidTransientCommunicationError(
                        f"LucidControl {operation} failed after "
                        f"{self.read_attempts} attempts. Last error: {exc}"
                    )
                    self.last_communication_error = str(error)
                    raise error from exc
                LOGGER.warning(
                    "Transient LucidControl read error; retrying %s "
                    "on %s CH%d (%d/%d): %s",
                    operation,
                    self.port,
                    channel,
                    attempt,
                    self.read_attempts,
                    exc,
                )
                if self.retry_delay_seconds:
                    time.sleep(self.retry_delay_seconds)

        raise AssertionError("read retry loop terminated unexpectedly")

    def _parse_error(
        self,
        *,
        operation: str,
        channel: int,
        result: _CommandResult,
    ) -> LucidControlError:
        error = LucidControlError(
            "Malformed LucidControl response. "
            + self._error_context(
                operation=operation,
                channel=channel,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )
        self.last_communication_error = str(error)
        return error

    def _error_context(
        self,
        *,
        operation: str,
        channel: int | None,
        exit_code: object,
        stdout: str,
        stderr: str,
    ) -> str:
        channel_context = "" if channel is None else f" CH{channel}"
        return (
            f"LucidControl command failed: {self.port}{channel_context}; "
            f"operation={operation}; exit={exit_code}; "
            f"stdout={stdout!r}; stderr={stderr!r}."
        )

    @staticmethod
    def _validate_channel(channel: int) -> None:
        if not isinstance(channel, int):
            raise TypeError("LucidControl channel must be an integer.")
        if channel < 0:
            raise ValueError("LucidControl channel must not be negative.")

    @staticmethod
    def _validate_state(state: int) -> None:
        if state not in (0, 1):
            raise ValueError("Digital output state must be 0 or 1.")

    def read_channel(self, channel: int) -> int:
        """Read authoritative logical output state with bounded retries."""

        self._validate_channel(channel)
        operation = "read logical state"

        def parse(result: _CommandResult) -> int:
            match = re.search(
                rf"\bCH{channel}\s*:\s*(\d+)\b",
                result.stdout,
                flags=re.IGNORECASE,
            )
            if match is None:
                raise self._parse_error(
                    operation=operation,
                    channel=channel,
                    result=result,
                )
            state = int(match.group(1))
            if state not in (0, 1):
                raise self._parse_error(
                    operation=operation,
                    channel=channel,
                    result=result,
                )
            self._last_logical_states[channel] = state
            return state

        return self._read_with_retries(
            operation=operation,
            channel=channel,
            arguments=(f"-c{channel}", "-tL", "-r"),
            parser=parse,
        )

    def read_output_mode(self, channel: int) -> str:
        self._validate_channel(channel)
        operation = "read outDiMode"

        def parse(result: _CommandResult) -> str:
            match = re.search(
                r"\boutDiMode\s*=\s*([A-Za-z0-9_-]+)\b",
                result.stdout,
                flags=re.IGNORECASE,
            )
            if match is None:
                raise self._parse_error(
                    operation=operation,
                    channel=channel,
                    result=result,
                )
            mode = match.group(1).lower()
            self._last_output_modes[channel] = mode
            return mode

        return self._read_with_retries(
            operation=operation,
            channel=channel,
            arguments=(f"-c{channel}", "-goutDiMode"),
            parser=parse,
        )

    def read_output_inverted(self, channel: int) -> bool:
        self._validate_channel(channel)
        operation = "read outDiInverted"

        def parse(result: _CommandResult) -> bool:
            match = re.search(
                r"\boutDiInverted\s*=\s*([A-Za-z0-9_-]+)\b",
                result.stdout,
                flags=re.IGNORECASE,
            )
            if match is None:
                raise self._parse_error(
                    operation=operation,
                    channel=channel,
                    result=result,
                )
            value = match.group(1).lower()
            if value in {"off", "false", "0"}:
                inverted = False
            elif value in {"on", "true", "1"}:
                inverted = True
            else:
                raise self._parse_error(
                    operation=operation,
                    channel=channel,
                    result=result,
                )
            self._last_output_inverted[channel] = inverted
            return inverted

        return self._read_with_retries(
            operation=operation,
            channel=channel,
            arguments=(f"-c{channel}", "-goutDiInverted"),
            parser=parse,
        )

    def read_output_value(self, channel: int) -> int:
        """Read non-authoritative internal/configured output diagnostics."""

        self._validate_channel(channel)
        operation = "read diagnostic outDiValue"

        def parse(result: _CommandResult) -> int:
            match = re.search(
                r"\boutDiValue\s*=\s*(-?\d+)\b",
                result.stdout,
                flags=re.IGNORECASE,
            )
            if match is None:
                raise self._parse_error(
                    operation=operation,
                    channel=channel,
                    result=result,
                )
            value = int(match.group(1))
            self._last_output_values[channel] = value
            self._output_value_errors.pop(channel, None)
            return value

        try:
            return self._read_with_retries(
                operation=operation,
                channel=channel,
                arguments=(f"-c{channel}", "-goutDiValue"),
                parser=parse,
            )
        except LucidControlError as exc:
            self._output_value_errors[channel] = str(exc)
            raise

    def inspect_channel(self, channel: int, *, role: str) -> dict[str, object]:
        """Collect critical configuration/state and optional diagnostics."""

        self._last_output_modes.pop(channel, None)
        self._last_output_inverted.pop(channel, None)
        self._last_logical_states.pop(channel, None)
        self._last_output_values.pop(channel, None)
        self._output_value_errors.pop(channel, None)
        mode = self.read_output_mode(channel)
        inverted = self.read_output_inverted(channel)
        actual_state = self.read_channel(channel)
        output_value: int | None = None
        optional_error: str | None = None
        try:
            output_value = self.read_output_value(channel)
        except LucidControlError as exc:
            optional_error = str(exc)
            LOGGER.warning(
                "Optional LucidControl outDiValue unavailable on %s CH%d: %s",
                self.port,
                channel,
                exc,
            )

        return {
            "port": self.port,
            "role": role,
            "channel": channel,
            "expected_mode": "reflect",
            "reported_mode": mode,
            "expected_inverted": False,
            "inverted": inverted,
            "actual_logical_state": actual_state,
            "internal_output_value": output_value,
            "optional_diagnostic_error": optional_error,
        }

    def channel_diagnostics(self, channel: int) -> dict[str, object]:
        return {
            "reported_mode": self._last_output_modes.get(channel),
            "inverted": self._last_output_inverted.get(channel),
            "actual_logical_state": self._last_logical_states.get(channel),
            "internal_output_value": self._last_output_values.get(channel),
            "optional_diagnostic_error": self._output_value_errors.get(channel),
        }

    def write_channel(self, channel: int, state: int) -> None:
        """Issue one actuator write and verify with authoritative read-back."""

        self._validate_channel(channel)
        self._validate_state(state)
        ambiguous_write_error: LucidTransientCommunicationError | None = None

        try:
            self._run(
                f"-c{channel}",
                "-tL",
                f"-w{state}",
                operation="write logical state",
                channel=channel,
            )
        except LucidTransientCommunicationError as exc:
            # The device may have applied the write before the response failed.
            # Never repeat the actuator command; verify using read retries only.
            ambiguous_write_error = exc
            LOGGER.warning(
                "Ambiguous LucidControl write response on %s CH%d; "
                "verifying without repeating the write: %s",
                self.port,
                channel,
                exc,
            )

        try:
            readback = self.read_channel(channel)
        except LucidControlError as exc:
            detail = f"Read-back unavailable: {exc}"
            if ambiguous_write_error is not None:
                detail = (
                    f"Write response was transient: {ambiguous_write_error} "
                    + detail
                )
            raise LucidVerificationError(
                port=self.port,
                channel=channel,
                requested=state,
                actual=None,
                detail=detail,
            ) from exc

        if readback != state:
            detail = ""
            if ambiguous_write_error is not None:
                detail = (
                    "The write response was transient; the command was not "
                    "repeated."
                )
            raise LucidVerificationError(
                port=self.port,
                channel=channel,
                requested=state,
                actual=readback,
                detail=detail,
            ) from ambiguous_write_error


class BinaryValve:
    """High-level abstraction for the downstream binary valve."""

    def __init__(
        self,
        controller: LucidDigitalOutput,
        channel: int,
        *,
        open_state: int = 1,
        closed_state: int = 0,
    ) -> None:
        if open_state == closed_state:
            raise ValueError("open_state and closed_state must differ.")

        self.controller = controller
        self.channel = channel
        self.open_state = open_state
        self.closed_state = closed_state
        self._last_state: int | None = None

    @property
    def last_known_state(self) -> int | None:
        return self._last_state

    @property
    def last_known_open(self) -> bool | None:
        if self._last_state is None:
            return None
        return self._last_state == self.open_state

    def preflight(self) -> dict[str, object]:
        return self.controller.inspect_channel(
            self.channel,
            role="Binary Valve",
        )

    def _write(self, state: int, semantic_state: str) -> None:
        try:
            self.controller.write_channel(self.channel, state)
        except LucidVerificationError as exc:
            if exc.actual is None:
                actual = "UNAVAILABLE"
            elif exc.actual == self.open_state:
                actual = f"OPEN ({exc.actual})"
            else:
                actual = f"CLOSED ({exc.actual})"
            raise LucidControlError(
                "Binary Valve verification failed: "
                f"{exc.port} CH{exc.channel} requested "
                f"{semantic_state} ({state}), actual read-back {actual}."
            ) from exc
        except LucidControlError as exc:
            raise LucidControlError(
                "Binary Valve command failed: "
                f"{self.controller.port} CH{self.channel} requested "
                f"{semantic_state} ({state}).\nLucid diagnostic: {exc}"
            ) from exc
        self._last_state = state

    def open(self) -> None:
        self._write(self.open_state, "OPEN")

    def close(self) -> None:
        self._write(self.closed_state, "CLOSED")

    def read_state(self, *, refresh: bool = True) -> int:
        if refresh or self._last_state is None:
            self._last_state = self.controller.read_channel(self.channel)
        return self._last_state

    def verify_closed(self) -> None:
        actual = self.read_state(refresh=True)
        if actual != self.closed_state:
            actual_semantic = (
                "OPEN" if actual == self.open_state else "UNKNOWN"
            )
            raise LucidControlError(
                "Binary Valve safe-state verification failed: "
                f"{self.controller.port} CH{self.channel} expected "
                f"CLOSED ({self.closed_state}), actual read-back "
                f"{actual_semantic} ({actual})."
            )

    def is_open(self, *, refresh: bool = True) -> bool:
        return self.read_state(refresh=refresh) == self.open_state


class LedController:
    """High-level abstraction for the LED output with cached read-back."""

    def __init__(
        self,
        controller: LucidDigitalOutput,
        channel: int,
        *,
        on_state: int = 1,
        off_state: int = 0,
    ) -> None:
        if on_state == off_state:
            raise ValueError("on_state and off_state must differ.")

        self.controller = controller
        self.channel = channel
        self.on_state = on_state
        self.off_state = off_state
        self._last_state: int | None = None

    @property
    def last_known_state(self) -> int | None:
        return self._last_state

    @property
    def last_known_on(self) -> bool | None:
        if self._last_state is None:
            return None
        return self._last_state == self.on_state

    def preflight(self) -> dict[str, object]:
        return self.controller.inspect_channel(
            self.channel,
            role="LED",
        )

    def _write(self, state: int, semantic_state: str) -> None:
        try:
            self.controller.write_channel(self.channel, state)
        except LucidVerificationError as exc:
            if exc.actual is None:
                actual = "UNAVAILABLE"
            elif exc.actual == self.on_state:
                actual = f"ON ({exc.actual})"
            else:
                actual = f"OFF ({exc.actual})"
            raise LucidControlError(
                "LED verification failed: "
                f"{exc.port} CH{exc.channel} requested "
                f"{semantic_state} ({state}), actual read-back {actual}."
            ) from exc
        except LucidControlError as exc:
            raise LucidControlError(
                "LED command failed: "
                f"{self.controller.port} CH{self.channel} requested "
                f"{semantic_state} ({state}).\nLucid diagnostic: {exc}"
            ) from exc
        self._last_state = state

    def on(self) -> None:
        self._write(self.on_state, "ON")

    def off(self) -> None:
        self._write(self.off_state, "OFF")

    def read_state(self, *, refresh: bool = True) -> int:
        if refresh or self._last_state is None:
            self._last_state = self.controller.read_channel(self.channel)
        return self._last_state

    def is_on(self, *, refresh: bool = True) -> bool:
        return self.read_state(refresh=refresh) == self.on_state
