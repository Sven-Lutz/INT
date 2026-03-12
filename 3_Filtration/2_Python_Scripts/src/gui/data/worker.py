# src/gui/data/worker.py
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal, Slot, Qt

from src.backend.core.device_manager import DeviceManager, DeviceManagerOptions
from src.backend.core.experimentator import Experimentator, ExperimentConfig
from src.backend.core.telemetry import RunTelemetryStore, build_run_meta


class Step(str, Enum):
    BACKWASH_INITIAL = "BACKWASH_INITIAL"
    BACKWASH_HOLD = "BACKWASH_HOLD"
    FILLING = "FILLING"
    FILTRATION = "FILTRATION"
    VENTING = "VENTING"
    BACKWASH_FINAL = "BACKWASH_FINAL"
    FINISHED = "FINISHED"
    ABORTED = "ABORTED"


@dataclass
class RunParams:

    v_bnnt_ml: float
    v_h2o_ml: float

    run_phase_0: bool
    phase_0_pressure_mbar: float

    run_phase_a: bool
    phase_a_target_mbar: float
    phase_a_step_mbar: float
    phase_a_time_min: float

    run_phase_b: bool
    v_extra_ml: float

    run_phase_c: bool
    phase_c_rate_mbar_min: float

    run_venting: bool
    venting_duration_s: float

class ExperimentWorker(QObject):
    request_ok = Signal(str, str)
    status = Signal(str)
    step_changed = Signal(str)
    manual_active_changed = Signal(bool)
    loss_updated = Signal(float)
    telemetry = Signal(dict)
    finished = Signal()
    failed = Signal(str)

    cmd_start_backwash_hold = Signal(float)
    cmd_stop_backwash_hold = Signal()
    cmd_abort = Signal(str)
    cmd_manual_vent = Signal()

    log_msg = Signal(str, str)

    def __init__(self, cfg: ExperimentConfig):
        super().__init__()
        self.cfg = cfg

        self._params: Optional[RunParams] = None

        self._ok_event = threading.Event()
        self._ok_event.clear()

        self._abort_event = threading.Event()
        self._abort_event.clear()
        self._abort_reason: str = "Aborted"

        self._hold_active = threading.Event()
        self._hold_active.clear()
        self._hold_pressure_mbar: float = 0.0
        self._hold_dirty_update = threading.Event()

        self._manual_vent_requested = threading.Event()
        self._manual_vent_requested.clear()

        self._dev: Optional[DeviceManager] = None
        self._dev_owned: bool = True

        self._exp: Optional[Experimentator] = None
        self._current_step: Step = Step.BACKWASH_INITIAL

        self._t0: Optional[float] = None
        self._step_t0: Optional[float] = None
        self._step_total_s: Optional[float] = None

        self._store: Optional[RunTelemetryStore] = None

        self.cmd_start_backwash_hold.connect(self._on_cmd_start_backwash_hold, Qt.ConnectionType.QueuedConnection)
        self.cmd_stop_backwash_hold.connect(self._on_cmd_stop_backwash_hold, Qt.ConnectionType.QueuedConnection)
        self.cmd_abort.connect(self._on_cmd_abort, Qt.ConnectionType.QueuedConnection)
        self.cmd_manual_vent.connect(self._on_cmd_manual_vent, Qt.ConnectionType.QueuedConnection)

    def set_params(self, params: RunParams) -> None:
        self._params = params

    def confirm_ok(self) -> None:
        self._ok_event.set()
        try:
            if self._store is not None:
                self._store.write_event("OK_BUTTON_PRESSED", {"step": self._current_step.value})
        except Exception:
            pass

    def set_device_manager(self, dev: DeviceManager) -> None:
        self._dev = dev
        self._dev_owned = False

    def abort(self, reason: str = "User abort") -> None:
        self.cmd_abort.emit(str(reason or "User abort"))

    def start_backwash_hold(self, pressure_mbar: float) -> None:
        self.cmd_start_backwash_hold.emit(float(pressure_mbar))

    def stop_backwash_hold(self) -> None:
        self.cmd_stop_backwash_hold.emit()

    def manual_vent(self) -> None:
        self.cmd_manual_vent.emit()

    @Slot(float)
    def _on_cmd_start_backwash_hold(self, pressure_mbar: float) -> None:
        self._hold_pressure_mbar = float(pressure_mbar)
        if self._hold_active.is_set():
            self._hold_dirty_update.set()
        else:
            self._hold_active.set()

    @Slot()
    def _on_cmd_stop_backwash_hold(self) -> None:
        self._hold_active.clear()
        self._hold_dirty_update.clear()

    @Slot(str)
    def _on_cmd_abort(self, reason: str) -> None:
        self._abort_reason = str(reason or "Aborted")
        self._abort_event.set()
        self._ok_event.set()
        self._hold_active.clear()
        self._hold_dirty_update.clear()
        try:
            if self._store is not None:
                self._store.write_event(
                    "ABORT_REQUESTED",
                    {"reason": self._abort_reason, "step": self._current_step.value},
                )
        except Exception:
            pass

    @Slot()
    def _on_cmd_manual_vent(self) -> None:
        self._manual_vent_requested.set()

    def _should_abort(self) -> bool:
        return self._abort_event.is_set()

    def _raise_if_abort(self) -> None:
        if self._should_abort():
            raise RuntimeError(self._abort_reason)

    def _sleep_abortable(self, seconds: float, *, tick: float = 0.05) -> None:
        t_end = time.monotonic() + float(max(0.0, seconds))
        while True:
            self._raise_if_abort()
            now = time.monotonic()
            if now >= t_end:
                return
            time.sleep(float(min(tick, t_end - now)))

    def _wait_ok(self, step: Step, reason: str) -> None:
        self._ok_event.clear()
        self._current_step = step

        self._step_t0 = time.monotonic()
        self._step_total_s = None

        self.step_changed.emit(step.value)
        self.status.emit(f"Waiting for OK: {reason}")
        self.request_ok.emit(step.value, reason)
        try:
            if self._store is not None:
                self._store.write_event("OK_GATE_REQUESTED", {"step": step.value, "reason": reason})
        except Exception:
            pass

        while not self._ok_event.wait(timeout=0.1):
            self._raise_if_abort()
            self._apply_manual_vent_if_requested()

        try:
            if self._store is not None:
                self._store.write_event("OK_CONFIRMED", {"step": step.value})
        except Exception:
            pass

    def _ensure_t0(self) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()
            try:
                if self._store is not None:
                    self._store.set_run_start(self._t0)
            except Exception:
                pass

    def _emit_sample(self, *, event: str = "") -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            return

        self._ensure_t0()
        now = time.monotonic()
        assert self._t0 is not None
        t_s = now - float(self._t0)

        step_elapsed_s = (now - self._step_t0) if self._step_t0 is not None else None

        try:
            flow = float(dev.read_flow())
        except Exception:
            flow = None

        try:
            valve_state = str(dev.get_valve_state())
        except Exception:
            valve_state = "UNKNOWN"

        p1_set = p1_meas = p2_set = p2_meas = None
        if getattr(dev, "pressure_controller", None) is not None:
            try:
                if hasattr(dev, "get_pressure_setpoint_mbar"):
                    _val = dev.get_pressure_setpoint_mbar(1) # type: ignore
                    p1_set = float(_val) if _val is not None else None
                else:
                    _val = dev.get_pressure_setpoint(1)
                    p1_set = float(_val) if _val is not None else None
            except Exception:
                p1_set = None
            try:
                p1_meas = float(dev.get_pressure_mbar(1)) if hasattr(dev, "get_pressure_mbar") else float(
                    dev.get_pressure(1))
            except Exception:
                p1_meas = None
            try:
                p2_set = float(dev.get_pressure_setpoint_mbar(2)) if hasattr(dev,
                                                                             "get_pressure_setpoint_mbar") else float(
                    dev.get_pressure_setpoint(2))
            except Exception:
                p2_set = None
            try:
                p2_meas = float(dev.get_pressure_mbar(2)) if hasattr(dev, "get_pressure_mbar") else float(
                    dev.get_pressure(2))
            except Exception:
                p2_meas = None

        try:
            vol = float(exp.volume_ml)
        except Exception:
            vol = None

        try:
            loss = float(getattr(exp, "last_filtration_venting_loss_ml", 0.0))
        except Exception:
            loss = 0.0

        sample = {
            "t": t_s,
            "step": self._current_step.value,
            "event": str(event or ""),
            "flow": flow,
            "p1_set": p1_set,
            "p1_meas": p1_meas,
            "p2_set": p2_set,
            "p2_meas": p2_meas,
            "volume_ml": vol,
            "loss_ml": loss,
            "valves": valve_state,
            "manual_active": bool(self._hold_active.is_set()),
            "step_elapsed_s": step_elapsed_s,
            "step_total_s": self._step_total_s,
            "run_elapsed_s": t_s,
            "pressure": {
                1: {"set": p1_set, "meas": p1_meas},
                2: {"set": p2_set, "meas": p2_meas},
            },
        }

        self.telemetry.emit(sample)

        try:
            if self._store is not None:
                self._store.write_sample(sample)
        except Exception:
            pass

    def _safe_set_pressure_mbar(self, *, channel: int, mbar: float) -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            return
        if getattr(dev, "pressure_controller", None) is None:
            return

        try:
            if hasattr(dev, "set_pressure_setpoint_mbar"):
                dev.set_pressure_setpoint_mbar(channel=int(channel), setpoint_mbar=float(mbar),
                                               ramp=True)  # type: ignore[attr-defined]
                return
        except Exception:
            pass

        try:
            pct = exp._mbar_to_percent(float(mbar))
            try:
                exp._set_pressure_pct(channel=int(channel), pct=float(pct), ramp=True)  # type: ignore[attr-defined]
            except Exception:
                dev.set_pressure(float(pct), channel=int(channel), ramp=True)
        except Exception:
            pass

    def _safe_drop_pressure_all(self) -> None:
        dev = self._dev
        if dev is None:
            return
        if getattr(dev, "pressure_controller", None) is None:
            return
        for ch in (1, 2):
            try:
                self._safe_set_pressure_mbar(channel=ch, mbar=0.0)
            except Exception:
                continue

    def _safe_valves_vent(self) -> None:
        dev = self._dev
        if dev is None:
            return
        try:
            if hasattr(dev, "valves_venting"):
                dev.valves_venting()
            elif hasattr(dev, "venting"):
                dev.venting()  # type: ignore[attr-defined]
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state(getattr(dev, "STATE_VENTING", "VENTING"))  # type: ignore[attr-defined]
        except Exception:
            pass

    def _apply_manual_vent_if_requested(self) -> None:
        if not self._manual_vent_requested.is_set():
            return
        self._manual_vent_requested.clear()

        self.status.emit("Manual vent requested (best-effort safe)")

        try:
            if self._store is not None:
                self._store.write_event("MANUAL_VENT_REQUESTED", {"step": self._current_step.value})
        except Exception:
            pass

        try:
            self._safe_drop_pressure_all()
        except Exception:
            pass
        try:
            self._safe_valves_vent()
        except Exception:
            pass

        self._emit_sample(event="MANUAL_VENT")

        try:
            if self._store is not None:
                self._store.write_event("MANUAL_VENT_APPLIED", {"step": self._current_step.value})
        except Exception:
            pass

    def _run_timed_with_telemetry(
            self,
            *,
            step: Step,
            mode: str,
            duration_s: float,
            pressure_channel: Optional[int],
            net_sign: float,
            set_valves: Callable[[], None],
            event_start: str,
            event_end: str,
            telemetry_dt_s: float = 0.2,
    ) -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            raise RuntimeError("Worker not initialized")

        self._current_step = step
        self._step_t0 = time.monotonic()
        self._step_total_s = float(max(0.0, duration_s))

        self.step_changed.emit(step.value)

        try:
            set_valves()
        except Exception:
            pass

        self.status.emit(f"Running {step.value}")
        self._emit_sample(event=event_start)

        try:
            if self._store is not None:
                self._store.write_event("STEP_START", {"step": step.value, "mode": str(mode), "event": event_start})
        except Exception:
            pass

        t_end = time.monotonic() + float(max(0.0, duration_s))
        next_emit = time.monotonic()

        while time.monotonic() < t_end:
            self._raise_if_abort()
            self._apply_manual_vent_if_requested()

            dt_s, flow_raw = exp._sample_flow()
            flow_ml_s = exp._flow_to_ml_per_s(flow_raw)
            net_ml_s = exp._update_volume(dt_s, flow_raw, net_sign=float(net_sign))

            exp._log_row(
                str(mode),
                float(dt_s),
                float(flow_raw),
                float(flow_ml_s),
                net_flow_ml_s=float(net_ml_s),
                pressure_channel=pressure_channel,
                event="",
            )

            now = time.monotonic()
            if now >= next_emit:
                self._emit_sample(event="")
                next_emit = now + float(telemetry_dt_s)

            exp._safety_check(str(mode))
            self._sleep_abortable(float(exp.cfg.sample_period_s), tick=0.05)

        exp._log_row(
            str(mode),
            0.0,
            exp._last_flow_raw if exp._last_flow_raw is not None else float("nan"),
            0.0,
            net_flow_ml_s=0.0,
            pressure_channel=pressure_channel,
            event=str(event_end),
        )
        self._emit_sample(event=event_end)

        try:
            if self._store is not None:
                self._store.write_event("STEP_END", {"step": step.value, "mode": str(mode), "event": event_end})
        except Exception:
            pass

    def _run_backwash_hold_loop(self, *, telemetry_dt_s: float = 0.2) -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            return

        self._current_step = Step.BACKWASH_HOLD
        self._step_t0 = time.monotonic()
        self._step_total_s = None

        self.step_changed.emit(Step.BACKWASH_HOLD.value)
        self.status.emit("Backwash HOLD active (manual fine)")
        self.manual_active_changed.emit(True)

        try:
            dev.valves_backwash()
        except Exception:
            try:
                dev.set_valve_state(getattr(dev, "STATE_BACKWASH", "BACKWASH"))  # type: ignore[attr-defined]
            except Exception:
                pass

        if getattr(dev, "pressure_controller", None) is not None:
            self._safe_set_pressure_mbar(channel=2, mbar=float(self._hold_pressure_mbar))

        self._emit_sample(event="START_BACKWASH_HOLD")
        try:
            if self._store is not None:
                self._store.write_event(
                    "BACKWASH_HOLD_START",
                    {"pressure_mbar": float(self._hold_pressure_mbar), "step": Step.BACKWASH_HOLD.value},
                )
        except Exception:
            pass

        next_emit = time.monotonic()

        while self._hold_active.is_set():
            self._raise_if_abort()
            self._apply_manual_vent_if_requested()

            if self._hold_dirty_update.is_set():
                self._hold_dirty_update.clear()
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=2, mbar=float(self._hold_pressure_mbar))
                self._emit_sample(event=f"HOLD_SETPOINT_UPDATE:{self._hold_pressure_mbar:.0f}")
                try:
                    if self._store is not None:
                        self._store.write_event(
                            "BACKWASH_HOLD_SETPOINT_UPDATE",
                            {"pressure_mbar": float(self._hold_pressure_mbar)},
                        )
                except Exception:
                    pass

            dt_s, flow_raw = exp._sample_flow()
            flow_ml_s = exp._flow_to_ml_per_s(flow_raw)
            net_ml_s = exp._update_volume(dt_s, flow_raw, net_sign=-1.0)

            exp._log_row(
                "BACKWASH_HOLD",
                float(dt_s),
                float(flow_raw),
                float(flow_ml_s),
                net_flow_ml_s=float(net_ml_s),
                pressure_channel=2 if getattr(dev, "pressure_controller", None) is not None else None,
                event="",
            )

            now = time.monotonic()
            if now >= next_emit:
                self._emit_sample(event="")
                next_emit = now + float(telemetry_dt_s)

            exp._safety_check("BACKWASH_HOLD")
            self._sleep_abortable(float(exp.cfg.sample_period_s), tick=0.05)

        self._safe_drop_pressure_all()

        exp._log_row(
            "BACKWASH_HOLD",
            0.0,
            exp._last_flow_raw if exp._last_flow_raw is not None else float("nan"),
            0.0,
            net_flow_ml_s=0.0,
            pressure_channel=2 if getattr(dev, "pressure_controller", None) is not None else None,
            event="END_BACKWASH_HOLD",
        )

        self._emit_sample(event="END_BACKWASH_HOLD")
        self.status.emit("Backwash HOLD stopped")
        self.manual_active_changed.emit(False)

        try:
            if self._store is not None:
                self._store.write_event("BACKWASH_HOLD_END", {"step": Step.BACKWASH_HOLD.value})
        except Exception:
            pass

    def _enter_safe_state(self) -> None:
        try:
            self._hold_active.clear()
            self._hold_dirty_update.clear()
        except Exception:
            pass

        try:
            if self._dev is not None and hasattr(self._dev, "vent_all"):
                self._dev.vent_all()  # type: ignore[attr-defined]
            else:
                self._safe_drop_pressure_all()
                self._safe_valves_vent()
        except Exception:
            pass

        try:
            if self._store is not None:
                self._store.write_event("SAFE_STATE", {"step": self._current_step.value})
        except Exception:
            pass

        try:
            self._emit_sample(event="SAFE_STATE")
        except Exception:
            pass

    @Slot()
    def run(self) -> None:
        dev_cm = None
        try:
            if self._params is None:
                raise RuntimeError("RunParams not set")
            p = self._params

            if self._dev is None:
                opts = DeviceManagerOptions(enable_pressure=True, enable_flow=True)
                self.status.emit("Initializing DeviceManager")
                self._dev = DeviceManager(opts)
                self._dev_owned = True
            else:
                self.status.emit("Using injected DeviceManager")

            dev = self._dev
            if dev is None:
                raise RuntimeError("DeviceManager missing")

            if self._dev_owned:
                try:
                    dev_cm = dev
                    dev_cm.__enter__()
                except Exception:
                    dev_cm = None

            self._raise_if_abort()

            self._exp = Experimentator(dev, self.cfg) # type: ignore
            self._t0 = None

            try:
                meta = build_run_meta(
                    experiment_config=self.cfg,
                    run_params=p,
                    extra={
                        "experimentator_log_path": getattr(self._exp, "log_path", ""),
                        "notes": "canonical telemetry emitted from worker._emit_sample",
                    },
                )
                self._store = RunTelemetryStore(meta=meta)
                self._store.write_event("RUN_START", {"step": self._current_step.value})
            except Exception as e:
                self._store = None
                self.status.emit(f"Telemetry store disabled: {e}")

            # =================================================================
            # MODULARE ABLAUFSTEUERUNG (Basierend auf UI-Checkboxes)
            # =================================================================
            
# =================================================================
            # MODULARE ABLAUFSTEUERUNG (Basierend auf UI-Checkboxes)
            # =================================================================
            
            target_vol = float(p.v_bnnt_ml) + float(p.v_h2o_ml)
            total_loss = 0.0

            def ramp_step_callback(msg: str):
                self._wait_ok(self._current_step, msg)

            # --- PHASE 0: FILLING ---
            if p.run_phase_0:
                self._current_step = Step.FILLING
                self.step_changed.emit("FILLING")
                self._wait_ok(Step.FILLING, f"Confirm Phase 0: Fill cell at {p.phase_0_pressure_mbar} mbar")
                self.status.emit("Running Phase 0 (Filling)")
                self._emit_sample(event="STEP_START_PHASE_0")
                
                try: dev.valves_filling_solution() # type: ignore
                except Exception: pass
                
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=int(self.cfg.main_pressure_channel), mbar=float(p.phase_0_pressure_mbar))
                
                self._wait_ok(Step.FILLING, "Phase 0 active. Click OK when cell is completely filled.")
                
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=int(self.cfg.main_pressure_channel), mbar=0.0)

            # --- PHASE A: RAMP UP ---
            if p.run_phase_a:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_A") # Eindeutiges Signal für das UI
                self._wait_ok(Step.FILTRATION, f"Start Phase A: Ramp up to {p.phase_a_target_mbar} mbar")
                self.status.emit("Running Phase A")
                self._emit_sample(event="STEP_START_PHASE_A")
                
                loss_a = self._exp.step_staircase_ramp(
                    target_pressure_mbar=float(p.phase_a_target_mbar),
                    step_size_mbar=float(p.phase_a_step_mbar),
                    step_time_s=float(p.phase_a_time_min * 60.0),
                    wait_for_ok_fn=ramp_step_callback 
                )
                total_loss += loss_a

            # --- PHASE B: STEADY STATE & DRY ---
            if p.run_phase_b:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_B")
                self._wait_ok(Step.FILTRATION, f"Start Phase B1: Hold until {target_vol:.2f}ml removed")
                self.status.emit("Running Phase B1")
                self._emit_sample(event="STEP_START_PHASE_B1")
                
                loss_b1 = self._exp.step_steady_state_volume_target(
                    target_volume_ml_to_remove=target_vol,
                    pressure_mbar=float(p.phase_a_target_mbar),
                    max_duration_s=86400.0 # Timeout Sicherung
                )
                total_loss += loss_b1

                if p.v_extra_ml > 0:
                    self._wait_ok(Step.FILTRATION, f"Start Phase B2: Dry with {p.v_extra_ml:.2f}ml extra")
                    self.status.emit("Running Phase B2")
                    loss_b2 = self._exp.step_steady_state_volume_target(
                        target_volume_ml_to_remove=float(p.v_extra_ml),
                        pressure_mbar=float(p.phase_a_target_mbar),
                        max_duration_s=86400.0
                    )
                    total_loss += loss_b2

            # --- PHASE C: RAMP DOWN ---
            if p.run_phase_c:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_C")
                self._wait_ok(Step.FILTRATION, "Start Phase C: Smooth Ramp Down")
                self.status.emit("Running Phase C")
                self._emit_sample(event="STEP_START_PHASE_C")
                
                # Wir übersetzen die Rate in kleine Sekundenschritte für einen sauberen Abbau!
                rate_mbar_s = float(p.phase_c_rate_mbar_min) / 60.0
                
                loss_c = self._exp.step_staircase_ramp_down( # type: ignore
                    start_pressure_mbar=float(p.phase_a_target_mbar),
                    step_size_mbar=rate_mbar_s, # Kleine Schritte
                    step_time_s=1.0,            # Jede Sekunde
                    wait_for_ok_fn=None         # Keine Abfragen mehr, es fährt automatisch runter!
                )
                total_loss += loss_c

            # --- VENTING ---
            if p.run_venting:
                self._current_step = Step.VENTING
                self.step_changed.emit("VENTING")
                self._wait_ok(Step.VENTING, "Confirm venting duration")
                self.status.emit("Running venting")
                self._emit_sample(event="STEP_START_VENTING")

                self._run_timed_with_telemetry(
                    step=Step.VENTING,
                    mode="VENTING",
                    duration_s=float(p.venting_duration_s),
                    pressure_channel=None,
                    net_sign=-1.0,
                    set_valves=getattr(dev, "valves_venting", dev.valves_venting), # type: ignore
                    event_start="START_VENTING",
                    event_end="END_VENTING",
                )

            # --- ABSCHLUSS & BILANZ ---
            self._exp.last_filtration_venting_loss_ml = float(total_loss)
            self.loss_updated.emit(total_loss)
            self._emit_sample(event=f"END_SEQUENCE total_loss={total_loss:.4f}")
            
            self.log_msg.emit("--- FINAL VOLUME BALANCE ---", "#00E5FF")
            self.log_msg.emit(f"TOTAL LOST: {total_loss:.3f} ml", "#EC4899")
            
            # =================================================================
            # SEQUENCE ENDE
            # =================================================================
            if self._should_abort():
                self.step_changed.emit(Step.ABORTED.value)
                self.status.emit(f"Aborted: {self._abort_reason}")
                try:
                    if self._store is not None:
                        self._store.write_event("RUN_END", {"status": "ABORTED", "reason": self._abort_reason})
                except Exception:
                    pass
            else:
                self.step_changed.emit(Step.FINISHED.value)
                self.status.emit("Process finished")
                try:
                    if self._store is not None:
                        self._store.write_event("RUN_END", {"status": "FINISHED"})
                except Exception:
                    pass
                self.finished.emit()

        except Exception as e:
            tb = traceback.format_exc()
            msg = f"{e}\n\n{tb}"
            self.step_changed.emit(Step.ABORTED.value)
            self.status.emit(f"Failed: {e}")
            try:
                self.manual_active_changed.emit(False)
            except Exception:
                pass
            try:
                if self._store is not None:
                    self._store.write_event("RUN_FAILED", {"error": str(e), "traceback": tb})
            except Exception:
                pass
            self.failed.emit(msg)

        finally:
            try:
                self._enter_safe_state()
            except Exception:
                pass

            try:
                if self._exp is not None:
                    self._exp.close()
            except Exception:
                pass
            self._exp = None

            try:
                if self._store is not None:
                    self._store.close()
            except Exception:
                pass
            self._store = None

            if self._dev_owned and self._dev is not None:
                try:
                    if hasattr(self._dev, "__exit__"):
                        self._dev.__exit__(None, None, None)
                    elif hasattr(self._dev, "disconnect"):
                        self._dev.disconnect()
                except Exception:
                    pass
                self._dev = None

            if dev_cm is not None:
                try:
                    dev_cm.__exit__(None, None, None)
                except Exception:
                    pass