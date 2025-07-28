import logging
import time

from PySide6.QtCore import QObject, Signal, QTimer

from operations.dummy_operations.dummy_run import DummyOperation

from utils.config_manager import ConfigManager

from core.pid_controller import PIDFlowController
from core.signals import operation_signals

logger = logging.getLogger(__name__)                            # Create a logger for this module

class BaseOperation(QObject):
    def __init__(self, device_manager, target_volume=None, direction=""):
        super().__init__()
        self._should_pause = False
        self.pid_ctrl = None

        self.device_manager = device_manager

        self._init_pid(target_volume, direction)

        #self.dummy = DummyOperation()
        #self.dummy.finished.connect(self._done)

        return

    def _init_pid(self, target_volume=None, direction=""):
        if target_volume is not None and direction != "":
            self.pid_ctrl = PIDFlowController(device_manager=self.device_manager, target_volume=target_volume, direction=direction)
            operation_signals.operation_done.connect(self._finalize)

            self.pid_ctrl.finished.connect(self._on_controller_done)
        else:
            logger.warning("PID Controller not initialized")
        return

    def start(self):
        self.device_manager.start_pump()
        if self.pid_ctrl:
            self.pid_ctrl.start()
        else:
            logger.warning("No PID controller configured")
        return

    def pause(self):
        self.device_manager.shut_container()
        self.device_manager.stop_pump()
        self._should_pause = True
        if self.pid_ctrl:
            self.pid_ctrl.pause()
        return

    def resume(self):
        self.device_manager.start_pump()
        self._should_pause = False
        if self.pid_ctrl:
            self.pid_ctrl.resume()
        self.device_manager.open_container()
        return

    def stop(self):
        self.device_manager.shut_container()
        if self.pid_ctrl:
            self.pid_ctrl.stop()
        self.device_manager.set_pressure(0)
        self._finalize("Operation stopped")
        return

    def _finalize(self, message: str = "Operation finished"):
        logger.info(message)
        self.device_manager.safe_state()
        #operation_signals.operation_done.emit()
        return

    def _on_controller_done(self):
        self._finalize("PID operation completed")
        return


class AddOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager, target_volume=1000.0, direction="positive")


class RemoveOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager, target_volume=5000.0, direction="negative")


class FillOperation(BaseOperation):
    def __init__(self, device_manager):
        cfg = ConfigManager().load_config("general")
        max_volume = cfg["Containers"].get(cfg.get("Selected Container")).get("Maximum Volume")
        super().__init__(device_manager, target_volume=1000.0, direction="positive")


class EmptyOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager, target_volume=1000.0, direction="negative")


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
        self.device_manager.start_pump()
        self.device_manager.filling()
        self.device_manager.set_pressure(4000)
        return

    def flush_step(self):
        if not self._running:
            return
        self.device_manager.filling()  # implement this in your device manager
        logger.debug("Flush step executed")
        return

    def stop(self):
        logger.info("FlushOperation stopping")
        self._running = False
        self._timer.stop()
        self._finalize("FlushOperation finished")
        return