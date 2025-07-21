from PySide6.QtCore import QObject
from core.signals import experiment_signals, data_signals

from experiments.fill import FillExperiment
from experiments.empty import EmptyExperiment
from experiments.add import AddExperiment
from experiments.remove import RemoveExperiment
from experiments.automatic import AutomaticExperiment


class ExperimentManager(QObject):
    def __init__(self):
        super().__init__()
        self.experiment = None
        experiment_signals.stop_experiment.connect(self.stop_experiment)

    def start_experiment(self, experiment_type):
        if self.experiment:
            self.stop_experiment()

        # Instantiate the appropriate experiment object
        self.experiment = self._create_experiment(experiment_type)

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

    def _create_experiment(self, experiment_type):
        if experiment_type == "fill":
            return FillExperiment()
        elif experiment_type == "empty":
            return EmptyExperiment()
        elif experiment_type == "add":
            return AddExperiment()
        elif experiment_type == "remove":
            return RemoveExperiment()
        elif experiment_type == "automatic":
            return AutomaticExperiment()
        else:
            raise ValueError(f"Unknown experiment type: {experiment_type}")

