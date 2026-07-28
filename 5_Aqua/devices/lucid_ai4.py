from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class LucidAnalogInputError(RuntimeError):
    """Base error for LucidControl AI4 communication failures."""


@dataclass(frozen=True)
class AnalogInputReading:
    channel: int
    voltage_v: float


class LucidAnalogInput:
    """Driver for a LucidControl AI4 analog-input module."""

    def __init__(
        self,
        executable: Path,
        port: str,
        *,
        channel_count: int = 4,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not executable.is_file():
            raise FileNotFoundError(
                "LucidIoCtrl.exe was not found:\n"
                f"{executable}"
            )

        if not port:
            raise ValueError(
                "LucidControl port must not be empty."
            )

        if channel_count <= 0:
            raise ValueError(
                "channel_count must be greater than zero."
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be greater than zero."
            )

        self.executable = executable
        self.port = port
        self.channel_count = channel_count
        self.timeout_seconds = timeout_seconds

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
            raise LucidAnalogInputError(
                f"LucidControl command timed out on {self.port}."
            ) from exc
        except OSError as exc:
            raise LucidAnalogInputError(
                "LucidIoCtrl.exe could not be executed."
            ) from exc

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stderr:
            raise LucidAnalogInputError(
                f"LucidControl reported an error on {self.port}:\n"
                f"{stderr}"
            )

        if result.returncode not in (0, 1):
            raise LucidAnalogInputError(
                f"LucidControl command failed on {self.port}.\n"
                f"Exit code: {result.returncode}\n"
                f"Output: {stdout!r}"
            )

        return stdout

    def _validate_channel(self, channel: int) -> None:
        if not isinstance(channel, int):
            raise TypeError(
                "AI4 channel must be an integer."
            )

        if not 0 <= channel < self.channel_count:
            raise ValueError(
                f"AI4 channel must be between 0 and "
                f"{self.channel_count - 1}, received {channel}."
            )

    @staticmethod
    def _parse_readings(
        output: str,
    ) -> tuple[AnalogInputReading, ...]:
        matches = re.findall(
            r"CH0*(\d+)\s*:\s*"
            r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)"
            r"(?:[eE][-+]?\d+)?)",
            output,
            flags=re.IGNORECASE,
        )

        if not matches:
            raise LucidAnalogInputError(
                "No analog input values could be parsed from "
                f"LucidIoCtrl output: {output!r}"
            )

        readings = tuple(
            AnalogInputReading(
                channel=int(channel),
                voltage_v=float(value),
            )
            for channel, value in matches
        )

        return tuple(
            sorted(
                readings,
                key=lambda reading: reading.channel,
            )
        )

    def identify(self) -> str:
        return self._run("-i")

    def read_channel_voltage(self, channel: int) -> float:
        self._validate_channel(channel)

        output = self._run(
            f"-c{channel}",
            "-tV",
            "-r",
        )

        readings = self._parse_readings(output)

        matching = [
            reading
            for reading in readings
            if reading.channel == channel
        ]

        if len(matching) != 1:
            raise LucidAnalogInputError(
                f"Expected exactly one reading for channel {channel}, "
                f"received {len(matching)}. Output: {output!r}"
            )

        return matching[0].voltage_v

    def read_channel_voltages(
        self,
        channels: tuple[int, ...],
    ) -> tuple[AnalogInputReading, ...]:
        if not channels:
            raise ValueError(
                "At least one AI4 channel must be requested."
            )

        for channel in channels:
            self._validate_channel(channel)

        channel_argument = ",".join(
            str(channel)
            for channel in channels
        )

        output = self._run(
            f"-c{channel_argument}",
            "-tV",
            "-r",
        )

        readings = self._parse_readings(output)

        requested = set(channels)
        received = {reading.channel for reading in readings}

        missing = requested - received
        if missing:
            raise LucidAnalogInputError(
                f"Missing channels: {sorted(missing)}. "
                f"Output: {output!r}"
            )

        return tuple(
            reading
            for reading in readings
            if reading.channel in requested
        )

    def read_all_channel_voltages(
        self,
    ) -> tuple[AnalogInputReading, ...]:
        return self.read_channel_voltages(
            tuple(range(self.channel_count))
        )
