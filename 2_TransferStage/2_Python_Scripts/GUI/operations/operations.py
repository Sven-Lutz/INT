import logging
import time

from PySide6.QtCore import QObject, Signal, QTimer

from operations.dummy_operations.dummy_run import DummyOperation

logger = logging.getLogger(__name__)                            # Create a logger for this module

class BaseOperation(QObject):
    finished = Signal()


    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)
        self._should_pause = False
        return

    def start(self):
        self.dummy.start()
        return

    def pause(self):
        self._should_pause = True
        self.device_manager.shut_container()
        self.dummy.pause()
        return

    def resume(self):
        self._should_pause = False
        self.device_manager.open_container()
        self.dummy.resume()
        return

    def _done(self):
        self.device_manager.safe_state()
        self.finished.emit()
        return

    def stop(self):
        self.device_manager.safe_state()
        self.finished.emit()
        return

class AddOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

    def start(self):
        self.device_manager.filling()
        super().start()
        logger.info("AddOperation started")


    def stop(self):
        super().stop()
        logger.info("AddOperation stopped")
        return


    def _done(self):
        super()._done()
        logger.info("AddOperation finished")

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