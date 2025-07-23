import logging

from PySide6.QtCore import QObject, Signal, QTimer

from operations.dummy_operations.dummy_run import DummyOperation

logger = logging.getLogger(__name__)                            # Create a logger for this module

class BaseOperation(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()

    def start(self):
        raise NotImplementedError

    def pause(self):
        raise NotImplementedError

    def resume(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

class AddOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        logger.info("AddOperation started")
        self.dummy.start()

    def stop(self):
        logger.info("AddOperation stopped")
        self.dummy.stop()
        self.finished.emit()  # Emit manually if interrupted

    def _done(self):
        logger.info("AddOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class RemoveOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        logger.info("RemoveOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        logger.info("RemoveOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        logger.info("RemoveOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class FillOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        logger.info("FillOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        logger.info("FillOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        logger.info("FillOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class EmptyOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        logger.info("EmptyOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        logger.info("EmptyOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        logger.info("EmptyOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class AutomaticOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        logger.info("AutomaticOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        logger.info("AutomaticOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        logger.info("AutomaticOperation finished")
        self.finished.emit()  # <-- notify OperationManager