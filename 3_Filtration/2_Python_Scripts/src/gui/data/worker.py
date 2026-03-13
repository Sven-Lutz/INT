from __future__ import annotations

import csv
import logging
import os
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from PySide6.QtCore import QObject, Signal, Slot, Qt

from src.backend.core.device_manager import DeviceManager, DeviceManagerOptions
from src.utils.path_utils import ensure_dir, project_root, resolve_under
from src.backend.core.telemetry import RunTelemetryStore, build_run_meta

logger = logging.getLogger(__name__)

# =========================================================================
# HELPER & PROTOKOLLE
# =========================================================================
def _ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _is_finite_number(x: Any) -> bool:
    try:
        v = float(x)
    except Exception:
        return False
    return v == v and v not in (float("inf"), float("-inf"))

def robust_switch_valves(dev: Any, mode: str, log_signal: Optional[Any] = None) -> None:
    """Kugelsicherer Ventil-Schalter mit 'Break before Make' Logik."""
    if dev is None: return
    mode = mode.upper()
    
    # 🚀 FLUIDIC SAFETY: Zuerst IMMER alles schließen (außer wir wollen explizit nur schließen)
    if mode != "SHUT":
        try:
            if hasattr(dev, "all_valves_shut"): dev.all_valves_shut()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("SHUT")
            import time
            time.sleep(0.1) # 100ms warten, damit die physischen Relais/Ventile sicher zu sind!
        except Exception as e:
            print(f"HW WARNING: Could not pre-shut valves: {e}")

    msg = f"HW CMD: Switching valves to {mode}"
    print(f">>> {msg}")
    
    if log_signal is not None and hasattr(log_signal, "emit"):
        log_signal.emit(msg, "#94A3B8")
        
    try:
        if mode == "FILLING":
            if hasattr(dev, "valves_filling_solution"): dev.valves_filling_solution()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("FILLING")
            else: raise RuntimeError("No FILLING method on device")
        elif mode == "FILTRATION":
            if hasattr(dev, "valves_filtration"): dev.valves_filtration()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("FILTRATION")
            else: raise RuntimeError("No FILTRATION method on device")
        elif mode == "BACKWASH":
            if hasattr(dev, "valves_backwash"): dev.valves_backwash()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("BACKWASH")
            else: raise RuntimeError("No BACKWASH method on device")
        elif mode == "VENTING":
            if hasattr(dev, "valves_venting"): dev.valves_venting()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("VENTING")
            else: raise RuntimeError("No VENTING method on device")
        elif mode == "SHUT":
            if hasattr(dev, "all_valves_shut"): dev.all_valves_shut()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("SHUT")
            else: raise RuntimeError("No SHUT method on device")
    except Exception as e:
        err = f"VALVE ERROR ({mode}): {e}"
        print(f"!!! {err} !!!")
        if log_signal is not None and hasattr(log_signal, "emit"):
            log_signal.emit(err, "#FF1744")

class _PressureControllerProto(Protocol):
    def set_pressure(self, *args, **kwargs): ...
    def read_pressure(self, *args, **kwargs): ...
    def read_setpoint(self, *args, **kwargs): ...

class _DeviceProto(Protocol):
    pressure_controller: Optional[_PressureControllerProto]
    def read_flow(self) -> float: ...
    def get_valve_state(self) -> str: ...
    def valves_backwash(self) -> None: ...
    def valves_filling_solution(self) -> None: ...
    def valves_filtration(self) -> None: ...
    def valves_venting(self) -> None: ...
    def all_valves_shut(self) -> None: ...
    def get_pressure_setpoint(self, channel: int) -> float: ...
    def get_pressure(self, channel: int) -> float: ...
    def set_pressure(self, value, channel: int, ramp: bool = True) -> None: ...
    def get_pressure_setpoint_mbar(self, channel: int) -> float: ...
    def get_pressure_mbar(self, channel: int) -> float: ...
    def set_pressure_setpoint_mbar(self, *, channel: int, setpoint_mbar: float, ramp: bool = True) -> None: ...

# =========================================================================
# EXPERIMENT CONFIG & DATA CLASSES
# =========================================================================
@dataclass
class ExperimentConfig:
    initial_volume_ml: float
    min_volume_ml: float = 0.0
    sample_period_s: float = 0.2
    ramp_update_dt_s: float = 0.15
    log_dir: str = "logs"
    log_name_prefix: str = "run"
    log_flush_every_n: int = 10
    log_flush_every_s: float = 1.0
    log_fsync_on_flush: bool = False
    flow_is_ml_per_min: bool = True
    pressure_full_scale_mbar: float = 8000.0
    base_backwash_remove_ml: float = 0.0
    flow_deadband_ml_per_s: float = 0.01
    clamp_volume_to_min: bool = True
    main_pressure_channel: int = 1
    backwash_pressure_channel: int = 2
    max_dt_s: float = 2.0
    write_csv_preamble: bool = True

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

    # Phase 0
    run_phase_0: bool
    run_phase_a: bool
    run_phase_b: bool
    run_phase_c: bool

    phase_0_mode: str = "auto"
    phase_0_pressure_mbar: float = 300.0

    # Phase A
    phase_a_mode: str = "auto" 
    phase_a_target_mbar: float = 2000.0
    phase_a_step_mbar: float = 250.0
    phase_a_time_min: float = 2.0

    # Phase B
    v_extra_ml: float = 0.0

    # Phase C
    phase_c_rate_mbar_min: float = 500.0
    
    # 🚀 RUN_VENTING WURDE ENTFERNT

# =========================================================================
# EXPERIMENT WORKER (ELITE LOGIC)
# =========================================================================
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
        self._abort_event = threading.Event()
        self._abort_reason: str = "Aborted"
        self._hold_active = threading.Event()
        self._hold_pressure_mbar: float = 0.0
        self._hold_dirty_update = threading.Event()
        self._manual_vent_requested = threading.Event()
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
        except Exception: pass

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
        if self._hold_active.is_set(): self._hold_dirty_update.set()
        else: self._hold_active.set()

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
                self._store.write_event("ABORT_REQUESTED", {"reason": self._abort_reason, "step": self._current_step.value})
        except Exception: pass

    @Slot()
    def _on_cmd_manual_vent(self) -> None:
        self._manual_vent_requested.set()

    def _should_abort(self) -> bool:
        return self._abort_event.is_set()

    def _raise_if_abort(self) -> None:
        if self._should_abort(): raise RuntimeError(self._abort_reason)

    def _sleep_abortable(self, seconds: float, *, tick: float = 0.05) -> None:
        t_end = time.monotonic() + float(max(0.0, seconds))
        while True:
            self._raise_if_abort()
            now = time.monotonic()
            if now >= t_end: return
            time.sleep(float(min(tick, t_end - now)))

    def _wait_ok(self, step: Step, reason: str) -> None:
        self._ok_event.clear()
        self._current_step = step
        self._step_t0 = time.monotonic()
        self._step_total_s = None

        self.step_changed.emit(step.value)
        self.status.emit(f"Waiting for OK: {reason}")
        self.request_ok.emit(step.value, reason)

        while not self._ok_event.wait(timeout=0.1):
            self._raise_if_abort()
            self._apply_manual_vent_if_requested()

    def _ensure_t0(self) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()

    def _emit_sample(self, *, event: str = "") -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None: return

        self._ensure_t0()
        now = time.monotonic()
        t_s = now - float(self._t0) # type: ignore

        try: flow = float(dev.read_flow())
        except Exception: flow = 0.0

        try: valve_state = str(dev.get_valve_state())
        except Exception: valve_state = "UNKNOWN"

        p1_set = p1_meas = p2_set = p2_meas = 0.0
        if getattr(dev, "pressure_controller", None) is not None:
            try: p1_set = float(dev.get_pressure_setpoint_mbar(1))
            except Exception: pass
            try: p1_meas = float(dev.get_pressure_mbar(1))
            except Exception: pass
            try: p2_set = float(dev.get_pressure_setpoint_mbar(2))
            except Exception: pass
            try: p2_meas = float(dev.get_pressure_mbar(2))
            except Exception: pass

        try: vol = float(exp.volume_ml)
        except Exception: vol = 0.0

        try: loss = float(getattr(exp, "last_filtration_venting_loss_ml", 0.0))
        except Exception: loss = 0.0

        sample = {
            "t": t_s,
            "step": self._current_step.value,
            "event": str(event or ""),
            "flow": flow,
            "p1_set": p1_set, "p1_meas": p1_meas,
            "p2_set": p2_set, "p2_meas": p2_meas,
            "volume_ml": vol, "loss_ml": loss,
            "valves": valve_state,
            "manual_active": bool(self._hold_active.is_set()),
            "pressure": {
                1: {"set": p1_set, "meas": p1_meas},
                2: {"set": p2_set, "meas": p2_meas},
            },
        }

        self.telemetry.emit(sample)
        try:
            if self._store is not None: self._store.write_sample(sample)
        except Exception: pass

    def _safe_set_pressure_mbar(self, *, channel: int, mbar: float) -> None:
        dev = self._dev
        if dev is None or getattr(dev, "pressure_controller", None) is None: return
        try: dev.set_pressure_setpoint_mbar(channel=int(channel), setpoint_mbar=float(mbar))
        except Exception: pass

    def _safe_drop_pressure_all(self) -> None:
        for ch in (1, 2):
            try: self._safe_set_pressure_mbar(channel=ch, mbar=0.0)
            except Exception: continue

    def _safe_valves_vent(self) -> None:
        try: self._dev.set_valve_state("VENTING") # type: ignore
        except Exception: pass

    def _apply_manual_vent_if_requested(self) -> None:
        if not self._manual_vent_requested.is_set(): return
        self._manual_vent_requested.clear()
        self.status.emit("Manual vent requested (best-effort safe)")
        try: self._safe_drop_pressure_all()
        except Exception: pass
        try: self._safe_valves_vent()
        except Exception: pass
        self._emit_sample(event="MANUAL_VENT")

    def _run_timed_with_telemetry(self, *, step: Step, mode: str, duration_s: float, pressure_channel: Optional[int], net_sign: float, set_valves: Callable[[], None], event_start: str, event_end: str, telemetry_dt_s: float = 0.2) -> None:
        dev = self._dev
        exp = self._exp
        self._current_step = step
        self.step_changed.emit(step.value)
        try: set_valves()
        except Exception: pass
        self.status.emit(f"Running {step.value}")
        self._emit_sample(event=event_start)
        t_end = time.monotonic() + float(max(0.0, duration_s))
        next_emit = time.monotonic()

        while time.monotonic() < t_end:
            self._raise_if_abort()
            self._apply_manual_vent_if_requested()
            dt_s, flow_raw = exp._sample_flow() # type: ignore
            flow_ml_s = exp._flow_to_ml_per_s(flow_raw) # type: ignore
            net_ml_s = exp._update_volume(dt_s, flow_raw, net_sign=float(net_sign)) # type: ignore
            exp._log_row(str(mode), float(dt_s), float(flow_raw), float(flow_ml_s), net_flow_ml_s=float(net_ml_s), pressure_channel=pressure_channel, event="") # type: ignore
            now = time.monotonic()
            if now >= next_emit:
                self._emit_sample(event="")
                next_emit = now + float(telemetry_dt_s)
            exp._safety_check(str(mode)) # type: ignore
            self._sleep_abortable(float(exp.cfg.sample_period_s), tick=0.05) # type: ignore

        self._emit_sample(event=event_end)

    def _enter_safe_state(self) -> None:
        try: self._hold_active.clear()
        except Exception: pass
        try:
            if self._dev is not None and hasattr(self._dev, "vent_all"): self._dev.vent_all()
            else:
                self._safe_drop_pressure_all()
                self._safe_valves_vent()
        except Exception: pass
        try: self._emit_sample(event="SAFE_STATE")
        except Exception: pass

    # =================================================================
    # 🚀 CORE EXPERIMENT RUN LOGIC
    # =================================================================
    @Slot()
    def run(self) -> None:
        dev_cm = None
        try:
            if self._params is None: raise RuntimeError("RunParams not set")
            p = self._params

            if self._dev is None:
                opts = DeviceManagerOptions(enable_pressure=True, enable_flow=True)
                self.status.emit("Initializing DeviceManager")
                self._dev = DeviceManager(opts)
                self._dev_owned = True

            dev = self._dev
            if dev is None: raise RuntimeError("DeviceManager missing")

            if self._dev_owned:
                try:
                    dev_cm = dev
                    dev_cm.__enter__()
                except Exception: dev_cm = None

            self._raise_if_abort()

            self._exp = Experimentator(dev, self.cfg) # type: ignore
            self._t0 = None

            try:
                meta = build_run_meta(experiment_config=self.cfg, run_params=p)
                self._store = RunTelemetryStore(meta=meta)
                self._store.write_event("RUN_START", {"step": self._current_step.value})
            except Exception: self._store = None

            target_vol = float(p.v_bnnt_ml) + float(p.v_h2o_ml)
            total_loss = 0.0

            # --- PHASE 0: FILLING SOLUTION ---
            if p.run_phase_0:
                self._current_step = Step.FILLING
                self.step_changed.emit("FILLING")
                
                # 🚀 Echte Hardware-Calls für Ventile
                self.log_msg.emit("HW: Switching to FILLING valves...", "#94A3B8")
                if hasattr(dev, "valves_filling_solution"):
                    dev.valves_filling_solution()
                elif hasattr(dev, "set_valve_state"):
                    dev.set_valve_state("FILLING")
                
                time.sleep(1.0) # Hardware Zeit geben zum Umschalten!
                
                if getattr(dev, "pressure_controller", None) is not None:
                    self.log_msg.emit(f"HW: Setting Pressure to {p.phase_0_pressure_mbar} mbar", "#94A3B8")
                    self._safe_set_pressure_mbar(channel=int(self.cfg.main_pressure_channel), mbar=float(p.phase_0_pressure_mbar))

                if p.phase_0_mode == "continuous":
                    self.status.emit("FILLING: Continuous (Click OK to Stop)")
                    self.log_msg.emit("Continuous Fill active. Press OK when full.", "#00E5FF")
                    self._wait_ok(Step.FILLING, "Stop continuous filling")
                else:
                    self.status.emit(f"FILLING: Auto target {target_vol:.2f} mL")
                    self.log_msg.emit(f"Auto Fill started: target {target_vol:.2f} mL.", "#00E5FF")
                    start_vol = self._exp.volume_ml
                    
                    while not self._should_abort():
                        dt_s, flow_raw = self._exp._sample_flow()
                        self._exp._update_volume(dt_s, flow_raw, net_sign=1.0)
                        filled = self._exp.volume_ml - start_vol
                        self.loss_updated.emit(-filled) 
                        self._emit_sample(event="FILLING_AUTO")
                        if filled >= target_vol:
                            self.log_msg.emit(f"Auto Fill complete ({filled:.2f} mL).", "#10B981")
                            break
                        time.sleep(0.1)

                # Druck abschalten nach dem Füllen!
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=int(self.cfg.main_pressure_channel), mbar=0.0)
                time.sleep(0.5)

            # --- PHASE A: RAMP UP ---
            if p.run_phase_a:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_A")
                
                if p.phase_a_mode == "manual":
                    self.log_msg.emit("Phase A: Manual Step Mode active.", "#8B5CF6")
                    def manual_gate(msg: str):
                        self._wait_ok(Step.FILTRATION, msg)
                    loss_a = self._exp.step_staircase_ramp(
                        target_pressure_mbar=float(p.phase_a_target_mbar),
                        step_size_mbar=float(p.phase_a_step_mbar),
                        step_time_s=1.0, 
                        wait_for_ok_fn=manual_gate
                    )
                else:
                    self.log_msg.emit("Phase A: Auto Ramp active.", "#8B5CF6")
                    loss_a = self._exp.step_staircase_ramp(
                        target_pressure_mbar=float(p.phase_a_target_mbar),
                        step_size_mbar=float(p.phase_a_step_mbar),
                        step_time_s=float(p.phase_a_time_min * 60.0),
                        wait_for_ok_fn=None 
                    )
                total_loss += loss_a

            # --- PHASE B: STEADY STATE & DRY ---
            if p.run_phase_b:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_B")
                self.status.emit(f"Running Phase B1 (Target: {target_vol:.2f}ml)")
                self.log_msg.emit(f"Phase B1: Waiting for {target_vol:.2f} mL to pass.", "#F59E0B")
                self._emit_sample(event="STEP_START_PHASE_B1")
                
                loss_b1 = self._exp.step_steady_state_volume_target(
                    target_volume_ml_to_remove=target_vol,
                    pressure_mbar=float(p.phase_a_target_mbar),
                    max_duration_s=86400.0 
                )
                total_loss += loss_b1

                if p.v_extra_ml > 0:
                    self.status.emit(f"Running Phase B2 (Extra dry: {p.v_extra_ml:.2f}ml)")
                    self.log_msg.emit(f"Phase B2: Drying {p.v_extra_ml:.2f} mL (Timeout: 5 Min).", "#F59E0B")
                    
                    v_start_b2 = self._exp.volume_ml
                    last_flow_time = time.time()
                    timeout_s = 5.0 * 60.0 
                    loss_b2 = 0.0

                    while not self._should_abort():
                        dt_s, flow_raw = self._exp._sample_flow()
                        flow_ml_s = self._exp._flow_to_ml_per_s(flow_raw)
                        net_ml_s = self._exp._update_volume(dt_s, flow_raw, net_sign=-1.0)
                        loss_b2 = v_start_b2 - self._exp.volume_ml
                        
                        if abs(flow_ml_s) > 0.01: last_flow_time = time.time()
                        elif (time.time() - last_flow_time) > timeout_s:
                            self.log_msg.emit("B2 Safety Trigger: No flow detected for 5 mins.", "#FF1744")
                            break

                        if loss_b2 >= p.v_extra_ml: break
                        self._emit_sample(event="PHASE_B2_DRYING")
                        time.sleep(0.2)
                        
                    total_loss += loss_b2

            # --- PHASE C: RAMP DOWN ---
            if p.run_phase_c:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_C")
                self.status.emit("Running Phase C (Ramp down)")
                self.log_msg.emit("Phase C: Ramping down.", "#EC4899")
                
                rate_mbar_s = float(p.phase_c_rate_mbar_min) / 60.0
                step_size_c = float(p.phase_a_step_mbar) if p.phase_a_step_mbar > 0 else 50.0
                step_time_c = step_size_c / rate_mbar_s if rate_mbar_s > 0 else 5.0
                
                loss_c = self._exp.step_staircase_ramp(
                    target_pressure_mbar=0.0, step_size_mbar=step_size_c, step_time_s=step_time_c, wait_for_ok_fn=None 
                )
                total_loss += loss_c

            # --- ABSCHLUSS ---
            self._exp.last_filtration_venting_loss_ml = float(total_loss)
            self.loss_updated.emit(total_loss)
            self._emit_sample(event=f"END_SEQUENCE total_loss={total_loss:.4f}")
            self.log_msg.emit("--- FINAL BALANCE ---", "#00E5FF")
            self.log_msg.emit(f"TOTAL REMOVED: {total_loss:.3f} ml", "#10B981")
            
            if self._should_abort():
                self.step_changed.emit(Step.ABORTED.value)
                self.status.emit(f"Aborted: {self._abort_reason}")
            else:
                self.step_changed.emit(Step.FINISHED.value)
                self.status.emit("Process finished")
                self.finished.emit()

        except Exception as e:
            tb = traceback.format_exc()
            self.step_changed.emit(Step.ABORTED.value)
            self.status.emit(f"Failed: {e}")
            self.failed.emit(f"{e}\n\n{tb}")

        finally:
            try: self._enter_safe_state()
            except Exception: pass
            if self._exp is not None: 
                try: self._exp.close()
                except Exception: pass
            if self._store is not None:
                try: self._store.close()
                except Exception: pass
            if self._dev_owned and self._dev is not None:
                try:
                    if hasattr(self._dev, "__exit__"): self._dev.__exit__(None, None, None)
                    elif hasattr(self._dev, "disconnect"): self._dev.disconnect()
                except Exception: pass

# =========================================================================
# EXPERIMENTATOR CORE
# =========================================================================
class Experimentator:
    def __init__(self, dev: _DeviceProto, cfg: ExperimentConfig):
        self.dev = dev
        self.cfg = cfg
        self.volume_ml: float = float(cfg.initial_volume_ml)
        self._t_prev: Optional[float] = None
        self._last_flow_raw: Optional[float] = None
        self.last_filtration_venting_loss_ml: float = 0.0
        self._loop_idx: int = 0
        self._step_start_volume: float = self.volume_ml
        
        root = project_root(__file__)
        log_dir_abs = Path(ensure_dir(resolve_under(root, cfg.log_dir)))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{cfg.log_name_prefix}_{stamp}.csv"
        self.log_path = str(resolve_under(str(log_dir_abs), name))
        self._csv_file = open(self.log_path, "w", newline="", encoding="utf-8")
        self._csv = csv.DictWriter(
            self._csv_file,
            fieldnames=[
                "ts", "mode", "loop_idx", "dt_s", "flow_raw", "flow_ml_per_s",
                "net_flow_ml_per_s", "volume_ml_est", "volume_delta_ml",
                "pressure_setpoint_pct", "pressure_meas_pct", "pressure_channel",
                "pressure_setpoint_mbar", "pressure_meas_mbar", "valve_state",
                "removed_ml_since_step_start", "event",
            ],
        )
        self._rows_since_flush: int = 0
        self._last_flush_t: float = time.monotonic()
        if bool(cfg.write_csv_preamble): self._write_preamble()
        self._csv.writeheader()
        self._flush(force=True)

    def close(self) -> None:
        try:
            try: self._flush(force=True)
            except Exception: pass
        finally:
            try: self._csv_file.close()
            except Exception: pass

    def _write_preamble(self) -> None:
        try:
            self._csv_file.write(f"# created={_ts_iso()}\n")
            self._csv_file.write(f"# host={os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or ''}\n")
            self._csv_file.write(f"# cfg={asdict(self.cfg)}\n")
        except Exception: pass

    def _flush(self, *, force: bool = False) -> None:
        n = max(1, int(getattr(self.cfg, "log_flush_every_n", 10)))
        every_s = float(getattr(self.cfg, "log_flush_every_s", 1.0))
        do_fsync = bool(getattr(self.cfg, "log_fsync_on_flush", False))
        now = time.monotonic()
        due_count = (self._rows_since_flush >= n)
        due_time = ((now - self._last_flush_t) >= every_s)
        if not force and not (due_count or due_time): return
        try: self._csv_file.flush()
        except Exception: pass
        if do_fsync:
            try: os.fsync(self._csv_file.fileno())
            except Exception: pass
        self._rows_since_flush = 0
        self._last_flush_t = now

    def _flow_to_ml_per_s(self, flow_raw: float) -> float:
        return float(flow_raw) / 60.0 if bool(self.cfg.flow_is_ml_per_min) else float(flow_raw)

    def _sample_flow(self) -> tuple[float, float]:
        t = time.monotonic()
        if self._t_prev is None:
            self._t_prev = t
            v0 = float(self.dev.read_flow())
            self._last_flow_raw = v0
            return 0.0, v0
        dt = float(t - self._t_prev)
        self._t_prev = t
        if dt < 0: dt = 0.0
        dt = min(dt, float(self.cfg.max_dt_s))
        flow_raw = float(self.dev.read_flow())
        self._last_flow_raw = flow_raw
        return dt, flow_raw

    def _update_volume(self, dt_s: float, flow_raw: float, *, net_sign: float) -> float:
        if dt_s <= 0.0: return 0.0
        flow_ml_s = self._flow_to_ml_per_s(flow_raw)
        dead = float(self.cfg.flow_deadband_ml_per_s or 0.0)
        if dead > 0.0 and abs(flow_ml_s) < dead: net_ml_s = 0.0
        else: net_ml_s = float(net_sign) * abs(float(flow_ml_s))
        old = float(self.volume_ml)
        new = old + net_ml_s * float(dt_s)
        if bool(self.cfg.clamp_volume_to_min):
            vmin = float(self.cfg.min_volume_ml)
            if new < vmin: new = vmin
        self.volume_ml = float(new)
        return float(net_ml_s)

    def _mbar_to_percent(self, mbar: float) -> float:
        fs = float(self.cfg.pressure_full_scale_mbar or 8000.0)
        if fs <= 0: fs = 8000.0
        return _clamp(float(mbar) / fs * 100.0, 0.0, 100.0)

    def _percent_to_mbar(self, pct: float) -> float:
        fs = float(self.cfg.pressure_full_scale_mbar or 8000.0)
        if fs <= 0: fs = 8000.0
        return (float(pct) / 100.0) * fs

    def _set_pressure_pct(self, *, channel: int, pct: float, ramp: bool) -> None:
        ch = int(channel)
        val = float(pct)
        fn = getattr(self.dev, "set_pressure", None)
        if not callable(fn): raise RuntimeError("Device has no set_pressure()")
        try: fn(val, channel=ch, ramp=ramp); return # type: ignore[misc]
        except TypeError: pass
        try: fn(val, ch, ramp=ramp); return # type: ignore[misc]
        except TypeError: pass
        fn(val, ch) # type: ignore[misc]

    def _set_pressure_mbar(self, *, channel: int, mbar: float, ramp: bool) -> None:
        if getattr(self.dev, "pressure_controller", None) is None: raise RuntimeError("PressureController disabled")
        if hasattr(self.dev, "set_pressure_setpoint_mbar"):
            try:
                self.dev.set_pressure_setpoint_mbar(channel=int(channel), setpoint_mbar=float(mbar), ramp=bool(ramp)) # type: ignore[attr-defined]
                return
            except Exception: pass
        pct = self._mbar_to_percent(float(mbar))
        self._set_pressure_pct(channel=int(channel), pct=float(pct), ramp=bool(ramp))

    def _get_pressure_setpoint_pct(self, channel: int) -> Optional[float]:
        try: return float(self.dev.get_pressure_setpoint(int(channel)))
        except Exception: return None

    def _get_pressure_meas_pct(self, channel: int) -> Optional[float]:
        try: return float(self.dev.get_pressure(int(channel)))
        except Exception: return None

    def _get_pressure_setpoint_mbar_best(self, channel: int) -> Optional[float]:
        try:
            if hasattr(self.dev, "get_pressure_setpoint_mbar"): return float(self.dev.get_pressure_setpoint_mbar(int(channel))) # type: ignore[attr-defined]
        except Exception: pass
        sp = self._get_pressure_setpoint_pct(int(channel))
        return None if sp is None else self._percent_to_mbar(float(sp))

    def _get_pressure_meas_mbar_best(self, channel: int) -> Optional[float]:
        try:
            if hasattr(self.dev, "get_pressure_mbar"): return float(self.dev.get_pressure_mbar(int(channel))) # type: ignore[attr-defined]
        except Exception: pass
        ms = self._get_pressure_meas_pct(int(channel))
        return None if ms is None else self._percent_to_mbar(float(ms))

    def _safety_check(self, mode: str) -> None:
        margin = float(self.volume_ml) - float(self.cfg.min_volume_ml)
        if margin < 0:
            try: self.dev.all_valves_shut()
            finally: raise RuntimeError(f"SAFETY STOP: volume {self.volume_ml:.6f} mL below min {self.cfg.min_volume_ml:.6f} mL (mode={mode})")

    def _log_row(self, mode: str, dt_s: float, flow_raw: float, flow_ml_s: float, *, net_flow_ml_s: float = 0.0, pressure_channel: Optional[int] = None, event: str = "") -> None:
        self._loop_idx += 1
        p_set_pct = p_meas_pct = p_set_mbar = p_meas_mbar = ch = ""

        if pressure_channel is not None and getattr(self.dev, "pressure_controller", None) is not None:
            ch_i = int(pressure_channel)
            sp = self._get_pressure_setpoint_pct(ch_i)
            ms = self._get_pressure_meas_pct(ch_i)
            sp_mbar = self._get_pressure_setpoint_mbar_best(ch_i)
            ms_mbar = self._get_pressure_meas_mbar_best(ch_i)
            if sp is not None: p_set_pct = f"{sp:.3f}"
            if ms is not None: p_meas_pct = f"{ms:.3f}"
            if sp_mbar is not None: p_set_mbar = f"{sp_mbar:.3f}"
            if ms_mbar is not None: p_meas_mbar = f"{ms_mbar:.3f}"
            ch = str(ch_i)

        try: valve_state = str(self.dev.get_valve_state())
        except Exception: valve_state = "UNKNOWN"

        removed_ml = max(0.0, float(self._step_start_volume) - float(self.volume_ml))
        volume_delta = float(net_flow_ml_s) * float(dt_s)

        def _nf(x: Any) -> Any:
            if isinstance(x, str): return x
            if x is None: return ""
            try: v = float(x)
            except Exception: return ""
            return v if _is_finite_number(v) else ""

        self._csv.writerow({
            "ts": _ts_iso(), "mode": str(mode), "loop_idx": int(self._loop_idx),
            "dt_s": round(float(dt_s), 6), "flow_raw": _nf(flow_raw),
            "flow_ml_per_s": _nf(flow_ml_s), "net_flow_ml_per_s": _nf(net_flow_ml_s),
            "volume_ml_est": _nf(self.volume_ml), "volume_delta_ml": _nf(volume_delta),
            "pressure_setpoint_pct": p_set_pct, "pressure_meas_pct": p_meas_pct,
            "pressure_channel": ch, "pressure_setpoint_mbar": p_set_mbar,
            "pressure_meas_mbar": p_meas_mbar, "valve_state": valve_state,
            "removed_ml_since_step_start": _nf(removed_ml), "event": str(event or ""),
        })
        self._rows_since_flush += 1
        self._flush(force=False)

    def step_staircase_ramp(self, *, target_pressure_mbar: float, step_size_mbar: float, step_time_s: float, wait_for_ok_fn: Optional[Callable[[str], None]] = None) -> float:
        ch = int(self.cfg.main_pressure_channel)
        try: self.dev.valves_filtration()
        except Exception: pass
        if step_size_mbar <= 0 or step_time_s <= 0: return 0.0

        start_mbar = self._get_pressure_setpoint_mbar_best(ch)
        if start_mbar is None: start_mbar = 0.0

        current_target = float(start_mbar)
        target = float(target_pressure_mbar)
        step = abs(float(step_size_mbar))
        v0 = float(self.volume_ml)
        ramping_up = (target > current_target)

        if abs(current_target - target) < 0.1: return 0.0

        while True:
            if ramping_up: current_target = min(current_target + step, target)
            else: current_target = max(current_target - step, target)

            if wait_for_ok_fn: wait_for_ok_fn(f"Confirm ramp step to {current_target:.0f} mbar")

            if getattr(self.dev, "pressure_controller", None) is not None:
                self._set_pressure_mbar(channel=ch, mbar=current_target, ramp=True)

            t_end = time.monotonic() + step_time_s
            while time.monotonic() < t_end:
                dt_s, flow_raw = self._sample_flow()
                flow_ml_s = self._flow_to_ml_per_s(flow_raw)
                net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=-1.0)
                self._log_row("STAIRCASE_RAMP", dt_s, flow_raw, flow_ml_s, net_flow_ml_s=net_ml_s, pressure_channel=ch)
                self._safety_check("STAIRCASE_RAMP")
                time.sleep(float(self.cfg.sample_period_s))

            if ramping_up and current_target >= target: break
            if not ramping_up and current_target <= target: break

        return float(max(0.0, v0 - float(self.volume_ml)))

    def step_steady_state_volume_target(self, *, target_volume_ml_to_remove: float, pressure_mbar: float, max_duration_s: float = 86400.0) -> float:
        ch = int(self.cfg.main_pressure_channel)
        try: self.dev.valves_filtration()
        except Exception: pass
        if getattr(self.dev, "pressure_controller", None) is not None:
            self._set_pressure_mbar(channel=ch, mbar=pressure_mbar, ramp=True)

        v_start = float(self.volume_ml)
        mode = "PHASE_B_STEADY"
        self._log_row(mode, 0.0, float("nan"), float("nan"), pressure_channel=ch, event="START_STEADY_STATE")

        t_end = time.monotonic() + float(max(0.0, max_duration_s))
        while time.monotonic() < t_end:
            dt_s, flow_raw = self._sample_flow()
            flow_ml_s = self._flow_to_ml_per_s(flow_raw)
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=-1.0) 
            removed = max(0.0, v_start - float(self.volume_ml))
            self._log_row(mode, dt_s, flow_raw, flow_ml_s, net_flow_ml_s=net_ml_s, pressure_channel=ch)
            self._safety_check(mode)
            if removed >= target_volume_ml_to_remove: break
            time.sleep(float(self.cfg.sample_period_s))

        removed = max(0.0, v_start - float(self.volume_ml))
        self._log_row(mode, 0.0, float("nan"), 0.0, pressure_channel=ch, event=f"END_STEADY_STATE removed={removed:.4f}")
        return removed