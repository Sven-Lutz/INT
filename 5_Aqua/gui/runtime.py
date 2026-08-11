from __future__ import annotations

import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from control.empty_detection import EmptyDetectionSettings
from control.state_machine import ProcessState
from control.water_process import WaterProcessController


LOGGER = logging.getLogger("aqua.gui.runtime")


class HardwareWorker(QObject):
    """Owns blocking hardware operations inside a dedicated QThread."""

    state_changed = Signal(str)
    telemetry_received = Signal(object, float, object, bool)
    run_started = Signal()
    run_finished = Signal(object)
    start_cycle_finished = Signal()
    operation_failed = Signal(str, str)
    developer_snapshot = Signal(object)

    def __init__(
        self,
        controller: WaterProcessController,
        *,
        runtime_log_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self.runtime_log_path = runtime_log_path
        self._session_started = time.monotonic()
        self._run_started: float | None = None
        self._poll_timer: QTimer | None = None
        self._last_poll_error: str | None = None
        self._last_poll_error_reported = 0.0

    @Slot()
    def initialize(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self.poll_once)
        self._emit_state()
        self._emit_developer_snapshot()

    @Slot()
    def connect_hardware(self) -> None:
        try:
            LOGGER.info("Connecting hardware")
            self.controller.connect()
            LOGGER.info("Hardware connected; safe state confirmed")
            self._emit_state()
            self._start_idle_polling()
            self.poll_once()
        except Exception as exc:
            LOGGER.exception("Hardware connection failed")
            self.operation_failed.emit("Connect failed", str(exc))
            self._emit_state()
            self._emit_developer_snapshot()

    @Slot()
    def disconnect_hardware(self) -> None:
        if self.controller.state in {ProcessState.RUNNING, ProcessState.STOPPING}:
            LOGGER.warning("Disconnect blocked while a run is active")
            self.operation_failed.emit(
                "Disconnect blocked",
                "Stop the active run before disconnecting hardware.",
            )
            return

        try:
            self._stop_idle_polling()
            LOGGER.info("Disconnecting hardware")
            self.controller.disconnect()
            LOGGER.info("Hardware disconnected")
        except Exception as exc:
            LOGGER.exception("Hardware disconnect failed")
            self.operation_failed.emit("Disconnect failed", str(exc))
        finally:
            self._emit_state()
            self._emit_developer_snapshot()

    @Slot(float, bool, float)
    def start_process(
        self,
        valve_position_percent: float,
        empty_stop_enabled: bool,
        empty_threshold: float,
    ) -> None:
        if self.controller.state not in {ProcessState.READY, ProcessState.STOPPED}:
            LOGGER.warning(
                "Start blocked in state %s",
                self.controller.state.name,
            )
            self.operation_failed.emit(
                "Start blocked",
                f"Cannot start from state {self.controller.state.name}.",
            )
            self.start_cycle_finished.emit()
            return

        try:
            self._stop_idle_polling()
            settings = self.controller.empty_detection_settings
            self.controller.configure_empty_detection(
                EmptyDetectionSettings(
                    empty_threshold=empty_threshold,
                    filled_threshold=settings.filled_threshold,
                    consecutive_samples=settings.consecutive_samples,
                    enabled=empty_stop_enabled,
                )
            )

            self._run_started = time.monotonic()
            self.run_started.emit()
            LOGGER.debug(
                "Starting drain run: valve=%.1f%%, empty stop=%s, "
                "threshold=%.3f scaled units",
                valve_position_percent,
                "on" if empty_stop_enabled else "off",
                empty_threshold,
            )

            summary = self.controller.start(
                valve_position_percent=valve_position_percent,
                on_measurement=self._on_run_measurement,
            )
            LOGGER.debug(
                "Drain run finished: %s; volume=%.2f ml; duration=%.2f s",
                summary.stop_reason,
                summary.total_volume_ml,
                summary.duration_seconds,
            )
            self.run_finished.emit(summary)
        except Exception as exc:
            LOGGER.exception("Drain run failed")
            self.operation_failed.emit("Process failed", str(exc))
        finally:
            try:
                self._run_started = None
                self._emit_state()
                self._emit_developer_snapshot()
                if self.controller.state != ProcessState.DISCONNECTED:
                    self._start_idle_polling()
            finally:
                # Never leave the GUI-side interlock latched, even if a
                # diagnostic update fails while unwinding the worker slot.
                self.start_cycle_finished.emit()

    @Slot(bool)
    def set_led(self, enabled: bool) -> None:
        if self.controller.state == ProcessState.RUNNING:
            LOGGER.warning("LED command blocked while a run is active")
            self.operation_failed.emit(
                "LED change blocked",
                "LED changes are disabled while a drain run is active.",
            )
            return

        try:
            self.controller.set_led(enabled)
            LOGGER.info("LED switched %s", "on" if enabled else "off")
            self.poll_once()
        except Exception as exc:
            LOGGER.exception("LED command failed")
            self.operation_failed.emit("LED command failed", str(exc))

    @Slot()
    def poll_once(self) -> None:
        if self.controller.state in {
            ProcessState.DISCONNECTED,
            ProcessState.RUNNING,
            ProcessState.STOPPING,
        }:
            return

        try:
            measurement = self.controller.measure()
            elapsed = time.monotonic() - self._session_started
            self.telemetry_received.emit(
                measurement,
                elapsed,
                self.controller.total_volume_ml,
                False,
            )
            if self._last_poll_error is not None:
                LOGGER.info("Idle telemetry polling recovered")
                self._last_poll_error = None
                self._last_poll_error_reported = 0.0
            self._emit_developer_snapshot(measurement)
        except Exception as exc:
            message = str(exc)
            now = time.monotonic()
            should_report = (
                message != self._last_poll_error
                or now - self._last_poll_error_reported >= 10.0
            )
            if should_report:
                LOGGER.warning("Idle telemetry poll failed: %s", message)
                self.operation_failed.emit("Telemetry poll failed", message)
                self._last_poll_error_reported = now
            self._last_poll_error = message
            self._emit_developer_snapshot()

    def _on_run_measurement(self, measurement: object) -> None:
        started = self._run_started or time.monotonic()
        elapsed = time.monotonic() - started
        self.telemetry_received.emit(
            measurement,
            elapsed,
            self.controller.total_volume_ml,
            True,
        )
        self._emit_developer_snapshot(measurement)

    def _start_idle_polling(self) -> None:
        if self._poll_timer is not None and not self._poll_timer.isActive():
            self._poll_timer.start()

    def _stop_idle_polling(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()

    def _emit_state(self) -> None:
        self.state_changed.emit(self.controller.state.name)

    def _emit_developer_snapshot(self, measurement: object | None = None) -> None:
        logger = self.controller.logger
        if measurement is None:
            measurement = self.controller.last_measurement
        snapshot: dict[str, Any] = {
            "process_state": self.controller.state.name,
            "repository_measurements": self.controller.repository.measurement_count(),
            "repository_events": self.controller.repository.event_count(),
            "logging_run_active": logger.run_started,
            "measurement_csv": str(
                logger.measurement_path
                or logger.last_measurement_path
                or "—"
            ),
            "event_csv": str(logger.event_path or logger.last_event_path or "—"),
            "summary_csv": str(logger.summary_path),
            "runtime_log": str(self.runtime_log_path or "—"),
            "empty_detector": self.controller.empty_detector.describe(),
        }

        if measurement is not None:
            try:
                snapshot["measurement"] = asdict(measurement)
            except TypeError:
                snapshot["measurement"] = repr(measurement)

        self.developer_snapshot.emit(snapshot)


class ProcessRuntime(QObject):
    """Thread boundary between the Qt operator UI and process hardware."""

    _connect_hardware = Signal()
    _disconnect_hardware = Signal()
    _start_process = Signal(float, bool, float)
    _set_led = Signal(bool)

    state_changed = Signal(str)
    telemetry_received = Signal(object, float, object, bool)
    run_started = Signal()
    run_finished = Signal(object)
    start_interlock_changed = Signal(bool)
    operation_failed = Signal(str, str)
    developer_snapshot = Signal(object)

    def __init__(
        self,
        controller: WaterProcessController,
        *,
        runtime_log_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.controller = controller
        self._shutdown_started = False
        self._start_in_flight = False
        self.thread = QThread(self)
        self.thread.setObjectName("AquaHardwareThread")
        self.worker = HardwareWorker(
            controller,
            runtime_log_path=runtime_log_path,
        )
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)

        self.thread.started.connect(self.worker.initialize)
        self._connect_hardware.connect(self.worker.connect_hardware)
        self._disconnect_hardware.connect(self.worker.disconnect_hardware)
        self._start_process.connect(self.worker.start_process)
        self._set_led.connect(self.worker.set_led)

        self.worker.state_changed.connect(self.state_changed)
        self.worker.telemetry_received.connect(self.telemetry_received)
        self.worker.run_started.connect(self.run_started)
        self.worker.run_finished.connect(self.run_finished)
        self.worker.start_cycle_finished.connect(
            self._release_start_interlock
        )
        self.worker.operation_failed.connect(self.operation_failed)
        self.worker.developer_snapshot.connect(self.developer_snapshot)

        self.thread.start()

    def connect_hardware(self) -> None:
        self._connect_hardware.emit()

    def disconnect_hardware(self) -> None:
        self._disconnect_hardware.emit()

    def start_process(
        self,
        valve_position_percent: float,
        empty_stop_enabled: bool,
        empty_threshold: float,
    ) -> None:
        # This method runs in the GUI thread. Guard before queueing work so a
        # second click cannot remain queued until the first blocking run ends.
        if self._start_in_flight:
            LOGGER.warning("Duplicate START ignored while a run is pending")
            self.operation_failed.emit(
                "Start blocked",
                "A start request is already pending or running.",
            )
            return

        self._start_in_flight = True
        self.start_interlock_changed.emit(True)
        self._start_process.emit(
            valve_position_percent,
            empty_stop_enabled,
            empty_threshold,
        )

    @Slot()
    def _release_start_interlock(self) -> None:
        if not self._start_in_flight:
            return
        self._start_in_flight = False
        self.start_interlock_changed.emit(False)

    def stop_process(self) -> None:
        # controller.start() blocks the worker event loop. request_stop()
        # only sets a threading.Event and is therefore intentionally called
        # directly from the GUI thread so STOP is immediate.
        if self.controller.state == ProcessState.RUNNING:
            self.controller.request_stop("Manual stop requested by operator.")
            self.state_changed.emit(ProcessState.STOPPING.name)

    def set_led(self, enabled: bool) -> None:
        self._set_led.emit(enabled)

    def shutdown(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        LOGGER.debug("Shutting down GUI runtime")
        self.stop_process()
        self.thread.quit()
        if not self.thread.wait(15_000):
            LOGGER.error(
                "Hardware thread did not stop cleanly; skipping concurrent disconnect"
            )
            return

        if self.controller.state != ProcessState.DISCONNECTED:
            try:
                self.controller.disconnect()
            except Exception:
                LOGGER.exception("Final hardware disconnect failed")
