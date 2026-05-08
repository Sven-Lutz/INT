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
    
    proc_nr: int = 33
    parm_nr: int = 0
    parm_type: int = 117  
    
    scale_mode: str = "engineering"
    full_scale_raw: float = 32767.0
    full_scale_ml_min: float = 150.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        logger.info(f"FlowSensorConfig.from_dict received: {d}")
        if "flow" in d and isinstance(d["flow"], dict): 
            d = d["flow"]
            
        port = d.get("port", d.get("COM Port", "COM5"))
        baudrate = int(d.get("baudrate", 38400))
        address = int(d.get("address", 3)) 
        
        meas = d.get("meas", [33, 0])
        proc_nr = int(meas[0])
        parm_nr = int(meas[1])
        
        parm_type = 117 if proc_nr == 33 else 114
        
        scale_mode = str(d.get("scale_mode", "engineering")).strip().lower()
        fs_raw = float(d.get("full_scale_raw", 32000.0))
        fs_ml = float(d.get("full_scale_ml_min", 20.0)) 
        
        return FlowSensorConfig(
            port=port, baudrate=baudrate, address=address,
            proc_nr=proc_nr, parm_nr=parm_nr, parm_type=parm_type,
            scale_mode=scale_mode, full_scale_raw=fs_raw, full_scale_ml_min=fs_ml
        )

# ... (Imports und FlowSensorConfig bleiben identisch)

class FlowSensor:
    """
    Treiber für Bronkhorst ES-FLOW / ProPar basierte Sensoren mit Auto-Fallback.
    """
    def __init__(self, cfg: FlowSensorConfig | Dict[str, Any]):
        if isinstance(cfg, dict): 
            self.cfg = FlowSensorConfig.from_dict(cfg)
        else: 
            self.cfg = cfg
            
        self.flow_sensor: Any = None
        
        # Wir speichern jetzt nur noch die ID des erfolgreichen Parameters
        # ID 205 = fMeasure (Float, Engineering Units)
        # ID 8 = Measure (Int, Raw 0-32000)
        self._cached_parameter_id: int = 0 
        
        self._last_good_flow: float = 0.0
        self._error_count: int = 0

    @staticmethod
    def _make_instrument(port: str, baudrate: int, address: int) -> Any:
        # propar 1.x exposes propar.instrument() directly
        if hasattr(propar, "instrument"):
            return propar.instrument(port, baudrate=baudrate, address=address)
        # propar 0.x uses a master/node pattern
        if hasattr(propar, "master"):
            master = propar.master(port, baudrate=baudrate)
            nodes = master.get_nodes()
            for node in nodes:
                if getattr(node, "address", None) == address:
                    return node
            if nodes:
                return nodes[0]
        raise RuntimeError(
            f"Unsupported propar API (version installed: {getattr(propar, '__version__', 'unknown')}). "
            "Expected 'propar.instrument' (v1.x) or 'propar.master' (v0.x)."
        )

    def connect(self) -> None:
        if self.flow_sensor is not None: return
        logger.info(f"FlowSensor: connecting to {self.cfg.port} (Baud: {self.cfg.baudrate}, Node: {self.cfg.address})")

        try:
            self.flow_sensor = self._make_instrument(
                self.cfg.port,
                self.cfg.baudrate,
                self.cfg.address,
            )

            # Hardware-Ping
            logger.info("FlowSensor DEBUG: Sende Hardware-Ping...")
            user_tag = self.flow_sensor.readParameter(115) # 115 ist oft der User Tag
            
            if user_tag is None:
                logger.error(f"FlowSensor: Keine Antwort auf Adresse {self.cfg.address}.")
                self.flow_sensor = None
                return

            logger.info(f"FlowSensor: Hardware-Ping erfolgreich! Gerät meldet sich als: '{user_tag}'")
                    
            # TEST 1: High-Level API für Float (Engineering Units) -> Parameter ID 205
            val_float = self.flow_sensor.readParameter(205)
            if val_float is not None:
                logger.info("FlowSensor: fMeasure (ID 205) erfolgreich! Nutze Engineering Units.")
                self._cached_parameter_id = 205
                object.__setattr__(self.cfg, 'scale_mode', 'engineering')
            else:
                logger.warning("FlowSensor: fMeasure (ID 205) nicht verfügbar.")
                
                # TEST 2: High-Level API für Raw Data (0-32000/32767) -> Parameter ID 8
                val_raw = self.flow_sensor.readParameter(8)
                if val_raw is not None:
                    logger.info("FlowSensor: Measure (ID 8) erfolgreich! Nutze Raw-Skalierung.")
                    self._cached_parameter_id = 8
                    object.__setattr__(self.cfg, 'scale_mode', 'raw')
                else:
                    raise ConnectionError("Alle Lese-Versuche (ID 205 & ID 8) gescheitert.")

            logger.info("FlowSensor: communication successfully started AND verified")
            self._error_count = 0
            self._last_good_flow = 0.0
            
        except Exception as e:
            logger.error(f"FlowSensor: connection failed on {self.cfg.port} -> {e}")
            self.flow_sensor = None

    def get_flow(self) -> float:
        if self.flow_sensor is None or self._cached_parameter_id == 0: 
            return 0.0

        try:
            # Wir lesen direkt den verifizierten Parameter aus
            data = self.flow_sensor.readParameter(self._cached_parameter_id)
            
            if data is None: 
                return self._last_good_flow

            raw_value = float(data)
            
            # Verarbeite Rohwerte (ID 8) oder Engineering Floats (ID 205)
            if self.cfg.scale_mode == "engineering":
                flow_ml_min = raw_value
            else:
                # Absicherung gegen Daten-Müll (größer als 150% des Messbereichs)
                if abs(raw_value) > self.cfg.full_scale_raw * 1.5:
                    return self._last_good_flow 
                # Umrechnung von z.B. 0-32767 auf 0-150 ml/min
                flow_ml_min = (raw_value / self.cfg.full_scale_raw) * self.cfg.full_scale_ml_min

            self._error_count = 0
            self._last_good_flow = flow_ml_min
            return flow_ml_min

        except Exception as e:
            self._error_count += 1
            logger.warning(f"FlowSensor: read error -> {e} (failures: {self._error_count})")
            return self._last_good_flow

    def close(self) -> None:
        if self.flow_sensor is None: return
        logger.info("FlowSensor: disconnected")
        self.flow_sensor = None