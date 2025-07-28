import logging

from hardware.drivers.dummy_devices.dummy_valves import Valve
from hardware.drivers.pressure_controller import PressureController

from core.signals import hardware_signals

from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

class DeviceManager:
    def __init__(self):
        cfg = ConfigManager().load_config("valves")
        self.valve = Valve(cfg)

        cfg = ConfigManager.load_config("pressure_controller")
        print(cfg)
        #self.pressure_ctl = PressureController(cfg)
        #self.pump = PumpController(config["pump"])
        return

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown_all()
        return

    def shutdown_all(self):
        logger.warning("Shutting down all devices")
        self.valve.shutdown()
        #self.pump.shutdown()
        # other shutdowns...
        return

    def venting(self):
        self.valve.vent_pos()
        self._update_signals()
        return

    def filling(self):
        self.valve.push_pos()
        self._update_signals()
        return

    def removing(self):
        self.valve.suck_pos()
        self._update_signals()
        return

    def shut_container(self):
        self.valve.block_pos()
        self._update_signals()
        return

    def open_container(self):
        self.valve.open_pos()
        self._update_signals()
        return

    def safe_state(self):
        self.valve.vent_pos()
        self._update_signals()

    def _update_signals(self):
        hardware_signals.liquid_valve_changed.emit(self.valve.state["Liquid"])  # send a snapshot
        hardware_signals.container_valve_changed.emit(self.valve.state["Container"])  # send a snapshot
        hardware_signals.venting_valve_changed.emit(not self.valve.state["Venting"])  # send a snapshot

