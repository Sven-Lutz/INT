# src/hardware/drivers/flow_sensor.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import propar

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class FlowSensorConfig:
    port: str = "COM5"
    proc_nr: int = 33
    parm_nr: int = 6
    parm_type: int = 65
    
    # NEU: Umrechnung der Rohwerte
    full_scale_raw: float = 32000.0
    full_scale_ml_min: float = 20.0  # Max-Flow deines Sensors. BITTE PRÜFEN! (z.B. 20 ml/min oder 50 ml/min)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        if "flow" in d and isinstance(d["flow"], dict): d = d["flow"]
        port = d.get("COM Port", d.get("port", "COM5"))
        
        # Scaling Parameter laden (Fallback, falls nicht im Config-File)
        fs_raw = float(d.get("full_scale_raw", 32000.0))
        # Nimm an, dass dein Sensor max 50 ml/min schafft. Ändere das, wenn er anders kalibriert ist!
        fs_ml = float(d.get("full_scale_ml_min", 50.0)) 
        
        return FlowSensorConfig(
            port=port, 
            proc_nr=33, parm_nr=6, parm_type=65,
            full_scale_raw=fs_raw, full_scale_ml_min=fs_ml
        )

class FlowSensor:
    def __init__(self, cfg: FlowSensorConfig | Dict[str, Any]):
        if isinstance(cfg, dict): self.cfg = FlowSensorConfig.from_dict(cfg)
        else: self.cfg = cfg
            
        self.flow_sensor: Any = None
        self._cached_request = [{
            "proc_nr": self.cfg.proc_nr,
            "parm_nr": self.cfg.parm_nr,
            "parm_type": self.cfg.parm_type
        }]
        self._last_good_flow: float = 0.0
        self._error_count: int = 0

    def connect(self) -> None:
        if self.flow_sensor is not None: return
        logger.info(f"FlowSensor: connecting to {self.cfg.port}")
        try:
            self.flow_sensor = propar.instrument(self.cfg.port)
            logger.info("FlowSensor: communication successfully started")
            self._error_count = 0
            self._last_good_flow = 0.0
        except Exception as e:
            logger.error(f"FlowSensor: connection failed on {self.cfg.port} -> {e}")
            self.flow_sensor = None
            raise

    def get_flow(self) -> float:
        if self.flow_sensor is None: return 0.0

        try:
            values = self.flow_sensor.read_parameters(self._cached_request)
            if not values or not isinstance(values, list) or len(values) == 0:
                return self._last_good_flow

            data = values[0].get("data")
            if data is None: return self._last_good_flow

            # 🚀 LÖSUNG: Rohwert (z.B. 16000) durch 32000 teilen und mit Max-Flow multiplizieren
            raw_value = float(data)
            
            # Wichtig: Wenn der Sensor abgetrennt ist, sendet er oft Müll. Wir deckeln es.
            if abs(raw_value) > self.cfg.full_scale_raw * 1.5:
                return 0.0 

            flow_ml_min = (raw_value / self.cfg.full_scale_raw) * self.cfg.full_scale_ml_min
            
            # Deadband Filter: Kleines Rauschen (< 0.05 ml/min) wird zu 0.0 geglättet
            if abs(flow_ml_min) < 0.05:
                flow_ml_min = 0.0

            self._error_count = 0
            self._last_good_flow = flow_ml_min
            return flow_ml_min

        except Exception as e:
            self._error_count += 1
            if self._error_count % 10 == 0:
                logger.warning(f"FlowSensor: read error -> {e} (failures: {self._error_count})")
            return self._last_good_flow

    def close(self) -> None:
        if self.flow_sensor is None: return
        try:
            if hasattr(self.flow_sensor, "close"): self.flow_sensor.close()
        except Exception: pass
        finally: self.flow_sensor = None