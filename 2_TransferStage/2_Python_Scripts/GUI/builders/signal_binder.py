import logging
from core.signals import ui_signals, experiment_signals, data_signals

logger = logging.getLogger(__name__)

def get_callable_name(callable_obj):
    if hasattr(callable_obj, "__name__"):
        return callable_obj.__name__
    elif hasattr(callable_obj, "__class__"):
        return callable_obj.__class__.__name__
    else:
        return str(callable_obj)

class SignalBinder:
    def __init__(self, ui, experiment_manager, config):
        self.ui = ui
        self.config = config
        self.experiment_manager = experiment_manager
        return

    def bind_signals(self):
        self._bind_ui_to_signals()
        return

    def _bind_ui_to_signals(self):
        self.ui.containerComboBox.currentTextChanged.connect(self._oncontainer_changed)
        self.ui.soakTimeLineEdit.editingFinished.connect(self._on_soak_time_changed)
        return


    def _oncontainer_changed(self,container_name):
        volume = self.config["Containers"].get(container_name, None).get("Maximum Volume", None)
        self.ui.maxVolLineEdit.setText(str(volume))

        logger.info(f"Container selected: {container_name}, maximum volume set to {volume}")
        ui_signals.container_changed.emit(container_name)

    def _on_soak_time_changed(self):
        try:
            value = int(self.ui.soakTimeLineEdit.text())
            ui_signals.config_changed.emit("general", "PVA Waiting Time", value, True)
            logger.info(f"Config update requested: PVA Waiting Time = {value}")
        except ValueError:
            logger.error("Invalid value entered for PVA Waiting Time")



