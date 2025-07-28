import logging

from simple_pid import PID
from PySide6.QtCore import QObject, QTimer, Signal

from core.signals import data_signals, operation_signals
from utils.config_manager import ConfigManager
logger = logging.getLogger(__name__)

class PIDFlowController(QObject):
    """
        PID controller to maintain flow by adjusting pressure.
        Terminates automatically when target volume is reached.
        """

    def __init__(self, device_manager, target_volume, direction):
        """
        :param setpoint: Desired flow rate in mL/s
        :param target_volume: Total volume to deliver in mL
        :param direction: "positive" or "negative" flow
        :param interval: Time between PID updates in ms
        """
        super().__init__()
        cfg_general = ConfigManager().load_config("general")
        cfg_pressure = ConfigManager().load_config("pressure_controller")
        self.device_manager = device_manager
        self.target_volume = target_volume
        self.container_vol = cfg_general.get("Container Volume")
        self.direction = direction
        self.interval = 100

        self._volume = 0.0
        self._previous_flow = 0.0

        self._paused = False

        # PID Controller
        self.pid = PID(Kp=cfg_general.get("P Term"), Ki=cfg_general.get("I Term"), Kd=cfg_general.get("D Term"), setpoint=cfg_general.get("Default Flow"))
        self.pid.output_limits = (cfg_pressure.get("Pressure Limits")[0], cfg_pressure.get("Pressure Limits")[1])                                  # Output is pressure in mbar

        # Timer for control loop
        self.timer = QTimer()
        self.timer.setInterval(int(self.interval))
        self.timer.timeout.connect(self._update)
        return

    def start(self):
        logger.info("PIDFlowController started")
        self._volume = 0.0
        self._paused = False

        if self.direction == "positive":
            self.device_manager.filling()
        else:
            self.device_manager.removing()

        self.timer.start()
        return

    def pause(self):
        if not self._paused:
            logger.info("PIDFlowController paused")
            self._paused = True
            self.timer.stop()
            self.device_manager.set_pressure(0)
            self.device_manager.shut_container()
        return

    def resume(self):
        if self._paused:
            logger.info("PIDFlowController resumed")
            self._paused = False
            self.device_manager.open_container()
            self.timer.start()
        return

    def stop(self):
        logger.info("PIDFlowController stopped")
        self.timer.stop()
        self.device_manager.set_pressure(0)
        operation_signals.operation_done.emit()
        return

    def _update(self):
        if self._paused:
            return
        flow = self.device_manager.get_flow()  # uL/min
        delta_f = flow-self._previous_flow
        self._volume += (flow + 0.5 * delta_f) * self.interval * 0.001 / 60  # This is the numerical integration of the volume, it uses rectangles and triangles. The volume has to be adjusted for µL/min

        pressure_output = self.pid(flow)
        self.device_manager.set_pressure(pressure_output)

        data_signals.flow_updated.emit(flow)
        data_signals.pressure_updated.emit(pressure_output)
        data_signals.volume_updated.emit(self.target_volume - self._volume)
        data_signals.container_volume_updated.emit(self.container_vol + self._volume)

        logger.debug(f"[PID] Flow: {flow:.2f} uL/min | Pressure: {pressure_output:.1f} mbar | Volume: {self._volume:.2f} uL")

        if self._volume >= self.target_volume:
            logger.info(f"Target volume of {self.target_volume:.2f} mL reached")
            self.stop()
        self.previous_flow = flow
        return
