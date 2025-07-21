from PySide6.QtCore import QObject, QTimer

from core.signals import ExperimentSignals, DataSignals

class ExperimentManager(QObject):
    def __init__(self):
        super().__init__()
        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.run_step)
        self.counter = 0

        ExperimentSignals.start_experiment.connect(self.start)
        ExperimentSignals.stop_experiment.connect(self.stop)

    def start(self):
        self.counter = 0
        DataSignals.update_status.emit("Running")
        self.timer.start()

    def run_step(self):
        value = 42 + self.counter * 0.5  # Fake data
        DataSignals.update_measurement.emit(value)
        self.counter += 1

        if self.counter >= 5:
            self.stop()

    def stop(self):
        self.timer.stop()
        DataSignals.update_status.emit("Finished")
        ExperimentSignals.experiment_done.emit()
