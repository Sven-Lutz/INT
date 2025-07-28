from simple_pid import PID
from PySide6.QtCore import QObject, QTimer, Signal
import logging

logger = logging.getLogger(__name__)

class PIDFlowController(QObject):
    """
        PID controller to maintain flow by adjusting pressure.
        Terminates automatically when target volume is reached.
        """
    finished = Signal()

    def __init__(self, device_manager, setpoint, target_volume, direction, interval=100):
        """
        :param device_manager: Interface for hardware control
        :param setpoint: Desired flow rate in mL/s
        :param target_volume: Total volume to deliver in mL
        :param direction: "positive" or "negative" flow
        :param interval: Time between PID updates in ms
        """
        super().__init__()
        self.device_manager = device_manager
        self.setpoint = setpoint
        self.target_volume = target_volume
        self.direction = direction
        self.interval = interval

        self._volume = 0.0
        self._previous_flow = 0.0

        self._paused = False

        # PID Controller
        self.pid = PID(Kp=1.0, Ki=0.1, Kd=0.05, setpoint=self.setpoint)
        self.pid.output_limits = (0, 5000)                                  # Output is pressure in mbar

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
        self.finished.emit()
        return

    def _update(self):
        if self._paused:
            return
        flow = self.device_manager.get_flow()  # uL/min
        delta_f = flow-self._previous_flow
        self._volume += (flow + 0.5 * delta_f) * self.interval * 1000 / 60  # This is the numerical integration of the volume, it uses rectangles and triangles. The volume has to be adjusted for µL/min

        pressure_output = self.pid(flow)
        self.device_manager.set_pressure(pressure_output)

        logger.debug(f"[PID] Flow: {flow:.2f} uL/min | Pressure: {pressure_output:.1f} mbar | Volume: {self._volume:.2f} uL")

        if self._volume >= self.target_volume:
            logger.info(f"Target volume of {self.target_volume:.2f} mL reached")
            self.stop()
        self.previous_flow = flow
        return
