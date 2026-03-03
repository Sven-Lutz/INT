# src/hardware/drivers/flow_sensor.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, Iterable, Union

import propar

logger = logging.getLogger(__name__)

ProcPar = Tuple[int, int]

# -----------------------------
# Defaults for ES-FLOW / ProPar
# -----------------------------
DEFAULT_MEAS: ProcPar = (33, 0)  # Fmeasure
DEFAULT_SETP: ProcPar = (33, 3)  # Fsetpoint

# Legacy mapping seen earlier (often wrong for ES-FLOW)
LEGACY_MEAS: ProcPar = (33, 205)
LEGACY_SETP: ProcPar = (33, 206)


@dataclass(frozen=True)
class FlowSensorConfig:
    port: str = "COM5"
    address: int = 3
    baudrate: int = 38400
    channel: int = 1

    scale_mode: str = "engineering"  # "engineering" | "raw_percent"
    full_scale_raw: int = 32000

    # MUST MATCH YOUR DEVICE
    meas: ProcPar = DEFAULT_MEAS
    setp: ProcPar = DEFAULT_SETP

    io_timeout_s: float = 1.5
    inter_request_sleep_s: float = 0.03

    max_write_retries: int = 2
    readback_tolerance: float = 0.05

    # If True: after write, verify readback within tolerance; else only warn
    enforce_setpoint_readback: bool = False

    ramp_max_step: Optional[float] = 0.2
    ramp_sleep_s: float = 0.15

    fail_soft: bool = True
    fail_hard_after_consecutive: int = 10
    log_raw_on_fail: bool = True

    @staticmethod
    def _as_procpar(x: Any, *, fallback: ProcPar) -> ProcPar:
        try:
            if isinstance(x, (list, tuple)) and len(x) == 2:
                return (int(x[0]), int(x[1]))
        except Exception:
            pass
        return (int(fallback[0]), int(fallback[1]))

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        """
        Backward-compatible config loader.

        Priority:
          1) meas / setp
          2) meas_raw / set_raw (legacy aliases)
        """
        meas_in = d.get("meas", None)
        setp_in = d.get("setp", None)

        if meas_in is None and d.get("meas_raw", None) is not None:
            meas_in = d.get("meas_raw")
        if setp_in is None and d.get("set_raw", None) is not None:
            setp_in = d.get("set_raw")

        meas = FlowSensorConfig._as_procpar(meas_in, fallback=DEFAULT_MEAS) if meas_in is not None else DEFAULT_MEAS
        setp = FlowSensorConfig._as_procpar(setp_in, fallback=DEFAULT_SETP) if setp_in is not None else DEFAULT_SETP

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
            inter_request_sleep_s=float(d.get("inter_request_sleep_s", 0.03)),
            max_write_retries=int(d.get("max_write_retries", 2)),
            readback_tolerance=float(d.get("readback_tolerance", d.get("readback_tolerance_percent", 0.05))),
            enforce_setpoint_readback=bool(d.get("enforce_setpoint_readback", False)),
            ramp_max_step=ramp_v,
            ramp_sleep_s=float(d.get("ramp_sleep_s", 0.15)),
            fail_soft=bool(d.get("fail_soft", True)),
            fail_hard_after_consecutive=int(d.get("fail_hard_after_consecutive", 10)),
            log_raw_on_fail=bool(d.get("log_raw_on_fail", True)),
        )


class FlowSensor:
    def __init__(self, cfg: FlowSensorConfig = FlowSensorConfig()):
        self.cfg = cfg
        self.inst: Optional[object] = None

        self._last_good_flow: Optional[float] = None
        self._last_good_setpoint: Optional[float] = None

        self._consecutive_read_failures: int = 0
        self._last_error: Optional[str] = None
        self._raw_dumped: set[tuple[int, int, str]] = set()  # (proc,parm,"read"/"write")

        if not str(self.cfg.port).strip():
            raise ValueError("FlowSensorConfig.port must be set.")
        if int(self.cfg.full_scale_raw) <= 0:
            raise ValueError("FlowSensorConfig.full_scale_raw must be > 0.")
        if self.cfg.io_timeout_s <= 0:
            raise ValueError("FlowSensorConfig.io_timeout_s must be > 0.")
        if self.cfg.max_write_retries < 0:
            raise ValueError("FlowSensorConfig.max_write_retries must be >= 0.")
        if self.cfg.fail_hard_after_consecutive < 1:
            raise ValueError("FlowSensorConfig.fail_hard_after_consecutive must be >= 1.")

    # ---------- connection ----------
    def connect(self) -> None:
        if self.inst is not None:
            logger.debug("FlowSensor: connect() called but already connected")
            return

        logger.info(
            "FlowSensor: connecting (port=%s, address=%s, baudrate=%s, channel=%s)",
            self.cfg.port, self.cfg.address, self.cfg.baudrate, self.cfg.channel
        )

        self.inst = propar.instrument(
            comport=self.cfg.port,
            address=self.cfg.address,
            baudrate=self.cfg.baudrate,
            channel=self.cfg.channel,
        )
        logger.info("FlowSensor: connected")

        # quick sanity read (non-fatal)
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
        """
        Map a vartype char to propar PP_TYPE_*.

        Supported:
          f (float32), l (int32), i (int16),
          b/B (uint8), h/H (uint16), c (string)
        """
        vt = (vartype or "").strip()
        if not vt:
            vt = "l"
        vtl = vt.lower()

        if vtl == "f":
            return int(getattr(propar, "PP_TYPE_FLOAT", 8))
        if vtl == "l":
            return int(getattr(propar, "PP_TYPE_INT32", 4))
        if vtl == "i":
            return int(getattr(propar, "PP_TYPE_INT16", 2))
        if vtl in ("b",):  # uint8
            return int(getattr(propar, "PP_TYPE_UINT8", 64))
        if vtl in ("h",):  # uint16
            return int(getattr(propar, "PP_TYPE_UINT16", 66))
        if vtl == "c":
            return int(getattr(propar, "PP_TYPE_STRING", 9))

        # fallback: int32
        return int(getattr(propar, "PP_TYPE_INT32", 4))

    def _maybe_raw_dump(self, *, kind: str, proc: int, parm: int, req: dict, res: Any, exc: Optional[Exception]) -> None:
        if not self.cfg.log_raw_on_fail:
            return
        key = (int(proc), int(parm), str(kind))
        if key in self._raw_dumped:
            return
        self._raw_dumped.add(key)
        logger.warning(
            "FlowSensor: RAW-DUMP (%s) proc=%s parm=%s\n  req=%r\n  res=%r\n  exc=%r",
            kind, proc, parm, req, res, exc
        )

    def _read_pp(self, proc: int, parm: int, *, vartype: str = "f", varlength: int = 0) -> Any:
        """
        ProPar read.

        Important behavior (patched):
        - If inst.readParameter(proc, parm) returns None -> fallback to read_parameters().
        - read_parameters() request dict MUST include parm_type and varlength for your stack.
        - Returns raw decoded value (not forced to float).
        """
        self._require_connected()
        inst = self.inst
        assert inst is not None

        # Fast path if supported: BUT None must fallback, not hard-fail.
        fn = getattr(inst, "readParameter", None)
        if callable(fn):
            try:
                v = fn(int(proc), int(parm))
                if v is not None:
                    return v
            except Exception as e:
                logger.debug("FlowSensor: readParameter failed (%s)", e)

        read_params = getattr(inst, "read_parameters", None)
        if not callable(read_params):
            raise RuntimeError("FlowSensor: propar instrument has no usable read API")

        base = {
            "proc_nr": int(proc),
            "parm_nr": int(parm),
            "parm_type": self._pp_type(vartype),
            "varlength": int(varlength),
        }

        req_variants = [
            {**base, "node": int(self.cfg.address)},
            base,
        ]

        t0 = time.time()
        last_exc: Optional[Exception] = None
        last_res: Any = None
        last_req: dict = {}

        while (time.time() - t0) < self.cfg.io_timeout_s:
            for req in req_variants:
                last_req = req
                try:
                    res = read_params([req])
                    last_res = res

                    if not (isinstance(res, list) and res and isinstance(res[0], dict)):
                        raise RuntimeError(f"FlowSensor: unexpected read_parameters response: {res!r}")

                    r0 = res[0]
                    status = r0.get("status", None)

                    # propar uses 'data'
                    data = r0.get("data", None)
                    if data is None and "value" in r0:
                        data = r0.get("value", None)

                    if status not in (None, 0):
                        raise RuntimeError(f"FlowSensor: propar status={status} for proc={proc} parm={parm} payload={r0!r}")
                    if data is None:
                        raise RuntimeError(f"FlowSensor: propar returned data=None for proc={proc} parm={parm} payload={r0!r}")

                    return data
                except Exception as e:
                    last_exc = e

            time.sleep(float(self.cfg.inter_request_sleep_s))

        self._maybe_raw_dump(kind="read", proc=proc, parm=parm, req=last_req, res=last_res, exc=last_exc)
        if last_exc:
            raise last_exc
        raise TimeoutError(f"FlowSensor: read timeout proc={proc} parm={parm}")

    def _write_pp(self, proc: int, parm: int, value: Any, *, vartype: str = "f", varlength: int = 0) -> None:
        """
        ProPar write (patched):
        - Prefer write_parameters() because on your setup it returns 0 on success and actually works.
        - writeParameter() exists but appears to be a no-op / not mapped correctly for your device.
        """
        self._require_connected()
        inst = self.inst
        assert inst is not None

        write_params = getattr(inst, "write_parameters", None)
        base = {
            "proc_nr": int(proc),
            "parm_nr": int(parm),
            "parm_type": self._pp_type(vartype),
            "varlength": int(varlength),
            "node": int(self.cfg.address),
            "data": value,
        }

        # 1) Preferred path: write_parameters
        if callable(write_params):
            t0 = time.time()
            last_exc: Optional[Exception] = None
            last_res: Any = None

            while (time.time() - t0) < self.cfg.io_timeout_s:
                try:
                    res = write_params([base])
                    last_res = res

                    # success formats:
                    if res is None or res == 0:
                        return
                    if isinstance(res, list) and res and isinstance(res[0], dict):
                        status = res[0].get("status", None)
                        if status in (None, 0):
                            return
                        raise RuntimeError(
                            f"FlowSensor: write status={status} for proc={proc} parm={parm} payload={res[0]!r}")

                    raise RuntimeError(f"FlowSensor: unexpected write_parameters response: {res!r}")

                except Exception as e:
                    last_exc = e
                    time.sleep(float(self.cfg.inter_request_sleep_s))

            self._maybe_raw_dump(kind="write", proc=proc, parm=parm, req=base, res=last_res, exc=last_exc)
            if last_exc:
                raise last_exc
            raise TimeoutError(f"FlowSensor: write timeout proc={proc} parm={parm}")

        # 2) Fallback: writeParameter
        fn = getattr(inst, "writeParameter", None)
        if callable(fn):
            fn(int(proc), int(parm), value)
            return

        raise RuntimeError("FlowSensor: propar instrument has no usable write API")

    # ---------- generic public reads/writes ----------
    def read_parameter(self, proc: int, parm: int, vartype: str = "f", *, varlength: int = 0) -> Any:
        """
        Public generic ProPar read to support diagnostics / scripts.
        Returns raw decoded value (not forced to float).
        """
        return self._read_pp(int(proc), int(parm), vartype=str(vartype), varlength=int(varlength))

    def write_parameter(self, proc: int, parm: int, value: Any, vartype: str = "f", *, varlength: int = 0) -> None:
        """
        Public generic ProPar write to support diagnostics / scripting.
        """
        self._write_pp(int(proc), int(parm), value, vartype=str(vartype), varlength=int(varlength))

    # ---------- scaling ----------
    def _raw_to_percent(self, raw: float) -> float:
        return float(raw) / float(self.cfg.full_scale_raw) * 100.0

    def _percent_to_raw(self, percent: float) -> float:
        return float(percent) / 100.0 * float(self.cfg.full_scale_raw)

    # ---------- health ----------
    def _mark_read_ok(self) -> None:
        self._consecutive_read_failures = 0
        self._last_error = None

    def _mark_read_fail(self, e: Exception) -> None:
        self._consecutive_read_failures += 1
        self._last_error = str(e)

    def _maybe_raise_on_soft_fail(self, e: Exception) -> None:
        if self._consecutive_read_failures >= int(self.cfg.fail_hard_after_consecutive):
            raise RuntimeError(
                f"FlowSensor unhealthy: {self._consecutive_read_failures} consecutive read failures. Last error: {e}"
            ) from e

    # ---------- public API ----------
    def read_flow(self) -> float:
        proc, parm = self.cfg.meas
        try:
            v = self._read_pp(proc, parm, vartype="f", varlength=0)
            v_f = float(v)
            out = self._raw_to_percent(v_f) if self.cfg.scale_mode == "raw_percent" else v_f
            self._last_good_flow = float(out)
            self._mark_read_ok()
            return float(out)
        except Exception as e:
            self._mark_read_fail(e)
            if self.cfg.fail_soft:
                logger.warning(
                    "FlowSensor: read_flow failed (%s) [fails=%s] -> using last_good/0.0",
                    e, self._consecutive_read_failures
                )
                self._maybe_raise_on_soft_fail(e)
                return float(self._last_good_flow if self._last_good_flow is not None else 0.0)
            raise

    def read_setpoint(self) -> float:
        proc, parm = self.cfg.setp
        try:
            v = self._read_pp(proc, parm, vartype="f", varlength=0)
            v_f = float(v)
            out = self._raw_to_percent(v_f) if self.cfg.scale_mode == "raw_percent" else v_f
            self._last_good_setpoint = float(out)
            self._mark_read_ok()
            return float(out)
        except Exception as e:
            self._mark_read_fail(e)
            if self.cfg.fail_soft:
                logger.warning(
                    "FlowSensor: read_setpoint failed (%s) [fails=%s] -> using last_good/0.0",
                    e, self._consecutive_read_failures
                )
                self._maybe_raise_on_soft_fail(e)
                return float(self._last_good_setpoint if self._last_good_setpoint is not None else 0.0)
            raise

    def set_setpoint(self, value: float, *, ramp: bool = True) -> None:
        # We assume engineering units for ES-FLOW Fsetpoint (float)
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
                cur = float(self._read_pp(proc, parm, vartype="f", varlength=0))
            except Exception as e:
                logger.warning("FlowSensor: ramp requested but read failed (%s) -> direct write", e)
                self._set_once(proc, parm, target_value)
                return

            step = float(self.cfg.ramp_max_step)
            if target_value == cur:
                return

            direction = 1.0 if target_value > cur else -1.0
            v = cur
            while (direction > 0 and v < target_value) or (direction < 0 and v > target_value):
                nxt = v + direction * step
                nxt = min(nxt, target_value) if direction > 0 else max(nxt, target_value)
                self._set_once(proc, parm, nxt)
                v = nxt
                time.sleep(float(self.cfg.ramp_sleep_s))
            return

        self._set_once(proc, parm, target_value)

    def _set_once(self, proc: int, parm: int, value: float) -> None:
        last_exc: Optional[Exception] = None
        for attempt in range(self.cfg.max_write_retries + 1):
            try:
                self._write_pp(proc, parm, float(value), vartype="f", varlength=0)

                # readback check (optional)
                try:
                    rb = float(self._read_pp(proc, parm, vartype="f", varlength=0))
                    tol = float(self.cfg.readback_tolerance)
                    if abs(rb - float(value)) > tol:
                        msg = f"FlowSensor: setpoint readback mismatch: wrote={value} readback={rb} tol={tol} (proc={proc},parm={parm})"
                        if self.cfg.enforce_setpoint_readback:
                            raise RuntimeError(msg)
                        logger.warning(msg)
                except Exception as e_rb:
                    # don't kill write if readback fails and not enforced
                    if self.cfg.enforce_setpoint_readback:
                        raise
                    logger.warning("FlowSensor: readback check failed (non-fatal): %s", e_rb)

                return
            except Exception as e:
                last_exc = e
                logger.warning("FlowSensor: set attempt %s failed: %s", attempt + 1, e)
                time.sleep(float(self.cfg.inter_request_sleep_s))
        assert last_exc is not None
        raise last_exc

    # -------- Legacy API expected by DeviceManager --------
    def read_flow_eng(self) -> float:
        return float(self.read_flow())

    def close(self) -> None:
        if self.inst is None:
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

    def probe_parameters(
        self,
        *,
        proc_candidates: Iterable[int] = (33, 1, 113, 97, 104, 114, 115, 124, 125, 127),
        parm_range=range(0, 80),
        vartypes: Iterable[str] = ("f", "i", "l"),
        limit_hits: int = 30,
        stop_on_status_25: bool = True,
    ) -> list[tuple[int, int, str, Any]]:
        """
        Probe proc/parm space and return hits that read with status=0 and data!=None.

        stop_on_status_25:
          If True, don't try other vartypes for a (proc,parm) once we got "status=25".
        """
        self._require_connected()
        hits: list[tuple[int, int, str, Any]] = []

        for proc in proc_candidates:
            for parm in parm_range:
                saw_25 = False
                for vt in vartypes:
                    if saw_25 and stop_on_status_25:
                        break
                    try:
                        v = self._read_pp(int(proc), int(parm), vartype=str(vt), varlength=0)
                        hits.append((int(proc), int(parm), str(vt), v))
                        logger.info("FlowSensor PROBE HIT: proc=%s parm=%s vt=%s val=%r", proc, parm, vt, v)
                        if len(hits) >= int(limit_hits):
                            return hits
                    except Exception as e:
                        if "status=25" in str(e):
                            saw_25 = True
                        pass
        return hits
