# hardware/drivers/pressure_controller.py
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

    full_scale_raw: int = 32000
    limit_percent_main: float = 80.0
    limit_percent_backwash: float = 80.0

    meas_raw: ProcPar = (1, 0)
    set_raw: ProcPar = (1, 1)

    readback_tolerance_percent: float = 1.0
    max_write_retries: int = 2
    io_timeout_s: float = 1.5

    ramp_max_step_percent: Optional[float] = 5.0
    ramp_sleep_s: float = 0.15

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PressureControllerConfig":
        meas = d.get("meas_raw", [1, 0])
        sp = d.get("set_raw", [1, 1])

        ramp = d.get("ramp_max_step_percent", 5.0)
        ramp_v: Optional[float]
        if ramp is None:
            ramp_v = None
        else:
            ramp_v = float(ramp)

        return PressureControllerConfig(
            main=ProparEndpoint.from_dict(d["main"]),
            backwash=ProparEndpoint.from_dict(d["backwash"]),
            full_scale_raw=int(d.get("full_scale_raw", 32000)),
            limit_percent_main=float(d.get("limit_percent_main", 80.0)),
            limit_percent_backwash=float(d.get("limit_percent_backwash", 80.0)),
            meas_raw=(int(meas[0]), int(meas[1])),
            set_raw=(int(sp[0]), int(sp[1])),
            readback_tolerance_percent=float(d.get("readback_tolerance_percent", 1.0)),
            max_write_retries=int(d.get("max_write_retries", 2)),
            io_timeout_s=float(d.get("io_timeout_s", 1.5)),
            ramp_max_step_percent=ramp_v,
            ramp_sleep_s=float(d.get("ramp_sleep_s", 0.15)),
        )


class _ProparPressureChannel:
    def __init__(
        self,
        name: str,
        endpoint: ProparEndpoint,
        full_scale_raw: int,
        limit_percent: float,
        meas_raw: ProcPar,
        set_raw: ProcPar,
        readback_tolerance_percent: float,
        max_write_retries: int,
        io_timeout_s: float,
        ramp_max_step_percent: Optional[float],
        ramp_sleep_s: float,
    ):
        self.name = name
        self.endpoint = endpoint
        self.full_scale_raw = int(full_scale_raw)
        self.limit_percent = float(limit_percent)
        self.meas_raw = (int(meas_raw[0]), int(meas_raw[1]))
        self.set_raw = (int(set_raw[0]), int(set_raw[1]))
        self.readback_tolerance_percent = float(readback_tolerance_percent)
        self.max_write_retries = int(max_write_retries)
        self.io_timeout_s = float(io_timeout_s)
        self.ramp_max_step_percent = ramp_max_step_percent if ramp_max_step_percent is None else float(ramp_max_step_percent)
        self.ramp_sleep_s = float(ramp_sleep_s)
        self.inst: Optional[object] = None

        if not str(self.endpoint.port).strip():
            raise ValueError(f"{self.name}: port must be set.")
        if self.full_scale_raw <= 0:
            raise ValueError(f"{self.name}: full_scale_raw must be > 0.")
        if not (0.0 < self.limit_percent <= 100.0):
            raise ValueError(f"{self.name}: limit_percent must be in (0, 100].")
        if self.readback_tolerance_percent < 0.0:
            raise ValueError(f"{self.name}: readback_tolerance_percent must be >= 0.")
        if self.max_write_retries < 0:
            raise ValueError(f"{self.name}: max_write_retries must be >= 0.")
        if self.io_timeout_s <= 0:
            raise ValueError(f"{self.name}: io_timeout_s must be > 0.")

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

        try:
            p = self.read_pressure_percent()
            sp = self.read_setpoint_percent()
            logger.info("%s: initial pressure=%.3f%% setpoint=%.3f%%", self.name, p, sp)
        except Exception:
            logger.exception("%s: initial read failed", self.name)

    def _require_connected(self) -> None:
        if self.inst is None:
            raise RuntimeError(f"{self.name}: not connected. Call connect() first.")

    def _read_parameter(self, proc: int, par: int) -> float:
        self._require_connected()
        t0 = time.time()
        last_exc: Optional[Exception] = None
        while (time.time() - t0) < self.io_timeout_s:
            try:
                v = self.inst.read_parameter(int(proc), int(par))  # type: ignore[union-attr]
                return float(v)
            except Exception as e:
                last_exc = e
                time.sleep(0.05)
        logger.exception("%s: read timeout (proc=%s, par=%s)", self.name, proc, par)
        if last_exc:
            raise last_exc
        raise TimeoutError(f"{self.name}: read timeout proc={proc} par={par}")

    def _write_parameter(self, proc: int, par: int, value: float) -> None:
        self._require_connected()
        t0 = time.time()
        last_exc: Optional[Exception] = None
        while (time.time() - t0) < self.io_timeout_s:
            try:
                self.inst.write_parameter(int(proc), int(par), float(value))  # type: ignore[union-attr]
                return
            except Exception as e:
                last_exc = e
                time.sleep(0.05)
        logger.exception("%s: write timeout (proc=%s, par=%s)", self.name, proc, par)
        if last_exc:
            raise last_exc
        raise TimeoutError(f"{self.name}: write timeout proc={proc} par={par}")

    def _raw_to_percent(self, raw: int) -> float:
        return int(raw) / float(self.full_scale_raw) * 100.0

    def _percent_to_raw(self, percent: float) -> int:
        return int(round(float(percent) / 100.0 * float(self.full_scale_raw)))

    def read_pressure_percent(self) -> float:
        proc, par = self.meas_raw
        raw = int(self._read_parameter(proc, par))
        pct = self._raw_to_percent(raw)
        logger.debug("%s: read pressure raw=%s -> %.6f%% (proc=%s par=%s)", self.name, raw, pct, proc, par)
        return pct

    def read_setpoint_percent(self) -> float:
        proc, par = self.set_raw
        raw = int(self._read_parameter(proc, par))
        pct = self._raw_to_percent(raw)
        logger.debug("%s: read setpoint raw=%s -> %.6f%% (proc=%s par=%s)", self.name, raw, pct, proc, par)
        return pct

    def set_pressure_percent(self, percent: float, *, ramp: bool = True) -> None:
        target = float(percent)
        if not (0.0 <= target <= self.limit_percent):
            raise ValueError(f"{self.name}: percent out of range [0, {self.limit_percent}]")

        if ramp and self.ramp_max_step_percent is not None and self.ramp_max_step_percent > 0:
            current = self.read_setpoint_percent()
            step = float(self.ramp_max_step_percent)
            if target == current:
                logger.info("%s: target unchanged (%.3f%%)", self.name, target)
                return

            direction = 1.0 if target > current else -1.0
            value = current
            logger.info("%s: ramp setpoint %.3f%% -> %.3f%% (step=%.3f%%)", self.name, current, target, step)

            while (direction > 0 and value < target) or (direction < 0 and value > target):
                nxt = value + direction * step
                if direction > 0:
                    nxt = min(nxt, target)
                else:
                    nxt = max(nxt, target)
                self._set_setpoint_once(nxt)
                value = nxt
                time.sleep(self.ramp_sleep_s)
            return

        logger.info("%s: set setpoint to %.3f%% (no ramp)", self.name, target)
        self._set_setpoint_once(target)

    def _set_setpoint_once(self, percent: float) -> None:
        proc, par = self.set_raw
        raw = self._percent_to_raw(percent)

        logger.debug("%s: write setpoint %.6f%% -> raw=%s (proc=%s par=%s)", self.name, percent, raw, proc, par)

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_write_retries + 1):
            try:
                self._write_parameter(proc, par, float(raw))
                rb = self.read_setpoint_percent()
                delta = abs(rb - float(percent))
                tol = self.readback_tolerance_percent
                logger.debug("%s: readback %.6f%% (delta=%.6f%% tol=%.6f%%)", self.name, rb, delta, tol)
                if delta <= tol:
                    logger.info("%s: setpoint accepted %.3f%%", self.name, float(percent))
                    return
                logger.warning("%s: readback mismatch (wanted=%.3f%% got=%.3f%%)", self.name, float(percent), rb)
            except Exception as e:
                last_exc = e
                logger.warning("%s: set attempt %s failed: %s", self.name, attempt + 1, e)
                time.sleep(0.05)

        logger.exception("%s: failed to set setpoint after retries", self.name)
        if last_exc:
            raise last_exc
        raise RuntimeError(f"{self.name}: failed to set setpoint")

    def shutdown(self) -> None:
        logger.info("%s: shutdown requested -> setpoint 0%%", self.name)
        try:
            self.set_pressure_percent(0.0, ramp=True)
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
            full_scale_raw=self.cfg.full_scale_raw,
            limit_percent=self.cfg.limit_percent_main,
            meas_raw=self.cfg.meas_raw,
            set_raw=self.cfg.set_raw,
            readback_tolerance_percent=self.cfg.readback_tolerance_percent,
            max_write_retries=self.cfg.max_write_retries,
            io_timeout_s=self.cfg.io_timeout_s,
            ramp_max_step_percent=self.cfg.ramp_max_step_percent,
            ramp_sleep_s=self.cfg.ramp_sleep_s,
        )

        self.backwash = _ProparPressureChannel(
            name="PressureController.backwash",
            endpoint=self.cfg.backwash,
            full_scale_raw=self.cfg.full_scale_raw,
            limit_percent=self.cfg.limit_percent_backwash,
            meas_raw=self.cfg.meas_raw,
            set_raw=self.cfg.set_raw,
            readback_tolerance_percent=self.cfg.readback_tolerance_percent,
            max_write_retries=self.cfg.max_write_retries,
            io_timeout_s=self.cfg.io_timeout_s,
            ramp_max_step_percent=self.cfg.ramp_max_step_percent,
            ramp_sleep_s=self.cfg.ramp_sleep_s,
        )

    def connect(self) -> None:
        self.main.connect()
        self.backwash.connect()

    def set_pressure_percent(self, channel: int, percent: float, *, ramp: bool = True) -> None:
        ch = int(channel)
        if ch == 1:
            self.main.set_pressure_percent(percent, ramp=ramp)
            return
        if ch == 2:
            self.backwash.set_pressure_percent(percent, ramp=ramp)
            return
        raise ValueError("channel must be 1 (main) or 2 (backwash)")

    def read_pressure_percent(self, channel: int) -> float:
        ch = int(channel)
        if ch == 1:
            return self.main.read_pressure_percent()
        if ch == 2:
            return self.backwash.read_pressure_percent()
        raise ValueError("channel must be 1 (main) or 2 (backwash)")

    def read_setpoint_percent(self, channel: int) -> float:
        ch = int(channel)
        if ch == 1:
            return self.main.read_setpoint_percent()
        if ch == 2:
            return self.backwash.read_setpoint_percent()
        raise ValueError("channel must be 1 (main) or 2 (backwash)")

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
