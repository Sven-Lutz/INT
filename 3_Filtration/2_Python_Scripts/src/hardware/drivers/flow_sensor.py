# src/hardware/drivers/flow_sensor.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import propar

logger = logging.getLogger(__name__)

ProcPar = Tuple[int, int]


@dataclass(frozen=True)
class FlowSensorConfig:
    port: str = "COM5"
    address: int = 3
    baudrate: int = 38400
    channel: int = 1

    # Default: treat ProPar flow values as engineering units (floats).
    scale_mode: str = "engineering"  # "engineering" | "raw_percent"
    full_scale_raw: int = 32000

    # Parameter mapping (process, parameter) -- MUST MATCH YOUR FLOW DEVICE
    meas: ProcPar = (33, 205)
    setp: ProcPar = (33, 206)

    io_timeout_s: float = 1.5
    max_write_retries: int = 2
    readback_tolerance: float = 0.05
    ramp_max_step: Optional[float] = 0.2
    ramp_sleep_s: float = 0.15

    # Hardening: do not crash on read errors; return last_good or 0.0
    fail_soft: bool = True

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        meas = d.get("meas", d.get("meas_raw", [33, 205]))
        setp = d.get("setp", d.get("set_raw", [33, 206]))
        ramp = d.get("ramp_max_step", d.get("ramp_max_step_percent", 0.2))
        ramp_v: Optional[float] = None if ramp is None else float(ramp)

        return FlowSensorConfig(
            port=str(d.get("port", "COM5")),
            address=int(d.get("address", 3)),
            baudrate=int(d.get("baudrate", 38400)),
            channel=int(d.get("channel", 1)),
            scale_mode=str(d.get("scale_mode", "engineering")),
            full_scale_raw=int(d.get("full_scale_raw", 32000)),
            meas=(int(meas[0]), int(meas[1])),
            setp=(int(setp[0]), int(setp[1])),
            io_timeout_s=float(d.get("io_timeout_s", 1.5)),
            max_write_retries=int(d.get("max_write_retries", 2)),
            readback_tolerance=float(d.get("readback_tolerance", d.get("readback_tolerance_percent", 0.05))),
            ramp_max_step=ramp_v,
            ramp_sleep_s=float(d.get("ramp_sleep_s", 0.15)),
            fail_soft=bool(d.get("fail_soft", True)),
        )


class FlowSensor:
    def __init__(self, cfg: FlowSensorConfig = FlowSensorConfig()):
        self.cfg = cfg
        self.inst: Optional[object] = None

        self._last_good_flow: Optional[float] = None
        self._last_good_setpoint: Optional[float] = None

        if not str(self.cfg.port).strip():
            raise ValueError("FlowSensorConfig.port must be set.")
        if int(self.cfg.full_scale_raw) <= 0:
            raise ValueError("FlowSensorConfig.full_scale_raw must be > 0.")
        if self.cfg.io_timeout_s <= 0:
            raise ValueError("FlowSensorConfig.io_timeout_s must be > 0.")
        if self.cfg.max_write_retries < 0:
            raise ValueError("FlowSensorConfig.max_write_retries must be >= 0.")
        if self.cfg.readback_tolerance < 0:
            raise ValueError("FlowSensorConfig.readback_tolerance must be >= 0.")

    # ---------- connection ----------
    def connect(self) -> None:
        if self.inst is not None:
            logger.debug("FlowSensor: connect() called but already connected")
            return

        logger.info(
            "FlowSensor: connecting (port=%s, address=%s, baudrate=%s, channel=%s)",
            self.cfg.port,
            self.cfg.address,
            self.cfg.baudrate,
            self.cfg.channel,
        )

        try:
            self.inst = propar.instrument(
                comport=self.cfg.port,
                address=self.cfg.address,
                baudrate=self.cfg.baudrate,
                channel=self.cfg.channel,
            )
        except Exception:
            logger.exception("FlowSensor: ProPar instrument initialization failed")
            raise

        logger.info("FlowSensor: connected")

        # non-fatal initial read
        try:
            m = self.read_flow()
            s = self.read_setpoint()
            logger.info("FlowSensor: initial flow=%r setpoint=%r", m, s)
        except Exception:
            logger.exception("FlowSensor: initial read failed (non-fatal)")

    def _require_connected(self) -> None:
        if self.inst is None:
            raise RuntimeError("FlowSensor not connected. Call connect() first.")

    # ---------- propar primitives ----------
    @staticmethod
    def _pp_type(vartype: str) -> int:
        vt = (vartype or "").strip().lower()
        if vt == "f":
            return int(getattr(propar, "PP_TYPE_FLOAT", 8))
        if vt == "l":
            return int(getattr(propar, "PP_TYPE_INT32", 4))
        if vt == "i":
            return int(getattr(propar, "PP_TYPE_INT16", 2))
        if vt == "c":
            return int(getattr(propar, "PP_TYPE_STRING", 9))
        return int(getattr(propar, "PP_TYPE_INT32", 4))

    def _read_pp(self, proc: int, parm: int, *, vartype: str = "f", varlength: int = 0) -> float:
        """
        Robust reader across propar variants:
        1) inst.readParameter(proc, parm)
        2) inst.read_parameters([dict]) with multiple schema variants
        """
        self._require_connected()
        inst = self.inst
        assert inst is not None

        fn = getattr(inst, "readParameter", None)
        if callable(fn):
            try:
                v = fn(int(proc), int(parm))
                if v is None:
                    raise RuntimeError(f"FlowSensor: readParameter returned None (proc={proc}, parm={parm})")
                return float(v)
            except Exception as e:
                logger.debug("FlowSensor: readParameter failed (%s)", e)

        read_params = getattr(inst, "read_parameters", None)
        if not callable(read_params):
            raise RuntimeError("FlowSensor: propar instrument has no usable read API")

        req_variants = [
            {"node": int(self.cfg.address), "proc_nr": int(proc), "parm_nr": int(parm), "parm_type": self._pp_type(vartype), "varlength": int(varlength)},
            {"node": int(self.cfg.address), "process": int(proc), "parameter": int(parm), "parm_type": self._pp_type(vartype), "varlength": int(varlength)},
            {"proc_nr": int(proc), "parm_nr": int(parm)},
            {"process": int(proc), "parameter": int(parm)},
        ]

        t0 = time.time()
        last_exc: Optional[Exception] = None

        while (time.time() - t0) < self.cfg.io_timeout_s:
            for req in req_variants:
                try:
                    res = read_params([req])
                    if not (isinstance(res, list) and res and isinstance(res[0], dict)):
                        raise RuntimeError(f"FlowSensor: unexpected read_parameters response: {res!r}")

                    r0 = res[0]
                    status = r0.get("status", None)
                    data = r0.get("data", None)

                    if status not in (None, 0):
                        raise RuntimeError(f"FlowSensor: propar status={status} for proc={proc} parm={parm} data={data!r}")
                    if data is None:
                        raise RuntimeError(f"FlowSensor: propar returned data=None for proc={proc} parm={parm}")

                    return float(data)

                except Exception as e:
                    last_exc = e

            time.sleep(0.05)

        if last_exc:
            raise last_exc
        raise TimeoutError(f"FlowSensor: read timeout proc={proc} parm={parm}")

    def _write_pp(self, proc: int, parm: int, value: float, *, vartype: str = "f", varlength: int = 0) -> None:
        """
        Robust writer across propar variants:
        1) inst.writeParameter(proc, parm, value)
        2) inst.write_parameters([dict]) with schema variants
        """
        self._require_connected()
        inst = self.inst
        assert inst is not None

        fn = getattr(inst, "writeParameter", None)
        if callable(fn):
            try:
                fn(int(proc), int(parm), float(value))
                return
            except Exception as e:
                logger.debug("FlowSensor: writeParameter failed (%s)", e)

        write_params = getattr(inst, "write_parameters", None)
        if not callable(write_params):
            raise RuntimeError("FlowSensor: propar instrument has no usable write API")

        req_variants = [
            {"node": int(self.cfg.address), "proc_nr": int(proc), "parm_nr": int(parm), "parm_type": self._pp_type(vartype), "varlength": int(varlength), "data": float(value)},
            {"node": int(self.cfg.address), "process": int(proc), "parameter": int(parm), "parm_type": self._pp_type(vartype), "varlength": int(varlength), "data": float(value)},
            {"proc_nr": int(proc), "parm_nr": int(parm), "data": float(value)},
            {"process": int(proc), "parameter": int(parm), "data": float(value)},
        ]

        t0 = time.time()
        last_exc: Optional[Exception] = None

        while (time.time() - t0) < self.cfg.io_timeout_s:
            for req in req_variants:
                try:
                    res = write_params([req])
                    if isinstance(res, list) and res and isinstance(res[0], dict):
                        status = res[0].get("status", None)
                        if status not in (None, 0):
                            raise RuntimeError(f"FlowSensor: write status={status} for proc={proc} parm={parm}")
                    return
                except Exception as e:
                    last_exc = e
            time.sleep(0.05)

        if last_exc:
            raise last_exc
        raise TimeoutError(f"FlowSensor: write timeout proc={proc} parm={parm}")

    # ---------- scaling ----------
    def _raw_to_percent(self, raw: float) -> float:
        return float(raw) / float(self.cfg.full_scale_raw) * 100.0

    def _percent_to_raw(self, percent: float) -> float:
        return float(percent) / 100.0 * float(self.cfg.full_scale_raw)

    # ---------- public API ----------
    def read_flow(self) -> float:
        proc, parm = self.cfg.meas
        try:
            v = self._read_pp(proc, parm, vartype="f", varlength=0)
            out = self._raw_to_percent(v) if self.cfg.scale_mode == "raw_percent" else v
            self._last_good_flow = float(out)
            return float(out)
        except Exception as e:
            if self.cfg.fail_soft:
                logger.warning("FlowSensor: read_flow failed (%s) -> using last_good/0.0", e)
                return float(self._last_good_flow if self._last_good_flow is not None else 0.0)
            raise

    def read_setpoint(self) -> float:
        proc, parm = self.cfg.setp
        try:
            v = self._read_pp(proc, parm, vartype="f", varlength=0)
            out = self._raw_to_percent(v) if self.cfg.scale_mode == "raw_percent" else v
            self._last_good_setpoint = float(out)
            return float(out)
        except Exception as e:
            if self.cfg.fail_soft:
                logger.warning("FlowSensor: read_setpoint failed (%s) -> using last_good/0.0", e)
                return float(self._last_good_setpoint if self._last_good_setpoint is not None else 0.0)
            raise

    def set_setpoint(self, value: float, *, ramp: bool = True) -> None:
        if self.cfg.scale_mode == "raw_percent":
            target = float(value)
            if not (0.0 <= target <= 100.0):
                raise ValueError("percent must be in [0, 100]")
            target_value = self._percent_to_raw(target)
        else:
            target_value = float(value)

        self._set_setpoint_value(target_value, ramp=ramp)

    def _set_setpoint_value(self, target_value: float, *, ramp: bool) -> None:
        proc, parm = self.cfg.setp

        if ramp and self.cfg.ramp_max_step is not None and self.cfg.ramp_max_step > 0:
            try:
                cur = self._read_pp(proc, parm, vartype="f", varlength=0)
            except Exception as e:
                logger.warning("FlowSensor: ramp requested but read failed (%s) -> direct write", e)
                self._set_once(proc, parm, target_value)
                return

            step = float(self.cfg.ramp_max_step)
            if target_value == cur:
                logger.info("FlowSensor: setpoint unchanged (%r)", target_value)
                return

            direction = 1.0 if target_value > cur else -1.0
            v = cur
            logger.info("FlowSensor: ramp setpoint %r -> %r (step=%r)", cur, target_value, step)

            while (direction > 0 and v < target_value) or (direction < 0 and v > target_value):
                nxt = v + direction * step
                nxt = min(nxt, target_value) if direction > 0 else max(nxt, target_value)
                self._set_once(proc, parm, nxt)
                v = nxt
                time.sleep(self.cfg.ramp_sleep_s)
            return

        self._set_once(proc, parm, target_value)

    def _set_once(self, proc: int, parm: int, value: float) -> None:
        last_exc: Optional[Exception] = None
        for attempt in range(self.cfg.max_write_retries + 1):
            try:
                self._write_pp(proc, parm, value, vartype="f", varlength=0)
                return
            except Exception as e:
                last_exc = e
                logger.warning("FlowSensor: set attempt %s failed: %s", attempt + 1, e)
                time.sleep(0.05)
        assert last_exc is not None
        raise last_exc

    # -------- Legacy API expected by DeviceManager --------
    def read_flow_eng(self) -> float:
        return float(self.read_flow())

    def close(self) -> None:
        if self.inst is None:
            logger.debug("FlowSensor: close() called but not connected")
            return

        try:
            close_fn = getattr(self.inst, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            logger.exception("FlowSensor: error while closing")
        finally:
            self.inst = None
            logger.info("FlowSensor: disconnected")

    def __enter__(self) -> "FlowSensor":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
