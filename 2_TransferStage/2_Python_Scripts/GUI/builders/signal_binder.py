import logging
from PySide6.QtCore import QTimer

from core.signals import ui_signals, operation_signals, data_signals, hardware_signals
from widgets.set_bottle_volume_dialog import SetBottleVolumeDialog
from utils.config_manager import ConfigManager

logger = logging.getLogger(__name__)

def get_callable_name(callable_obj):
    if hasattr(callable_obj, "__name__"):
        return callable_obj.__name__
    elif hasattr(callable_obj, "__class__"):
        return callable_obj.__class__.__name__
    else:
        return str(callable_obj)

class SignalBinder:
    def __init__(self, ui, operation_manager, device_manager, config):
        self.ui = ui
        self.config = config
        self.operation_manager = operation_manager
        self.device_manager = device_manager

        self._blink_state = False
        self._pause_button_blinking()
        return

    def bind_signals(self):
        self._bind_ui_to_signals()
        return

    def _bind_ui_to_signals(self):
        self.ui.containerComboBox.currentTextChanged.connect(self._on_container_changed)
        self.ui.containerComboBox.currentTextChanged.connect(self._select_tbc_volume)
        self.ui.containerComboBox.currentTextChanged.connect(self.device_manager.select_container)

        self.ui.operationComboBox.currentTextChanged.connect(self._on_operation_changed)
        self.ui.operationComboBox.currentTextChanged.connect(self._select_tbc_volume)

        self.ui.soakTimeLineEdit.editingFinished.connect(self._on_soak_time_changed)
        self.ui.startPushButton.clicked.connect(self._emit_start_operation)
        self.ui.stopPushButton.clicked.connect(ui_signals.stop_operation.emit)
        self.ui.pausePushButton.clicked.connect(self._handle_pause_clicked)

        self.ui.flushPushButton.pressed.connect(self.operation_manager.start_flush)
        self.ui.flushPushButton.released.connect(self.operation_manager.stop_flush)

        self.ui.setBottlePushButton.clicked.connect(self._set_bottle_volume)

        self.ui.resetContPushButton.clicked.connect(self._reset_container)

        hardware_signals.liquid_valve_changed.connect(self.ui.liquidToggleSwitch.setChecked)
        hardware_signals.container_valve_changed.connect(self.ui.containerToggleSwitch.setChecked)
        hardware_signals.venting_valve_changed.connect(self.ui.ventingToggleSwitch.setChecked)

        hardware_signals.pump_changed.connect(self.ui.pumpToggleSwitch.setChecked)

        data_signals.config_changed.connect(ConfigManager().update_config)  # Connect to signals to Configmanager

        data_signals.flow_updated.connect(self._update_flow_display)
        data_signals.pressure_updated.connect(self._update_pressure_display)
        data_signals.tbc_volume_updated.connect(self._update_volume_display)
        data_signals.container_volume_updated.connect(self._update_container_volume_display)

        data_signals.progress_updated.connect(self.ui.progressBar.setValue)
        data_signals.time_updated.connect(self.ui.remainingTimeLabel.setText)

        data_signals.bottle_volume_updated.connect(self._update_bottle_volume_display)
        return

    def _on_container_changed(self, container_name):
        cfg = ConfigManager().load_config("container_selector")
        max_volume = cfg["Containers"].get(container_name, None).get("Maximum Volume", None)
        self.ui.maxVolLineEdit.setText(str(max_volume))

        logger.debug(f"Container selected: {container_name}, maximum max_volume set to {max_volume}")
        ui_signals.container_changed.emit(container_name)
        data_signals.config_changed.emit("container_selector", "Selected Container", container_name, True)

        return

    def _on_soak_time_changed(self):
        try:
            value = int(self.ui.soakTimeLineEdit.text())
            data_signals.config_changed.emit("general", "PVA Waiting Time", value, True)
            logger.info(f"Config update requested: PVA Waiting Time = {value}")
        except ValueError:
            logger.error("Invalid value entered for PVA Waiting Time")
        return

    def _on_operation_changed(self, operation_name):
        logger.info(f"Operation selected: {operation_name}")
        data_signals.config_changed.emit("general", "Selected Operation", operation_name, True)
        return

    def _select_tbc_volume(self):
        cfg = ConfigManager().load_config("general")
        selected_operation = cfg.get("Selected Operation")
        container_volume = cfg.get("Container Volume")

        cfg = ConfigManager().load_config("container_selector")
        selected_container = cfg.get("Selected Container")

        if selected_operation in ("add", "remove"):
            tbc_volume = cfg["Containers"].get(selected_container).get("Small Volume")

        elif selected_operation in ("fill", "automatic"):
            max_volume = cfg["Containers"].get(selected_container, None).get("Maximum Volume", None)
            tbc_volume = max_volume - container_volume
        elif selected_operation == "empty":
            tbc_volume = container_volume

        self.ui.tbcVolLineEdit.setText(f"{tbc_volume:.2f} uL")

        self._update_final_volume(tbc_volume, container_volume, selected_operation)
        return

    def _update_final_volume(self, tbc_volume, container_volume, selected_operation):
        if selected_operation in ("add", "fill", "automatic"):
            final_volume = container_volume + tbc_volume
        elif selected_operation in ("remove", "empty"):
            final_volume = container_volume - tbc_volume

        self.ui.finalVolLineEdit.setText(f"{final_volume:.2f} uL")
        return

    def _emit_start_operation(self):
        selected_operation = self.ui.operationComboBox.currentText()
        ui_signals.start_operation.emit(selected_operation)
        return

    def _pause_button_blinking(self):
        self._blink_timer = QTimer(self.ui)
        self._blink_timer.setInterval(800)
        self._blink_timer.timeout.connect(self._toggle_pause_blink)
        self._blink_state = False
        return

    def _toggle_pause_blink(self):
        if self._blink_state:
            self.ui.pausePushButton.setStyleSheet("background-color: none;")
        else:
            self.ui.pausePushButton.setStyleSheet("background-color: orange; color: black; font-weight: bold;")
        self._blink_state = not self._blink_state
        return

    def reset_pause_button(self, enabled: bool):
        self.ui.pausePushButton.setEnabled(enabled)
        if not enabled:
            self.ui.pausePushButton.setText("Pause")
            self._blink_timer.stop()
            self.ui.pausePushButton.setStyleSheet("")
            self._blink_state = False
        return

    def _handle_pause_clicked(self):
        if self.operation_manager.paused:
            ui_signals.resume_operation.emit()
            self.ui.pausePushButton.setText("Pause")
            self._blink_timer.stop()
            self.ui.pausePushButton.setStyleSheet("")  # reset style
        else:
            ui_signals.pause_operation.emit()
            self.ui.pausePushButton.setText("Resume")
            self._blink_timer.start()
        return

    def _update_flow_display(self, flow):
        self.ui.measFlowLineEdit.setText(f"{flow:.2f} uL/min")
        return

    def _update_pressure_display(self, pressure):
        self.ui.appliedPressLineEdit.setText(f"{pressure:.1f} mbar")
        return

    def _update_volume_display(self, volume):
        self.ui.tbcVolLineEdit.setText(f"{volume:.2f} mL")

    def _clear_pid_display_fields(self):
        self.ui.flowLineEdit.clear()
        self.ui.pressureLineEdit.clear()
        self.ui.tbcVolLineEdit.clear()
        return

    def _update_container_volume_display(self, container_vol):
        self.ui.containerVolLineEdit.setText(f"{container_vol:.2f} mL")
        return

    def _update_bottle_volume_display(self,bottle_vol):
        self.ui.bottleVolLineEdit.setText(f"{bottle_vol:.2f} mL")
        return

    def _set_bottle_volume(self):
        dialog = SetBottleVolumeDialog(self.ui)
        dialog.exec()
        return

    def _reset_container(self):
        self._update_container_volume_display(0)
        ConfigManager().update_config("general", "Container Volume", 0)
        return





