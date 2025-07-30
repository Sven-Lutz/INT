import logging

from hardware.drivers.valves import Valve
from hardware.drivers.dummy_devices.dummy_pressure_controller import PressureController
from hardware.drivers.dummy_devices.dummy_flow_sensor import FlowSensor
from hardware.drivers.dummy_devices.dummy_vacuum_pump import VacuumPump
from hardware.drivers.container_selector import ContainerSelector

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
        #self.flow_snsr = FlowSensor(cfg)
        self.flow_snsr = FlowSensor(self.pressure_ctrl)                 # this is only for the dummy device

        cfg = ConfigManager().load_config("vacuum_pump")
        self.pump = VacuumPump(cfg)

        cfg = ConfigManager().load_config("container_selector")
        self.container_selector = ContainerSelector(cfg)

        self.safe_state()
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
        self.shut_container()
        self.pressure_ctrl.set_pressure(0)
        self.pump.stop()
        self.valve.vent_pos()
        self.container_selector.select_container("Drain")

        hardware_signals.pump_changed.emit(False)
        self._update_signals()
        logger.info("System is now in a safe state")
        return

    def set_pressure(self, p):
        self.pressure_ctrl.set_pressure(p)
        return

    def get_pressure(self):
        logger.debug(self.pressure_ctrl.get_pressure())
        return self.pressure_ctrl.get_pressure()

    def get_flow(self):
        return self.flow_snsr.get_flow()

    def start_pump(self):
        hardware_signals.pump_changed.emit(True)
        self.pump.start()
        return

    def stop_pump(self):
        hardware_signals.pump_changed.emit(False)
        self.pump.stop()
        return

    def select_container(self, container_name):
        logger.info("Container Selected")
        self.container_selector.select_container(container_name)
        return

    def _update_signals(self):
        hardware_signals.liquid_valve_changed.emit(self.valve.state["Liquid"])  # send a snapshot
        hardware_signals.container_valve_changed.emit(self.valve.state["Container"])  # send a snapshot
        hardware_signals.venting_valve_changed.emit(not self.valve.state["Venting"])  # send a snapshot


        ConfigManager().update_config("valves","Valves.Liquid.State", self.valve.state["Liquid"])
        ConfigManager().update_config("valves", "Valves.Container.State", self.valve.state["Container"])
        ConfigManager().update_config("valves", "Valves.Venting.State", not self.valve.state["Venting"])
        return

