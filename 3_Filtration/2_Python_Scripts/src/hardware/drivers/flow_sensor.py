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
    baudrate: int = 38400
    address: int = 3
    
    # ProPar Parameter (Standard: 33/0 für Engineering Float)
    proc_nr: int = 33
    parm_nr: int = 0
    parm_type: int = 117  # 117 = IEEE Float (Standard für proc 33). 114 = Int (für proc 1)
    
    scale_mode: str = "engineering"
    full_scale_raw: float = 32000.0
    full_scale_ml_min: float = 20.0 

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        if "flow" in d and isinstance(d["flow"], dict): 
            d = d["flow"]
            
        port = d.get("port", d.get("COM Port", "COM5"))
        baudrate = int(d.get("baudrate", 38400))
        address = int(d.get("address", 3))
        
        # Lese Prozess/Parameter aus YAML (z.B. [33, 0])
        meas = d.get("meas", [33, 0])
        proc_nr = int(meas[0])
        parm_nr = int(meas[1])
        
        # 117 für Floats (Proc 33), 114 für Integer (Proc 1)
        parm_type = 117 if proc_nr == 33 else 114
        
        scale_mode = str(d.get("scale_mode", "engineering")).strip().lower()
        fs_raw = float(d.get("full_scale_raw", 32000.0))
        fs_ml = float(d.get("full_scale_ml_min", 20.0)) 
        
        return FlowSensorConfig(
            port=port, baudrate=baudrate, address=address,
            proc_nr=proc_nr, parm_nr=parm_nr, parm_type=parm_type,
            scale_mode=scale_mode, full_scale_raw=fs_raw, full_scale_ml_min=fs_ml
        )

class FlowSensor:
    """
    Treiber für Bronkhorst ES-FLOW / ProPar basierte Sensoren.
    """
    def __init__(self, cfg: FlowSensorConfig | Dict[str, Any]):
        if isinstance(cfg, dict): 
            self.cfg = FlowSensorConfig.from_dict(cfg)
        else: 
            self.cfg = cfg
            
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
        logger.info(f"FlowSensor: connecting to {self.cfg.port} (Baud: {self.cfg.baudrate}, Node: {self.cfg.address})")
        
        try:
            # 🚀 FIX: Wir zwingen ProPar, exakt deine Settings zu nutzen
            self.flow_sensor = propar.instrument(
                self.cfg.port, 
                baudrate=self.cfg.baudrate, 
                address=self.cfg.address
            )
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

            raw_value = float(data)
            
            # 🚀 FIX: Logische Skalierung basierend auf der YAML
            if self.cfg.scale_mode == "engineering":
                # Sensor liefert bereits echte ml/min oder l/h Werte
                flow_ml_min = raw_value
            else:
                # Sensor liefert Rohwerte (0-32000). Outlier-Filter nutzen.
                if abs(raw_value) > self.cfg.full_scale_raw * 1.5:
                    return self._last_good_flow # Keinen 0.0 Drop erzeugen!
                
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
        logger.info("FlowSensor: disconnected")
        self.flow_sensor = None