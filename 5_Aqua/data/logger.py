from __future__ import annotations

import csv
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar

from data.models import (
    ProcessEvent,
    ProcessSummary,
    SystemMeasurement,
)


T = TypeVar(
    "T",
    SystemMeasurement,
    ProcessEvent,
    ProcessSummary,
)


class CsvLoggerError(RuntimeError):
    """Base error for CSV logging failures."""


class CsvDataLogger:
    def __init__(
        self,
        directory: Path,
        *,
        delimiter: str = ";",
        file_prefix: str = "process_control",
        datetime_format: str = "%Y-%m-%d_%H-%M-%S",
    ) -> None:
        self.directory = directory
        self.delimiter = delimiter
        self.file_prefix = file_prefix
        self.datetime_format = datetime_format

        self._lock = Lock()
        self._run_timestamp: str | None = None
        self._measurement_path: Path | None = None
        self._event_path: Path | None = None
        self._last_measurement_path: Path | None = None
        self._last_event_path: Path | None = None
        self._summary_path = (
            self.directory
            / f"{self.file_prefix}_summaries.csv"
        )

    @property
    def run_started(self) -> bool:
        return self._run_timestamp is not None

    @property
    def measurement_path(self) -> Path | None:
        return self._measurement_path

    @property
    def event_path(self) -> Path | None:
        return self._event_path

    @property
    def last_measurement_path(self) -> Path | None:
        return self._last_measurement_path

    @property
    def last_event_path(self) -> Path | None:
        return self._last_event_path

    @property
    def summary_path(self) -> Path:
        return self._summary_path

    def start_run(
        self,
        timestamp: datetime | None = None,
    ) -> None:
        if self.run_started:
            raise CsvLoggerError(
                "A logging run is already active."
            )

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        run_time = timestamp or datetime.now()
        self._run_timestamp = run_time.strftime(
            self.datetime_format
        )

        self._measurement_path = (
            self.directory
            / (
                f"{self.file_prefix}_measurements_"
                f"{self._run_timestamp}.csv"
            )
        )

        self._event_path = (
            self.directory
            / (
                f"{self.file_prefix}_events_"
                f"{self._run_timestamp}.csv"
            )
        )

        self._last_measurement_path = self._measurement_path
        self._last_event_path = self._event_path

    def finish_run(self) -> None:
        self._run_timestamp = None
        self._measurement_path = None
        self._event_path = None

    def _require_active_run(self) -> None:
        if not self.run_started:
            raise CsvLoggerError(
                "No active logging run. Call start_run() first."
            )

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat(timespec="milliseconds")
        if isinstance(value, bool):
            return int(value)
        if value is None:
            return ""
        return value

    @classmethod
    def _serialize_dataclass(
        cls,
        item: T,
    ) -> dict[str, Any]:
        row = asdict(item)
        return {
            key: cls._serialize_value(value)
            for key, value in row.items()
        }

    @staticmethod
    def _field_names(item_type: type[T]) -> list[str]:
        return [field.name for field in fields(item_type)]

    def _append_row(
        self,
        *,
        path: Path,
        row: dict[str, Any],
        field_names: list[str],
    ) -> None:
        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        write_header = (
            not path.exists()
            or path.stat().st_size == 0
        )

        try:
            with path.open(
                "a",
                encoding="utf-8",
                newline="",
            ) as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=field_names,
                    delimiter=self.delimiter,
                    extrasaction="raise",
                )
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except (OSError, csv.Error) as exc:
            raise CsvLoggerError(
                f"Could not write CSV data to:\n{path}"
            ) from exc

    def log_measurement(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        self._require_active_run()

        if self._measurement_path is None:
            raise CsvLoggerError(
                "Measurement file path is unavailable."
            )

        with self._lock:
            self._append_row(
                path=self._measurement_path,
                row=self._serialize_dataclass(measurement),
                field_names=self._field_names(SystemMeasurement),
            )

    def log_event(
        self,
        event: ProcessEvent,
    ) -> None:
        self._require_active_run()

        if self._event_path is None:
            raise CsvLoggerError(
                "Event file path is unavailable."
            )

        with self._lock:
            self._append_row(
                path=self._event_path,
                row=self._serialize_dataclass(event),
                field_names=self._field_names(ProcessEvent),
            )

    def log_summary(
        self,
        summary: ProcessSummary,
    ) -> None:
        with self._lock:
            self._append_row(
                path=self._summary_path,
                row=self._serialize_dataclass(summary),
                field_names=self._field_names(ProcessSummary),
            )
