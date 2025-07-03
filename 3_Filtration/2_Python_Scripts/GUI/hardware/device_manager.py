from hardware.drivers.pressure_controller import PressureController
from hardware.drivers.flow_sensor import FlowSensor
from hardware.drivers.valves import ValveController

from utils.config_manager import ConfigManager

class DeviceManager:
    def __init__(self):
        cfg_mgr = ConfigManager()
        valve_config = cfg_mgr.load_config("valves")
        pressure_config = cfg_mgr.load_config("pressure_controller")

        #self.pressure_controller = PressureController(pressure_config)
        #self.flow_sensor = FlowSensor()
        self.valve_controller = ValveController(valve_config)

    def set_pressure(self, pressure, channel):
        self.pressure_controller.set_pressure(pressure, channel)
        return

    def get_pressure(self, channel):
        self.pressure_controller.get_pressure(channel)
        return
    #def read_flow(self):
        #return self.flow_sensor.read_flow()

    def valves_filtration(self):
        self.valve_controller.filtration()
        return

    def valves_filling_solution(self):
        self.valve_controller.filling_solution()
        return

    def venting(self):
        self.valve_controller.venting()
        return

    def all_valves_shut(self):
        self.valve_controller.all_shut()
        return

    def all_valves_open(self):
        self.valve_controller.all_open()
        return

    def disconnect_valves(self):
        self.valve_controller.venting()
        return

