from .drivers.pressure_controller import PressureController
from .drivers.flow_sensor import FlowSensor
from .drivers.valves import ValveController

class DeviceManager:
    def __init__(self, config):
        self.pressure_controller = PressureController()
        self.flow_sensor = FlowSensor(config["flow_port"])
        self.valve_controller = ValveController(config["valve_port"])

    def set_pressure(self, value):
        self.pressure_controller.set_pressure(value)

    def read_flow(self):
        return self.flow_sensor.read_flow()

    def open_valve(self, valve_id):
        self.valve_controller.open_valve(valve_id)

    def close_valve(self, valve_id):
        self.valve_controller.close_valve(valve_id)

