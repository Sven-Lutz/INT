import logging
from core.signals import ui_signals, operation_signals, data_signals, hardware_signals

logger = logging.getLogger(__name__)

def get_callable_name(callable_obj):
    if hasattr(callable_obj, "__name__"):
        return callable_obj.__name__
    elif hasattr(callable_obj, "__class__"):
        return callable_obj.__class__.__name__
    else:
        return str(callable_obj)

class SignalBinder:
    def __init__(self, ui, operation_manager, config):
        self.ui = ui
        self.config = config
        self.operation_manager = operation_manager
        return

    def bind_signals(self):
        self._bind_ui_to_signals()
        return

    def _bind_ui_to_signals(self):
        self.ui.containerComboBox.currentTextChanged.connect(self._on_container_changed)
        self.ui.soakTimeLineEdit.editingFinished.connect(self._on_soak_time_changed)
        self.ui.startPushButton.clicked.connect(self._emit_start_operation)

        hardware_signals.liquid_valve_changed.connect(self.ui.liquidToggleSwitch.setChecked)
        hardware_signals.container_valve_changed.connect(self.ui.containerToggleSwitch.setChecked)
        hardware_signals.venting_valve_changed.connect(self.ui.ventingToggleSwitch.setChecked)
        #self.ui.stopPushButton.clicked.connect(lambda: ui_signals.stop_operation.emit())
        #self.ui.pausePushButton.clicked.connect(lambda: operation_signals.pause_operation.emit())
        return

    def _on_container_changed(self,container_name):
        volume = self.config["Containers"].get(container_name, None).get("Maximum Volume", None)
        self.ui.maxVolLineEdit.setText(str(volume))

        logger.info(f"Container selected: {container_name}, maximum volume set to {volume}")
        ui_signals.container_changed.emit(container_name)
        ui_signals.config_changed.emit("general", "Selected Container", container_name, True)
        return

    def _on_soak_time_changed(self):
        try:
            value = int(self.ui.soakTimeLineEdit.text())
            ui_signals.config_changed.emit("general", "PVA Waiting Time", value, True)
            logger.info(f"Config update requested: PVA Waiting Time = {value}")
        except ValueError:
            logger.error("Invalid value entered for PVA Waiting Time")

    def _on_operation_changed(self,operation_name):
        logger.info(f"Operation selected: {operation_name}")
        ui_signals.config_changed.emit("general", "Selected Operation", operation_name, True)
        return

    def _emit_start_operation(self):
        selected_operation = self.ui.operationComboBox.currentText()
        ui_signals.start_operation.emit(selected_operation)



