from __future__ import annotations

import csv
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from src.backend.core.device_manager import DeviceManager

logger = logging.getLogger(__name__)


def _ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class ExperimentConfig:
    initial_volume_ml: float
    min_volume_ml: float = 0.0
    sample_period_s: float = 0.2
    log_dir: str = "logs"
    log_name_prefix: str = "run"
    flow_is_ml_per_min: bool = True
    pressure_full_scale_mbar: float = 8000.0
    ramp_update_dt_s: float = 0.15
    base_backwash_remove_ml: float = 0.0


class Experimentator:
    def __init__(self, dev: DeviceManager, cfg: ExperimentConfig):
        self.dev = dev
        self.cfg = cfg

        self.volume_ml: float = cfg.initial_volume_ml
        self._t_prev: Optional[float] = None
        self._last_flow_raw: Optional[float] = None
        self.last_filtration_venting_loss_ml: float = 0.0

        self._loop_idx = 0
        self._step_start_volume = self.volume_ml

        os.makedirs(cfg.log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(cfg.log_dir, f"{cfg.log_name_prefix}_{stamp}.csv")

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
                "valve_state",
                "removed_ml_since_step_start",
                "event",
            ],
        )
        self._csv.writeheader()
        self._csv_file.flush()

        logger.info("Experimentator initialized")
        logger.info("Initial volume: %.6f mL", self.volume_ml)
        logger.info("Config: %s", self.cfg)

    def close(self) -> None:
        try:
            self._csv_file.flush()
        finally:
            self._csv_file.close()

    def _flow_to_ml_per_s(self, flow_raw: float) -> float:
        return flow_raw / 60.0 if self.cfg.flow_is_ml_per_min else flow_raw

    def _sample_flow(self) -> tuple[float, float]:
        t = time.monotonic()
        if self._t_prev is None:
            self._t_prev = t
            return 0.0, float(self.dev.read_flow())
        dt = t - self._t_prev
        self._t_prev = t
        flow_raw = float(self.dev.read_flow())
        self._last_flow_raw = flow_raw
        return dt, flow_raw

    def _safety_check(self, mode: str) -> None:
        margin = self.volume_ml - self.cfg.min_volume_ml
        logger.debug("Safety margin: %.6f mL", margin)
        if margin < 0:
            logger.error("SAFETY STOP triggered in mode %s", mode)
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

        p_set = ""
        p_meas = ""
        p_set_mbar = ""
        ch = ""

        if pressure_channel is not None and self.dev.pressure_controller is not None:
            try:
                p_set_val = self.dev.get_pressure_setpoint(pressure_channel)
                p_set = f"{p_set_val:.3f}"
                p_set_mbar = f"{p_set_val * self.cfg.pressure_full_scale_mbar / 100.0:.3f}"
            except Exception:
                logger.exception("Failed to read pressure setpoint")
            try:
                p_meas = f"{self.dev.get_pressure(pressure_channel):.3f}"
            except Exception:
                logger.exception("Failed to read pressure measurement")
            ch = str(int(pressure_channel))

        try:
            valve_state = self.dev.get_valve_state()
        except Exception:
            valve_state = "UNKNOWN"

        removed_ml = max(0.0, self._step_start_volume - self.volume_ml)
        volume_delta = net_flow_ml_s * dt_s

        self._csv.writerow(
            {
                "ts": _ts_iso(),
                "mode": mode,
                "loop_idx": self._loop_idx,
                "dt_s": round(dt_s, 6),
                "flow_raw": flow_raw,
                "flow_ml_per_s": flow_ml_s,
                "net_flow_ml_per_s": net_flow_ml_s,
                "volume_ml_est": self.volume_ml,
                "volume_delta_ml": volume_delta,
                "pressure_setpoint_pct": p_set,
                "pressure_meas_pct": p_meas,
                "pressure_channel": ch,
                "pressure_setpoint_mbar": p_set_mbar,
                "valve_state": valve_state,
                "removed_ml_since_step_start": removed_ml,
                "event": event,
            }
        )
        self._csv_file.flush()

        logger.debug(
            "[%s] loop=%d dt=%.6f flow_raw=%.6f net=%.6f vol=%.6f removed=%.6f event=%s",
            mode,
            self._loop_idx,
            dt_s,
            flow_raw,
            net_flow_ml_s,
            self.volume_ml,
            removed_ml,
            event,
        )

    def _update_volume(self, dt_s: float, flow_raw: float, *, net_sign: float) -> float:
        flow_ml_s = self._flow_to_ml_per_s(flow_raw)
        net_ml_s = net_sign * abs(flow_ml_s)
        old_volume = self.volume_ml
        self.volume_ml += net_ml_s * dt_s
        logger.debug(
            "Volume integration: %.6f + (%.6f * %.6f) = %.6f",
            old_volume,
            net_ml_s,
            dt_s,
            self.volume_ml,
        )
        return net_ml_s

    def _mbar_to_percent(self, mbar: float) -> float:
        return max(
            0.0,
            min(100.0, float(mbar) / float(self.cfg.pressure_full_scale_mbar) * 100.0),
        )

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

    def ramp_pressure_linear_mbar(
        self, *, channel: int, target_mbar: float, duration_s: float
    ) -> None:
        mode = "RAMP"
        ch = int(channel)
        target_pct = self._mbar_to_percent(target_mbar)

        if self.dev.pressure_controller is None:
            raise RuntimeError("PressureController disabled")

        start_pct = self.dev.get_pressure_setpoint(ch)

        logger.info(
            "RAMP START channel=%d start_pct=%.3f target_pct=%.3f duration=%.3f",
            ch,
            start_pct,
            target_pct,
            duration_s,
        )

        if duration_s <= 0:
            self.dev.set_pressure(target_pct, ch, ramp=False)
            self._log_row(
                mode,
                0.0,
                float("nan"),
                float("nan"),
                pressure_channel=ch,
                event="RAMP_INSTANT",
            )
            return

        dt = max(0.05, float(self.cfg.ramp_update_dt_s))
        steps = max(1, int(duration_s / dt))

        for i in range(1, steps + 1):
            alpha = i / steps
            pct = start_pct + (target_pct - start_pct) * alpha
            logger.info(
                "RAMP STEP %d/%d channel=%d set_pct=%.3f",
                i,
                steps,
                ch,
                pct,
            )
            self.dev.set_pressure(pct, ch, ramp=False)
            dt_s, flow_raw = self._sample_flow()
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=+1.0)
            self._log_row(
                mode,
                dt_s,
                flow_raw,
                self._flow_to_ml_per_s(flow_raw),
                net_flow_ml_s=net_ml_s,
                pressure_channel=ch,
            )
            self._safety_check(mode)
            time.sleep(dt)

        self._log_row(
            mode,
            0.0,
            float("nan"),
            float("nan"),
            pressure_channel=ch,
            event="RAMP_END",
        )
        logger.info("RAMP END channel=%d", ch)

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
        logger.info("===== START %s =====", mode)
        self._step_start_volume = self.volume_ml

        logger.info("Switching valves for %s", mode)
        set_valves()

        self._log_row(
            mode,
            0.0,
            float("nan"),
            float("nan"),
            pressure_channel=pressure_channel,
            event=event_start,
        )

        t_end = time.monotonic() + float(duration_s)

        while time.monotonic() < t_end:
            dt_s, flow_raw = self._sample_flow()
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=net_sign)
            self._log_row(
                mode,
                dt_s,
                flow_raw,
                self._flow_to_ml_per_s(flow_raw),
                net_flow_ml_s=net_ml_s,
                pressure_channel=pressure_channel,
            )
            self._safety_check(mode)
            time.sleep(self.cfg.sample_period_s)

        self._log_row(
            mode,
            0.0,
            self._last_flow_raw if self._last_flow_raw is not None else float("nan"),
            0.0,
            pressure_channel=pressure_channel,
            event=event_end,
        )

        delta = self._step_start_volume - self.volume_ml
        logger.info("===== END %s | ΔV=%.6f mL =====", mode, delta)

    def step_backwash_manual_then_run(
        self,
        *,
        ok_fn: Optional[Callable[[], bool]],
        duration_s: float,
        pressure_mbar: Optional[float] = None,
    ) -> None:
        self.wait_for_ok("Perform BACKWASH and confirm", ok_fn=ok_fn)

        logger.info("Executing BACKWASH step")
        self.dev.valves_backwash()

        if pressure_mbar is not None and self.dev.pressure_controller is not None:
            pct = self._mbar_to_percent(pressure_mbar)
            logger.info(
                "Setting BACKWASH pressure channel=2 mbar=%.3f pct=%.3f",
                pressure_mbar,
                pct,
            )
            self.dev.set_pressure(pct, channel=2, ramp=True)

        self._run_timed_step(
            mode="BACKWASH",
            duration_s=duration_s,
            pressure_channel=2 if self.dev.pressure_controller is not None else None,
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
            "Executing FILLING step target_mbar=%.3f ramp=%.3f hold=%.3f",
            target_pressure_mbar,
            ramp_duration_s,
            hold_duration_s,
        )

        if ramp_duration_s <= 0:
            ramp_duration_s = max(
                5.0, min(30.0, abs(target_pressure_mbar) / 50.0 * 5.0)
            )

        target_pct = self._mbar_to_percent(target_pressure_mbar)

        logger.info("Switching valves to FILLING")
        self.dev.valves_filling_solution()

        if self.dev.pressure_controller is not None:
            self.ramp_pressure_linear_mbar(
                channel=1,
                target_mbar=target_pressure_mbar,
                duration_s=ramp_duration_s,
            )

        if hold_duration_s > 0 and self.dev.pressure_controller is not None:
            logger.info(
                "Holding pressure channel=1 pct=%.3f for %.3f s",
                target_pct,
                hold_duration_s,
            )
            self.dev.set_pressure(target_pct, channel=1, ramp=False)

        self._run_timed_step(
            mode="FILLING",
            duration_s=hold_duration_s,
            pressure_channel=1 if self.dev.pressure_controller is not None else None,
            net_sign=+1.0,
            set_valves=self.dev.valves_filling_solution,
            event_start="START_FILLING",
            event_end="END_FILLING",
        )

        return target_pct, ramp_duration_s

    def step_filtration_and_venting_track_loss(
        self,
        *,
        filtration_duration_s: float,
        venting_duration_s: float,
        filtration_pressure_mbar: Optional[float] = None,
    ) -> float:
        logger.info(
            "Executing FILTRATION+VENTING filtration=%.3f venting=%.3f",
            filtration_duration_s,
            venting_duration_s,
        )

        v0 = self.volume_ml

        self.dev.valves_filtration()

        if (
            filtration_pressure_mbar is not None
            and self.dev.pressure_controller is not None
        ):
            pct = self._mbar_to_percent(filtration_pressure_mbar)
            logger.info(
                "Setting FILTRATION pressure channel=1 mbar=%.3f pct=%.3f",
                filtration_pressure_mbar,
                pct,
            )
            self.dev.set_pressure(pct, channel=1, ramp=True)

        self._run_timed_step(
            mode="FILTRATION",
            duration_s=filtration_duration_s,
            pressure_channel=1 if self.dev.pressure_controller is not None else None,
            net_sign=-1.0,
            set_valves=self.dev.valves_filtration,
            event_start="START_FILTRATION",
            event_end="END_FILTRATION",
        )

        if self.dev.pressure_controller is not None:
            logger.info("Dropping pressure to 0 on both channels")
            self.dev.set_pressure(0.0, channel=1, ramp=True)
            self.dev.set_pressure(0.0, channel=2, ramp=True)

        self._run_timed_step(
            mode="VENTING",
            duration_s=venting_duration_s,
            pressure_channel=None,
            net_sign=-1.0,
            set_valves=self.dev.venting,
            event_start="START_VENTING",
            event_end="END_VENTING",
        )

        v1 = self.volume_ml
        loss_ml = max(0.0, v0 - v1)
        self.last_filtration_venting_loss_ml = loss_ml

        logger.info(
            "FILTRATION+VENTING loss=%.6f mL (from %.6f to %.6f)",
            loss_ml,
            v0,
            v1,
        )

        self._log_row(
            "LOSS",
            0.0,
            float("nan"),
            float("nan"),
            event=f"FILTRATION_VENTING_LOSS={loss_ml:.6f}",
        )

        return loss_ml

    def step_backwash_remove_volume(
        self,
        *,
        base_remove_ml: Optional[float] = None,
        add_previous_loss: bool = True,
        max_duration_s: float = 300.0,
        backwash_pressure_mbar: Optional[float] = None,
    ) -> float:
        base = (
            float(base_remove_ml)
            if base_remove_ml is not None
            else self.cfg.base_backwash_remove_ml
        )
        add = self.last_filtration_venting_loss_ml if add_previous_loss else 0.0
        target_remove_ml = max(0.0, base + add)

        logger.info(
            "Executing BACKWASH2 target_remove_ml=%.6f base=%.6f add=%.6f",
            target_remove_ml,
            base,
            add,
        )

        self.dev.valves_backwash()

        if (
            backwash_pressure_mbar is not None
            and self.dev.pressure_controller is not None
        ):
            pct = self._mbar_to_percent(backwash_pressure_mbar)
            logger.info(
                "Setting BACKWASH2 pressure channel=2 mbar=%.3f pct=%.3f",
                backwash_pressure_mbar,
                pct,
            )
            self.dev.set_pressure(pct, channel=2, ramp=True)

        v_start = self.volume_ml
        self._step_start_volume = self.volume_ml

        t_end = time.monotonic() + float(max_duration_s)

        while time.monotonic() < t_end:
            dt_s, flow_raw = self._sample_flow()
            net_ml_s = self._update_volume(dt_s, flow_raw, net_sign=-1.0)

            removed = max(0.0, v_start - self.volume_ml)

            self._log_row(
                "BACKWASH2",
                dt_s,
                flow_raw,
                self._flow_to_ml_per_s(flow_raw),
                net_flow_ml_s=net_ml_s,
                pressure_channel=2
                if self.dev.pressure_controller is not None
                else None,
                event="",
            )

            self._safety_check("BACKWASH2")

            if removed >= target_remove_ml:
                logger.info(
                    "BACKWASH2 target reached removed=%.6f mL",
                    removed,
                )
                break

            time.sleep(self.cfg.sample_period_s)

        removed = max(0.0, v_start - self.volume_ml)

        self._log_row(
            "BACKWASH2",
            0.0,
            self._last_flow_raw
            if self._last_flow_raw is not None
            else float("nan"),
            0.0,
            pressure_channel=2
            if self.dev.pressure_controller is not None
            else None,
            event=f"END_BACKWASH2 removed_ml={removed:.6f}",
        )

        logger.info("BACKWASH2 finished removed=%.6f mL", removed)

        return removed
