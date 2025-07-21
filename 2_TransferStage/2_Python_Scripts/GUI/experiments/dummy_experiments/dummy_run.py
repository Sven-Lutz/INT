from PySide6.QtCore import QObject, Signal, QTimer

class DummyExperiment(QObject):
    finished = Signal()

    def start(self):
        print("Dummy experiment started")
        QTimer.singleShot(1000, self._complete)

    def stop(self):
        print("Dummy experiment stopped")

    def _complete(self):
        self.finished.emit()
