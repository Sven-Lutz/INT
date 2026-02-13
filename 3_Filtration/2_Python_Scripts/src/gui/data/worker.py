from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal

from src.backend.core.device_manager import DeviceManager, DeviceManagerOptions
from src.backend.core.experimentator import Experimentator, ExperimentConfig


class Step(str, Enum):
    BACKWASH_INITIAL = "BACKWASH_INITIAL"
    FILLING = "FILLING"
    FILTRATION = "FILTRATION"
    VENTING = "VENTING"
    BACKWASH_FINAL = "BACKWASH_FINAL"
    FINISHED = "FINISHED"


@dataclass
class RunParams:
    backwash1_duration_s: float
    backwash1_pressure_mbar: Optional[float]

    filling_target_mbar: float
    filling_ramp_s: float
    filling_hold_s: float

    filtration_duration_s: float
    filtration_pressure_mbar: Optional[float]

    venting_duration_s: float

    backwash2_base_remove_ml: float
    backwash2_pressure_mbar: Optional[float]
    backwash2_max_duration_s: float


class ExperimentWorker(QObject):
    request_ok = Signal(str, str)
    status = Signal(str)
    step_changed = Signal(str)
    loss_updated = Signal(float)
    telemetry = Signal(dict)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, cfg: ExperimentConfig):
        super().__init__()
        self.cfg = cfg
        self._ok_event = threading.Event()
        self._ok_event.clear()
        self._params: Optional[RunParams] = None
        self._dev: Optional[DeviceManager] = None
        self._exp: Optional[Experimentator] = None
        self._current_step: Step = Step.BACKWASH_INITIAL
        self._t0: Optional[float] = None

    def set_params(self, params: RunParams) -> None:
        self._params = params

    def confirm_ok(self) -> None:
        self._ok_event.set()

    def _wait_ok(self, step: Step, reason: str) -> None:
        self._ok_event.clear()
        self._current_step = step
        self.step_changed.emit(step.value)
        self.status.emit(f"Waiting for OK: {reason}")
        self.request_ok.emit(step.value, reason)
        self._ok_event.wait()

    def _emit_sample(self, *, event: str = "") -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            return

        if self._t0 is None:
            self._t0 = time.monotonic()

        t = time.monotonic() - self._t0

        flow = None
        try:
            flow = float(dev.read_flow())
        except Exception:
            flow = None

        valve_state = "UNKNOWN"
        try:
            valve_state = dev.get_valve_state()
        except Exception:
            valve_state = "UNKNOWN"

        p1_set = p1_meas = p2_set = p2_meas = None
        if dev.pressure_controller is not None:
            try:
                p1_set = float(dev.get_pressure_setpoint(1))
            except Exception:
                p1_set = None
            try:
                p1_meas = float(dev.get_pressure(1))
            except Exception:
                p1_meas = None
            try:
                p2_set = float(dev.get_pressure_setpoint(2))
            except Exception:
                p2_set = None
            try:
                p2_meas = float(dev.get_pressure(2))
            except Exception:
                p2_meas = None

        vol = None
        try:
            vol = float(exp.volume_ml)
        except Exception:
            vol = None

        self.telemetry.emit(
            {
                "t_s": t,
                "step": self._current_step.value,
                "event": event,
                "flow": flow,
                "p1_set": p1_set,
                "p1_meas": p1_meas,
                "p2_set": p2_set,
                "p2_meas": p2_meas,
                "volume_ml": vol,
                "loss_ml": float(getattr(exp, "last_filtration_venting_loss_ml", 0.0)),
                "valve_state": valve_state,
            }
        )

    def _run_timed_with_telemetry(
        self,
        *,
        mode: str,
        duration_s: float,
        pressure_channel: Optional[int],
        net_sign: float,
        set_valves,
        event_start: str,
        event_end: str,
        telemetry_dt_s: float = 0.2,
    ) -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            raise RuntimeError("Worker not initialized")

        set_valves()
        self._emit_sample(event=event_start)

        t_end = time.monotonic() + float(duration_s)
        next_emit = time.monotonic()

        while time.monotonic() < t_end:
            dt_s, flow_raw = exp._sample_flow()
            net_ml_s = exp._update_volume(dt_s, flow_raw, net_sign=net_sign)
            exp._log_row(mode, dt_s, flow_raw, net_ml_s, pressure_channel=pressure_channel, event="")

            if time.monotonic() >= next_emit:
                self._emit_sample(event="")
                next_emit = time.monotonic() + float(telemetry_dt_s)

            exp._safety_check(mode)
            time.sleep(exp.cfg.sample_period_s)

        exp._log_row(mode, 0.0, exp._last_flow_raw if exp._last_flow_raw is not None else float("nan"), 0.0, pressure_channel=pressure_channel, event=event_end)
        self._emit_sample(event=event_end)

    def run(self) -> None:
        try:
            if self._params is None:
                raise RuntimeError("RunParams not set")

            p = self._params

            opts = DeviceManagerOptions(enable_pressure=True, enable_flow=True)
            self.status.emit("Initializing DeviceManager")

            with DeviceManager(opts) as dev:
                self._dev = dev
                exp = Experimentator(dev, self.cfg)
                self._exp = exp
                self._t0 = None

                try:
                    self._wait_ok(Step.BACKWASH_INITIAL, "Perform initial backwash (setup check) and confirm")
                    self.status.emit("Running initial backwash")
                    self._emit_sample(event="STEP_START")

                    exp.dev.valves_backwash()
                    if p.backwash1_pressure_mbar is not None and dev.pressure_controller is not None:
                        exp.dev.set_pressure(exp._mbar_to_percent(p.backwash1_pressure_mbar), channel=2, ramp=True)

                    self._run_timed_with_telemetry(
                        mode="BACKWASH",
                        duration_s=p.backwash1_duration_s,
                        pressure_channel=2 if dev.pressure_controller is not None else None,
                        net_sign=-1.0,
                        set_valves=dev.valves_backwash,
                        event_start="START_BACKWASH_UI",
                        event_end="END_BACKWASH_UI",
                    )

                    self._wait_ok(Step.FILLING, "Confirm filling parameters and start filling")
                    self.status.emit("Running filling")
                    self._emit_sample(event="STEP_START")

                    exp.step_filling_with_linear_ramp(
                        target_pressure_mbar=p.filling_target_mbar,
                        ramp_duration_s=p.filling_ramp_s,
                        hold_duration_s=p.filling_hold_s,
                    )
                    self._emit_sample(event="END_FILLING_UI")

                    self._wait_ok(Step.FILTRATION, "Confirm filtration parameters and start filtration")
                    self.status.emit("Running filtration")
                    self._emit_sample(event="STEP_START")

                    if p.filtration_pressure_mbar is not None and dev.pressure_controller is not None:
                        dev.set_pressure(exp._mbar_to_percent(p.filtration_pressure_mbar), channel=1, ramp=True)

                    self._run_timed_with_telemetry(
                        mode="FILTRATION",
                        duration_s=p.filtration_duration_s,
                        pressure_channel=1 if dev.pressure_controller is not None else None,
                        net_sign=-1.0,
                        set_valves=dev.valves_filtration,
                        event_start="START_FILTRATION_UI",
                        event_end="END_FILTRATION_UI",
                    )

                    self._wait_ok(Step.VENTING, "Confirm venting duration and start venting")
                    self.status.emit("Running venting")
                    self._emit_sample(event="STEP_START")

                    self._run_timed_with_telemetry(
                        mode="VENTING",
                        duration_s=p.venting_duration_s,
                        pressure_channel=None,
                        net_sign=-1.0,
                        set_valves=dev.venting,
                        event_start="START_VENTING_UI",
                        event_end="END_VENTING_UI",
                    )

                    loss_ml = float(getattr(exp, "last_filtration_venting_loss_ml", 0.0))
                    self.loss_updated.emit(loss_ml)
                    self._emit_sample(event=f"LOSS_UPDATED:{loss_ml:.6f}")

                    self._wait_ok(Step.BACKWASH_FINAL, "Confirm final backwash target (base + loss) and start")
                    self.status.emit("Running final backwash (remove volume)")
                    self._emit_sample(event="STEP_START")

                    removed = exp.step_backwash_remove_volume(
                        base_remove_ml=p.backwash2_base_remove_ml,
                        add_previous_loss=True,
                        max_duration_s=p.backwash2_max_duration_s,
                        backwash_pressure_mbar=p.backwash2_pressure_mbar,
                    )
                    self.status.emit(f"Final backwash completed (removed {removed:.3f} mL)")
                    self._emit_sample(event=f"END_BACKWASH2_UI removed_ml={removed:.6f}")

                finally:
                    try:
                        exp.close()
                    except Exception:
                        pass
                    self._exp = None
                    self._dev = None

            self.step_changed.emit(Step.FINISHED.value)
            self.status.emit("Process finished")
            self.finished.emit()

        except Exception as e:
            self.failed.emit(str(e))
