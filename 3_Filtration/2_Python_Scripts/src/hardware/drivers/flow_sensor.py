# src/hardware/drivers/flow_sensor.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict

import propar

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class FlowSensorConfig:
    """Konfiguration, die exakt zu deiner alten YAML-Struktur passt."""
    port: str = "COM5"
    
    # Das sind exakt die Werte aus deiner alten flow_sensor_default.yaml
    proc_nr: int = 33
    parm_nr: int = 6
    parm_type: int = 65

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        # Manchmal ist alles verschachtelt
        if "flow" in d and isinstance(d["flow"], dict):
            d = d["flow"]
            
        port = d.get("COM Port", d.get("port", "COM5"))
        
        # Hole die Commands aus dem alten Layout, falls vorhanden
        cmds = d.get("Commands", {})
        vol_flow = cmds.get("Volume Flow", {})
        
        proc = vol_flow.get("proc_nr", d.get("proc_nr", 33))
        parm = vol_flow.get("parm_nr", d.get("parm_nr", 6))
        ptype = vol_flow.get("parm_type", d.get("parm_type", 65))
        
        return FlowSensorConfig(port=port, proc_nr=proc, parm_nr=parm, parm_type=ptype)


class FlowSensor:
    """
    Elite FlowSensor: Nutzt exakt die funktionierende Logik deines alten Codes, 
    liefert aber saubere Typen für das neue PelliKAn OS.
    """
    def __init__(self, cfg: FlowSensorConfig | Dict[str, Any]):
        if isinstance(cfg, dict):
            self.cfg = FlowSensorConfig.from_dict(cfg)
        else:
            self.cfg = cfg
            
        # 🚀 KORREKTUR: 'Any' statt 'Optional[object]', damit Pylance aufhört zu meckern!
        self.flow_sensor: Any = None
        self.Instr_ID: Any = None

    def connect(self) -> None:
        """Stellt die Verbindung exakt wie in deinem alten Code her."""
        if self.flow_sensor is not None:
            return

        logger.info(f"FlowSensor: connecting to {self.cfg.port}")
        
        try:
            # WICHTIG: Keine Baudrate/Address erzwingen, lass propar das machen!
            self.flow_sensor = propar.instrument(self.cfg.port)
            self.Instr_ID = self.flow_sensor.id
            logger.info(f"FlowSensor: communication successfully started (ID: {self.Instr_ID})")
        except Exception as e:
            logger.error(f"FlowSensor: connection failed -> {e}")
            self.flow_sensor = None
            raise

    def get_flow(self) -> float:
        """
        Liest den Flow exakt wie dein alter Code, extrahiert aber 
        direkt einen Float (statt der 'pint' Einheit ml/min).
        """
        if self.flow_sensor is None:
            raise RuntimeError("FlowSensor not connected.")

        # Exakt dein altes Dictionary Format!
        param_info = {
            "proc_nr": self.cfg.proc_nr,
            "parm_nr": self.cfg.parm_nr,
            "parm_type": self.cfg.parm_type
        }

        try:
            # Exakt dein alter Call!
            values = self.flow_sensor.read_parameters([param_info])
            
            # Fehlerbehandlung, falls propar Quatsch zurückgibt
            if not values or not isinstance(values, list) or len(values) == 0:
                logger.warning("FlowSensor: Empty response from propar")
                return 0.0

            data = values[0].get("data")
            if data is None:
                logger.warning(f"FlowSensor: No data in response: {values[0]}")
                return 0.0
            
            return float(data)

        except Exception as e:
            logger.warning(f"FlowSensor: read error -> {e}")
            # Um das UI nicht abstürzen zu lassen, geben wir im Fehlerfall 0.0 zurück
            return 0.0

    def close(self) -> None:
        """Schließt die Verbindung, falls der Treiber das anbietet."""
        if self.flow_sensor is None:
            return
        logger.info("FlowSensor: disconnecting")
        try:
            if hasattr(self.flow_sensor, "close"):
                self.flow_sensor.close()
        except Exception as e:
            logger.warning(f"FlowSensor: error during disconnect -> {e}")
        finally:
            self.flow_sensor = None