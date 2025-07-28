import logging

from hardware.drivers.valves import Valve
from hardware.drivers.pressure_controller import PressureController
from hardware.drivers.flow_sensor import FlowSensor

from core.signals import hardware_signals

from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

class DeviceManager:
    def __init__(self):
        cfg = ConfigManager().load_config("valves")
        self.valve = Valve(cfg)

        cfg = ConfigManager().load_config("pressure_controller")
        self.pressure_ctrl = PressureController(cfg)

        cfg = ConfigManager().load_config("flow_sensor")
        self.flow_sns = FlowSensor(cfg)
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
        self.pressure_ctrl.set_pressure(0)
        self._update_signals()
        return

    def set_pressure(self,p):
        self.pressure_ctrl.set_pressure(p)
        return

    def get_pressure(self):
        return self.pressure_ctrl.get_pressure()

    def get_flow(self):
        return self.flow_sns.get_flow()

    def _update_signals(self):
        hardware_signals.liquid_valve_changed.emit(self.valve.state["Liquid"])  # send a snapshot
        hardware_signals.container_valve_changed.emit(self.valve.state["Container"])  # send a snapshot
        hardware_signals.venting_valve_changed.emit(not self.valve.state["Venting"])  # send a snapshot

