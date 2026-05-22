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
from src.backend.core.telemetry import RunTelemetryStore, build_run_meta
from src.backend.core.experimentator import Experimentator, ExperimentConfig

logger = logging.getLogger(__name__)

# =========================================================================
# HELPER
# =========================================================================


def robust_switch_valves(dev: Any, mode: str, log_signal: Optional[Any] = None) -> None:
    """Kugelsicherer Ventil-Schalter mit 'Break before Make' Logik."""
    if dev is None:
        return
    mode = mode.upper()

    # Break before Make (Sicherheitsschließung)
    if mode not in ["SHUT", "ALL_SHUT"]:
        try:
            if hasattr(dev, "all_shut"):
                dev.all_shut()
            elif hasattr(dev, "all_valves_shut"):
                dev.all_valves_shut()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("ALL_SHUT")
            time.sleep(0.1)
        except Exception as e:
            logger.warning("HW: Could not pre-shut valves: %s", e)

    msg = f"HW CMD: Switching valves to {mode}"
    logger.debug("%s", msg)

    if log_signal is not None and hasattr(log_signal, "emit"):
        log_signal.emit(msg, "#94A3B8")

    try:
        if mode == "FILLING":
            if hasattr(dev, "valves_filling_solution"):
                dev.valves_filling_solution()
            elif hasattr(dev, "filling_solution"):
                dev.filling_solution()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("FILLING")
            else:
                raise RuntimeError("No FILLING method")
        elif mode == "FILTRATION":
            if hasattr(dev, "valves_filtration"):
                dev.valves_filtration()
            elif hasattr(dev, "filtration"):
                dev.filtration()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("FILTRATION")
            else:
                raise RuntimeError("No FILTRATION method")
        elif mode == "VENTING":
            if hasattr(dev, "valves_venting"):
                dev.valves_venting()
            elif hasattr(dev, "venting"):
                dev.venting()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("VENTING")
            else:
                raise RuntimeError("No VENTING method")
        elif mode == "BACKWASH":
            if hasattr(dev, "valves_backwash"):
                dev.valves_backwash()
            elif hasattr(dev, "backwash"):
                dev.backwash()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("BACKWASH")
            else:
                raise RuntimeError("No BACKWASH method")
        elif mode in ["OPEN", "ALL_OPEN"]:
            if hasattr(dev, "all_open"):
                dev.all_open()
            elif hasattr(dev, "all_valves_open"):
                dev.all_valves_open()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("ALL_OPEN")
            else:
                raise RuntimeError("No ALL_OPEN method")
        elif mode in ["SHUT", "ALL_SHUT"]:
            if hasattr(dev, "all_shut"):
                dev.all_shut()
            elif hasattr(dev, "all_valves_shut"):
                dev.all_valves_shut()
            elif hasattr(dev, "set_valve_state"):
                dev.set_valve_state("ALL_SHUT")
            else:
                raise RuntimeError("No ALL_SHUT method")
    except Exception as e:
        err = f"VALVE ERROR ({mode}): {e}"
        logger.error("%s", err)
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
    VENTING = "VENTING"  # Kann als legacy bleiben, schadet nicht
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
    phase_0_target_ml: float = 1400.0
    phase_0_mode: str = "AUTO"          # "AUTO" | "CONTINUOUS" | "MANUAL"

    phase_a_target_mbar: float = 2000.0
    phase_a_rate_mbar_min: float = 125.0
    phase_a_mode: str = "SMOOTH"        # "SMOOTH" | "STEPPED"
    phase_a_step_mbar: float = 250.0
    phase_a_time_per_step_min: float = 2.0

    v_extra_ml: float = 0.0
    phase_b_no_flow_timeout_min: float = 5.0

    phase_c_rate_mbar_min: float = 500.0
    phase_c_mode: str = "SMOOTH"        # "SMOOTH" | "STEPPED"
    phase_c_step_mbar: float = 250.0
    phase_c_time_per_step_min: float = 2.0

    confirm_between_phases: bool = True

    def save_yaml(self, path: str) -> None:
        """Speichert die RunParams als YAML-Datei."""
        import yaml
        from dataclasses import asdict
        from pathlib import Path
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            yaml.dump(
                asdict(self),
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False)

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
        if "v_bnnt_ml" not in data:
            data["v_bnnt_ml"] = 0.0
        # Rückwärtskompatibilität: altes v_h2o_ml → phase_b1_target_ml
        if "phase_b1_target_ml" not in data:
            data["phase_b1_target_ml"] = data.pop("v_h2o_ml", 1400.0)
        if "run_phase_0" not in data:
            data["run_phase_0"] = True
        if "run_phase_a" not in data:
            data["run_phase_a"] = True
        if "run_phase_b" not in data:
            data["run_phase_b"] = True
        if "run_phase_c" not in data:
            data["run_phase_c"] = True
        # Alte Felder entfernen die nicht mehr existieren
        for _old in ("v_h2o_ml", "phase_0_stagnation_s"):
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
    # Annotation flow: main thread → worker (write to store); worker → main thread (chart marker)
    make_annotation = Signal(str)
    annotation_placed = Signal(float, str)
    # Emits the run_dir path once the telemetry store is initialised
    run_started = Signal(str)
    # Emits the effective total target volume after it is computed in run()
    progress_target_updated = Signal(float)

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
        self._last_ramp_loss_ml: float = 0.0   # Verlust vom letzten Zyklus (Empfehlung für Filling)
        self._filling_amount_ml: float = 0.0   # Vom Bediener manuell eingegebene Füllmenge
        self._flow_ema_ml_s: float = 0.0       # Exponential moving average des Flusses (Rauschen dämpfen)

        self.cmd_start_backwash_hold.connect(
            self._on_cmd_start_backwash_hold,
            Qt.ConnectionType.QueuedConnection)
        self.cmd_stop_backwash_hold.connect(
            self._on_cmd_stop_backwash_hold,
            Qt.ConnectionType.QueuedConnection)
        self.cmd_abort.connect(self._on_cmd_abort, Qt.ConnectionType.QueuedConnection)
        self.make_annotation.connect(
            self._on_make_annotation, Qt.ConnectionType.QueuedConnection)

    def set_params(self, params: RunParams) -> None:
        self._params = params

    def confirm_ok(self) -> None:
        self._ok_event.set()
        try:
            if self._store is not None:
                self._store.write_event("OK_BUTTON_PRESSED", {"step": self._current_step.value})
        except Exception as exc:
            logger.warning("confirm_ok: telemetry write failed: %s", exc)

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
                    "ABORT_REQUESTED", {
                        "reason": self._abort_reason, "step": self._current_step.value})
        except Exception:
            pass

    @Slot(str)
    def _on_make_annotation(self, text: str) -> None:
        t = self._store.t_s() if self._store is not None else 0.0
        if self._store is not None:
            try:
                self._store.write_event("ANNOTATION", {"text": str(text)})
            except Exception as exc:
                logger.warning("Annotation write failed: %s", exc)
        self.annotation_placed.emit(float(t), str(text))

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

        while not self._ok_event.wait(timeout=0.1):
            self._raise_if_abort()
            self._emit_sample(event=f"WAITING_OK_{step.value}")

    def _ensure_t0(self) -> None:
        if self._t0 is None:
            self._t0 = time.monotonic()

    def _unwrap_sensor(self, val) -> float:
        """Sicheres Entpacken von Hardware-Rückgaben."""
        if val is None:
            return 0.0
        if isinstance(val, (list, tuple)):
            return float(val[-1])
        return float(val)

    def _emit_sample(self, *, event: str = "") -> None:
        dev = self._dev
        exp = self._exp
        if dev is None or exp is None:
            return

        self._ensure_t0()
        now = time.monotonic()
        t_s = now - float(self._t0)  # type: ignore

        try:
            flow = self._unwrap_sensor(dev.read_flow())
        except Exception:
            flow = 0.0

        try:
            fn_valve = getattr(dev, "get_valve_state", getattr(dev, "get_state", None))
            valve_state = str(fn_valve()) if callable(fn_valve) else "UNKNOWN"
        except Exception:
            valve_state = "UNKNOWN"

        p1_set = p1_meas = p2_set = p2_meas = 0.0
        if getattr(dev, "pressure_controller", None) is not None:
            try:
                p1_set = self._unwrap_sensor(dev.get_pressure_setpoint_mbar(1))
            except Exception:
                pass
            try:
                p1_meas = self._unwrap_sensor(dev.get_pressure_mbar(1))
            except Exception:
                pass
            try:
                p2_set = self._unwrap_sensor(dev.get_pressure_setpoint_mbar(2))
            except Exception:
                pass
            try:
                p2_meas = self._unwrap_sensor(dev.get_pressure_mbar(2))
            except Exception:
                pass

        # Loss is maintained live by each phase loop via _total_loss_so_far.
        # We do NOT derive it from exp.volume_ml, which requires initial_volume_ml
        # to be set correctly in config (otherwise clamped to 0 and always 0).
        loss = self._total_loss_so_far

        sample = {
            "t": t_s,
            "step": self._current_step.value,
            "event": str(event or ""),
            "flow": flow,
            "p1_set": p1_set, "p1_meas": p1_meas,
            "p2_set": p2_set, "p2_meas": p2_meas,
            "volume_ml": loss, "loss_ml": loss,
            "valves": valve_state,
            "manual_active": bool(self._hold_active.is_set()),
            "pressure": {
                1: {"set": p1_set, "meas": p1_meas},
                2: {"set": p2_set, "meas": p2_meas},
            },
        }

        self.telemetry.emit(sample)
        # Emit live loss for progress bars (works during ALL phases including ramps)
        if loss > 0:
            self.loss_updated.emit(loss)
        try:
            if self._store is not None:
                self._store.write_sample(sample)
        except Exception as exc:
            logger.warning("_emit_sample: telemetry store write failed: %s", exc)

    def _safe_set_pressure_mbar(self, *, channel: int, mbar: float, ramp: bool = False) -> None:
        """Setzt Drucksollwert. ramp=False verhindert Hardware-Rampen (Software regelt selbst)."""
        dev = self._dev
        if dev is None or getattr(dev, "pressure_controller", None) is None:
            return
        try:
            dev.set_pressure_setpoint_mbar(
                channel=int(channel), setpoint_mbar=float(mbar), ramp=ramp)
        except Exception:
            pass

    def _safe_drop_pressure_all(self) -> None:
        for ch in (1, 2):
            try:
                self._safe_set_pressure_mbar(channel=ch, mbar=0.0)
            except Exception:
                continue

    def _enter_safe_state(self) -> None:
        try:
            self._hold_active.clear()
        except Exception:
            pass
        self._safe_drop_pressure_all()
        robust_switch_valves(self._dev, "SHUT")
        try:
            self._emit_sample(event="SAFE_STATE")
        except Exception:
            pass

    @Slot()
    def run(self) -> None:
        """Orchestrate the full filtration sequence."""
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

            self._exp = Experimentator(dev, self.cfg)  # type: ignore
            self._exp._on_sample = lambda ev="": self._emit_sample(event=ev)
            self._t0 = None
            _run_wall_t0 = time.monotonic()

            try:
                meta = build_run_meta(experiment_config=self.cfg, run_params=p)
                self._store = RunTelemetryStore(meta=meta)
                self._store.write_event("RUN_START", {"step": self._current_step.value})
                self.run_started.emit(str(self._store.paths.run_dir))
            except Exception:
                self._store = None

            exp = self._exp
            loss_a: float = 0.0
            loss_b1: float = 0.0
            loss_b2: float = 0.0
            loss_c: float = 0.0

            if p.run_phase_0:
                self._phase_0_backwash(dev, exp, p)

            # B1 target: operator input takes precedence; fallback from config.
            _config_target = float(p.v_bnnt_ml) + float(p.phase_b1_target_ml)
            target_vol = max(
                self._filling_amount_ml if self._filling_amount_ml > 0 else _config_target,
                float(p.phase_b1_target_ml),
                1.0,
            )
            self.progress_target_updated.emit(target_vol)

            if p.run_phase_a or p.run_phase_b or p.run_phase_c:
                self.log_msg.emit("─" * 52, "#8B5CF6")
                self.log_msg.emit(
                    f"Starting ramp automatically. Target: {p.phase_a_target_mbar:.0f} mbar",
                    "#8B5CF6")
                self.log_msg.emit("─" * 52, "#8B5CF6")

            if p.run_phase_a:
                loss_a = self._phase_a_ramp_up(dev, exp, p, target_vol)
            if p.run_phase_b:
                loss_b1, loss_b2 = self._phase_b_steady_state(dev, exp, p, target_vol, loss_a)
            if p.run_phase_c:
                loss_c = self._phase_c_ramp_down(dev, exp, p)

            total_loss = loss_a + loss_b1 + loss_b2 + loss_c
            self._exp.last_filtration_venting_loss_ml = float(total_loss)
            self._last_ramp_loss_ml = float(total_loss)
            self.loss_updated.emit(total_loss)
            self._emit_sample(event=f"END_SEQUENCE total_loss={total_loss:.4f}")

            elapsed_s = time.monotonic() - _run_wall_t0
            dur_min = int(elapsed_s) // 60
            dur_sec = int(elapsed_s) % 60
            _W = 36  # inner width of summary box
            def _row(label: str, val: str, col: str = "#CBD5E1") -> None:
                inner = f"  {label:<18}{val:>10}  "
                self.log_msg.emit(f"│{inner}│", col)

            self.log_msg.emit(f"┌{'─' * _W}┐", "#10B981")
            self.log_msg.emit(f"│{'  RUN COMPLETE':<{_W}}│", "#10B981")
            self.log_msg.emit(f"│{'─' * _W}│", "#10B981")
            _row("Duration:", f"{dur_min} min {dur_sec:02d} s")
            self.log_msg.emit(f"│{'─' * _W}│", "#475569")
            _row("Phase A  ramp up:", f"{loss_a:>8.1f} ml", "#8B5CF6")
            _row("Phase B1 steady:", f"{loss_b1:>8.1f} ml", "#F59E0B")
            _row("Phase B2 drying:", f"{loss_b2:>8.1f} ml", "#F59E0B")
            _row("Phase C  ramp dn:", f"{loss_c:>8.1f} ml", "#EC4899")
            self.log_msg.emit(f"│{'─' * _W}│", "#475569")
            _row("Total loss:", f"{total_loss:>8.1f} ml", "#10B981")
            _row("Next BW target:", f"{total_loss:>8.1f} ml", "#00E5FF")
            self.log_msg.emit(f"└{'─' * _W}┘", "#10B981")

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
            try:
                self._enter_safe_state()
            except Exception:
                pass
            if self._exp is not None:
                try:
                    self._exp.close()
                except Exception:
                    pass
            if self._store is not None:
                try:
                    self._store.close()
                except Exception:
                    pass
            if self._dev_owned and self._dev is not None:
                try:
                    if hasattr(self._dev, "__exit__"):
                        self._dev.__exit__(None, None, None)
                    elif hasattr(self._dev, "disconnect"):
                        self._dev.disconnect()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # PHASE 0: BACKWASH
    # ------------------------------------------------------------------

    def _phase_0_backwash(
        self,
        dev: DeviceManager,
        exp: Experimentator,
        p: RunParams,
    ) -> None:
        """Run Phase 0 (backwash) and the subsequent manual-filling gate."""
        self._current_step = Step.FILLING
        self.step_changed.emit("FILLING")
        bw_ch = int(self.cfg.backwash_pressure_channel)
        flow_dead = float(self.cfg.flow_deadband_ml_per_s)
        bw_target_ml = max(1.0, float(p.phase_0_target_ml))
        max_bw_duration_s = 3600.0  # safety ceiling: 60 min
        p0_mode = str(getattr(p, "phase_0_mode", "AUTO")).upper()

        self.log_msg.emit("═" * 52, "#EC4899")
        self.log_msg.emit(
            f"PHASE 0: BACKWASH [{p0_mode}]  "
            + (f"target: {bw_target_ml:.0f} ml  " if p0_mode == "AUTO" else "")
            + f"@ {p.phase_0_pressure_mbar:.0f} mbar",
            "#EC4899")
        self.log_msg.emit("═" * 52, "#EC4899")

        if p0_mode == "MANUAL":
            self.log_msg.emit(
                "Phase 0 MANUAL: use HOLD SPACE to backwash. Click OK when done.", "#EC4899")
            self.status.emit("Phase 0 MANUAL — operator controls pressure via HOLD SPACE")
        else:
            self.status.emit(
                f"BACKWASH [{p0_mode}]: "
                + (f"filling {bw_target_ml:.0f} ml..." if p0_mode == "AUTO"
                   else "fill until stopped..."))
            robust_switch_valves(dev, "BACKWASH", self.log_msg)
            if getattr(dev, "pressure_controller", None) is not None:
                self._safe_set_pressure_mbar(channel=bw_ch, mbar=float(p.phase_0_pressure_mbar))

            mode_bw = "PHASE_0_BACKWASH"
            exp._log_row(mode_bw, 0.0, float("nan"), float("nan"),
                         pressure_channel=bw_ch, event="START_BACKWASH")
            t_deadline = time.monotonic() + max_bw_duration_s
            bw_vol_filled = 0.0  # direct flow integration — no initial_volume dependency

            while not self._should_abort():
                dt_s, flow_raw = exp._sample_flow()
                flow_ml_s = exp._flow_to_ml_per_s(flow_raw)
                bw_vol_filled += abs(flow_ml_s) * dt_s
                exp._log_row(mode_bw, dt_s, flow_raw, flow_ml_s, pressure_channel=bw_ch)
                self._emit_sample(event="BACKWASH")
                self.phase_detail_updated.emit("P0", bw_vol_filled, bw_target_ml)

                if abs(flow_ml_s) > flow_dead:
                    bw_eta_s = (
                        max(0.0, bw_target_ml - bw_vol_filled) / abs(flow_ml_s)
                        if p0_mode == "AUTO" else 0
                    )
                    self.status.emit(
                        f"BW: {bw_vol_filled:.1f}"
                        + (f"/{bw_target_ml:.0f}" if p0_mode == "AUTO" else "")
                        + f" ml | Flow: {abs(flow_ml_s) * 60:.1f} ml/min"
                        + (f" | ETA: {bw_eta_s / 60:.1f} min" if p0_mode == "AUTO" else ""))
                else:
                    self.status.emit(f"BW: {bw_vol_filled:.1f} ml | Flow: waiting...")

                if p0_mode == "AUTO" and bw_vol_filled >= bw_target_ml:
                    self.log_msg.emit(
                        f"Backwash complete: {bw_vol_filled:.1f} ml filled "
                        f"(target: {bw_target_ml:.0f} ml).", "#10B981")
                    exp._log_row(mode_bw, 0.0, float("nan"), 0.0,
                                 pressure_channel=bw_ch, event="END_BACKWASH_TARGET")
                    break

                if time.monotonic() > t_deadline:
                    self.log_msg.emit(
                        f"BW safety timeout (60 min) — {bw_vol_filled:.1f} ml filled. "
                        "Continuing.", "#F59E0B")
                    exp._log_row(mode_bw, 0.0, float("nan"), 0.0,
                                 pressure_channel=bw_ch, event="END_BACKWASH_TIMEOUT")
                    break

                time.sleep(float(self.cfg.sample_period_s))

            if getattr(dev, "pressure_controller", None) is not None:
                self._safe_set_pressure_mbar(channel=bw_ch, mbar=0.0)
            robust_switch_valves(dev, "SHUT", self.log_msg)

        # Gate: Manual filling confirmation
        self._raise_if_abort()
        if self._last_ramp_loss_ml > 0:
            recommended_fill = max(0.0, self._last_ramp_loss_ml)
        else:
            recommended_fill = float(p.v_bnnt_ml) + float(p.phase_b1_target_ml)
        self.log_msg.emit("─" * 52, "#00E5FF")
        self.log_msg.emit("MANUAL FILLING REQUIRED", "#00E5FF")
        self.log_msg.emit(f"Recommended amount: {recommended_fill:.1f} ml", "#00E5FF")
        self.log_msg.emit("─" * 52, "#00E5FF")
        self.filling_requested.emit(recommended_fill)
        self._wait_ok(Step.FILLING, "Fill liquid and confirm")
        self.log_msg.emit(
            f"Filling confirmed: {self._filling_amount_ml:.1f} ml added.", "#10B981")

    # ------------------------------------------------------------------
    # PHASE A: RAMP UP
    # ------------------------------------------------------------------

    def _phase_a_ramp_up(
        self,
        dev: DeviceManager,
        exp: Experimentator,
        p: RunParams,
        target_vol: float,
    ) -> float:
        """Smooth pressure ramp from current setpoint to target. Returns filtrate loss [ml].

        Loss is computed via direct flow integration (flow_ml/s * dt), independent
        of initial_volume_ml config. _total_loss_so_far is updated live each tick
        so the GUI progress bar rises in real time.
        """
        self._current_step = Step.FILTRATION
        self.step_changed.emit("PHASE_A")
        ch = int(self.cfg.main_pressure_channel)

        start_mbar = exp._get_pressure_setpoint_mbar_best(ch)
        if start_mbar is None or start_mbar < 0:
            start_mbar = 0.0
        target_mbar = float(p.phase_a_target_mbar)
        delta_mbar = max(0.0, target_mbar - start_mbar)
        rate_mbar_s = float(p.phase_a_rate_mbar_min) / 60.0
        duration_s = (
            delta_mbar / rate_mbar_s if rate_mbar_s > 0 and delta_mbar > 0 else 10.0)

        robust_switch_valves(dev, "FILTRATION", self.log_msg)

        self.log_msg.emit("═" * 52, "#8B5CF6")
        self.log_msg.emit(
            f"PHASE A: {start_mbar:.0f} → {target_mbar:.0f} mbar"
            f"  @ {p.phase_a_rate_mbar_min:.0f} mbar/min"
            f"  ETA {duration_s / 60:.1f} min", "#8B5CF6")
        self.log_msg.emit(
            f"B1 target = {target_vol:.1f} ml "
            f"(Phase A loss will be subtracted)", "#64748B")
        self.log_msg.emit("═" * 52, "#8B5CF6")
        self._emit_sample(
            event=f"PHASE_A_START start={start_mbar:.0f} target={target_mbar:.0f}")

        _a_base = self._total_loss_so_far
        loss_a = 0.0
        t_start = time.monotonic()
        t_end = t_start + duration_s

        while not self._should_abort():
            now = time.monotonic()
            if now >= t_end:
                break
            alpha = min(1.0, (now - t_start) / duration_s)
            current_p = start_mbar + delta_mbar * alpha
            self._safe_set_pressure_mbar(channel=ch, mbar=current_p)

            dt_s, flow_raw = exp._sample_flow()
            flow_ml_s = abs(exp._flow_to_ml_per_s(flow_raw))
            loss_a += flow_ml_s * dt_s
            self._total_loss_so_far = _a_base + loss_a  # live update for progress bar

            eta_s = max(0.0, t_end - now)
            self.status.emit(
                f"Phase A: {current_p:.0f}/{target_mbar:.0f} mbar"
                f" | loss: {loss_a:.1f} ml | ETA: {eta_s / 60:.1f} min")
            self._emit_sample(event="PHASE_A_RAMP")
            time.sleep(float(self.cfg.sample_period_s))

        # Ensure pressure lands exactly on target
        self._safe_set_pressure_mbar(channel=ch, mbar=target_mbar)
        self._emit_sample(event=f"PHASE_A_END loss={loss_a:.4f}")
        self.log_msg.emit(f"Phase A complete. Loss: {loss_a:.1f} ml", "#8B5CF6")
        # _total_loss_so_far already == _a_base + loss_a

        # Wait for pressure overshoot to settle (max 30 s, within 5 % of setpoint).
        if getattr(dev, "pressure_controller", None) is not None:
            stab_deadline = time.monotonic() + 30.0
            self.status.emit(
                f"Phase A → B: waiting for pressure to stabilize at {target_mbar:.0f} mbar...")
            while not self._should_abort() and time.monotonic() < stab_deadline:
                try:
                    p_now = self._unwrap_sensor(dev.get_pressure_mbar(ch))
                except Exception:
                    break
                if target_mbar <= 0 or abs(p_now - target_mbar) / target_mbar < 0.05:
                    break
                self._emit_sample(event="PHASE_A_STABILIZING")
                time.sleep(0.5)

        return loss_a

    # ------------------------------------------------------------------
    # PHASE B: STEADY STATE + OPTIONAL DRYING (B1 + B2)
    # ------------------------------------------------------------------

    _EMA_ALPHA = 0.15  # flow EMA smoothing coefficient (~13 sample warm-up)

    def _phase_b_steady_state(
        self,
        dev: DeviceManager,
        exp: Experimentator,
        p: RunParams,
        target_vol: float,
        loss_a: float,
    ) -> tuple[float, float]:
        """Hold at target pressure until B1 (and optional B2) volume is removed.

        Returns (loss_b1, loss_b2) in ml.
        """
        self._current_step = Step.FILTRATION
        self.step_changed.emit("PHASE_B")
        ch = int(self.cfg.main_pressure_channel)
        stagnation_timeout_s = float(p.phase_b_no_flow_timeout_min) * 60.0
        flow_dead = float(self.cfg.flow_deadband_ml_per_s)

        # B1 target = overall filtration goal minus whatever was already lost in Phase A.
        remaining_b1 = max(0.0, target_vol - loss_a)
        self.status.emit(f"Phase B1 active (target: {remaining_b1:.1f} ml)")
        self.log_msg.emit("═" * 52, "#F59E0B")
        self.log_msg.emit(
            f"PHASE B1: STEADY STATE  {p.phase_a_target_mbar:.0f} mbar"
            f" | target: {remaining_b1:.1f} ml"
            f"  (total: {target_vol:.1f} ml − A-loss: {loss_a:.1f} ml)"
            f"  (timeout: {p.phase_b_no_flow_timeout_min:.0f} min)", "#F59E0B")
        if p.v_extra_ml > 0:
            self.log_msg.emit(f"Next: B2 — Drying ({p.v_extra_ml:.1f} ml)", "#64748B")
        else:
            self.log_msg.emit("Next: C — Ramp Down", "#64748B")
        self.log_msg.emit("═" * 52, "#F59E0B")
        self._emit_sample(event="STEP_START_PHASE_B1")

        robust_switch_valves(dev, "FILTRATION", self.log_msg)
        if getattr(dev, "pressure_controller", None) is not None:
            self._safe_set_pressure_mbar(channel=ch, mbar=float(p.phase_a_target_mbar))

        # Loss computed via direct flow integration — no exp.volume_ml dependency.
        _b1_base = self._total_loss_so_far
        loss_b1 = 0.0
        self._flow_ema_ml_s = 0.0
        last_flow_time_b1 = time.monotonic()

        while not self._should_abort():
            dt_s, flow_raw = exp._sample_flow()
            flow_ml_s = abs(exp._flow_to_ml_per_s(flow_raw))
            loss_b1 += flow_ml_s * dt_s
            self._total_loss_so_far = _b1_base + loss_b1  # live update for progress bar

            self._flow_ema_ml_s = (
                self._EMA_ALPHA * flow_ml_s
                + (1.0 - self._EMA_ALPHA) * self._flow_ema_ml_s
            )

            if self._flow_ema_ml_s > flow_dead:
                last_flow_time_b1 = time.monotonic()
            elif (time.monotonic() - last_flow_time_b1) > stagnation_timeout_s:
                self.log_msg.emit(
                    f"B1 SAFETY: No flow for {p.phase_b_no_flow_timeout_min:.0f} min! "
                    f"Filter may be clogged. ({loss_b1:.1f}/{remaining_b1:.1f} mL)",
                    "#FF1744")
                break

            if loss_b1 >= remaining_b1:
                self.log_msg.emit(
                    f"Phase B1 complete: {loss_b1:.1f} mL removed.", "#10B981")
                break

            self.phase_detail_updated.emit("B1", loss_b1, remaining_b1)
            self._emit_sample(event="PHASE_B1_HOLD")
            remaining_ml = max(0.0, remaining_b1 - loss_b1)
            if self._flow_ema_ml_s > flow_dead:
                eta_s = remaining_ml / self._flow_ema_ml_s
                self.status.emit(
                    f"B1: {loss_b1:.1f}/{remaining_b1:.1f} ml"
                    f" | {self._flow_ema_ml_s * 60:.1f} ml/min"
                    f" | ETA: {eta_s / 60:.1f} min")
            else:
                self.status.emit(
                    f"B1: {loss_b1:.1f}/{remaining_b1:.1f} ml | Flow: waiting...")
            time.sleep(float(self.cfg.sample_period_s))

        # _total_loss_so_far already == _b1_base + loss_b1

        # B2: optional extra drying volume
        loss_b2 = 0.0
        if p.v_extra_ml > 0 and not self._should_abort():
            self.status.emit(f"Phase B2 active (drying: {p.v_extra_ml:.1f} ml)")
            self.log_msg.emit("─" * 52, "#F59E0B")
            self.log_msg.emit(
                f"PHASE B2: DRYING → target: {p.v_extra_ml:.1f} ml"
                f"  (timeout: {p.phase_b_no_flow_timeout_min:.0f} min)", "#F59E0B")
            self.log_msg.emit("Next: C — Ramp Down", "#64748B")
            self.log_msg.emit("─" * 52, "#F59E0B")

            _b2_base = self._total_loss_so_far
            last_flow_time_b2 = time.monotonic()
            self._flow_ema_ml_s = 0.0

            while not self._should_abort():
                dt_s, flow_raw = exp._sample_flow()
                flow_ml_s = abs(exp._flow_to_ml_per_s(flow_raw))
                loss_b2 += flow_ml_s * dt_s
                self._total_loss_so_far = _b2_base + loss_b2  # live update

                self._flow_ema_ml_s = (
                    self._EMA_ALPHA * flow_ml_s
                    + (1.0 - self._EMA_ALPHA) * self._flow_ema_ml_s
                )

                if self._flow_ema_ml_s > flow_dead:
                    last_flow_time_b2 = time.monotonic()
                elif (time.monotonic() - last_flow_time_b2) > stagnation_timeout_s:
                    self.log_msg.emit(
                        f"B2 SAFETY: No flow for {p.phase_b_no_flow_timeout_min:.0f} min!"
                        f" ({loss_b2:.1f}/{p.v_extra_ml:.1f} mL)", "#FF1744")
                    break

                if loss_b2 >= p.v_extra_ml:
                    self.log_msg.emit(
                        f"Phase B2 complete: {loss_b2:.1f} mL dried.", "#10B981")
                    break

                self.phase_detail_updated.emit("B2", loss_b2, p.v_extra_ml)
                self._emit_sample(event="PHASE_B2_DRYING")
                rem_b2 = max(0.0, p.v_extra_ml - loss_b2)
                if self._flow_ema_ml_s > flow_dead:
                    eta_s = rem_b2 / self._flow_ema_ml_s
                    self.status.emit(
                        f"B2: {loss_b2:.1f}/{p.v_extra_ml:.1f} ml"
                        f" | {self._flow_ema_ml_s * 60:.1f} ml/min"
                        f" | ETA: {eta_s / 60:.1f} min")
                else:
                    self.status.emit(
                        f"B2: {loss_b2:.1f}/{p.v_extra_ml:.1f} ml | Flow: waiting...")
                time.sleep(float(self.cfg.sample_period_s))
            # _total_loss_so_far already == _b2_base + loss_b2

        self._emit_sample(event=f"PHASE_B_END total_b={loss_b1 + loss_b2:.4f}")
        return loss_b1, loss_b2

    # ------------------------------------------------------------------
    # PHASE C: RAMP DOWN
    # ------------------------------------------------------------------

    def _phase_c_ramp_down(
        self,
        dev: DeviceManager,
        exp: Experimentator,
        p: RunParams,
    ) -> float:
        """Smooth pressure ramp from current setpoint down to 0 mbar. Returns filtrate loss [ml].

        Loss is computed via direct flow integration so it is independent of
        initial_volume_ml. _total_loss_so_far is updated live for the progress bar.
        """
        self._current_step = Step.FILTRATION
        self.step_changed.emit("PHASE_C")
        ch = int(self.cfg.main_pressure_channel)

        start_mbar = exp._get_pressure_meas_mbar_best(ch)
        if start_mbar is None or start_mbar <= 0:
            start_mbar = exp._get_pressure_setpoint_mbar_best(ch)
        if start_mbar is None or start_mbar <= 0:
            start_mbar = float(p.phase_a_target_mbar)

        rate_mbar_min = float(p.phase_c_rate_mbar_min)
        duration_s = (
            start_mbar / rate_mbar_min * 60.0
            if rate_mbar_min > 0 and start_mbar > 0 else 30.0
        )

        self.log_msg.emit("═" * 52, "#EC4899")
        self.log_msg.emit(
            f"PHASE C: {start_mbar:.0f} → 0 mbar"
            f"  @ {rate_mbar_min:.0f} mbar/min"
            f"  ETA {duration_s / 60:.1f} min", "#EC4899")
        self.log_msg.emit("═" * 52, "#EC4899")
        self.status.emit(f"Phase C: pressure release {start_mbar:.0f} → 0 mbar")
        self._emit_sample(event=f"PHASE_C_START from={start_mbar:.0f}")

        _c_base = self._total_loss_so_far
        loss_c = 0.0
        t_start = time.monotonic()
        t_end = t_start + duration_s

        while not self._should_abort():
            now = time.monotonic()
            if now >= t_end:
                break
            alpha = min(1.0, (now - t_start) / duration_s)
            current_p = max(0.0, start_mbar * (1.0 - alpha))
            self._safe_set_pressure_mbar(channel=ch, mbar=current_p)

            dt_s, flow_raw = exp._sample_flow()
            flow_ml_s = abs(exp._flow_to_ml_per_s(flow_raw))
            loss_c += flow_ml_s * dt_s
            self._total_loss_so_far = _c_base + loss_c  # live update for progress bar

            eta_s = max(0.0, t_end - now)
            self.status.emit(
                f"Phase C: {current_p:.0f}/{start_mbar:.0f} mbar"
                f" | loss: {loss_c:.1f} ml | ETA: {eta_s / 60:.1f} min")
            self._emit_sample(event="PHASE_C_RAMP_DOWN")
            time.sleep(float(self.cfg.sample_period_s))

        self._safe_set_pressure_mbar(channel=ch, mbar=0.0)
        robust_switch_valves(dev, "SHUT", self.log_msg)

        self._emit_sample(event=f"PHASE_C_END loss={loss_c:.4f}")
        self.log_msg.emit(f"Phase C complete. Loss: {loss_c:.1f} ml", "#EC4899")
        # _total_loss_so_far already == _c_base + loss_c
        return loss_c
