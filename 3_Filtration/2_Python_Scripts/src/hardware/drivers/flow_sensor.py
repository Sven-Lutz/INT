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
    ist aber optimiert für High-Frequency Polling ohne Memory Leaks und Log-Spam.
    """
    def __init__(self, cfg: FlowSensorConfig | Dict[str, Any]):
        if isinstance(cfg, dict):
            self.cfg = FlowSensorConfig.from_dict(cfg)
        else:
            self.cfg = cfg
            
        self.flow_sensor: Any = None
        self.Instr_ID: Any = None
        
        # 🚀 ELITE TWEAK 1: Pre-compiled Request (Verhindert Memory Allocation im Loop)
        self._cached_request = [{
            "proc_nr": self.cfg.proc_nr,
            "parm_nr": self.cfg.parm_nr,
            "parm_type": self.cfg.parm_type
        }]
        
        # 🚀 ELITE TWEAK 2: State Tracking für Anti-Jitter und Log-Drosselung
        self._last_good_flow: float = 0.0
        self._error_count: int = 0

    def connect(self) -> None:
        """Stellt die serielle Verbindung zum Bronkhorst-Sensor her."""
        if self.flow_sensor is not None:
            return

        logger.info(f"FlowSensor: connecting to {self.cfg.port}")
        
        try:
            # WICHTIG: Keine Baudrate/Address erzwingen, lass propar das automatisch aushandeln
            self.flow_sensor = propar.instrument(self.cfg.port)
            self.Instr_ID = self.flow_sensor.id
            logger.info(f"FlowSensor: communication successfully started (ID: {self.Instr_ID})")
            
            # Reset Error State bei erfolgreichem Connect
            self._error_count = 0
            self._last_good_flow = 0.0
        except Exception as e:
            logger.error(f"FlowSensor: connection failed -> {e}")
            self.flow_sensor = None
            raise

    def get_flow(self) -> float:
        """
        Liest den Flow. Nutzt Fallbacks und Fehlerdrosselung, um das UI
        niemals abstürzen zu lassen oder Spikes in Graphen zu erzeugen.
        """
        if self.flow_sensor is None:
            # Fallback, wenn Disconnect aufgerufen wurde, aber Polling noch läuft
            return 0.0

        try:
            # Exakt dein alter Call, aber extrem performant mit pre-compiled List
            values = self.flow_sensor.read_parameters(self._cached_request)
            
            # Strikte Gültigkeitsprüfung
            if not values or not isinstance(values, list) or len(values) == 0:
                raise ValueError("Empty response from propar")

            data = values[0].get("data")
            if data is None:
                raise ValueError(f"No data in response: {values[0]}")
            
            # Versuche sauberen Float-Cast (Sicherheitshalber)
            current_flow = float(data)
            
            # Wenn wir hier sind, war der Read 100% erfolgreich
            if self._error_count > 0:
                logger.info("FlowSensor: Connection recovered.")
                self._error_count = 0
                
            self._last_good_flow = current_flow
            return current_flow

        except Exception as e:
            self._error_count += 1
            
            # 🚀 ELITE TWEAK 3: Log Spam Throttling. Loggt nur den 1., 10., 50., 100. Fehler
            if self._error_count in (1, 10) or self._error_count % 50 == 0:
                logger.warning(f"FlowSensor: read error -> {e} (Consecutive failures: {self._error_count})")
            
            # 🚀 ELITE TWEAK 4: Signal Smoothing. Wir geben den letzten guten Wert zurück.
            # Wenn der Sensor nur einen kurzen USB-Hänger hat, zuckt der Graph dadurch nicht auf 0 runter!
            # Wenn der Sensor dauerhaft weg ist, wird er langfristig die Konstante zeichnen.
            return self._last_good_flow

    def close(self) -> None:
        """Schließt die Verbindung sicher."""
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
            self.Instr_ID = None