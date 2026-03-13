from __future__ import annotations

import csv
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from src.utils.path_utils import ensure_dir, project_root, resolve_under

logger = logging.getLogger(__name__)


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
                "ts",
                "mode",
                "loop_idx",
                "dt_s",
                "flow_raw",
                "flow_ml_per_s",
                "net_flow_ml_per_s",
                "volume_ml_est",
                "volume_delta_ml",
                "pressure_setpoint_pct",
                "pressure_meas_pct",
                "pressure_channel",
                "pressure_setpoint_mbar",
                "pressure_meas_mbar",
                "valve_state",
                "removed_ml_since_step_start",
                "event",
            ],
        )

        self._rows_since_flush: int = 0
        self._last_flush_t: float = time.monotonic()

        if bool(cfg.write_csv_preamble):
            self._write_preamble()

        self._csv.writeheader()
        self._flush(force=True)

        logger.info("Experimentator initialized (log=%s)", self.log_path)
        logger.info("Initial volume: %.6f mL | cfg=%s", self.volume_ml, asdict(self.cfg))

    def close(self) -> None:
        try:
            try:
                self._flush(force=True)
            except Exception:
                pass
        finally:
            try:
                self._csv_file.close()
            except Exception:
                pass

    def _write_preamble(self) -> None:
        try:
            self._csv_file.write(f"# created={_ts_iso()}\n")
            self._csv_file.write(f"# host={os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or ''}\n")
            self._csv_file.write(f"# cfg={asdict(self.cfg)}\n")
        except Exception:
            pass

    def _flush(self, *, force: bool = False) -> None:
        n = max(1, int(getattr(self.cfg, "log_flush_every_n", 10)))
        every_s = float(getattr(self.cfg, "log_flush_every_s", 1.0))
        do_fsync = bool(getattr(self.cfg, "log_fsync_on_flush", False))

        now = time.monotonic()
        due_count = (self._rows_since_flush >= n)
        due_time = ((now - self._last_flush_t) >= every_s)

        if not force and not (due_count or due_time):
            return

        try:
            self._csv_file.flush()
        except Exception:
            pass

        if do_fsync:
            try:
                os.fsync(self._csv_file.fileno())
            except Exception:
                pass

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

        if dt < 0:
            dt = 0.0
        dt = min(dt, float(self.cfg.max_dt_s))

        flow_raw = float(self.dev.read_flow())
        self._last_flow_raw = flow_raw
        return dt, flow_raw

    def _update_volume(self, dt_s: float, flow_raw: float, *, net_sign: float) -> float:
        if dt_s <= 0.0:
            return 0.0

        flow_ml_s = self._flow_to_ml_per_s(flow_raw)

        dead = float(self.cfg.flow_deadband_ml_per_s or 0.0)
        if dead > 0.0 and abs(flow_ml_s) < dead:
            net_ml_s = 0.0
        else:
            net_ml_s = float(net_sign) * abs(float(flow_ml_s))

        old = float(self.volume_ml)
        new = old + net_ml_s * float(dt_s)

        if bool(self.cfg.clamp_volume_to_min):
            vmin = float(self.cfg.min_volume_ml)
            if new < vmin:
                new = vmin

        self.volume_ml = float(new)
        return float(net_ml_s)

    def _mbar_to_percent(self, mbar: float) -> float:
        fs = float(self.cfg.pressure_full_scale_mbar or 8000.0)
        if fs <= 0:
            fs = 8000.0
        return _clamp(float(mbar) / fs * 100.0, 0.0, 100.0)

    def _percent_to_mbar(self, pct: float) -> float:
        fs = float(self.cfg.pressure_full_scale_mbar or 8000.0)
        if fs <= 0:
            fs = 8000.0
        return (float(pct) / 100.0) * fs

    def _set_pressure_pct(self, *, channel: int, pct: float, ramp: bool) -> None:
        ch = int(channel)
        val = float(pct)
        fn = getattr(self.dev, "set_pressure", None)
        if not callable(fn):
            raise RuntimeError("Device has no set_pressure()")

        try:
            fn(val, channel=ch, ramp=ramp)  # type: ignore[misc]
            return
        except TypeError:
            pass
        try:
            fn(val, ch, ramp=ramp)  # type: ignore[misc]
            return
        except TypeError:
            pass
        fn(val, ch)  # type: ignore[misc]

    def _set_pressure_mbar(self, *, channel: int, mbar: float, ramp: bool) -> None:
        if getattr(self.dev, "pressure_controller", None) is None:
            raise RuntimeError("PressureController disabled")

        if hasattr(self.dev, "set_pressure_setpoint_mbar"):
            try:
                self.dev.set_pressure_setpoint_mbar(channel=int(channel), setpoint_mbar=float(mbar), ramp=bool(ramp))  # type: ignore[attr-defined]
                return
            except Exception:
                pass

        pct = self._mbar_to_percent(float(mbar))
        self._set_pressure_pct(channel=int(channel), pct=float(pct), ramp=bool(ramp))

    def _get_pressure_setpoint_pct(self, channel: int) -> Optional[float]:
        try:
            v = self.dev.get_pressure_setpoint(int(channel))
            return float(v)
        except Exception:
            return None

    def _get_pressure_meas_pct(self, channel: int) -> Optional[float]:
        try:
            v = self.dev.get_pressure(int(channel))
            return float(v)
        except Exception:
            return None

    def _get_pressure_setpoint_mbar_best(self, channel: int) -> Optional[float]:
        try:
            if hasattr(self.dev, "get_pressure_setpoint_mbar"):
                return float(self.dev.get_pressure_setpoint_mbar(int(channel)))  # type: ignore[attr-defined]
        except Exception:
            pass
        sp = self._get_pressure_setpoint_pct(int(channel))
        if sp is None:
            return None
        return self._percent_to_mbar(float(sp))

    def _get_pressure_meas_mbar_best(self, channel: int) -> Optional[float]:
        try:
            if hasattr(self.dev, "get_pressure_mbar"):
                return float(self.dev.get_pressure_mbar(int(channel)))  # type: ignore[attr-defined]
        except Exception:
            pass
        ms = self._get_pressure_meas_pct(int(channel))
        if ms is None:
            return None
        return self._percent_to_mbar(float(ms))

    def _safety_check(self, mode: str) -> None:
        margin = float(self.volume_ml) - float(self.cfg.min_volume_ml)
        if margin < 0:
            logger.error(
                "SAFETY STOP triggered in mode %s (volume=%.6f < min=%.6f)",
                mode,
                self.volume_ml,
                self.cfg.min_volume_ml,
            )
            try:
                self.dev.all_valves_shut()
            finally:
                raise RuntimeError(
                    f"SAFETY STOP: volume {self.volume_ml:.6f} mL below min {self.cfg.min_volume_ml:.6f} mL (mode={mode})"
                )

    def _log_row(
        self,
        mode: str,
        dt_s: float,
        flow_raw: float,
        flow_ml_s: float,
        *,
        net_flow_ml_s: float = 0.0,
        pressure_channel: Optional[int] = None,
        event: str = "",
    ) -> None:
        self._loop_idx += 1

        p_set_pct = ""
        p_meas_pct = ""
        p_set_mbar = ""
        p_meas_mbar = ""
        ch = ""

        if pressure_channel is not None and getattr(self.dev, "pressure_controller", None) is not None:
            ch_i = int(pressure_channel)
            sp = self._get_pressure_setpoint_pct(ch_i)
            ms = self._get_pressure_meas_pct(ch_i)
            sp_mbar = self._get_pressure_setpoint_mbar_best(ch_i)
            ms_mbar = self._get_pressure_meas_mbar_best(ch_i)

            if sp is not None:
                p_set_pct = f"{sp:.3f}"
            if ms is not None:
                p_meas_pct = f"{ms:.3f}"
            if sp_mbar is not None:
                p_set_mbar = f"{sp_mbar:.3f}"
            if ms_mbar is not None:
                p_meas_mbar = f"{ms_mbar:.3f}"
            ch = str(ch_i)

        try:
            valve_state = str(self.dev.get_valve_state())
        except Exception:
            valve_state = "UNKNOWN"

        removed_ml = max(0.0, float(self._step_start_volume) - float(self.volume_ml))
        volume_delta = float(net_flow_ml_s) * float(dt_s)

        def _nf(x: Any) -> Any:
            if isinstance(x, str):
                return x
            if x is None:
                return ""
            try:
                v = float(x)
            except Exception:
                return ""
            return v if _is_finite_number(v) else ""

        self._csv.writerow(
            {
                "ts": _ts_iso(),
                "mode": str(mode),
                "loop_idx": int(self._loop_idx),
                "dt_s": round(float(dt_s), 6),
                "flow_raw": _nf(flow_raw),
                "flow_ml_per_s": _nf(flow_ml_s),
                "net_flow_ml_per_s": _nf(net_flow_ml_s),
                "volume_ml_est": _nf(self.volume_ml),
                "volume_delta_ml": _nf(volume_delta),
                "pressure_setpoint_pct": p_set_pct,
                "pressure_meas_pct": p_meas_pct,
                "pressure_channel": ch,
                "pressure_setpoint_mbar": p_set_mbar,
                "pressure_meas_mbar": p_meas_mbar,
                "valve_state": valve_state,
                "removed_ml_since_step_start": _nf(removed_ml),
                "event": str(event or ""),
            }
        )

        self._rows_since_flush += 1
        self._flush(force=False)

    def wait_for_ok(self, reason: str, ok_fn: Optional[Callable[[], bool]] = None) -> None:
        logger.info("Waiting for manual OK: %s", reason)
        self._log_row("GATE", 0.0, float("nan"), float("nan"), event=f"WAIT_OK:{reason}")

        if ok_fn is None:
            input(f"[MANUAL OK REQUIRED] {reason} -> press ENTER to continue...")
            self._log_row("GATE", 0.0, float("nan"), float("nan"), event="OK_RECEIVED")
            return

        while True:
            if ok_fn():
                self._log_row("GATE", 0.0, float("nan"), float("nan"), event="OK_RECEIVED")
                return
            time.sleep(0.1)

    def ramp_pressure_linear_mbar(self, *, channel: int, target_mbar: float, duration_s: float) -> None:
        mode = "RAMP"
        ch = int(channel)
        target_pct = self._mbar_to_percent(float(target_mbar))

        if getattr(self.dev, "pressure_controller", None) is None:
            raise RuntimeError("PressureController disabled")

        start_pct = self._get_pressure_setpoint_pct(ch)
        if start_pct is None:
            start_pct = 0.0

        logger.info(
            "RAMP START ch=%d start_pct=%.3f target_pct=%.3f duration_s=%.3f (target_mbar=%.1f)",
            ch,
            start_pct,
            target_pct,
            float(duration_s),
            float(target_mbar),
        )

        if float(duration_s) <= 0.0:
            self._set_pressure_pct(channel=ch, pct=target_pct, ramp=False)
            self._log_row(mode, 0.0, float("nan"), float("nan"), pressure_channel=ch, event="RAMP_INSTANT")
            return

        dt = max(0.05, float(self.cfg.ramp_update_dt_s or 0.15))
        steps = max(1, int(float(duration_s) / dt))

        self._log_row(mode, 0.0, float("nan"), float("nan"), pressure_channel=ch, event="RAMP_START")

        for i in range(1, steps + 1):
            alpha = i / steps
            pct = float(start_pct) + (float(target_pct) - float(start_pct)) * alpha
            self._set_pressure_pct(channel=ch, pct=pct, ramp=False)

            dt_s, flow_raw = self._sample_flow()
            flow_ml_s = self._flow_to_ml_per_s(flow_raw)
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=+1.0)

            self._log_row(
                mode,
                dt_s,
                flow_raw,
                flow_ml_s,
                net_flow_ml_s=net_ml_s,
                pressure_channel=ch,
            )
            self._safety_check(mode)
            time.sleep(dt)

        self._log_row(mode, 0.0, float("nan"), float("nan"), pressure_channel=ch, event="RAMP_END")
        logger.info("RAMP END ch=%d", ch)

    def _run_timed_step(
        self,
        *,
        mode: str,
        duration_s: float,
        pressure_channel: Optional[int],
        net_sign: float,
        set_valves: Callable[[], None],
        event_start: str,
        event_end: str,
    ) -> None:
        mode = str(mode)
        logger.info("===== START %s (duration=%.3f) =====", mode, float(duration_s))
        self._step_start_volume = float(self.volume_ml)

        try:
            set_valves()
        except Exception:
            pass

        self._log_row(mode, 0.0, float("nan"), float("nan"), pressure_channel=pressure_channel, event=str(event_start))

        t_end = time.monotonic() + float(max(0.0, duration_s))

        while time.monotonic() < t_end:
            dt_s, flow_raw = self._sample_flow()
            flow_ml_s = self._flow_to_ml_per_s(flow_raw)
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=float(net_sign))

            self._log_row(
                mode,
                dt_s,
                flow_raw,
                flow_ml_s,
                net_flow_ml_s=net_ml_s,
                pressure_channel=pressure_channel,
            )

            self._safety_check(mode)
            time.sleep(float(self.cfg.sample_period_s))

        self._log_row(
            mode,
            0.0,
            self._last_flow_raw if self._last_flow_raw is not None else float("nan"),
            0.0,
            pressure_channel=pressure_channel,
            event=str(event_end),
        )

        delta = float(self._step_start_volume) - float(self.volume_ml)
        logger.info("===== END %s | ΔV=%.6f mL =====", mode, delta)

    def step_backwash_manual_then_run(
            self,
            *,
            ok_fn: Optional[Callable[[], bool]],
            duration_s: float,
            pressure_mbar: Optional[float] = None,
    ) -> None:
        # KORREKTUR 1: Zuerst in den Backwash-Status schalten!
        try:
            self.dev.valves_backwash()
        except Exception:
            pass

        # KORREKTUR 2: Jetzt erst warten, während die Ventile schon offen sind
        self.wait_for_ok("Perform BACKWASH and confirm", ok_fn=ok_fn)

        # Ab hier läuft der eigentliche, zeitgesteuerte Backwash 1
        pch = int(self.cfg.backwash_pressure_channel)
        if pressure_mbar is not None and getattr(self.dev, "pressure_controller", None) is not None:
            self._set_pressure_mbar(channel=pch, mbar=float(pressure_mbar), ramp=True)

        self._run_timed_step(
            mode="BACKWASH",
            duration_s=float(duration_s),
            pressure_channel=pch if getattr(self.dev, "pressure_controller", None) is not None else None,
            net_sign=-1.0,
            set_valves=self.dev.valves_backwash,
            event_start="START_BACKWASH",
            event_end="END_BACKWASH",
        )

    def step_filling_with_linear_ramp(
        self,
        *,
        target_pressure_mbar: float,
        ramp_duration_s: float,
        hold_duration_s: float,
    ) -> tuple[float, float]:
        logger.info(
            "Executing FILLING target_mbar=%.1f ramp=%.3f hold=%.3f",
            float(target_pressure_mbar),
            float(ramp_duration_s),
            float(hold_duration_s),
        )

        if float(ramp_duration_s) <= 0.0:
            ramp_duration_s = max(5.0, min(30.0, abs(float(target_pressure_mbar)) / 50.0 * 5.0))

        target_pct = self._mbar_to_percent(float(target_pressure_mbar))
        ch = int(self.cfg.main_pressure_channel)

        try:
            self.dev.valves_filling_solution()
        except Exception:
            pass

        if getattr(self.dev, "pressure_controller", None) is not None:
            self.ramp_pressure_linear_mbar(channel=ch, target_mbar=float(target_pressure_mbar), duration_s=float(ramp_duration_s))
            if float(hold_duration_s) > 0.0:
                self._set_pressure_pct(channel=ch, pct=target_pct, ramp=False)

        self._run_timed_step(
            mode="FILLING",
            duration_s=float(hold_duration_s),
            pressure_channel=ch if getattr(self.dev, "pressure_controller", None) is not None else None,
            net_sign=+1.0,
            set_valves=self.dev.valves_filling_solution,
            event_start="START_FILLING",
            event_end="END_FILLING",
        )
        return float(target_pct), float(ramp_duration_s)
    
    def step_staircase_ramp(
        self,
        *,
        target_pressure_mbar: float,
        step_size_mbar: float,
        step_time_s: float,
        wait_for_ok_fn: Optional[Callable[[str], None]] = None
    ) -> float:
        """
        Staircase ramp — funktioniert jetzt in BEIDE Richtungen.
        - Aktueller Druck > target → rampt RUNTER
        - Aktueller Druck < target → rampt HOCH
        """
        logger.info(
            "STAIRCASE RAMP to %.1f mbar (step: %.1f, time: %.1fs)",
            target_pressure_mbar, step_size_mbar, step_time_s
        )
 
        ch = int(self.cfg.main_pressure_channel)
 
        try:
            self.dev.valves_filtration()
        except Exception:
            pass
 
        if step_size_mbar <= 0 or step_time_s <= 0:
            return 0.0
 
        # ═══════════════════════════════════════════════
        # FIX: Startpunkt = aktueller Druck, nicht 0!
        # ═══════════════════════════════════════════════
        start_mbar = self._get_pressure_setpoint_mbar_best(ch)
        if start_mbar is None:
            start_mbar = 0.0
 
        current_target = float(start_mbar)
        target = float(target_pressure_mbar)
        step = abs(float(step_size_mbar))
        v0 = float(self.volume_ml)
 
        # Richtung bestimmen
        ramping_up = (target > current_target)
 
        # Schon am Ziel?
        if abs(current_target - target) < 0.1:
            return 0.0
 
        while True:
            # Nächste Stufe berechnen
            if ramping_up:
                current_target = min(current_target + step, target)
            else:
                current_target = max(current_target - step, target)
 
            # Optionaler OK-Gate
            if wait_for_ok_fn:
                wait_for_ok_fn(f"Confirm ramp step to {current_target:.0f} mbar")
 
            # Druck setzen
            if getattr(self.dev, "pressure_controller", None) is not None:
                self._set_pressure_mbar(channel=ch, mbar=current_target, ramp=True)
 
            # Halten & Messen
            self._run_timed_step(
                mode="STAIRCASE_RAMP",
                duration_s=float(step_time_s),
                pressure_channel=ch if getattr(self.dev, "pressure_controller", None) is not None else None,
                net_sign=-1.0,
                set_valves=self.dev.valves_filtration,
                event_start=f"RAMP_STEP_{current_target:.0f}_START",
                event_end=f"RAMP_STEP_{current_target:.0f}_END",
            )
 
            # Ziel erreicht?
            if ramping_up and current_target >= target:
                break
            if not ramping_up and current_target <= target:
                break
 
        loss_ml = max(0.0, v0 - float(self.volume_ml))
        return float(loss_ml)

    def step_steady_state_volume_target(
        self,
        *,
        target_volume_ml_to_remove: float,
        pressure_mbar: float,
        max_duration_s: float = 86400.0, 
    ) -> float:
        """Phase B: Hält den Druck, bis das exakte Zielvolumen durchgelaufen ist."""
        logger.info("STEADY STATE at %.1f mbar until %.4f mL removed", pressure_mbar, target_volume_ml_to_remove)
        
        ch = int(self.cfg.main_pressure_channel)
        try:
            self.dev.valves_filtration()
        except Exception:
            pass

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

            if removed >= target_volume_ml_to_remove:
                logger.info("STEADY STATE Target volume reached (%.4f / %.4f ml)", removed, target_volume_ml_to_remove)
                break

            time.sleep(float(self.cfg.sample_period_s))

        removed = max(0.0, v_start - float(self.volume_ml))
        self._log_row(mode, 0.0, float("nan"), 0.0, pressure_channel=ch, event=f"END_STEADY_STATE removed={removed:.4f}")
        return removed

    def step_filtration_and_venting_track_loss(
        self,
        *,
        filtration_duration_s: float,
        venting_duration_s: float,
        filtration_pressure_mbar: Optional[float] = None,
    ) -> float:
        logger.info(
            "Executing FILTRATION+VENTING filtration=%.3f venting=%.3f",
            float(filtration_duration_s),
            float(venting_duration_s),
        )

        v0 = float(self.volume_ml)
        ch = int(self.cfg.main_pressure_channel)

        try:
            self.dev.valves_filtration()
        except Exception:
            pass

        if filtration_pressure_mbar is not None and getattr(self.dev, "pressure_controller", None) is not None:
            self._set_pressure_mbar(channel=ch, mbar=float(filtration_pressure_mbar), ramp=True)

        self._run_timed_step(
            mode="FILTRATION",
            duration_s=float(filtration_duration_s),
            pressure_channel=ch if getattr(self.dev, "pressure_controller", None) is not None else None,
            net_sign=-1.0,
            set_valves=self.dev.valves_filtration,
            event_start="START_FILTRATION",
            event_end="END_FILTRATION",
        )

        if getattr(self.dev, "pressure_controller", None) is not None:
            for c in (int(self.cfg.main_pressure_channel), int(self.cfg.backwash_pressure_channel)):
                try:
                    self._set_pressure_pct(channel=c, pct=0.0, ramp=True)
                except Exception:
                    pass

        self._run_timed_step(
            mode="VENTING",
            duration_s=float(venting_duration_s),
            pressure_channel=None,
            net_sign=-1.0,
            set_valves=self.dev.valves_venting,
            event_start="START_VENTING",
            event_end="END_VENTING",
        )

        v1 = float(self.volume_ml)
        loss_ml = max(0.0, v0 - v1)
        self.last_filtration_venting_loss_ml = float(loss_ml)

        self._log_row("LOSS", 0.0, float("nan"), float("nan"), event=f"FILTRATION_VENTING_LOSS={loss_ml:.6f}")
        return float(loss_ml)

    def step_backwash_remove_volume(
        self,
        *,
        base_remove_ml: Optional[float] = None,
        add_previous_loss: bool = True,
        max_duration_s: float = 300.0,
        backwash_pressure_mbar: Optional[float] = None,
    ) -> float:
        base = float(base_remove_ml) if base_remove_ml is not None else float(self.cfg.base_backwash_remove_ml)
        add = float(self.last_filtration_venting_loss_ml) if bool(add_previous_loss) else 0.0
        target_remove_ml = max(0.0, base + add)

        logger.info("Executing BACKWASH2 target_remove_ml=%.6f (base=%.6f add=%.6f)", target_remove_ml, base, add)

        try:
            self.dev.valves_backwash()
        except Exception:
            pass

        ch = int(self.cfg.backwash_pressure_channel)
        if backwash_pressure_mbar is not None and getattr(self.dev, "pressure_controller", None) is not None:
            self._set_pressure_mbar(channel=ch, mbar=float(backwash_pressure_mbar), ramp=True)

        v_start = float(self.volume_ml)
        self._step_start_volume = float(self.volume_ml)

        self._log_row("BACKWASH2", 0.0, float("nan"), float("nan"), pressure_channel=ch if getattr(self.dev, "pressure_controller", None) is not None else None, event="START_BACKWASH2")

        t_end = time.monotonic() + float(max(0.0, max_duration_s))

        while time.monotonic() < t_end:
            dt_s, flow_raw = self._sample_flow()
            flow_ml_s = self._flow_to_ml_per_s(flow_raw)
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=-1.0)

            removed = max(0.0, v_start - float(self.volume_ml))

            self._log_row(
                "BACKWASH2",
                dt_s,
                flow_raw,
                flow_ml_s,
                net_flow_ml_s=net_ml_s,
                pressure_channel=ch if getattr(self.dev, "pressure_controller", None) is not None else None,
            )

            self._safety_check("BACKWASH2")

            if removed >= float(target_remove_ml):
                break

            time.sleep(float(self.cfg.sample_period_s))

        removed = max(0.0, v_start - float(self.volume_ml))

        self._log_row(
            "BACKWASH2",
            0.0,
            self._last_flow_raw if self._last_flow_raw is not None else float("nan"),
            0.0,
            pressure_channel=ch if getattr(self.dev, "pressure_controller", None) is not None else None,
            event=f"END_BACKWASH2 removed_ml={removed:.6f}",
        )

        return float(removed)