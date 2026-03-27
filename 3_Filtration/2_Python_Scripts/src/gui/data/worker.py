from __future__ import annotations

import logging
import threading
import time
import traceback
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal, Slot, Qt

from src.backend.core.device_manager import DeviceManager, DeviceManagerOptions
from src.utils.path_utils import ensure_dir, project_root, resolve_under
from src.backend.core.telemetry import RunTelemetryStore, build_run_meta
from src.backend.core.experimentator import Experimentator, ExperimentConfig

logger = logging.getLogger(__name__)

# =========================================================================
# HELPER
# =========================================================================
def robust_switch_valves(dev: Any, mode: str, log_signal: Optional[Any] = None) -> None:
    """Kugelsicherer Ventil-Schalter mit 'Break before Make' Logik."""
    if dev is None: return
    mode = mode.upper()
    
    # Break before Make (Sicherheitsschließung)
    if mode not in ["SHUT", "ALL_SHUT"]:
        try:
            if hasattr(dev, "all_shut"): dev.all_shut()
            elif hasattr(dev, "all_valves_shut"): dev.all_valves_shut()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("ALL_SHUT")
            import time; time.sleep(0.1) 
        except Exception as e:
            print(f"HW WARNING: Could not pre-shut valves: {e}")

    msg = f"HW CMD: Switching valves to {mode}"
    print(f">>> {msg}")
    
    if log_signal is not None and hasattr(log_signal, "emit"):
        log_signal.emit(msg, "#94A3B8")
        
    try:
        if mode == "FILLING":
            if hasattr(dev, "valves_filling_solution"): dev.valves_filling_solution()
            elif hasattr(dev, "filling_solution"): dev.filling_solution()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("FILLING")
            else: raise RuntimeError("No FILLING method")
        elif mode == "FILTRATION":
            if hasattr(dev, "valves_filtration"): dev.valves_filtration()
            elif hasattr(dev, "filtration"): dev.filtration()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("FILTRATION")
            else: raise RuntimeError("No FILTRATION method")
        elif mode == "VENTING":
            if hasattr(dev, "valves_venting"): dev.valves_venting()
            elif hasattr(dev, "venting"): dev.venting()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("VENTING")
            else: raise RuntimeError("No VENTING method")
        elif mode == "BACKWASH":
            if hasattr(dev, "valves_backwash"): dev.valves_backwash()
            elif hasattr(dev, "backwash"): dev.backwash()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("BACKWASH")
            else: raise RuntimeError("No BACKWASH method")
        elif mode in ["OPEN", "ALL_OPEN"]:
            if hasattr(dev, "all_open"): dev.all_open()
            elif hasattr(dev, "all_valves_open"): dev.all_valves_open()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("ALL_OPEN")
            else: raise RuntimeError("No ALL_OPEN method")
        elif mode in ["SHUT", "ALL_SHUT"]:
            if hasattr(dev, "all_shut"): dev.all_shut()
            elif hasattr(dev, "all_valves_shut"): dev.all_valves_shut()
            elif hasattr(dev, "set_valve_state"): dev.set_valve_state("ALL_SHUT")
            else: raise RuntimeError("No ALL_SHUT method")
    except Exception as e:
        err = f"VALVE ERROR ({mode}): {e}"
        print(f"!!! {err} !!!")
        if log_signal is not None and hasattr(log_signal, "emit"):
            log_signal.emit(err, "#FF1744")


# =========================================================================
# EXPERIMENT DATA CLASSES (ExperimentConfig kommt aus experimentator.py)
# =========================================================================

class Step(str, Enum):
    BACKWASH_INITIAL = "BACKWASH_INITIAL"
    BACKWASH_HOLD = "BACKWASH_HOLD"
    FILLING = "FILLING"
    FILTRATION = "FILTRATION"
    VENTING = "VENTING" # Kann als legacy bleiben, schadet nicht
    BACKWASH_FINAL = "BACKWASH_FINAL"
    FINISHED = "FINISHED"
    ABORTED = "ABORTED"

@dataclass
class RunParams:
    v_bnnt_ml: float
    phase_b1_target_ml: float  # B1 Zielvolumen (früher v_h2o_ml)

    run_phase_0: bool
    run_phase_a: bool
    run_phase_b: bool
    run_phase_c: bool

    phase_0_pressure_mbar: float = 300.0
    phase_0_stagnation_s: float = 8.0   # Backwash-Ende: Kein Flow für N Sekunden → Membran erreicht

    phase_a_target_mbar: float = 2000.0
    phase_a_rate_mbar_min: float = 125.0

    v_extra_ml: float = 0.0
    phase_b_no_flow_timeout_min: float = 5.0
    phase_c_rate_mbar_min: float = 500.0

    # Orchestrator: Bestätigungs-Gates zwischen Phasen
    confirm_between_phases: bool = True

    def save_yaml(self, path: str) -> None:
        """Speichert die RunParams als YAML-Datei."""
        import yaml
        from dataclasses import asdict
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(asdict(self), f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    @classmethod
    def load_yaml(cls, path: str) -> "RunParams":
        """Lädt RunParams aus einer YAML-Datei. Fehlende Felder bekommen Defaults."""
        import yaml
        from pathlib import Path
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"RunParams file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # Pflichtfelder die keine Defaults haben
        if "v_bnnt_ml" not in data: data["v_bnnt_ml"] = 0.0
        # Rückwärtskompatibilität: altes v_h2o_ml → phase_b1_target_ml
        if "phase_b1_target_ml" not in data:
            data["phase_b1_target_ml"] = data.pop("v_h2o_ml", 1400.0)
        if "run_phase_0" not in data: data["run_phase_0"] = True
        if "run_phase_a" not in data: data["run_phase_a"] = True
        if "run_phase_b" not in data: data["run_phase_b"] = True
        if "run_phase_c" not in data: data["run_phase_c"] = True
        # Alte Felder entfernen die nicht mehr existieren
        for _old in ("v_h2o_ml", "phase_0_mode", "phase_a_mode", "phase_a_step_mbar"):
            data.pop(_old, None)
        # Nur bekannte Felder übergeben (ignoriert alte/unbekannte Keys)
        import dataclasses
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

# =========================================================================
# EXPERIMENT WORKER
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
    log_msg = Signal(str, str)
    # Neues Filling-Signal: empfiehlt Nachfüllmenge an die UI
    filling_requested = Signal(float)
    # B1/B2 Detail-Fortschritt: (phase_id, current_ml, target_ml)
    phase_detail_updated = Signal(str, float, float)

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
        self._dev: Optional[DeviceManager] = None
        self._dev_owned: bool = True
        self._exp: Optional[Experimentator] = None
        self._current_step: Step = Step.BACKWASH_INITIAL
        self._t0: Optional[float] = None
        self._step_t0: Optional[float] = None
        self._step_total_s: Optional[float] = None
        self._store: Optional[RunTelemetryStore] = None
        self._on_sample_cb: Optional[Callable] = None
        self._total_loss_so_far: float = 0.0
        self._phase_vol_start: Optional[float] = None
        self._last_ramp_loss_ml: float = 0.0   # Verlust vom letzten Zyklus (Empfehlung für Filling)
        self._filling_amount_ml: float = 0.0   # Vom Bediener manuell eingegebene Füllmenge

        self.cmd_start_backwash_hold.connect(self._on_cmd_start_backwash_hold, Qt.ConnectionType.QueuedConnection)
        self.cmd_stop_backwash_hold.connect(self._on_cmd_stop_backwash_hold, Qt.ConnectionType.QueuedConnection)
        self.cmd_abort.connect(self._on_cmd_abort, Qt.ConnectionType.QueuedConnection)

    def set_params(self, params: RunParams) -> None:
        self._params = params

    def confirm_ok(self) -> None:
        self._ok_event.set()
        try:
            if self._store is not None:
                self._store.write_event("OK_BUTTON_PRESSED", {"step": self._current_step.value})
        except Exception: pass

    def set_filling_amount(self, ml: float) -> None:
        """Wird vom MainWindow aufgerufen wenn der Bediener die Füllmenge bestätigt hat."""
        self._filling_amount_ml = max(0.0, float(ml))

    def set_device_manager(self, dev: DeviceManager) -> None:
        self._dev = dev
        self._dev_owned = False

    def abort(self, reason: str = "User abort") -> None:
        self.cmd_abort.emit(str(reason or "User abort"))

    def start_backwash_hold(self, pressure_mbar: float) -> None:
        self.cmd_start_backwash_hold.emit(float(pressure_mbar))

    def stop_backwash_hold(self) -> None:
        self.cmd_stop_backwash_hold.emit()

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
            self._emit_sample(event=f"WAITING_OK_{step.value}")

    def _ensure_t0(self) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()

    def _unwrap_sensor(self, val) -> float:
        """Sicheres Entpacken von Hardware-Rückgaben."""
        if val is None: return 0.0
        if isinstance(val, (list, tuple)): return float(val[-1])
        return float(val)

    def _emit_sample(self, *, event: str = "") -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None: return

        self._ensure_t0()
        now = time.monotonic()
        t_s = now - float(self._t0) # type: ignore

        try: flow = self._unwrap_sensor(dev.read_flow())
        except Exception: flow = 0.0

        try:
            fn_valve = getattr(dev, "get_valve_state", getattr(dev, "get_state", None))
            valve_state = str(fn_valve()) if callable(fn_valve) else "UNKNOWN"
        except Exception: 
            valve_state = "UNKNOWN"

        p1_set = p1_meas = p2_set = p2_meas = 0.0
        if getattr(dev, "pressure_controller", None) is not None:
            try: p1_set = self._unwrap_sensor(dev.get_pressure_setpoint_mbar(1))
            except Exception: pass
            try: p1_meas = self._unwrap_sensor(dev.get_pressure_mbar(1))
            except Exception: pass
            try: p2_set = self._unwrap_sensor(dev.get_pressure_setpoint_mbar(2))
            except Exception: pass
            try: p2_meas = self._unwrap_sensor(dev.get_pressure_mbar(2))
            except Exception: pass

        try: vol = float(exp.volume_ml)
        except Exception: vol = 0.0

        # Live-Loss: Akkumulierter Verlust + aktueller Phasenverlust
        try:
            current_phase_loss = 0.0
            if self._phase_vol_start is not None:
                current_phase_loss = max(0.0, self._phase_vol_start - float(exp.volume_ml))
            loss = self._total_loss_so_far + current_phase_loss
        except Exception:
            loss = 0.0

        sample = {
            "t": t_s,
            "step": self._current_step.value,
            "event": str(event or ""),
            "flow": flow,
            "p1_set": p1_set, "p1_meas": p1_meas,
            "p2_set": p2_set, "p2_meas": p2_meas,
            "volume_ml": vol, "loss_ml": loss, # Dieser Wert pusht jetzt ins TopFrame!
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

    def _enter_safe_state(self) -> None:
        try: self._hold_active.clear()
        except Exception: pass
        self._safe_drop_pressure_all()
        robust_switch_valves(self._dev, "SHUT")
        try: self._emit_sample(event="SAFE_STATE")
        except Exception: pass

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
            self._exp._on_sample = lambda ev="": self._emit_sample(event=ev)
            self._t0 = None

            try:
                meta = build_run_meta(experiment_config=self.cfg, run_params=p)
                self._store = RunTelemetryStore(meta=meta)
                self._store.write_event("RUN_START", {"step": self._current_step.value})
            except Exception: self._store = None

            target_vol = float(p.v_bnnt_ml) + float(p.phase_b1_target_ml)
            total_loss = 0.0

            # -------------------------------------------------------------
            # PHASE 0: BACKWASH (automatisch bis Membran)
            # -------------------------------------------------------------
            if p.run_phase_0:
                self._current_step = Step.FILLING
                self.step_changed.emit("FILLING")
                self._phase_vol_start = float(self._exp.volume_ml)
                bw_ch = int(self.cfg.backwash_pressure_channel)
                flow_dead = float(self.cfg.flow_deadband_ml_per_s)
                stagnation_threshold_s = max(3.0, float(p.phase_0_stagnation_s))
                max_bw_duration_s = 1800.0  # Safety: max 30 min

                self.log_msg.emit("═" * 52, "#EC4899")
                self.log_msg.emit("BACKWASH STARTED — filling system to membrane level", "#EC4899")
                self.log_msg.emit("═" * 52, "#EC4899")
                self.status.emit("BACKWASH: filling to membrane...")

                robust_switch_valves(dev, "BACKWASH", self.log_msg)
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=bw_ch, mbar=float(p.phase_0_pressure_mbar))

                mode_bw = "PHASE_0_BACKWASH"
                self._exp._step_start_volume = float(self._exp.volume_ml)
                self._exp._log_row(mode_bw, 0.0, float("nan"), float("nan"),
                                   pressure_channel=bw_ch, event="START_BACKWASH")

                t_deadline = time.monotonic() + max_bw_duration_s
                last_flow_time_bw = time.monotonic()

                while not self._should_abort():
                    if time.monotonic() > t_deadline:
                        self.log_msg.emit("SAFETY: Backwash-Timeout (30 min)!", "#FF1744")
                        break

                    dt_s, flow_raw = self._exp._sample_flow()
                    flow_ml_s = self._exp._flow_to_ml_per_s(flow_raw)
                    self._exp._update_volume(dt_s, flow_raw, net_sign=+1.0)
                    self._exp._log_row(mode_bw, dt_s, flow_raw, flow_ml_s, pressure_channel=bw_ch)
                    self._emit_sample(event="BACKWASH")

                    if abs(flow_ml_s) > flow_dead:
                        last_flow_time_bw = time.monotonic()
                    elif (time.monotonic() - last_flow_time_bw) > stagnation_threshold_s:
                        self.log_msg.emit(
                            f"Backwash complete: no flow for {stagnation_threshold_s:.0f}s — membrane reached.", "#10B981")
                        self._exp._log_row(mode_bw, 0.0, float("nan"), 0.0,
                                           pressure_channel=bw_ch, event="END_BACKWASH_STAGNATION")
                        break

                    time.sleep(float(self.cfg.sample_period_s))

                # Druck und Ventile schließen
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=bw_ch, mbar=0.0)
                robust_switch_valves(dev, "SHUT", self.log_msg)
                self._phase_vol_start = None

                # --- Manuelles Filling anfordern ---
                self._raise_if_abort()
                recommended_fill = max(0.0, self._last_ramp_loss_ml) if self._last_ramp_loss_ml > 0 else target_vol
                self.log_msg.emit("─" * 52, "#00E5FF")
                self.log_msg.emit("MANUAL FILLING REQUIRED", "#00E5FF")
                self.log_msg.emit(f"Recommended amount: {recommended_fill:.1f} ml", "#00E5FF")
                self.log_msg.emit(f"Next phase after confirmation: RAMP ({p.phase_a_target_mbar:.0f} mbar)", "#64748B")
                self.log_msg.emit("─" * 52, "#00E5FF")
                self.filling_requested.emit(recommended_fill)
                self._wait_ok(Step.FILLING, "Fill liquid and confirm")
                self.log_msg.emit(
                    f"Filling confirmed: {self._filling_amount_ml:.1f} ml added.", "#10B981")

            # --- PHASE A: RAMP UP (automatisch, kontinuierlich) ---
            if p.run_phase_a:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_A")
                self._phase_vol_start = float(self._exp.volume_ml)
                ch = int(self.cfg.main_pressure_channel)

                current_mbar = self._exp._get_pressure_setpoint_mbar_best(ch)
                if current_mbar is None or current_mbar < 0:
                    current_mbar = 0.0
                delta_mbar = max(0.0, float(p.phase_a_target_mbar) - current_mbar)
                rate_mbar_s = float(p.phase_a_rate_mbar_min) / 60.0
                total_duration_s = (delta_mbar / rate_mbar_s) if rate_mbar_s > 0 and delta_mbar > 0 else 10.0

                self.log_msg.emit("═" * 52, "#8B5CF6")
                self.log_msg.emit(
                    f"PHASE A: RAMP  {current_mbar:.0f} → {p.phase_a_target_mbar:.0f} mbar  "
                    f"({p.phase_a_rate_mbar_min:.0f} mbar/min, ETA {total_duration_s/60:.1f} min)", "#8B5CF6")
                self.log_msg.emit(f"Next phase: B1 — Steady State (target: {target_vol:.1f} ml)", "#64748B")
                self.log_msg.emit("═" * 52, "#8B5CF6")
                self.status.emit(f"Phase A: ramp {current_mbar:.0f} → {p.phase_a_target_mbar:.0f} mbar")

                self._emit_sample(event=f"PHASE_A_START current={current_mbar:.0f} target={p.phase_a_target_mbar:.0f}")

                # Kontinuierliche Rampe
                loss_a = self._exp.step_continuous_ramp(
                    target_pressure_mbar=float(p.phase_a_target_mbar),
                    duration_s=total_duration_s,
                    abort_check_fn=self._should_abort
                )

                self._emit_sample(event=f"PHASE_A_END loss={loss_a:.4f}")
                self.log_msg.emit(f"Phase A complete. Loss: {loss_a:.3f} ml", "#8B5CF6")
                total_loss += loss_a
                self._total_loss_so_far += loss_a
                self._phase_vol_start = None

            # --- GATE: Phase A → Phase B (nur wenn confirm_between_phases) ---
            if p.run_phase_a and p.run_phase_b and p.confirm_between_phases:
                self._raise_if_abort()
                self.log_msg.emit("Phase A complete. Continuing to Phase B (Steady State).", "#F59E0B")
                self._wait_ok(Step.FILTRATION, "Phase A → B: confirm pressure hold")

            # --- PHASE B: STEADY STATE & TROCKNUNG ---
            if p.run_phase_b:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_B")
                self._phase_vol_start = float(self._exp.volume_ml)
                ch = int(self.cfg.main_pressure_channel)
                stagnation_timeout_s = float(p.phase_b_no_flow_timeout_min) * 60.0
                flow_dead = float(self.cfg.flow_deadband_ml_per_s)

                # ============================================================
                # PHASE B1: Steady State bis Zielvolumen
                # ============================================================
                self.status.emit(f"Phase B1 active (target: {target_vol:.2f} ml)")
                self.log_msg.emit("═" * 52, "#F59E0B")
                self.log_msg.emit(
                    f"PHASE B1: STEADY STATE  {p.phase_a_target_mbar:.0f} mbar  "
                    f"→ target: {target_vol:.2f} ml  (timeout: {p.phase_b_no_flow_timeout_min:.0f} min)", "#F59E0B")
                if p.v_extra_ml > 0:
                    self.log_msg.emit(f"Next phase: B2 — Drying ({p.v_extra_ml:.1f} ml)", "#64748B")
                else:
                    self.log_msg.emit("Next phase: C — Ramp Down", "#64748B")
                self.log_msg.emit("═" * 52, "#F59E0B")
                self._emit_sample(event="STEP_START_PHASE_B1")

                # Ventile & Druck setzen
                robust_switch_valves(dev, "FILTRATION", self.log_msg)
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=ch, mbar=float(p.phase_a_target_mbar))

                v_start_b1 = float(self._exp.volume_ml)
                self._exp._step_start_volume = v_start_b1
                last_flow_time_b1 = time.monotonic()
                mode_b1 = "PHASE_B1_STEADY"
                loss_b1 = 0.0

                self._exp._log_row(mode_b1, 0.0, float("nan"), float("nan"),
                                   pressure_channel=ch, event="START_B1")

                while not self._should_abort():
                    dt_s, flow_raw = self._exp._sample_flow()
                    flow_ml_s = self._exp._flow_to_ml_per_s(flow_raw)
                    net_ml_s = self._exp._update_volume(dt_s, flow_raw, net_sign=-1.0)

                    loss_b1 = max(0.0, v_start_b1 - float(self._exp.volume_ml))

                    self._exp._log_row(mode_b1, dt_s, flow_raw, flow_ml_s,
                                       net_flow_ml_s=net_ml_s, pressure_channel=ch)

                    # Stagnation-Watchdog: Wenn Fluss vorhanden → Timer resetten
                    if abs(flow_ml_s) > flow_dead:
                        last_flow_time_b1 = time.monotonic()
                    elif (time.monotonic() - last_flow_time_b1) > stagnation_timeout_s:
                        self.log_msg.emit(
                            f"B1 SAFETY: No flow for {p.phase_b_no_flow_timeout_min:.0f} min! "
                            f"Filter may be clogged. ({loss_b1:.2f}/{target_vol:.2f} mL)", "#FF1744")
                        self._exp._log_row(mode_b1, 0.0, float("nan"), 0.0,
                                           pressure_channel=ch, event="B1_STAGNATION_TIMEOUT")
                        break

                    # Zielvolumen erreicht?
                    if loss_b1 >= target_vol:
                        self.log_msg.emit(f"Phase B1 complete: {loss_b1:.2f} mL removed.", "#10B981")
                        self._exp._log_row(mode_b1, 0.0, float("nan"), 0.0,
                                           pressure_channel=ch,
                                           event=f"END_B1 removed={loss_b1:.4f}")
                        break

                    self.loss_updated.emit(self._total_loss_so_far + loss_b1)
                    self.phase_detail_updated.emit("B1", loss_b1, target_vol)
                    self._emit_sample(event="PHASE_B1_HOLD")
                    time.sleep(float(self.cfg.sample_period_s))

                total_loss += loss_b1

                # ============================================================
                # PHASE B2: Extra-Trockenvolumen (optional)
                # ============================================================
                loss_b2 = 0.0
                if p.v_extra_ml > 0 and not self._should_abort():
                    self.status.emit(f"Phase B2 active (drying: {p.v_extra_ml:.2f} ml)")
                    self.log_msg.emit("─" * 52, "#F59E0B")
                    self.log_msg.emit(
                        f"PHASE B2: DRYING  → target: {p.v_extra_ml:.2f} ml  "
                        f"(timeout: {p.phase_b_no_flow_timeout_min:.0f} min)", "#F59E0B")
                    self.log_msg.emit("Next phase: C — Ramp Down", "#64748B")
                    self.log_msg.emit("─" * 52, "#F59E0B")

                    v_start_b2 = float(self._exp.volume_ml)
                    self._exp._step_start_volume = v_start_b2
                    last_flow_time_b2 = time.monotonic()
                    mode_b2 = "PHASE_B2_DRYING"

                    self._exp._log_row(mode_b2, 0.0, float("nan"), float("nan"),
                                       pressure_channel=ch, event="START_B2")

                    while not self._should_abort():
                        dt_s, flow_raw = self._exp._sample_flow()
                        flow_ml_s = self._exp._flow_to_ml_per_s(flow_raw)
                        net_ml_s = self._exp._update_volume(dt_s, flow_raw, net_sign=-1.0)

                        loss_b2 = max(0.0, v_start_b2 - float(self._exp.volume_ml))

                        self._exp._log_row(mode_b2, dt_s, flow_raw, flow_ml_s,
                                           net_flow_ml_s=net_ml_s, pressure_channel=ch)

                        # Stagnation-Watchdog
                        if abs(flow_ml_s) > flow_dead:
                            last_flow_time_b2 = time.monotonic()
                        elif (time.monotonic() - last_flow_time_b2) > stagnation_timeout_s:
                            self.log_msg.emit(
                                f"B2 SAFETY: No flow for {p.phase_b_no_flow_timeout_min:.0f} min! "
                                f"({loss_b2:.2f}/{p.v_extra_ml:.2f} mL)", "#FF1744")
                            self._exp._log_row(mode_b2, 0.0, float("nan"), 0.0,
                                               pressure_channel=ch, event="B2_STAGNATION_TIMEOUT")
                            break

                        if loss_b2 >= p.v_extra_ml:
                            self.log_msg.emit(f"Phase B2 complete: {loss_b2:.2f} mL dried.", "#10B981")
                            self._exp._log_row(mode_b2, 0.0, float("nan"), 0.0,
                                               pressure_channel=ch,
                                               event=f"END_B2 removed={loss_b2:.4f}")
                            break

                        self.loss_updated.emit(self._total_loss_so_far + loss_b1 + loss_b2)
                        self.phase_detail_updated.emit("B2", loss_b2, p.v_extra_ml)
                        self._emit_sample(event="PHASE_B2_DRYING")
                        time.sleep(float(self.cfg.sample_period_s))

                    total_loss += loss_b2

                self._total_loss_so_far += loss_b1 + loss_b2
                self._emit_sample(event=f"PHASE_B_END total_b={loss_b1 + loss_b2:.4f}")
                self._phase_vol_start = None

            # --- GATE: Phase B → Phase C ---
            if p.run_phase_b and p.run_phase_c and p.confirm_between_phases:
                self._raise_if_abort()
                self.log_msg.emit("Phase B complete. Continuing to Phase C (Ramp Down).", "#F59E0B")
                self._wait_ok(Step.FILTRATION, "Phase B → C: confirm pressure release")

            # --- PHASE C: RAMP DOWN ---
            if p.run_phase_c:
                self._current_step = Step.FILTRATION
                self.step_changed.emit("PHASE_C")
                self._phase_vol_start = float(self._exp.volume_ml)

                ch = int(self.cfg.main_pressure_channel)

                start_mbar = self._exp._get_pressure_meas_mbar_best(ch)
                if start_mbar is None or start_mbar <= 0:
                    start_mbar = self._exp._get_pressure_setpoint_mbar_best(ch)
                if start_mbar is None or start_mbar <= 0:
                    start_mbar = float(p.phase_a_target_mbar)

                rate_mbar_min = float(p.phase_c_rate_mbar_min)
                duration_s = (start_mbar / rate_mbar_min * 60.0) if rate_mbar_min > 0 and start_mbar > 0 else 30.0

                self.log_msg.emit("═" * 52, "#EC4899")
                self.log_msg.emit(
                    f"PHASE C: RAMP DOWN  {start_mbar:.0f} → 0 mbar  "
                    f"({rate_mbar_min:.0f} mbar/min, ETA {duration_s/60:.1f} min)", "#EC4899")
                self.log_msg.emit("═" * 52, "#EC4899")
                self.status.emit(f"Phase C: pressure release {start_mbar:.0f} → 0 mbar")
                self._emit_sample(event=f"PHASE_C_START from={start_mbar:.0f}")

                loss_c = self._exp.step_continuous_ramp(
                    target_pressure_mbar=0.0,
                    duration_s=duration_s,
                    abort_check_fn=self._should_abort
                )

                # Druck explizit auf 0 setzen (Sicherheit falls Rampe durch Abort abgebrochen)
                if getattr(dev, "pressure_controller", None) is not None:
                    self._safe_set_pressure_mbar(channel=ch, mbar=0.0)

                # Ventile nach Druckabbau schließen
                robust_switch_valves(dev, "SHUT", self.log_msg)

                self._emit_sample(event=f"PHASE_C_END loss={loss_c:.4f}")
                self.log_msg.emit(f"Phase C complete. Loss: {loss_c:.4f} ml", "#EC4899")
                total_loss += loss_c
                self._total_loss_so_far += loss_c
                self._phase_vol_start = None

            # --- ABSCHLUSS ---
            self._exp.last_filtration_venting_loss_ml = float(total_loss)
            self._last_ramp_loss_ml = float(total_loss)  # Für nächsten Zyklus: Filling-Empfehlung
            self.loss_updated.emit(total_loss)
            self._emit_sample(event=f"END_SEQUENCE total_loss={total_loss:.4f}")
            self.log_msg.emit("═" * 52, "#00E5FF")
            self.log_msg.emit(f"SEQUENCE COMPLETE — Total loss: {total_loss:.3f} ml", "#10B981")
            self.log_msg.emit(f"Recommendation for next filling: {total_loss:.1f} ml", "#00E5FF")
            self.log_msg.emit("═" * 52, "#00E5FF")
            
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
            self._total_loss_so_far = 0.0
            self._filling_amount_ml = 0.0
            self._phase_vol_start = None
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


# Experimentator wird aus src.backend.core.experimentator importiert (Single Source of Truth)