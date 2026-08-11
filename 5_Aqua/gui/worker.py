from __future__ import annotations

import time
import traceback
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Slot

from control.empty_detection import EmptyDetectionSettings
from control.state_machine import ProcessState
from control.water_process import WaterProcessController
from data.models import ProcessSummary, SystemMeasurement


class ProcessWorker(QObject):
    """Runs the process controller off the GUI thread.

    Every device call blocks on a serial port, so nothing here may run
    in the GUI thread. The worker reports what it is doing through
    signals, so a failed connect shows up as a message instead of
    silence.
    """

    state_changed = Signal(object)
    connection_changed = Signal(bool)
    measurement_ready = Signal(object, float, float)
    run_finished = Signal(object)
    log_message = Signal(str, str)
    failed = Signal(str)

    def __init__(
        self,
        controller_factory,
    ) -> None:
        super().__init__()

        self._controller_factory = controller_factory
        self._controller: WaterProcessController | None = None
        self._run_started_monotonic: float | None = None

    # -------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------

    @property
    def controller(self) -> WaterProcessController | None:
        return self._controller

    def _log(self, message: str, level: str = "INFO") -> None:
        self.log_message.emit(message, level)

    def _report_failure(
        self,
        context: str,
        exc: Exception,
    ) -> None:
        detail = f"{type(exc).__name__}: {exc}"

        self._log(f"{context} failed. {detail}", "ERROR")
        self._log(
            traceback.format_exc().strip(),
            "DEBUG",
        )
        self.failed.emit(f"{context} failed.\n\n{detail}")

    def _emit_state(self) -> None:
        if self._controller is None:
            self.state_changed.emit(
                ProcessState.DISCONNECTED
            )
            return

        self.state_changed.emit(self._controller.state)

    # -------------------------------------------------------------
    # Slots
    # -------------------------------------------------------------

    @Slot()
    def connect_devices(self) -> None:
        if self._controller is not None:
            self._log(
                "Already connected.",
                "WARNING",
            )
            return

        self._log("Building device drivers…")

        try:
            controller = self._controller_factory()
        except Exception as exc:
            self._report_failure("Device setup", exc)
            self._emit_state()
            return

        self._log(
            "Opening Bronkhorst, LucidControl DO and AI4…"
        )

        try:
            controller.connect()
        except Exception as exc:
            self._report_failure("Connect", exc)
            self._emit_state()
            return

        self._controller = controller

        self._log(
            "Connected. Valve closed, safe state confirmed.",
            "SUCCESS",
        )
        self.connection_changed.emit(True)
        self._emit_state()

    @Slot()
    def disconnect_devices(self) -> None:
        if self._controller is None:
            self._log("Not connected.", "WARNING")
            return

        self._log("Closing valve and releasing ports…")

        try:
            self._controller.disconnect()
        except Exception as exc:
            self._report_failure("Disconnect", exc)
        else:
            self._log("Disconnected.", "SUCCESS")
        finally:
            self._controller = None
            self.connection_changed.emit(False)
            self._emit_state()

    @Slot(bool)
    def set_led(self, enabled: bool) -> None:
        if self._controller is None:
            self._log(
                "LED needs a connection.",
                "WARNING",
            )
            return

        try:
            self._controller.set_led(enabled)
        except Exception as exc:
            self._report_failure("LED switching", exc)
            return

        self._log(
            f"LED switched {'on' if enabled else 'off'}.",
            "SUCCESS",
        )

    @Slot(float, bool, float)
    def start_process(
        self,
        valve_position_percent: float,
        empty_stop_enabled: bool,
        empty_threshold: float,
    ) -> None:
        if self._controller is None:
            self._log(
                "Connect before starting a run.",
                "WARNING",
            )
            return

        controller = self._controller
        previous = controller.empty_detection_settings

        try:
            controller.configure_empty_detection(
                EmptyDetectionSettings(
                    empty_threshold=empty_threshold,
                    filled_threshold=previous.filled_threshold,
                    consecutive_samples=(
                        previous.consecutive_samples
                    ),
                    enabled=empty_stop_enabled,
                )
            )
        except Exception as exc:
            self._report_failure("Empty detection setup", exc)
            return

        self._log(
            "Starting drain run at "
            f"{valve_position_percent:.0f} % valve opening.",
            "SUCCESS",
        )

        self._run_started_monotonic = time.monotonic()
        self._emit_state()

        try:
            summary = controller.start(
                valve_position_percent=valve_position_percent,
                on_measurement=self._forward_measurement,
            )
        except Exception as exc:
            self._report_failure("Drain run", exc)
            self._emit_state()
            return
        finally:
            self._run_started_monotonic = None

        self._log(
            f"Run finished: {summary.stop_reason}",
            "SUCCESS"
            if summary.completed_successfully
            else "WARNING",
        )
        self.run_finished.emit(summary)
        self._emit_state()

    def request_stop(self) -> None:
        """Stops a running process.

        Called directly from the GUI thread while this worker is busy
        inside the measurement loop. It only sets a thread-safe event,
        so it does not touch any serial port itself.
        """

        if self._controller is None:
            return

        self._controller.request_stop(
            "Manual stop requested by operator."
        )

    def shutdown(self) -> None:
        """Best-effort cleanup when the window closes."""

        if self._controller is None:
            return

        try:
            self._controller.disconnect()
        except Exception:
            pass
        finally:
            self._controller = None

    # -------------------------------------------------------------
    # Measurement callback (runs in the worker thread)
    # -------------------------------------------------------------

    def _forward_measurement(
        self,
        measurement: SystemMeasurement,
    ) -> None:
        started = self._run_started_monotonic

        elapsed = (
            time.monotonic() - started
            if started is not None
            else 0.0
        )

        total_volume = (
            self._controller.total_volume_ml
            if self._controller is not None
            else 0.0
        )

        self.measurement_ready.emit(
            measurement,
            elapsed,
            total_volume,
        )


def describe_summary(summary: ProcessSummary) -> str:
    started = summary.started_at.strftime("%H:%M:%S")
    stopped = summary.stopped_at.strftime("%H:%M:%S")

    return (
        f"{started} – {stopped} "
        f"({summary.duration_seconds:.1f} s), "
        f"{summary.total_volume_ml:.1f} ml drained, "
        f"valve {summary.valve_position_percent:.0f} %"
    )


def timestamp_now() -> str:
    return datetime.now().strftime("%H:%M:%S")
