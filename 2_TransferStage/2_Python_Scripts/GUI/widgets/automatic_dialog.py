import os
import logging

from PySide6.QtWidgets import QDialog, QVBoxLayout

from builders.ui_builder import UiBuilder
from utils.config_manager import ConfigManager
from core.signals import data_signals

logger = logging.getLogger(__name__)

class AutomaticDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_config()


        ui_path = os.path.join(self.config.get("Project Path"),"ui", "automatic_dialog.ui")
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
        self.dialog.startTimerPushButton.clicked.connect(self.accept)
        return

    def accept(self):
        super().accept()