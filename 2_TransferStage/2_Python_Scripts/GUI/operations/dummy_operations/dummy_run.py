from PySide6.QtCore import QObject, Signal, QTimer

class DummyOperation(QObject):
    finished = Signal()

    def start(self):
        print("Dummy operation started")
        QTimer.singleShot(1000, self._complete)

    def stop(self):
        print("Dummy operation stopped")

    def _complete(self):
        self.finished.emit()
