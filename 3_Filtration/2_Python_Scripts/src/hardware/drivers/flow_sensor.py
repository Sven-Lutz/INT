# hardware/drivers/flow_sensor.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import propar

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlowSensorConfig:
    port: str = "COM5"
    address: int = 3
    baudrate: int = 38400
    channel: int = 1
    full_scale_raw: int = 32000


class FlowSensor:
    def __init__(self, cfg: FlowSensorConfig = FlowSensorConfig()):
        self.cfg = cfg
        self.inst: Optional[object] = None

        if not str(self.cfg.port).strip():
            raise ValueError("FlowSensorConfig.port must be set.")

        if int(self.cfg.full_scale_raw) <= 0:
            raise ValueError("FlowSensorConfig.full_scale_raw must be > 0.")

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

        dev_id = None
        try:
            dev_id = getattr(self.inst, "id", None)
        except Exception:
            dev_id = None

        logger.info("FlowSensor: connected (id=%r)", dev_id)

    def _require_connected(self) -> None:
        if self.inst is None:
            raise RuntimeError("FlowSensor not connected. Call connect() first.")

    def read_flow_percent(self) -> float:
        self._require_connected()
        try:
            raw = int(self.inst.read_parameter(1, 0))  # type: ignore[union-attr]
            pct = raw / float(self.cfg.full_scale_raw) * 100.0
            logger.debug("FlowSensor: read_flow_percent -> %.6f (raw=%s)", pct, raw)
            return pct
        except Exception:
            logger.exception("FlowSensor: read_flow_percent failed (proc=1, par=0)")
            raise

    def read_setpoint_percent(self) -> float:
        self._require_connected()
        try:
            raw = int(self.inst.read_parameter(1, 1))  # type: ignore[union-attr]
            pct = raw / float(self.cfg.full_scale_raw) * 100.0
            logger.debug("FlowSensor: read_setpoint_percent -> %.6f (raw=%s)", pct, raw)
            return pct
        except Exception:
            logger.exception("FlowSensor: read_setpoint_percent failed (proc=1, par=1)")
            raise

    def set_setpoint_percent(self, percent: float) -> None:
        self._require_connected()
        p = float(percent)
        if not (0.0 <= p <= 100.0):
            raise ValueError("percent must be in [0, 100]")

        raw = int(round(p / 100.0 * float(self.cfg.full_scale_raw)))
        logger.info("FlowSensor: set_setpoint_percent %.3f -> raw=%s", p, raw)

        try:
            self.inst.write_parameter(1, 1, raw)  # type: ignore[union-attr]
        except Exception:
            logger.exception("FlowSensor: set_setpoint_percent failed (proc=1, par=1)")
            raise

        try:
            rb_raw = int(self.inst.read_parameter(1, 1))  # type: ignore[union-attr]
            rb_pct = rb_raw / float(self.cfg.full_scale_raw) * 100.0
            logger.debug("FlowSensor: setpoint read-back -> %.6f (raw=%s)", rb_pct, rb_raw)
        except Exception:
            logger.exception("FlowSensor: setpoint read-back failed (proc=1, par=1)")

    def read_flow_eng(self) -> float:
        self._require_connected()
        try:
            v = float(self.inst.read_parameter(33, 0))  # type: ignore[union-attr]
            logger.debug("FlowSensor: read_flow_eng -> %s", v)
            return v
        except Exception:
            logger.exception("FlowSensor: read_flow_eng failed (proc=33, par=0)")
            raise

    def read_setpoint_eng(self) -> float:
        self._require_connected()
        try:
            v = float(self.inst.read_parameter(33, 3))  # type: ignore[union-attr]
            logger.debug("FlowSensor: read_setpoint_eng -> %s", v)
            return v
        except Exception:
            logger.exception("FlowSensor: read_setpoint_eng failed (proc=33, par=3)")
            raise

    def set_setpoint_eng(self, value: float) -> None:
        self._require_connected()
        v = float(value)
        logger.info("FlowSensor: set_setpoint_eng -> %s", v)
        try:
            self.inst.write_parameter(33, 3, v)  # type: ignore[union-attr]
        except Exception:
            logger.exception("FlowSensor: set_setpoint_eng failed (proc=33, par=3)")
            raise

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
