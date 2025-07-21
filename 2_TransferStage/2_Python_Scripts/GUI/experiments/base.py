from PySide6.QtCore import QObject, Signal, QTimer

class BaseExperiment(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError
