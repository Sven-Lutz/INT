# src/hardware/drivers/pressure_controller.py
from __future__ import annotations

import os
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional, Any, Dict

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
    # allow import on non-lab machines
    OB1_Initialization = OB1_Destructor = OB1_Set_Press = OB1_Get_Press = OB1_Calib = None
    Elveflow_Calibration_Load = Elveflow_Calibration_Save = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PressureControllerConfig:
    device: str = "ASRL10::INSTR"
    # KORREKTUR: Kanal 1 UND Kanal 2 sind jetzt aktiviert!
    regs: tuple[int, int, int, int] = (5, 5, 0, 0)
    calib_path: str = ""
    pressure_limit_mbar: float = 8000.0
    timeout_ms: int = 1000
    autoload_calib: bool = True

    @staticmethod
    def _candidate_calib_paths(project_path: str) -> list[str]:
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
    def _candidate_env_paths() -> list[str]:
        return [
            r"C:\Users\Public\Desktop\Calibration\OB1_Calib_latest.txt",
            r"C:\Users\Public\Desktop\Calibration\OB1_Calib.txt",
        ]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PressureControllerConfig":
        device = str(d.get("device", d.get("Device", d.get("device_name", "ASRL10::INSTR")))).strip() or "ASRL10::INSTR"

        regs = d.get("regs", d.get("Regs", d.get("regulator_types", d.get("Regulators", (5, 5, 0, 0)))))
        try:
            regs_t = tuple(int(x) for x in regs)  # type: ignore[arg-type]
            if len(regs_t) != 4:
                raise ValueError
        except Exception:
            # KORREKTUR AUCH HIER: (5, 5, 0, 0)
            regs_t = (5, 5, 0, 0)

        timeout_ms = int(d.get("timeout_ms", d.get("Timeout MS", d.get("timeout", 1000))))

        pressure_limit = float(
            d.get(
                "pressure_limit_mbar",
                d.get("pressure_limit", d.get("Pressure Limit (mbar)", d.get("limit_mbar", 8000.0))),
            )
        )

        calib_path = str(d.get("calib_path", d.get("Calib Path", d.get("calibration_path", "")))).strip()

        if calib_path and not os.path.isfile(calib_path):
            logger.warning("PressureControllerConfig: calib_path does not exist: %s", calib_path)
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
            regs=regs_t,  # type: ignore[arg-type]
            calib_path=calib_path,
            pressure_limit_mbar=pressure_limit,
            timeout_ms=timeout_ms,
            autoload_calib=autoload_calib)

class PressureController:
    """
    OB1 pressure controller wrapper.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        self.cfg = PressureControllerConfig.from_dict(config)

        if OB1_Initialization is None:
            raise RuntimeError("PressureController: Elveflow bindings not available (OB1_Initialization missing)")

        self._instr_id = c_int32(-1)
        self._calib = (c_double * 1000)()

        logger.info(
            "PressureController(OB1): configured device=%s regs=%s calib=%s limit=%s timeout=%sms",
            self.cfg.device,
            self.cfg.regs,
            self.cfg.calib_path,
            self.cfg.pressure_limit_mbar,
            self.cfg.timeout_ms,
        )

        err = OB1_Initialization(self.cfg.device, *self.cfg.regs, byref(self._instr_id))
        if err != 0 or self._instr_id.value < 0:
            raise RuntimeError(f"OB1_Initialization failed: err={err}, id={self._instr_id.value}")

        if self.cfg.autoload_calib:
            self._load_calibration_nonfatal()

    def close(self) -> None:
        if OB1_Destructor is None:
            return
        try:
            OB1_Destructor(self._instr_id.value)
        except Exception:
            logger.exception("PressureController(OB1): destructor crashed")

    # ---------- calibration ----------

    def _load_calibration_nonfatal(self) -> None:
        if Elveflow_Calibration_Load is None:
            logger.warning("PressureController(OB1): Elveflow_Calibration_Load not available; running without calib file")
            return

        path = (self.cfg.calib_path or "").strip()
        if not path or not os.path.isfile(path):
            logger.warning("PressureController(OB1): no usable calib file found; using default calib array")
            return

        try:
            err = Elveflow_Calibration_Load(path, byref(self._calib), 1000)
            if err != 0:
                logger.warning("PressureController(OB1): calibration load failed (err=%s) path=%s", err, path)
            else:
                logger.info("PressureController(OB1): calibration loaded (%s)", path)
        except Exception:
            logger.exception("PressureController(OB1): calibration load crashed (continuing)")

    def calibrate_and_save(self, path: Optional[str] = None) -> None:
        if OB1_Calib is None:
            raise RuntimeError("OB1_Calib not available in Elveflow bindings")

        OB1_Calib(self._instr_id.value, byref(self._calib), max(60000, int(self.cfg.timeout_ms)))

        save_path = (path or self.cfg.calib_path or "").strip()
        if not save_path:
            logger.info("PressureController(OB1): calibration done; no save_path provided")
            return

        if Elveflow_Calibration_Save is None:
            raise RuntimeError("Elveflow_Calibration_Save not available in Elveflow bindings")

        err = Elveflow_Calibration_Save(save_path, byref(self._calib), 1000)
        if err != 0:
            raise RuntimeError(f"Elveflow_Calibration_Save failed (err={err}) path={save_path}")
        logger.info("PressureController(OB1): calibration saved (%s)", save_path)

    # ---------- IO ----------

    def get_pressure_mbar(self, ch: int) -> float:
        if OB1_Get_Press is None:
            return 0.0

        out = c_double(0.0)
        err = OB1_Get_Press(self._instr_id.value, int(ch), 1, byref(self._calib), byref(out), 1000)
        if err != 0:
            logger.debug(f"OB1_Get_Press busy (err={err}) ch={ch}")
            return 0.0
        return float(out.value)

    def set_pressure_mbar(self, ch: int, value_mbar: float) -> None:
        if OB1_Set_Press is None:
            return

        v = float(value_mbar)
        if abs(v) > float(self.cfg.pressure_limit_mbar):
            logger.error(f"Pressure setpoint exceeds limit: {v} mbar > {self.cfg.pressure_limit_mbar} mbar")
            return

        err = OB1_Set_Press(self._instr_id.value, int(ch), v, byref(self._calib), 1000)
        if err != 0:
            logger.warning(f"OB1_Set_Press failed (err={err}) ch={ch} value={v}mbar")

    # convenience aliases used elsewhere in your codebase
    def read_pressure(self, channel: int) -> float:
        return self.get_pressure_mbar(int(channel))

    def read_setpoint(self, channel: int) -> float:
        return self.get_pressure_mbar(int(channel))

    def set_pressure(self, channel: int, value: float, ramp: bool = True) -> None:
        self.set_pressure_mbar(int(channel), float(value))