# src/hardware/drivers/valves.py
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

# 🚀 Wir importieren DEINEN robusten Rly02 Treiber!
from src.hardware.drivers.rly02 import Rly02, Rly02Config

logger = logging.getLogger(__name__)

class ValveMode(str, Enum):
    FILTRATION = "FILTRATION"
    FILLING = "FILLING"
    VENTING = "VENTING"
    BACKWASH = "BACKWASH"
    ALL_SHUT = "ALL_SHUT"
    ALL_OPEN = "ALL_OPEN"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class ValveControllerConfig:
    relay: Rly02Config = Rly02Config(port="COM6", baudrate=9600)
    safe_state_on_disconnect: ValveMode = ValveMode.VENTING

    # 🚀 INVERTIERTE LOGIK FÜR PHYSISCHE SCHLÄUCHE
    filtration_r1_on: bool = False
    filtration_r2_on: bool = True
    
    filling_r1_on: bool = True
    filling_r2_on: bool = False
    
    venting_r1_on: bool = True
    venting_r2_on: bool = False

    backwash_r1_on: bool = True
    backwash_r2_on: bool = True

    settle_delay_s: float = 0.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ValveControllerConfig":
        cfg_src = d.get("valves", d)
        
        # Mapping der COM-Port Namen aus der yaml für den Rly02Config
        port = cfg_src.get("port", cfg_src.get("COM Port", "COM6"))
        baud = int(cfg_src.get("baudrate", cfg_src.get("Baud Rate", 9600)))
        
        relay_cfg = Rly02Config(port=str(port).strip(), baudrate=baud)
        
        safe_mode_str = str(cfg_src.get("safe_state_on_disconnect", cfg_src.get("safe_state", "VENTING"))).upper()
        safe_mode = ValveMode.__members__.get(safe_mode_str, ValveMode.VENTING)

        return ValveControllerConfig(
            relay=relay_cfg,
            safe_state_on_disconnect=safe_mode,
            filtration_r1_on=bool(cfg_src.get("filtration_r1_on", False)),
            filtration_r2_on=bool(cfg_src.get("filtration_r2_on", True)),
            filling_r1_on=bool(cfg_src.get("filling_r1_on", True)),
            filling_r2_on=bool(cfg_src.get("filling_r2_on", False)),
            venting_r1_on=bool(cfg_src.get("venting_r1_on", True)),
            venting_r2_on=bool(cfg_src.get("venting_r2_on", False)),
            backwash_r1_on=bool(cfg_src.get("backwash_r1_on", True)),
            backwash_r2_on=bool(cfg_src.get("backwash_r2_on", True)),
            settle_delay_s=float(cfg_src.get("settle_delay_s", 0.0)),
        )

class ValveController:
    """
    Abstrakte Controller-Klasse, die Schlauch-Zustände (Filtration, Venting)
    in physische Relais-Befehle via Rly02 Treiber übersetzt.
    """
    def __init__(self, config: Dict[str, Any]):
        self.cfg = ValveControllerConfig.from_dict(config)
        # 🚀 Wir nutzen die echte, thread-sichere Hardware-Klasse
        self.relais = Rly02(self.cfg.relay)
        
        self._state: ValveMode = ValveMode.UNKNOWN
        self._r1_on: Optional[bool] = None
        self._r2_on: Optional[bool] = None

    def connect(self) -> None:
        logger.info("ValveController: connecting via Rly02 (port=%s)", self.cfg.relay.port)
        self.relais.connect()

    def _apply_relay(self, r_num: int, target_on: bool, current_on: Optional[bool]) -> Optional[bool]:
        """Hilfsfunktion, um redundante Befehle an die Hardware zu vermeiden."""
        if current_on == target_on: 
            return current_on
            
        if target_on: 
            self.relais.relay_on(r_num)
        else: 
            self.relais.relay_off(r_num)
            
        return target_on

    def _set_relays(self, *, r1_on: bool, r2_on: bool, state: ValveMode) -> None:
        if self._state == state: return
        logger.debug("ValveController: set state=%s (R1=%s, R2=%s)", state.value, r1_on, r2_on)
        
        self._r1_on = self._apply_relay(1, r1_on, self._r1_on)
        self._r2_on = self._apply_relay(2, r2_on, self._r2_on)
        
        if self.cfg.settle_delay_s > 0: 
            time.sleep(self.cfg.settle_delay_s)
            
        self._state = state

    def get_state(self) -> str: 
        return self._state.value
        
    def filtration(self) -> None: 
        self._set_relays(r1_on=self.cfg.filtration_r1_on, r2_on=self.cfg.filtration_r2_on, state=ValveMode.FILTRATION)
        
    def filling_solution(self) -> None: 
        self._set_relays(r1_on=self.cfg.filling_r1_on, r2_on=self.cfg.filling_r2_on, state=ValveMode.FILLING)
        
    def venting(self) -> None: 
        self._set_relays(r1_on=self.cfg.venting_r1_on, r2_on=self.cfg.venting_r2_on, state=ValveMode.VENTING)
        
    def backwash(self) -> None: 
        self._set_relays(r1_on=self.cfg.backwash_r1_on, r2_on=self.cfg.backwash_r2_on, state=ValveMode.BACKWASH)
        
    def all_shut(self) -> None: 
        self._set_relays(r1_on=False, r2_on=False, state=ValveMode.ALL_SHUT)
        
    def all_open(self) -> None: 
        self._set_relays(r1_on=True, r2_on=True, state=ValveMode.ALL_OPEN)

    def set_state(self, state: str | ValveMode) -> None:
        if isinstance(state, ValveMode): 
            mode = state
        else: 
            mode = ValveMode.__members__.get(str(state).strip().upper(), ValveMode.UNKNOWN)
            
        if mode == ValveMode.FILTRATION: self.filtration()
        elif mode == ValveMode.FILLING: self.filling_solution()
        elif mode == ValveMode.VENTING: self.venting()
        elif mode == ValveMode.BACKWASH: self.backwash()
        elif mode == ValveMode.ALL_SHUT: self.all_shut()
        elif mode == ValveMode.ALL_OPEN: self.all_open()

    def disconnect(self) -> None:
        try:
            # Fahre in den sicheren Zustand vor dem Trennen
            self.set_state(self.cfg.safe_state_on_disconnect)
        except Exception as e: 
            logger.warning(f"Could not apply safe state on disconnect: {e}")
        finally:
            try: 
                self.relais.close()
            except Exception: 
                pass
            self._r1_on = self._r2_on = None
            self._state = ValveMode.UNKNOWN

    def close(self) -> None: 
        self.disconnect()
        
    def __enter__(self) -> "ValveController": 
        self.connect()
        return self
        
    def __exit__(self, exc_type, exc, tb) -> None: 
        self.close()