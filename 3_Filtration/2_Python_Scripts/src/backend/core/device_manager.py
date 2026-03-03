# src/backend/core/device_manager.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from src.hardware.drivers.flow_sensor import FlowSensor, FlowSensorConfig
from src.hardware.drivers.pressure_controller import PressureController
from src.hardware.drivers.valves import ValveController
from src.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceManagerOptions:
    enable_pressure: bool = True
    enable_flow: bool = True

    safe_valves_on_disconnect: bool = True

    # Fail-fast toggles
    require_valves: bool = True
    require_pressure: bool = True
    require_flow: bool = True


class DeviceManager:
    """
    Thin, synchronous control layer for UI + backend.

    Patched/optimized:
    - Canonical mbar API for UI/worker:
        * set_pressure_setpoint_mbar(channel, setpoint_mbar, ramp)
        * get_pressure_mbar(channel)
        * get_pressure_setpoint_mbar(channel)
      (Legacy percent API preserved via set_pressure()/set_pressure_setpoint().)

    - Robust driver lifecycle:
      connect/open/start/initialize/init autodetect and close/disconnect/stop/shutdown autodetect.

    - Deterministic safe shutdown ordering:
      flow -> pressure (drop setpoints) -> valves (safe + close).

    - Optional comm status:
      comm_ok property derived from driver availability.
    """

    # Canonical valve states used by UI
    STATE_FILTRATION = "FILTRATION"
    STATE_FILLING = "FILLING"
    STATE_VENTING = "VENTING"
    STATE_BACKWASH = "BACKWASH"
    STATE_SHUT = "SHUT"
    STATE_OPEN = "OPEN"

    def __init__(self, opts: DeviceManagerOptions = DeviceManagerOptions()):
        self.opts = opts
        self.cfg_mgr = ConfigManager()

        self._valves_connected: bool = False

        logger.info(
            "DeviceManager: initializing (pressure=%s, flow=%s)",
            opts.enable_pressure,
            opts.enable_flow,
        )

        # ---- load configs (fail fast if required) ----
        valve_cfg = self._load_required_cfg("valves")

        pressure_cfg: Optional[Dict[str, Any]] = None
        if opts.enable_pressure:
            pressure_cfg = self._load_required_cfg("pressure_controller")
        else:
            self._load_optional_cfg("pressure_controller")

        flow_cfg: Optional[Dict[str, Any]] = None
        if opts.enable_flow:
            flow_cfg = self._load_required_cfg("flow_sensor")
        else:
            self._load_optional_cfg("flow_sensor")

        # ---- Valves ----
        self.valve_controller = ValveController(valve_cfg)
        logger.info("DeviceManager: ValveController initialized")

        try:
            self._try_connect_valves()
            logger.info("DeviceManager: ValveController connected")
        except Exception:
            self._valves_connected = False
            logger.exception("DeviceManager: ValveController connect failed")
            if self.opts.require_valves:
                raise

        # ---- Pressure ----
        self.pressure_controller: Optional[PressureController] = None
        self._pressure_full_scale_mbar: float = (
            self._infer_pressure_full_scale_mbar(pressure_cfg) if pressure_cfg else 8000.0
        )

        if opts.enable_pressure:
            assert pressure_cfg is not None
            try:
                self.pressure_controller = PressureController(pressure_cfg)
                self._try_connect_pressure(self.pressure_controller)
                logger.info(
                    "DeviceManager: PressureController connected (full_scale_mbar=%.1f)",
                    float(self._pressure_full_scale_mbar),
                )
            except Exception:
                logger.exception("DeviceManager: PressureController init/connect failed")
                if self.opts.require_pressure:
                    raise
                self.pressure_controller = None
        else:
            logger.info("DeviceManager: PressureController disabled")

        # ---- Flow ----
        self.flow_sensor: Optional[FlowSensor] = None
        if opts.enable_flow:
            assert flow_cfg is not None
            try:
                fs_cfg = self._parse_flow_cfg(flow_cfg)
                self.flow_sensor = FlowSensor(fs_cfg)
                self._try_connect_flow(self.flow_sensor)
                logger.info(
                    "DeviceManager: FlowSensor connected (port=%s, address=%s, baudrate=%s, channel=%s, full_scale_raw=%s)",
                    fs_cfg.port,
                    getattr(fs_cfg, "address", None),
                    getattr(fs_cfg, "baudrate", None),
                    getattr(fs_cfg, "channel", None),
                    fs_cfg.full_scale_raw,
                )
            except Exception:
                logger.exception("DeviceManager: FlowSensor init/connect failed")
                if self.opts.require_flow:
                    raise
                self.flow_sensor = None
        else:
            logger.info("DeviceManager: FlowSensor disabled")

        logger.info("DeviceManager: initialization complete")

    # ---------------- status ----------------

    @property
    def comm_ok(self) -> bool:
        """
        Coarse comm status for HMI health.
        True means "drivers initialized and (for valves) connected flag is set".
        Fine-grained per-device comm checks belong in the specific driver.
        """
        if self.opts.require_valves and not self._valves_connected:
            return False
        if self.opts.enable_pressure and self.opts.require_pressure and self.pressure_controller is None:
            return False
        if self.opts.enable_flow and self.opts.require_flow and self.flow_sensor is None:
            return False
        return True

    # ---------------- config helpers ----------------

    def _load_required_cfg(self, name: str) -> Dict[str, Any]:
        logger.debug("DeviceManager: loading required config '%s'", name)
        cfg = self.cfg_mgr.load_config(name)
        if not isinstance(cfg, dict):
            raise ValueError(f"Config '{name}' must be a mapping.")
        logger.debug("DeviceManager: loaded '%s' (keys=%s)", name, list(cfg.keys()))
        return cfg

    def _load_optional_cfg(self, name: str) -> Optional[Dict[str, Any]]:
        logger.debug("DeviceManager: loading optional config '%s'", name)
        try:
            cfg = self.cfg_mgr.load_config(name)
            if not isinstance(cfg, dict):
                logger.info("DeviceManager: optional config '%s' ignored (not a mapping)", name)
                return None
            logger.debug("DeviceManager: loaded optional '%s' (keys=%s)", name, list(cfg.keys()))
            return cfg
        except Exception as e:
            logger.info("DeviceManager: optional config '%s' not loaded (%s)", name, e)
            return None

    @staticmethod
    def _infer_pressure_full_scale_mbar(cfg: Optional[Dict[str, Any]]) -> float:
        """
        Try to infer pressure full-scale (mbar) from the pressure controller config.
        Accepts both nested and flat shapes. Falls back to 8000 mbar.
        """
        if not cfg or not isinstance(cfg, dict):
            return 8000.0
        src = cfg.get("pressure_controller") if isinstance(cfg.get("pressure_controller"), dict) else cfg
        for k in ("pressure_full_scale_mbar", "full_scale_mbar", "full_scale", "fs_mbar"):
            try:
                if k in src and src[k] is not None:
                    v = float(src[k])
                    if v > 0:
                        return v
            except Exception:
                continue
        return 8000.0

    def _parse_flow_cfg(self, cfg: Dict[str, Any]) -> FlowSensorConfig:
        """
        Accept both:
          - {"flow": {...}}
          - {...} (flat)
        """
        src = cfg.get("flow") if isinstance(cfg.get("flow"), dict) else cfg
        return FlowSensorConfig(
            port=str(src.get("port", "COM5")).strip() or "COM5",
            address=int(src.get("address", 3)),
            baudrate=int(src.get("baudrate", 38400)),
            channel=int(src.get("channel", 1)),
            full_scale_raw=int(src.get("full_scale_raw", 32000)),
        )

    # ---------------- connect helpers (driver variance) ----------------

    @staticmethod
    def _first_callable(obj: Any, names: tuple[str, ...]) -> Optional[Callable[[], Any]]:
        for n in names:
            fn = getattr(obj, n, None)
            if callable(fn):
                return fn
        return None

    def _try_connect_valves(self) -> None:
        vc = self.valve_controller
        fn = self._first_callable(vc, ("connect", "open", "start", "initialize", "init"))
        if fn is not None:
            logger.info("DeviceManager: ValveController connecting via %s()", fn.__name__)
            fn()
        self._valves_connected = True

    def _try_connect_pressure(self, pc: PressureController) -> None:
        fn = self._first_callable(pc, ("connect", "open", "start", "initialize", "init"))
        if fn is None:
            logger.info("DeviceManager: PressureController has no connect/open/start; assuming initialized in __init__")
            return
        logger.info("DeviceManager: PressureController connecting via %s()", fn.__name__)
        fn()

    def _try_connect_flow(self, fs: FlowSensor) -> None:
        fn = self._first_callable(fs, ("connect", "open", "start", "initialize", "init"))
        if fn is None:
            return
        fn()

    # ---------------- guards ----------------

    def _require_valves(self) -> None:
        if not self._valves_connected:
            raise RuntimeError("ValveController not connected/available (check COM port + require_valves).")

    def _require_pressure(self) -> PressureController:
        if self.pressure_controller is None:
            raise RuntimeError("PressureController is not enabled/initialized.")
        return self.pressure_controller

    def _require_flow(self) -> FlowSensor:
        if self.flow_sensor is None:
            raise RuntimeError("FlowSensor is not enabled/initialized.")
        return self.flow_sensor

        # ---------------- canonical pressure API (mbar) ----------------

    def set_pressure_setpoint_mbar(self, *, channel: int, setpoint_mbar: float, ramp: bool = True) -> None:
            """
            Canonical pressure setter (mbar).
            Sendet den Wert direkt ans Gerät, ohne ihn in Prozent umzurechnen!
            """
            self.set_pressure_setpoint(channel=int(channel), value=float(setpoint_mbar), ramp=bool(ramp))

    def get_pressure_mbar(self, channel: int) -> float:
            """
            Canonical pressure reader (mbar).
            Liest den mbar-Wert direkt vom Gerät.
            """
            return float(self.get_pressure(int(channel)))

    def get_pressure_setpoint_mbar(self, channel: int) -> float:
        return float(self.get_pressure_setpoint(int(channel)))

    def _mbar_to_percent(self, mbar: float) -> float:
        fs = float(self._pressure_full_scale_mbar if self._pressure_full_scale_mbar > 0 else 8000.0)
        v = max(0.0, float(mbar))
        return (v / fs) * 100.0

    def _percent_to_mbar(self, pct: float) -> float:
        fs = float(self._pressure_full_scale_mbar if self._pressure_full_scale_mbar > 0 else 8000.0)
        return (float(pct) / 100.0) * fs

    # ---------------- legacy pressure API (percent facade) ----------------

    def set_pressure_setpoint(self, *, channel: int, value: float, ramp: bool = True) -> None:
        """
        Legacy canonical setter (percent).

        Expected driver APIs:
          - set_pressure(channel=..., value=..., ramp=...)
          - set_pressure(value, channel, ramp)
          - set_pressure(value, channel)   (no ramp)
        """
        pc = self._require_pressure()

        # Preferred: keyword form used elsewhere
        try:
            pc.set_pressure(channel=int(channel), value=float(value), ramp=bool(ramp))  # type: ignore[arg-type]
            return
        except TypeError:
            pass
        except Exception:
            raise

        # Fallback: positional with ramp
        try:
            pc.set_pressure(float(value), int(channel), bool(ramp))  # type: ignore[misc]
            return
        except TypeError:
            pass

        # Fallback: positional without ramp
        try:
            pc.set_pressure(float(value), int(channel))  # type: ignore[misc]
            return
        except Exception as e:
            raise RuntimeError(f"PressureController.set_pressure signature unsupported: {e}") from e

    def get_pressure(self, channel: int) -> float:
        pc = self._require_pressure()
        for name in ("read_pressure", "get_pressure", "pressure"):
            fn = getattr(pc, name, None)
            if callable(fn):
                return float(fn(int(channel)))
        raise RuntimeError("PressureController has no read_pressure/get_pressure method")

    def get_pressure_setpoint(self, channel: int) -> float:
        pc = self._require_pressure()
        for name in ("read_setpoint", "get_setpoint", "setpoint"):
            fn = getattr(pc, name, None)
            if callable(fn):
                return float(fn(int(channel)))
        raise RuntimeError("PressureController has no read_setpoint/get_setpoint method")

    # Backwards-compat names used elsewhere (keep stable)
    def set_pressure(self, percent: float, channel: int, ramp: bool = True) -> None:
        self.set_pressure_setpoint(channel=int(channel), value=float(percent), ramp=bool(ramp))

    # ---------------- canonical flow API ----------------

    def read_flow(self) -> float:
        fs = self._require_flow()
        fn = getattr(fs, "read_flow_eng", None)
        if callable(fn):
            return float(fn())
        fn2 = getattr(fs, "read_flow", None)
        if callable(fn2):
            return float(fn2())
        raise RuntimeError("FlowSensor has no read_flow_eng/read_flow method")

    # ---------------- canonical valve API ----------------

    def set_valve_state(self, state: str) -> None:
        """Canonical: switch valves to a named state."""
        self._require_valves()
        st = (state or "").strip().upper()

        if st in (self.STATE_FILTRATION, "FILTER"):
            self.valve_controller.filtration()
            return

        if st in (self.STATE_FILLING, "FILL", "FILLING_SOLUTION"):
            self.valve_controller.filling_solution()
            return

        if st in (self.STATE_VENTING, "VENT"):
            self.valve_controller.venting()
            return

        if st in (self.STATE_BACKWASH,):
            fn = getattr(self.valve_controller, "backwash", None)
            if callable(fn):
                fn()
                return
            # Safety: do NOT silently map to another process. Venting is safer.
            self.valve_controller.venting()
            raise RuntimeError("ValveController has no backwash(); fell back to venting (safer).")

        if st in (self.STATE_SHUT, "ALL_SHUT", "CLOSE"):
            fn = getattr(self.valve_controller, "all_shut", None)
            if callable(fn):
                fn()
                return
            self.valve_controller.venting()
            return

        if st in (self.STATE_OPEN, "ALL_OPEN"):
            fn = getattr(self.valve_controller, "all_open", None)
            if callable(fn):
                fn()
                return
            raise RuntimeError("ValveController has no all_open()")

        raise ValueError(f"Unknown valve state '{state}'")

    def get_valve_state(self) -> str:
        fn = getattr(self.valve_controller, "get_state", None)
        if callable(fn):
            try:
                return str(fn())
            except Exception:
                return "UNKNOWN"
        return "UNKNOWN"

    # ---------------- legacy valve actions (preserved) ----------------

    def valves_filtration(self) -> None:
        self.set_valve_state(self.STATE_FILTRATION)

    def valves_filling_solution(self) -> None:
        self.set_valve_state(self.STATE_FILLING)

    def valves_venting(self) -> None:
        self.set_valve_state(self.STATE_VENTING)

    def venting(self) -> None:
        """Backward-compatible alias. Prefer valves_venting()/set_valve_state()."""
        self.valves_venting()

    def all_valves_shut(self) -> None:
        self.set_valve_state(self.STATE_SHUT)

    def all_valves_open(self) -> None:
        self.set_valve_state(self.STATE_OPEN)

    def valves_backwash(self) -> None:
        self.set_valve_state(self.STATE_BACKWASH)

    # ---------------- SAFE STATE helpers ----------------

    def vent_all(self) -> None:
        """
        Best-effort safety action: venting valve state and dropping pressure setpoints.
        This is intentionally tolerant: it should never raise in STOP paths.
        """
        try:
            self.valves_venting()
        except Exception:
            logger.exception("DeviceManager: vent_all -> valves_venting failed")

        if self.pressure_controller is not None:
            for ch in (1, 2):
                try:
                    self.set_pressure(0.0, ch, ramp=True)
                except Exception:
                    pass

    # ---------------- shutdown ----------------

    def disconnect(self) -> None:
        logger.info("DeviceManager: disconnect requested")

        # Flow first
        if self.flow_sensor is not None:
            try:
                fn = self._first_callable(self.flow_sensor, ("close", "disconnect", "stop", "shutdown"))
                if fn is not None:
                    fn()
                logger.info("DeviceManager: FlowSensor closed")
            except Exception:
                logger.exception("DeviceManager: error while closing FlowSensor")
            finally:
                self.flow_sensor = None

        # Pressure next
        if self.pressure_controller is not None:
            try:
                pc = self.pressure_controller
                for ch in (1, 2):
                    try:
                        self.set_pressure(0.0, ch, ramp=True)
                    except Exception:
                        pass

                fn = self._first_callable(pc, ("close", "disconnect", "stop", "shutdown"))
                if fn is not None:
                    fn()
                logger.info("DeviceManager: PressureController closed")
            except Exception:
                logger.exception("DeviceManager: error while closing PressureController")
            finally:
                self.pressure_controller = None

        # Valves last: safe state + close if implemented
        if self._valves_connected:
            try:
                if self.opts.safe_valves_on_disconnect:
                    fn = self._first_callable(self.valve_controller, ("close", "disconnect", "stop", "shutdown"))
                    if fn is not None:
                        fn()
                    else:
                        try:
                            self.valve_controller.venting()
                        except Exception:
                            logger.exception("DeviceManager: venting safe-state failed")

                        rel = getattr(self.valve_controller, "relais", None)
                        if rel is not None:
                            rfn = self._first_callable(rel, ("close", "disconnect"))
                            if rfn is not None:
                                rfn()
                else:
                    rel = getattr(self.valve_controller, "relais", None)
                    if rel is not None:
                        rfn = self._first_callable(rel, ("close", "disconnect"))
                        if rfn is not None:
                            rfn()
            except Exception:
                logger.exception("DeviceManager: error while closing ValveController")
            finally:
                self._valves_connected = False
        else:
            logger.warning("DeviceManager: valves were not connected; skipping ValveController shutdown")

        logger.info("DeviceManager: disconnect complete")

    def __enter__(self) -> "DeviceManager":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()