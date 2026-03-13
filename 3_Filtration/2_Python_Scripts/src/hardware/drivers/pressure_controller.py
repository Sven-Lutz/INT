# src/hardware/drivers/pressure_controller.py
from __future__ import annotations

import os
import logging
import time
from dataclasses import dataclass
from typing import Optional, Any, Dict, List, Tuple

from ctypes import c_int32, c_double, byref

try:
    from src.hardware.drivers.elveflow import (
        OB1_Initialization,
        OB1_Destructor,
        OB1_Set_Press,
        OB1_Get_Press,
        OB1_Calib,
        Elveflow_Calibration_Load,
        Elveflow_Calibration_Save,
    )
except Exception:
    # allow import on non-lab machines / simulation mode
    OB1_Initialization = OB1_Destructor = OB1_Set_Press = OB1_Get_Press = OB1_Calib = None
    Elveflow_Calibration_Load = Elveflow_Calibration_Save = None

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class PressureControllerConfig:
    device: str = "ASRL10::INSTR"
    regs: Tuple[int, int, int, int] = (5, 5, 0, 0)
    calib_path: str = ""
    pressure_limit_mbar: float = 8000.0
    timeout_ms: int = 1000
    autoload_calib: bool = True

    @staticmethod
    def _candidate_calib_paths(project_path: str) -> List[str]:
        project_path = (project_path or "").strip()
        if not project_path:
            return []
        cfg_dir = os.path.join(project_path, "4_Config")
        return [
            os.path.join(cfg_dir, "Calibration", "OB1_Calib_latest.txt"),
            os.path.join(cfg_dir, "OB1_Calib_latest.txt"),
            os.path.join(cfg_dir, "Calibration", "OB1_Calib.txt"),
            os.path.join(cfg_dir, "OB1_Calib.txt"),
        ]

    @staticmethod
    def _candidate_env_paths() -> List[str]:
        return [
            r"C:\Users\Public\Desktop\Calibration\OB1_Calib_latest.txt",
            r"C:\Users\Public\Desktop\Calibration\OB1_Calib.txt",
        ]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PressureControllerConfig":
        device = str(d.get("device", d.get("Device", d.get("device_name", "ASRL10::INSTR")))).strip() or "ASRL10::INSTR"

        regs = d.get("regs", d.get("Regs", d.get("regulator_types", d.get("Regulators", (5, 5, 0, 0)))))
        try:
            regs_t = tuple(int(x) for x in regs)
            if len(regs_t) != 4:
                raise ValueError
        except Exception:
            regs_t = (5, 5, 0, 0)

        timeout_ms = int(d.get("timeout_ms", d.get("Timeout MS", d.get("timeout", 1000))))

        pressure_limit = float(
            d.get("pressure_limit_mbar", 
                  d.get("pressure_limit", 
                        d.get("Pressure Limit (mbar)", 
                              d.get("limit_mbar", 8000.0))))
        )

        calib_path = str(d.get("calib_path", d.get("Calib Path", d.get("calibration_path", "")))).strip()

        if calib_path and not os.path.isfile(calib_path):
            logger.debug(f"PressureControllerConfig: calib_path does not exist: {calib_path}")
            calib_path = ""

        if not calib_path:
            project_path = str(d.get("project_path", d.get("Project Path", ""))).strip()
            for p in cls._candidate_calib_paths(project_path):
                if os.path.isfile(p):
                    calib_path = p
                    break

        if not calib_path:
            project_path = os.environ.get("PELLIKAN_PROJECT_PATH", "").strip()
            for p in cls._candidate_calib_paths(project_path):
                if os.path.isfile(p):
                    calib_path = p
                    break

        if not calib_path:
            for p in cls._candidate_env_paths():
                if os.path.isfile(p):
                    calib_path = p
                    break

        autoload_calib = bool(d.get("autoload_calib", d.get("Autoload Calib", True)))

        return cls(
            device=device,
            regs=regs_t,  # type: ignore
            calib_path=calib_path,
            pressure_limit_mbar=pressure_limit,
            timeout_ms=timeout_ms,
            autoload_calib=autoload_calib
        )

class PressureController:
    """
    Elite OB1 pressure controller wrapper.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.cfg = PressureControllerConfig.from_dict(config)
        self._instr_id = c_int32(-1)
        self._calib = (c_double * 1000)()
        self._connected = False

        self._last_p = {1: 0.0, 2: 0.0}

    def connect(self) -> None:
        """Stellt die Verbindung her. Wird vom DeviceManager aufgerufen."""
        if self._connected:
            return
            
        if OB1_Initialization is None:
            raise RuntimeError("PressureController: Elveflow bindings not available (OB1_Initialization missing)")

        logger.info(
            "PressureController(OB1): connecting device=%s regs=%s limit=%.0f mbar",
            self.cfg.device, self.cfg.regs, self.cfg.pressure_limit_mbar
        )

        err = OB1_Initialization(self.cfg.device.encode('ascii'), *self.cfg.regs, byref(self._instr_id))
        
        if err != 0 or self._instr_id.value < 0:
            raise RuntimeError(f"OB1_Initialization failed: err={err}, id={self._instr_id.value}")

        self._connected = True

        if self.cfg.autoload_calib:
            self._load_calibration_nonfatal()

    def close(self) -> None:
        if OB1_Destructor is None or not self._connected:
            return
        try:
            # Sicherheitshalber Druck vor dem Disconnect auf 0 setzen
            self.set_pressure_mbar(1, 0.0)
            self.set_pressure_mbar(2, 0.0)
            time.sleep(0.1)
            OB1_Destructor(self._instr_id.value)
        except Exception:
            logger.exception("PressureController(OB1): destructor crashed")
        finally:
            self._connected = False
            logger.info("PressureController(OB1): disconnected")

    # ---------- calibration ----------

    def _load_calibration_nonfatal(self) -> None:
        if Elveflow_Calibration_Load is None:
            logger.warning("PressureController(OB1): Elveflow_Calibration_Load not available")
            return

        path = (self.cfg.calib_path or "").strip()
        if not path or not os.path.isfile(path):
            logger.warning("PressureController(OB1): no usable calib file found; using default calib array")
            return

        try:
            err = Elveflow_Calibration_Load(path.encode('ascii'), byref(self._calib), 1000)
            if err != 0:
                logger.warning(f"PressureController(OB1): calibration load failed (err={err}) path={path}")
            else:
                logger.info(f"PressureController(OB1): calibration loaded ({path})")
        except Exception:
            logger.exception("PressureController(OB1): calibration load crashed (continuing)")

    def calibrate_and_save(self, path: Optional[str] = None) -> None:
        if OB1_Calib is None or Elveflow_Calibration_Save is None:
            raise RuntimeError("OB1 Calibration bindings not available")

        logger.info("PressureController(OB1): starting calibration...")
        OB1_Calib(self._instr_id.value, byref(self._calib), max(60000, int(self.cfg.timeout_ms)))

        save_path = (path or self.cfg.calib_path or "").strip()
        if not save_path:
            logger.info("PressureController(OB1): calibration done; no save_path provided")
            return

        err = Elveflow_Calibration_Save(save_path.encode('ascii'), byref(self._calib), 1000)
        if err != 0:
            raise RuntimeError(f"Elveflow_Calibration_Save failed (err={err}) path={save_path}")
        logger.info(f"PressureController(OB1): calibration saved ({save_path})")

    # ---------- IO ----------

    def get_pressure_mbar(self, ch: int) -> float:
        if OB1_Get_Press is None or not self._connected:
            return 0.0

        out = c_double(0.0)
        err = OB1_Get_Press(self._instr_id.value, int(ch), 1, byref(self._calib), byref(out), 1000)
        
        if err == 0:
            self._last_p[ch] = float(out.value)
            return float(out.value)
            
        return self._last_p.get(ch, 0.0)

    def set_pressure_mbar(self, ch: int, value_mbar: float) -> None:
        if OB1_Set_Press is None or not self._connected:
            return

        v = float(value_mbar)
        
        # Hard Limit Check
        if abs(v) > float(self.cfg.pressure_limit_mbar):
            logger.error(f"Pressure setpoint exceeds limit: {v} mbar > {self.cfg.pressure_limit_mbar} mbar")
            return

        # 🚀 C-Types Konvertierung für Elveflow
        err = OB1_Set_Press(self._instr_id.value, int(ch), c_double(v), byref(self._calib), 1000)
        
        if err != 0:
            # 🚀 ELITE TWEAK: Unterdrücke den harmlosen Error 8008, wenn wir 0.0 mbar anlegen (Venting)
            if err == 8008 and v == 0.0:
                pass 
            else:
                logger.warning(f"OB1_Set_Press failed (err={err}) ch={ch} value={v}mbar")

    # ---------- Legacy Aliases ----------
    def read_pressure(self, channel: int) -> float:
        return self.get_pressure_mbar(int(channel))

    def read_setpoint(self, channel: int) -> float:
        return self.get_pressure_mbar(int(channel))

    def set_pressure(self, channel: int, value: float, ramp: bool = True) -> None:
        self.set_pressure_mbar(int(channel), float(value))