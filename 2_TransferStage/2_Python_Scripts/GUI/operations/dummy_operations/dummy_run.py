import logging
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)

class DummyOperation(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self._paused = False

    def start(self):
        logger.info("Dummy operation started")
        QTimer.singleShot(1000, self._complete)

    def pause(self):
        logger.info("Dummy operation paused")
        self._paused = True
        # You might cancel timers, or block actions in progress

    def stop(self):
        logger.info("Dummy operation stopped")

    def _complete(self):
        logger.info("Dummy operation complete")
        self.finished.emit()
