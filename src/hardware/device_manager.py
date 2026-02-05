from datetime import datetime
from typing import Optional

from hardware.drivers.pressure_controller import PressureController
from hardware.drivers.flow_sensor import FlowSensor
from hardware.drivers.valves import ValveController
from utils.config_manager import ConfigManager


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


class DeviceManager:

    def __init__(self, enable_pressure: bool = False, enable_flow: bool = True):
        _log("DeviceManager: initializing...")

        cfg_mgr = ConfigManager()

        try:
            valve_config = cfg_mgr.load_config("valves")
            _log("DeviceManager: valve config loaded")
        except Exception as e:
            _log(f"ERROR: DeviceManager: failed to load valves config: {e}")
            raise

        pressure_config = None
        try:
            pressure_config = cfg_mgr.load_config("pressure_controller")
            _log("DeviceManager: pressure controller config loaded")
        except Exception as e:
            _log(f"WARNING: DeviceManager: failed to load pressure config: {e}")

        flow_config = None
        try:
            flow_config = cfg_mgr.load_config("flow_sensor")  # optional
            _log("DeviceManager: flow sensor config loaded")
        except Exception as e:
            _log(f"WARNING: DeviceManager: failed to load flow_sensor config: {e}")

        self.valve_controller: ValveController = ValveController(valve_config)
        _log("DeviceManager: ValveController initialized")

        self.pressure_controller: Optional[PressureController] = None
        if enable_pressure:
            if pressure_config is None:
                raise RuntimeError("enable_pressure=True but pressure_controller config is missing.")
            _log("DeviceManager: initializing PressureController...")
            self.pressure_controller = PressureController(pressure_config)
            _log("DeviceManager: PressureController initialized")
        else:
            _log("DeviceManager: PressureController disabled")

        self.flow_sensor: Optional[FlowSensor] = None
        if enable_flow:
            port = "COM5"
            if isinstance(flow_config, dict):
                port = flow_config.get("port", port)

            _log(f"DeviceManager: initializing FlowSensor on {port}...")
            self.flow_sensor = FlowSensor(port=port)
            self.flow_sensor.connect()
            _log("DeviceManager: FlowSensor connected")
        else:
            _log("DeviceManager: FlowSensor disabled")

        _log("DeviceManager: initialization complete")

    def set_pressure(self, pressure, channel) -> None:
        if self.pressure_controller is None:
            raise RuntimeError("PressureController is not enabled/initialized.")
        self.pressure_controller.set_pressure(pressure, channel)

    def get_pressure(self, channel):
        if self.pressure_controller is None:
            raise RuntimeError("PressureController is not enabled/initialized.")
        return self.pressure_controller.get_pressure(channel)

    def read_flow(self) -> float:
        if self.flow_sensor is None:
            raise RuntimeError("FlowSensor is not enabled/initialized.")
        return self.flow_sensor.read_flow()

    def valves_filtration(self) -> None:
        self.valve_controller.filtration()

    def valves_filling_solution(self) -> None:
        self.valve_controller.filling_solution()

    def venting(self) -> None:
        self.valve_controller.venting()

    def all_valves_shut(self) -> None:
        self.valve_controller.all_shut()

    def all_valves_open(self) -> None:
        self.valve_controller.all_open()

    def disconnect(self) -> None:
        _log("DeviceManager: disconnect requested")

        try:
            self.valve_controller.all_shut()
            _log("DeviceManager: valves set to ALL_SHUT")
        except Exception as e:
            _log(f"WARNING: DeviceManager: failed to shut valves: {e}")

        if self.flow_sensor is not None:
            try:
                self.flow_sensor.close()
                _log("DeviceManager: FlowSensor closed")
            except Exception as e:
                _log(f"WARNING: DeviceManager: error while closing FlowSensor: {e}")
            finally:
                self.flow_sensor = None

        if self.pressure_controller is not None:
            try:
                if hasattr(self.pressure_controller, "close"):
                    self.pressure_controller.close()
                    _log("DeviceManager: PressureController closed")
            except Exception as e:
                _log(f"WARNING: DeviceManager: error while closing PressureController: {e}")
            finally:
                self.pressure_controller = None

        _log("DeviceManager: disconnect complete")

