from PySide6.QtCore import QObject
from core.signals import experiment_signals, data_signals



class ExperimentManager(QObject):
    def __init__(self):
        super().__init__()
        self.experiment = None
        experiment_signals.stop_experiment.connect(self.stop_experiment)

    def start_experiment(self, experiment_type):
        if self.experiment:
            self.stop_experiment()

        data_signals.update_status.emit(f"Running: {experiment_type}")
        self.experiment.finished.connect(self.on_experiment_done)
        self.experiment.start()

    def stop_experiment(self):
        if self.experiment:
            self.experiment.stop()
            self.experiment = None
            data_signals.update_status.emit("Stopped")

    def on_experiment_done(self):
        data_signals.update_status.emit("Done")
        experiment_signals.experiment_done.emit()
