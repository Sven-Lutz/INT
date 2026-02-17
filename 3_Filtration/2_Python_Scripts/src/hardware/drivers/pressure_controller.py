# src/hardware/drivers/pressure_controller.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import propar

logger = logging.getLogger(__name__)

ProcPar = Tuple[int, int]


@dataclass(frozen=True)
class ProparEndpoint:
    port: str
    address: int
    baudrate: int = 38400
    channel: int = 1

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ProparEndpoint":
        return ProparEndpoint(
            port=str(d["port"]),
            address=int(d["address"]),
            baudrate=int(d.get("baudrate", 38400)),
            channel=int(d.get("channel", 1)),
        )


@dataclass(frozen=True)
class PressureControllerConfig:
    main: ProparEndpoint
    backwash: ProparEndpoint

    # engineering: set_pressure_percent() forwards "percent" as engineering units (your current Experimentator assumption)
    # raw_percent: percent is converted to raw (0..full_scale_raw) before writing
    scale_mode: str = "engineering"  # "engineering" | "raw_percent"

    full_scale_raw: int = 32000
    limit_percent_main: float = 80.0
    limit_percent_backwash: float = 80.0

    meas: ProcPar = (33, 205)
    setp: ProcPar = (33, 206)

    # Readback checks are nice, but must not kill the run if reads fail
    verify_readback: bool = False

    readback_tolerance: float = 1.0
    max_write_retries: int = 2
    io_timeout_s: float = 1.5

    ramp_max_step: Optional[float] = 0.2
    ramp_sleep_s: float = 0.15

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PressureControllerConfig":
        meas = d.get("meas", d.get("meas_raw", [33, 205]))
        setp = d.get("setp", d.get("set_raw", [33, 206]))

        ramp = d.get("ramp_max_step", d.get("ramp_max_step_percent", 0.2))
        ramp_v: Optional[float] = None if ramp is None else float(ramp)

        return PressureControllerConfig(
            main=ProparEndpoint.from_dict(d["main"]),
            backwash=ProparEndpoint.from_dict(d["backwash"]),
            scale_mode=str(d.get("scale_mode", "engineering")),
            full_scale_raw=int(d.get("full_scale_raw", 32000)),
            limit_percent_main=float(d.get("limit_percent_main", 80.0)),
            limit_percent_backwash=float(d.get("limit_percent_backwash", 80.0)),
            meas=(int(meas[0]), int(meas[1])),
            setp=(int(setp[0]), int(setp[1])),
            verify_readback=bool(d.get("verify_readback", False)),
            readback_tolerance=float(d.get("readback_tolerance", d.get("readback_tolerance_percent", 1.0))),
            max_write_retries=int(d.get("max_write_retries", 2)),
            io_timeout_s=float(d.get("io_timeout_s", 1.5)),
            ramp_max_step=ramp_v,
            ramp_sleep_s=float(d.get("ramp_sleep_s", 0.15)),
        )


class _ProparPressureChannel:
    def __init__(
        self,
        name: str,
        endpoint: ProparEndpoint,
        cfg: PressureControllerConfig,
        *,
        limit_percent: float,
    ):
        self.name = name
        self.endpoint = endpoint
        self.cfg = cfg
        self.limit_percent = float(limit_percent)

        self.inst: Optional[object] = None

        if not str(self.endpoint.port).strip():
            raise ValueError(f"{self.name}: port must be set.")
        if self.cfg.full_scale_raw <= 0:
            raise ValueError(f"{self.name}: full_scale_raw must be > 0.")
        if not (0.0 < self.limit_percent <= 100.0):
            raise ValueError(f"{self.name}: limit_percent must be in (0, 100].")
        if self.cfg.readback_tolerance < 0.0:
            raise ValueError(f"{self.name}: readback_tolerance must be >= 0.")
        if self.cfg.max_write_retries < 0:
            raise ValueError(f"{self.name}: max_write_retries must be >= 0.")
        if self.cfg.io_timeout_s <= 0:
            raise ValueError(f"{self.name}: io_timeout_s must be > 0.")

    # ---------- connection ----------
    def connect(self) -> None:
        if self.inst is not None:
            logger.debug("%s: connect() called but already connected", self.name)
            return

        logger.info(
            "%s: connecting (port=%s, address=%s, baudrate=%s, channel=%s)",
            self.name,
            self.endpoint.port,
            self.endpoint.address,
            self.endpoint.baudrate,
            self.endpoint.channel,
        )

        try:
            self.inst = propar.instrument(
                comport=self.endpoint.port,
                address=self.endpoint.address,
                baudrate=self.endpoint.baudrate,
                channel=self.endpoint.channel,
            )
        except Exception:
            logger.exception("%s: ProPar instrument initialization failed", self.name)
            raise

        dev_id = None
        try:
            dev_id = getattr(self.inst, "id", None)
        except Exception:
            dev_id = None

        logger.info("%s: connected (id=%r)", self.name, dev_id)

        # initial read (non-fatal)
        try:
            m = self.read_measure()
            s = self.read_setpoint()
            logger.info("%s: initial measure=%r setpoint=%r", self.name, m, s)
        except Exception:
            logger.exception("%s: initial read failed (non-fatal)", self.name)

    def _require_connected(self) -> None:
        if self.inst is None:
            raise RuntimeError(f"{self.name}: not connected. Call connect() first.")

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
        2) inst.read_parameters([dict]) but ONLY with proc_nr/parm_nr keys (your propar requires them)
        """
        self._require_connected()
        inst = self.inst
        assert inst is not None

        # Variant A: classic API
        fn = getattr(inst, "readParameter", None)
        if callable(fn):
            try:
                v = fn(int(proc), int(parm))
                if v is None:
                    raise RuntimeError(f"{self.name}: readParameter returned None (proc={proc}, parm={parm})")
                return float(v)
            except Exception as e:
                logger.debug("%s: readParameter failed (%s)", self.name, e)

        # Variant B: read_parameters schema(s) — MUST include proc_nr/parm_nr
        read_params = getattr(inst, "read_parameters", None)
        if not callable(read_params):
            raise RuntimeError(f"{self.name}: propar instrument has no usable read API")

        req_variants = [
            {
                "proc_nr": int(proc),
                "parm_nr": int(parm),
                "parm_type": self._pp_type(vartype),
                "varlength": int(varlength),
            },
            # Some builds accept/need node; safe to include
            {
                "node": int(self.endpoint.address),
                "proc_nr": int(proc),
                "parm_nr": int(parm),
                "parm_type": self._pp_type(vartype),
                "varlength": int(varlength),
            },
        ]

        t0 = time.time()
        last_exc: Optional[Exception] = None

        while (time.time() - t0) < self.cfg.io_timeout_s:
            for req in req_variants:
                try:
                    res = read_params([req])
                    if not (isinstance(res, list) and res and isinstance(res[0], dict)):
                        raise RuntimeError(f"{self.name}: unexpected read_parameters response: {res!r}")

                    r0 = res[0]
                    status = r0.get("status", None)
                    data = r0.get("data", None)

                    if status not in (None, 0):
                        raise RuntimeError(
                            f"{self.name}: propar status={status} for proc={proc} parm={parm} data={data!r}"
                        )
                    if data is None:
                        raise RuntimeError(f"{self.name}: propar returned data=None for proc={proc} parm={parm}")

                    return float(data)

                except Exception as e:
                    last_exc = e

            time.sleep(0.05)

        if last_exc:
            raise last_exc
        raise TimeoutError(f"{self.name}: read timeout proc={proc} parm={parm}")

    def _write_pp(self, proc: int, parm: int, value: float, *, vartype: str = "f", varlength: int = 0) -> None:
        """
        Robust writer across propar variants:
        1) inst.writeParameter(proc, parm, value)
        2) inst.write_parameters([dict]) but ONLY with proc_nr/parm_nr keys (your propar requires them)
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
                logger.debug("%s: writeParameter failed (%s)", self.name, e)

        write_params = getattr(inst, "write_parameters", None)
        if not callable(write_params):
            raise RuntimeError(f"{self.name}: propar instrument has no usable write API")

        req_variants = [
            {
                "proc_nr": int(proc),
                "parm_nr": int(parm),
                "parm_type": self._pp_type(vartype),
                "varlength": int(varlength),
                "data": float(value),
            },
            {
                "node": int(self.endpoint.address),
                "proc_nr": int(proc),
                "parm_nr": int(parm),
                "parm_type": self._pp_type(vartype),
                "varlength": int(varlength),
                "data": float(value),
            },
        ]

        t0 = time.time()
        last_exc: Optional[Exception] = None

        while (time.time() - t0) < self.cfg.io_timeout_s:
            for req in req_variants:
                try:
                    res = write_params([req])

                    # treat None as success; list with status must be checked
                    if isinstance(res, list) and res and isinstance(res[0], dict):
                        status = res[0].get("status", None)
                        if status not in (None, 0):
                            raise RuntimeError(f"{self.name}: write status={status} for proc={proc} parm={parm}")
                    return

                except Exception as e:
                    last_exc = e

            time.sleep(0.05)

        if last_exc:
            raise last_exc
        raise TimeoutError(f"{self.name}: write timeout proc={proc} parm={parm}")

    # ---------- scaling ----------
    def _raw_to_percent(self, raw: float) -> float:
        return float(raw) / float(self.cfg.full_scale_raw) * 100.0

    def _percent_to_raw(self, percent: float) -> float:
        return float(percent) / 100.0 * float(self.cfg.full_scale_raw)

    # ---------- high-level API ----------
    def read_measure(self) -> float:
        proc, parm = self.cfg.meas
        return self._read_pp(proc, parm, vartype="f", varlength=0)

    def read_setpoint(self) -> float:
        proc, parm = self.cfg.setp
        return self._read_pp(proc, parm, vartype="f", varlength=0)

    def set_setpoint(self, target: float, *, ramp: bool = True) -> None:
        if self.cfg.scale_mode == "raw_percent":
            if not (0.0 <= float(target) <= self.limit_percent):
                raise ValueError(f"{self.name}: target percent out of range [0, {self.limit_percent}]")
            target_value = self._percent_to_raw(float(target))
        else:
            target_value = float(target)

        self._set_setpoint_value(target_value, ramp=ramp)

    def _set_setpoint_value(self, target_value: float, *, ramp: bool) -> None:
        proc, parm = self.cfg.setp

        # If ramp requested but we can't read current setpoint, fall back to single write
        if ramp and self.cfg.ramp_max_step is not None and self.cfg.ramp_max_step > 0:
            try:
                cur = self.read_setpoint()
            except Exception as e:
                logger.warning("%s: ramp requested but read_setpoint failed (%s) -> direct write", self.name, e)
                self._set_once(proc, parm, target_value)
                return

            step = float(self.cfg.ramp_max_step)
            if target_value == cur:
                logger.info("%s: setpoint unchanged (%r)", self.name, target_value)
                return

            direction = 1.0 if target_value > cur else -1.0
            v = cur
            logger.info("%s: ramp setpoint %r -> %r (step=%r)", self.name, cur, target_value, step)

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

                # Optional readback verify
                if not self.cfg.verify_readback:
                    logger.info("%s: setpoint write OK (verify_readback disabled) value=%r", self.name, value)
                    return

                try:
                    rb = self.read_setpoint()
                except Exception as e:
                    logger.warning("%s: readback failed (%s) -> accepting write", self.name, e)
                    return

                delta = abs(rb - float(value))
                tol = float(self.cfg.readback_tolerance)

                if delta <= tol:
                    logger.info("%s: setpoint accepted value=%r (rb=%r, tol=%r)", self.name, value, rb, tol)
                    return

                logger.warning(
                    "%s: readback mismatch (wanted=%r got=%r delta=%r tol=%r)",
                    self.name,
                    value,
                    rb,
                    delta,
                    tol,
                )

            except Exception as e:
                last_exc = e
                logger.warning("%s: set attempt %s failed: %s", self.name, attempt + 1, e)
                time.sleep(0.05)

        if last_exc:
            raise last_exc
        raise RuntimeError(f"{self.name}: failed to set setpoint after retries")

    def shutdown(self) -> None:
        logger.info("%s: shutdown requested -> setpoint 0", self.name)
        try:
            self.set_setpoint(0.0, ramp=False)
        except Exception:
            logger.exception("%s: shutdown failed", self.name)

    def close(self) -> None:
        logger.info("%s: close requested", self.name)
        try:
            self.shutdown()
        except Exception:
            logger.exception("%s: shutdown during close failed", self.name)

        if self.inst is None:
            return

        try:
            close_fn = getattr(self.inst, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            logger.exception("%s: error while closing", self.name)
        finally:
            self.inst = None
            logger.info("%s: disconnected", self.name)


class PressureController:
    def __init__(self, config: Dict[str, Any]):
        cfg = PressureControllerConfig.from_dict(config)
        self.cfg = cfg

        self.main = _ProparPressureChannel(
            name="PressureController.main",
            endpoint=self.cfg.main,
            cfg=self.cfg,
            limit_percent=self.cfg.limit_percent_main,
        )

        self.backwash = _ProparPressureChannel(
            name="PressureController.backwash",
            endpoint=self.cfg.backwash,
            cfg=self.cfg,
            limit_percent=self.cfg.limit_percent_backwash,
        )

    def connect(self) -> None:
        self.main.connect()
        self.backwash.connect()

    # Engineering units by default
    def read_pressure(self, channel: int) -> float:
        ch = int(channel)
        if ch == 1:
            return self.main.read_measure()
        if ch == 2:
            return self.backwash.read_measure()
        raise ValueError("channel must be 1 (main) or 2 (backwash)")

    def read_setpoint(self, channel: int) -> float:
        ch = int(channel)
        if ch == 1:
            return self.main.read_setpoint()
        if ch == 2:
            return self.backwash.read_setpoint()
        raise ValueError("channel must be 1 (main) or 2 (backwash)")

    def set_pressure(self, channel: int, value: float, *, ramp: bool = True) -> None:
        ch = int(channel)
        if ch == 1:
            self.main.set_setpoint(value, ramp=ramp)
            return
        if ch == 2:
            self.backwash.set_setpoint(value, ramp=ramp)
            return
        raise ValueError("channel must be 1 (main) or 2 (backwash)")

    # -------- Legacy API expected by DeviceManager/Experimentator --------
    def set_pressure_percent(self, channel: int, percent: float, ramp: bool = True) -> None:
        # In engineering mode, "percent" is forwarded as the device expects (current system assumption)
        self.set_pressure(channel=int(channel), value=float(percent), ramp=bool(ramp))

    def read_pressure_percent(self, channel: int) -> float:
        return float(self.read_pressure(int(channel)))

    def read_setpoint_percent(self, channel: int) -> float:
        return float(self.read_setpoint(int(channel)))

    def shutdown(self) -> None:
        self.main.shutdown()
        self.backwash.shutdown()

    def close(self) -> None:
        self.main.close()
        self.backwash.close()

    def __enter__(self) -> "PressureController":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
