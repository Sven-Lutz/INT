import logging
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)

class DummyOperation(QObject):
    finished = Signal()
    def __init__(self):
        super().__init__()
        self._paused = False
        self._stopped = False

        self._elapsed_ms = 0
        self._duration_ms = 5000

        self._timer = QTimer(self)
        self._timer.setInterval(100)  # 100 ms resolution
        self._timer.timeout.connect(self._on_tick)

    def start(self):
        self._stopped = False
        self._paused = False
        self._elapsed_ms = 0
        self._timer.start()
        logger.info("Dummy operation started")
        return

    def pause(self):
        self._paused = True
        self._timer.stop()
        logger.info("Dummy operation paused")
        return

    def resume(self):
        self._paused = False
        self._timer.start()
        logger.info("Dummy operation resumed")
        return

    def stop(self):
        self._stopped = True
        self._timer.stop()
        logger.info("Dummy operation stopped")
        self.finished.emit()

    def _complete(self):
        self._stopped = True
        self._timer.stop()
        logger.info("Dummy operation complete")
        self.finished.emit()
        return

    def _on_tick(self):
        if self._stopped:
            return

        self._elapsed_ms += self._timer.interval()
        logging.debug(f"Dummy elapsed: {self._elapsed_ms} ms")

        if self._elapsed_ms >= self._duration_ms:
            self._complete()

