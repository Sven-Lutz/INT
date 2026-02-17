# src/backend/core/device_manager.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.hardware.drivers.flow_sensor import FlowSensor, FlowSensorConfig
from src.hardware.drivers.pressure_controller import PressureController
from src.hardware.drivers.valves import ValveController
from src.utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceManagerOptions:
    enable_pressure: bool = False
    enable_flow: bool = True
    safe_valves_on_disconnect: bool = True
    # Optional: fail fast if valves can't connect (recommended)
    require_valves: bool = True


class DeviceManager:
    def __init__(self, opts: DeviceManagerOptions = DeviceManagerOptions()):
        self.opts = opts
        self.cfg_mgr = ConfigManager()

        # Track if relay/valves are actually connected
        self._valves_connected: bool = False

        logger.info(
            "DeviceManager: initializing (pressure=%s, flow=%s)",
            opts.enable_pressure,
            opts.enable_flow,
        )

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

        # ---------------- Valves ----------------
        self.valve_controller = ValveController(valve_cfg)
        logger.info("DeviceManager: ValveController initialized")

        try:
            self.valve_controller.connect()
            self._valves_connected = True
            logger.info("DeviceManager: ValveController connected")
        except Exception:
            self._valves_connected = False
            logger.exception("DeviceManager: ValveController connect failed")
            if self.opts.require_valves:
                raise

        # ---------------- Pressure ----------------
        self.pressure_controller: Optional[PressureController] = None
        if opts.enable_pressure:
            assert pressure_cfg is not None
            self.pressure_controller = PressureController(pressure_cfg)
            self.pressure_controller.connect()
            logger.info("DeviceManager: PressureController initialized")
        else:
            logger.info("DeviceManager: PressureController disabled")

        # ---------------- Flow ----------------
        self.flow_sensor: Optional[FlowSensor] = None
        if opts.enable_flow:
            assert flow_cfg is not None
            fs_cfg = self._parse_flow_cfg(flow_cfg)
            self.flow_sensor = FlowSensor(fs_cfg)
            self.flow_sensor.connect()
            logger.info(
                "DeviceManager: FlowSensor connected (port=%s, address=%s, baudrate=%s, channel=%s, full_scale_raw=%s)",
                fs_cfg.port,
                getattr(fs_cfg, "address", None),
                getattr(fs_cfg, "baudrate", None),
                getattr(fs_cfg, "channel", None),
                fs_cfg.full_scale_raw,
            )
        else:
            logger.info("DeviceManager: FlowSensor disabled")

        logger.info("DeviceManager: initialization complete")

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

    def _parse_flow_cfg(self, cfg: Dict[str, Any]) -> FlowSensorConfig:
        src = cfg.get("flow") if isinstance(cfg.get("flow"), dict) else cfg
        return FlowSensorConfig(
            port=str(src.get("port", "COM5")).strip() or "COM5",
            address=int(src.get("address", 3)),
            baudrate=int(src.get("baudrate", 38400)),
            channel=int(src.get("channel", 1)),
            full_scale_raw=int(src.get("full_scale_raw", 32000)),
        )

    # ---------------- guards ----------------

    def _require_valves(self) -> None:
        if not self._valves_connected:
            raise RuntimeError("ValveController not connected/available (check COM port + require_valves).")

    # ---------------- pressure/flow API ----------------

    def set_pressure(self, percent: float, channel: int, ramp: bool = True) -> None:
        if self.pressure_controller is None:
            raise RuntimeError("PressureController is not enabled/initialized.")
        self.pressure_controller.set_pressure_percent(channel=int(channel), percent=float(percent), ramp=bool(ramp))

    def get_pressure(self, channel: int) -> float:
        if self.pressure_controller is None:
            raise RuntimeError("PressureController is not enabled/initialized.")
        return float(self.pressure_controller.read_pressure_percent(int(channel)))

    def get_pressure_setpoint(self, channel: int) -> float:
        if self.pressure_controller is None:
            raise RuntimeError("PressureController is not enabled/initialized.")
        return float(self.pressure_controller.read_setpoint_percent(int(channel)))

    def read_flow(self) -> float:
        if self.flow_sensor is None:
            raise RuntimeError("FlowSensor is not enabled/initialized.")
        return float(self.flow_sensor.read_flow_eng())

    # ---------------- valve actions ----------------

    def valves_filtration(self) -> None:
        self._require_valves()
        self.valve_controller.filtration()

    def valves_filling_solution(self) -> None:
        self._require_valves()
        self.valve_controller.filling_solution()

    def valves_venting(self) -> None:
        """Canonical valve method name (matches other valves_* methods)."""
        self._require_valves()
        self.valve_controller.venting()

    def venting(self) -> None:
        """Backward-compatible alias. Prefer valves_venting()."""
        self.valves_venting()

    def all_valves_shut(self) -> None:
        self._require_valves()
        self.valve_controller.all_shut()

    def all_valves_open(self) -> None:
        self._require_valves()
        self.valve_controller.all_open()

    def valves_backwash(self) -> None:
        self._require_valves()
        self.valve_controller.backwash()

    def get_valve_state(self) -> str:
        return str(self.valve_controller.get_state())


    # ---------------- shutdown ----------------

    def disconnect(self) -> None:
        logger.info("DeviceManager: disconnect requested")

        # Close flow first (no dependence on valves)
        if self.flow_sensor is not None:
            try:
                self.flow_sensor.close()
                logger.info("DeviceManager: FlowSensor closed")
            except Exception:
                logger.exception("DeviceManager: error while closing FlowSensor")
            finally:
                self.flow_sensor = None

        # Then pressure (may try to ramp/shutdown internally)
        if self.pressure_controller is not None:
            try:
                self.pressure_controller.close()
                logger.info("DeviceManager: PressureController closed")
            except Exception:
                logger.exception("DeviceManager: error while closing PressureController")
            finally:
                self.pressure_controller = None

        # Finally valves: do ONE deterministic safe-state transition + close relay
        if self._valves_connected:
            try:
                if self.opts.safe_valves_on_disconnect:
                    self.valve_controller.close()  # sets configured safe state + closes relay
                else:
                    # If you explicitly do NOT want safe-state, just close relay (best effort)
                    try:
                        self.valve_controller.relais.close()
                    except Exception:
                        logger.exception("DeviceManager: relay close failed")
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
