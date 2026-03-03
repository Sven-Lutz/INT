# src/gui/health.py
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SystemHealth(str, Enum):
    ERROR = "ERROR"
    NO_COMM = "NO_COMM"
    SAFE_STATE = "SAFE_STATE"
    WARNING = "WARNING"
    RUNNING = "RUNNING"
    OK = "OK"


# Strict precedence (highest first)
_PRECEDENCE: tuple[SystemHealth, ...] = (
    SystemHealth.ERROR,
    SystemHealth.NO_COMM,
    SystemHealth.SAFE_STATE,
    SystemHealth.WARNING,
    SystemHealth.RUNNING,
    SystemHealth.OK,
)


@dataclass(frozen=True)
class HealthSnapshot:
    health: SystemHealth
    title: str

    detail: str = ""
    action: str = ""

    last_error_short: str = ""
    last_error_full: str = ""

    device_ok: bool = True
    worker_running: bool = False
    manual_hold: bool = False
    p1_mbar: Optional[float] = None
    p2_mbar: Optional[float] = None
    flow: Optional[float] = None
    valves: Optional[str] = None

    comm_ok: bool = True
    last_good_comm_age_s: Optional[float] = None


@dataclass
class HealthRules:
    # Warning threshold when idle (if pressure persists while no run/hold)
    idle_pressure_warn_mbar: float = 200.0

    # Absolute alarm threshold (ERROR)
    pressure_alarm_mbar: float = 8000.0

    # Flow warning (optional)
    flow_low_warn: Optional[float] = 0.05

    # comm staleness timeout (seconds since last_good_comm_ts)
    comm_timeout_s: float = 2.0


def _short_error(err: Optional[str]) -> str:
    if not err:
        return ""
    s = str(err).strip()
    if not s:
        return ""
    return s.splitlines()[0][:180]


def _one_line(text: str, *, limit: int = 220) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    s = " ".join([p.strip() for p in s.splitlines() if p.strip()])
    return s[:limit]


def _two_lines(text: str, *, limit: int = 260) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if not lines:
        return ""
    return "\n".join(lines[:2])[:limit]


def _finite_f(x: Optional[float]) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:
            return None
        if v == float("inf") or v == float("-inf"):
            return None
        return v
    except Exception:
        return None


class HealthEvaluator:
    """
    Deterministic health-state machine.

    Rules:
    - All decision logic lives here (frames only consume HealthSnapshot).
    - SAFE_STATE is latched once entered; exits only via:
        * reset_safe_state(), OR
        * new_run_started=True (recommended hook from MainWindow)
    - Precedence is strict and fixed: ERROR > NO_COMM > SAFE_STATE > WARNING > RUNNING > OK
    """

    def __init__(self, rules: Optional[HealthRules] = None) -> None:
        self.rules = rules or HealthRules()
        self._safe_state_latched: bool = False

    # -------------------------
    # SAFE_STATE lifecycle
    # -------------------------
    def reset_safe_state(self) -> None:
        self._safe_state_latched = False

    def latch_safe_state(self) -> None:
        self._safe_state_latched = True

    # -------------------------
    # Evaluation
    # -------------------------
    def evaluate(
        self,
        *,
        device_ok: bool,
        worker_running: bool,
        last_error_short: str = "",
        last_error_full: str = "",
        last_error: Optional[str] = None,
        safe_state_forced: bool,
        manual_hold: bool,
        p1_mbar: Optional[float],
        p2_mbar: Optional[float],
        flow: Optional[float],
        valves: Optional[str],
        last_good_comm_ts: Optional[float] = None,
        now_monotonic: Optional[float] = None,
        # New: allow MainWindow to explicitly clear SAFE_STATE on a new run start
        new_run_started: bool = False,
    ) -> HealthSnapshot:
        now = float(time.monotonic() if now_monotonic is None else now_monotonic)

        # Standardize last_error fields (short=1 line; full=traceback/log)
        if (not last_error_short) and (not last_error_full) and last_error:
            last_error_full = str(last_error)
            last_error_short = _short_error(last_error_full)

        last_error_short = _short_error(last_error_short)
        last_error_full = str(last_error_full or "")

        # SAFE_STATE enter/exit policy
        if bool(new_run_started):
            # explicit exit path (MainWindow should call this on Start Run)
            self._safe_state_latched = False

        if bool(safe_state_forced):
            # enter latch on STOP/ABORT/FATAL, etc.
            self._safe_state_latched = True

        dev_ok = bool(device_ok)
        run = bool(worker_running)
        hold = bool(manual_hold)

        p1 = _finite_f(p1_mbar)
        p2 = _finite_f(p2_mbar)
        q = _finite_f(flow)
        vstate = (str(valves).strip() if valves is not None else "") or None

        # Comm freshness (uses last_good_comm_ts if provided)
        comm_ok = dev_ok
        age_s: Optional[float] = None
        if last_good_comm_ts is not None:
            try:
                age_s = max(0.0, now - float(last_good_comm_ts))
                timeout = float(self.rules.comm_timeout_s)
                if not (timeout > 0):
                    timeout = 2.0
                if age_s > timeout:
                    comm_ok = False
            except Exception:
                age_s = None
                comm_ok = dev_ok

        # Absolute pressure alarm => ERROR
        thr_alarm = float(self.rules.pressure_alarm_mbar)
        alarm = False
        try:
            if p1 is not None and p1 >= thr_alarm:
                alarm = True
            if p2 is not None and p2 >= thr_alarm:
                alarm = True
        except Exception:
            alarm = False

        # -------------------------
        # STRICT precedence
        # -------------------------

        # 1) ERROR: explicit error string
        if last_error_short:
            det = _one_line(last_error_short, limit=220)
            return HealthSnapshot(
                health=SystemHealth.ERROR,
                title="ERROR",
                detail=det,
                action=_two_lines("Press STOP if unsafe.\nCheck logs. Fix root cause, then restart."),
                last_error_short=det,
                last_error_full=last_error_full or det,
                device_ok=dev_ok,
                worker_running=run,
                manual_hold=hold,
                p1_mbar=p1,
                p2_mbar=p2,
                flow=q,
                valves=vstate,
                comm_ok=bool(comm_ok),
                last_good_comm_age_s=age_s,
            )

        # 1b) ERROR: pressure alarm
        if alarm:
            return HealthSnapshot(
                health=SystemHealth.ERROR,
                title="PRESSURE ALARM",
                detail=f"Pressure high (≥ {thr_alarm:.0f} mbar)",
                action=_two_lines("Press STOP.\nVerify valves. Reduce upstream pressure."),
                device_ok=dev_ok,
                worker_running=run,
                manual_hold=hold,
                p1_mbar=p1,
                p2_mbar=p2,
                flow=q,
                valves=vstate,
                comm_ok=bool(comm_ok),
                last_good_comm_age_s=age_s,
            )

        # 2) NO_COMM
        if not comm_ok:
            det = "No recent telemetry / device comm"
            if age_s is not None:
                det = f"No comm for {age_s:.1f}s"
            return HealthSnapshot(
                health=SystemHealth.NO_COMM,
                title="NO COMM",
                detail=det,
                action=_two_lines(
                    "Press STOP if running.\nCheck USB/COM + power."
                    if run
                    else "Check USB/COM + power.\nPower-cycle controller if needed."
                ),
                device_ok=dev_ok,
                worker_running=run,
                manual_hold=hold,
                p1_mbar=p1,
                p2_mbar=p2,
                flow=q,
                valves=vstate,
                comm_ok=False,
                last_good_comm_age_s=age_s,
            )

        # 3) SAFE_STATE (latched)
        if self._safe_state_latched:
            return HealthSnapshot(
                health=SystemHealth.SAFE_STATE,
                title="SAFE STATE",
                detail="Safe vent / pressure=0 applied",
                action=_two_lines("Verify valves/lines are safe.\nStart a new run or reset SAFE_STATE."),
                device_ok=True,
                worker_running=run,
                manual_hold=hold,
                p1_mbar=p1,
                p2_mbar=p2,
                flow=q,
                valves=vstate,
                comm_ok=True,
                last_good_comm_age_s=age_s,
            )

        # 4) WARNING checks
        idle_hi = 200.0
        try:
            idle_hi = float(self.rules.idle_pressure_warn_mbar)
        except Exception:
            idle_hi = 200.0

        if (not run) and (not hold):
            try:
                if (p1 is not None and p1 > idle_hi) or (p2 is not None and p2 > idle_hi):
                    return HealthSnapshot(
                        health=SystemHealth.WARNING,
                        title="PRESSURE WHILE IDLE",
                        detail=f"Idle pressure > {idle_hi:.0f} mbar",
                        action=_two_lines("Vent to 0 mbar or check valve state.\nConfirm lines are open."),
                        device_ok=True,
                        worker_running=False,
                        manual_hold=False,
                        p1_mbar=p1,
                        p2_mbar=p2,
                        flow=q,
                        valves=vstate,
                        comm_ok=True,
                        last_good_comm_age_s=age_s,
                    )
            except Exception:
                pass

        if run and self.rules.flow_low_warn is not None and q is not None:
            try:
                f_thr = float(self.rules.flow_low_warn)
                if q < f_thr:
                    return HealthSnapshot(
                        health=SystemHealth.WARNING,
                        title="LOW FLOW",
                        detail=f"Flow below threshold (< {f_thr:g})",
                        action=_two_lines("Check feed, tubing, and sensor.\nVerify valve positions."),
                        device_ok=True,
                        worker_running=True,
                        manual_hold=hold,
                        p1_mbar=p1,
                        p2_mbar=p2,
                        flow=q,
                        valves=vstate,
                        comm_ok=True,
                        last_good_comm_age_s=age_s,
                    )
            except Exception:
                pass

        # 5) RUNNING
        if run:
            if hold:
                det = "Experiment active (HOLD active)"
                act = "Release HOLD to stop.\nUse STOP if unsafe."
            else:
                det = "Experiment active"
                act = "Monitor pressures/flow.\nUse STOP if unsafe."
            return HealthSnapshot(
                health=SystemHealth.RUNNING,
                title="RUNNING",
                detail=det,
                action=_two_lines(act),
                device_ok=True,
                worker_running=True,
                manual_hold=hold,
                p1_mbar=p1,
                p2_mbar=p2,
                flow=q,
                valves=vstate,
                comm_ok=True,
                last_good_comm_age_s=age_s,
            )

        # 6) OK (idle)
        if hold and (not run):
            # This case typically shouldn't happen if you gate HOLD to BACKWASH_HOLD during runs,
            # but we keep it explicit and safe.
            return HealthSnapshot(
                health=SystemHealth.OK,
                title="OK",
                detail="Idle (manual hold active)",
                action=_two_lines("Release HOLD to stop.\nUse STOP if unsafe."),
                device_ok=True,
                worker_running=False,
                manual_hold=True,
                p1_mbar=p1,
                p2_mbar=p2,
                flow=q,
                valves=vstate,
                comm_ok=True,
                last_good_comm_age_s=age_s,
            )

        return HealthSnapshot(
            health=SystemHealth.OK,
            title="OK",
            detail="System idle and stable",
            action="",
            device_ok=True,
            worker_running=False,
            manual_hold=False,
            p1_mbar=p1,
            p2_mbar=p2,
            flow=q,
            valves=vstate,
            comm_ok=True,
            last_good_comm_age_s=age_s,
        )