import logging
import time

from PySide6.QtCore import QObject, Signal, QTimer

from operations.dummy_operations.dummy_run import DummyOperation
from core.pid_controller import PIDFlowController

logger = logging.getLogger(__name__)                            # Create a logger for this module

class BaseOperation(QObject):
    finished = Signal()


    def __init__(self, device_manager, setpoint=None, target_volume=None, direction=""):
        super().__init__()
        self.device_manager = device_manager

        self._init_pid(setpoint,target_volume,direction)

        self._should_pause = False

        #self.dummy = DummyOperation()
        #self.dummy.finished.connect(self._done)

        return

    def _init_pid(self, setpoint=None, target_volume=None, direction=""):

        self.pid_ctrl = None

        if setpoint is not None and target_volume is not None and direction != "":
            self.pid_controller = PIDFlowController(device_manager=self.device_manager, setpoint=setpoint, target_volume=target_volume, direction=direction)
            self.pid_controller.finished.connect(self._done)
        return

    def start(self):
        if self.pid_controller:
            self.pid_controller.start()
        else:
            logger.warning("No PID controller configured")
        return

    def pause(self):
        self._should_pause = True
        if self.pid_controller:
            self.pid_controller.pause()
        self.device_manager.shut_container()
        return

    def resume(self):
        self._should_pause = False
        if self.pid_controller:
            self.pid_controller.resume()
        self.device_manager.open_container()
        return

    def stop(self):
        if self.pid_controller:
            self.pid_controller.stop()
        self.device_manager.safe_state()
        self.finished.emit()
        return

    def _done(self):
        self.device_manager.safe_state()
        self.finished.emit()
        return

class AddOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager, setpoint=3000.0, target_volume=1000.0, direction="positive")

class RemoveOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

    def start(self):
        logger.info("RemoveOperation started")
        super().start()
        self.device_manager.removing()
        return

    def stop(self):
        super().stop()
        logger.info("RemoveOperation stopped")


    def _done(self):
        super()._done()
        logger.info("RemoveOperation finished")


class FillOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

    def start(self):
        logger.info("FillOperation started")
        super().start()
        self.device_manager.filling()


    def stop(self):
        super().stop()
        logger.info("FillOperation stopped")


    def _done(self):
        super()._done()
        logger.info("FillOperation finished")


class EmptyOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

    def start(self):
        self.device_manager.removing()
        super().start()
        logger.info("EmptyOperation started")


    def stop(self):
        super().stop()
        logger.info("EmptyOperation stopped")


    def _done(self):
        super()._done()
        logger.info("EmptyOperation finished")


class AutomaticOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

    def start(self):
        self.device_manager.filling()
        super().start()
        logger.info("AutomaticOperation started")
        return

    def stop(self):
        super().stop()
        logger.info("AutomaticOperation stopped")


    def _done(self):
        super()._done()
        logger.info("AutomaticOperation finished")


class FlushOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)
        self._timer = QTimer()
        self._timer.timeout.connect(self.flush_step)
        self._running = False

    def start(self):
        logger.info("FlushOperation started")
        self._running = True
        self._timer.start(100)  # adjust flush frequency (ms)
        self.device_manager.filling()

    def flush_step(self):
        if not self._running:
            return
        self.device_manager.filling()  # implement this in your device manager
        logger.debug("Flush step executed")

    def stop(self):
        logger.info("FlushOperation stopping")
        self._running = False
        self._timer.stop()
        super().stop()

    def _done(self):
        super()._done()
        logger.info("FlushOperation finished")