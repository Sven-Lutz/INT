import os
import logging

from PySide6.QtWidgets import QDialog, QVBoxLayout

from builders.ui_builder import UiBuilder
from utils.config_manager import ConfigManager
from core.signals import data_signals

logger = logging.getLogger(__name__)

class SetBottleVolumeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_config()


        ui_path = os.path.join(self.config.get("Project Path"),"ui", "set_bottle_dialog.ui")
        self.dialog = UiBuilder.load_ui(ui_path, parent=None)
        layout = QVBoxLayout()
        layout.addWidget(self.dialog)
        self.setLayout(layout)

        self._init_signals()
        return

    def _init_config(self):
        cfg_manager = ConfigManager()
        self.config = cfg_manager.general_config
        return

    def _init_signals(self):
        self.dialog.buttonBox.accepted.connect(self.accept)
        self.dialog.buttonBox.rejected.connect(self.reject)
        return

    def get_volume(self):
        return self.dialog.bottleVolSpinBox.value()

    def accept(self):
        new_volume = self.get_volume()
        data_signals.bottle_volume_updated.emit(new_volume)
        ConfigManager().update_config("general","Remaining Bottle Volume", new_volume)
        logger.info(f"Set bottle volume: {new_volume} mL")
        super().accept()