import propar
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FlowSensorConfig:
    port: str = "COM5"
    full_scale_raw: int = 32000


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

class FlowSensor:
    def __init__(self, cfg: FlowSensorConfig = FlowSensorConfig()):
        self.cfg = cfg
        self.flow = None

    def connect(self) -> None:
        _log(f"Connecting to flow controller on {self.cfg.port}...")
        try:
            self.flow = propar.instrument(self.cfg.port)
        except Exception as e:
            _log(f"ERROR: Connection failed on {self.cfg.port}: {e}")
            raise

        try:
            _log(f"Connected to device: {self.flow.id}")
        except Exception:
            _log("Connected to device (ID not available).")

    def _require_connected(self) -> None:
        if self.flow is None:
            raise RuntimeError("FlowSensor is not connected. Call connect() first.")

    def read_flow(self) -> float:
        self._require_connected()
        try:
            value = float(self.flow.measure)
            _log(f"Read flow: {value}")
            return value
        except Exception as e:
            _log(f"ERROR: Failed to read flow: {e}")
            raise

    def read_setpoint_raw(self) -> int:
        self._require_connected()
        try:
            sp = int(self.flow.setpoint)
            _log(f"Read setpoint (raw): {sp}")
            return sp
        except Exception as e:
            _log(f"ERROR: Failed to read setpoint: {e}")
            raise

    def read_setpoint_percent(self) -> float:
        sp = self.read_setpoint_raw()
        percent = sp / self.cfg.full_scale_raw * 100.0
        _log(f"Setpoint (percent): {percent:.2f}%")
        return percent

    def set_setpoint_percent(self, percent: float) -> None:
        self._require_connected()
        if not (0.0 <= percent <= 100.0):
            raise ValueError("percent must be in [0, 100].")

        raw = int(round(percent / 100.0 * self.cfg.full_scale_raw))
        _log(f"Setting setpoint: {percent:.2f}% → raw={raw}")

        try:
            self.flow.setpoint = raw
            verify = self.read_setpoint_raw()
            _log(f"Setpoint updated (read-back raw): {verify}")
        except Exception as e:
            _log(f"ERROR: Failed to set setpoint: {e}")
            raise

    def close(self) -> None:
        if self.flow is None:
            return
        if hasattr(self.flow, "close"):
            try:
                self.flow.close()
                _log("Connection closed.")
            except Exception as e:
                _log(f"WARNING: Error while closing connection: {e}")
        self.flow = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
