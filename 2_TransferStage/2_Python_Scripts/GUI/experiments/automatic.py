from experiments.base import BaseExperiment
from experiments.dummy_experiments.dummy_run import DummyExperiment
from PySide6.QtCore import QTimer

class AutomaticExperiment(BaseExperiment):
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._done)
        self.dummy = DummyExperiment()
    def start(self):
        print("AutomaticExperiment started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second experiment

    def stop(self):
        print("AutomaticExperiment stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        print("AutomaticExperiment finished")
        self.dummy._complete()
