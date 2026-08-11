from __future__ import annotations

import re
import subprocess
from pathlib import Path


class LucidControlError(RuntimeError):
    """Base error for LucidControl communication failures."""


class LucidDigitalOutput:
    """Low-level driver for LucidControl digital outputs."""

    def __init__(
        self,
        executable: Path,
        port: str,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.executable = executable
        self.port = port
        self.timeout_seconds = timeout_seconds

        if not self.executable.is_file():
            raise FileNotFoundError(
                "LucidIoCtrl.exe was not found:\n"
                f"{self.executable}"
            )

        if not self.port:
            raise ValueError("LucidControl port must not be empty.")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

    def _run(self, *arguments: str) -> str:
        command = [
            str(self.executable),
            f"-d{self.port}",
            *arguments,
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LucidControlError(
                f"LucidControl command timed out on {self.port}."
            ) from exc
        except OSError as exc:
            raise LucidControlError(
                "LucidIoCtrl.exe could not be executed."
            ) from exc

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stderr:
            raise LucidControlError(
                f"LucidControl reported an error on {self.port}:\n"
                f"{stderr}"
            )

        # The installed LucidIoCtrl version was observed to return 1
        # for successful commands. Read-back therefore remains authoritative.
        if result.returncode not in (0, 1):
            raise LucidControlError(
                f"LucidControl command failed on {self.port}.\n"
                f"Exit code: {result.returncode}\n"
                f"Output: {stdout!r}"
            )

        return stdout

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
        self._validate_channel(channel)

        output = self._run(
            f"-c{channel}",
            "-tL",
            "-r",
        )

        match = re.search(
            rf"CH{channel}\s*:\s*(\d+)",
            output,
            flags=re.IGNORECASE,
        )

        if match is None:
            raise LucidControlError(
                f"Could not parse channel {channel} "
                f"on {self.port} from output: {output!r}"
            )

        return 1 if int(match.group(1)) != 0 else 0

    def write_channel(self, channel: int, state: int) -> None:
        self._validate_channel(channel)
        self._validate_state(state)

        self._run(
            f"-c{channel}",
            "-tL",
            f"-w{state}",
        )

        readback = self.read_channel(channel)
        if readback != state:
            raise LucidControlError(
                f"LucidControl read-back failed on {self.port}, "
                f"channel {channel}: expected {state}, "
                f"received {readback}."
            )


class BinaryValve:
    """High-level abstraction for the downstream binary valve.

    Successful writes already perform a hardware read-back. The cached
    state can therefore be used by high-frequency telemetry without
    launching another LucidIoCtrl subprocess for every sample. Calls to
    ``is_open()`` still refresh from hardware by default for diagnostics
    and backward compatibility.
    """

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
    def last_known_open(self) -> bool | None:
        if self._last_state is None:
            return None
        return self._last_state == self.open_state

    def open(self) -> None:
        self.controller.write_channel(self.channel, self.open_state)
        self._last_state = self.open_state

    def close(self) -> None:
        self.controller.write_channel(self.channel, self.closed_state)
        self._last_state = self.closed_state

    def is_open(self, *, refresh: bool = True) -> bool:
        if refresh or self._last_state is None:
            self._last_state = self.controller.read_channel(self.channel)
        return self._last_state == self.open_state


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
    def last_known_on(self) -> bool | None:
        if self._last_state is None:
            return None
        return self._last_state == self.on_state

    def on(self) -> None:
        self.controller.write_channel(self.channel, self.on_state)
        self._last_state = self.on_state

    def off(self) -> None:
        self.controller.write_channel(self.channel, self.off_state)
        self._last_state = self.off_state

    def is_on(self, *, refresh: bool = True) -> bool:
        if refresh or self._last_state is None:
            self._last_state = self.controller.read_channel(self.channel)
        return self._last_state == self.on_state
