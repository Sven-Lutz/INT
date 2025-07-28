import logging

from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

from qt_plugins.toggle_switch import ToggleSwitch

logger = logging.getLogger(__name__)

class UiBuilder:
    @staticmethod
    def load_ui(ui_path: str, parent=None):
        loader = QUiLoader()
        loader.registerCustomWidget(ToggleSwitch)

        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.ReadOnly):
            logger.error(f"Failed to load {ui_path}")
            raise RuntimeError(f"Failed to load {ui_path}")

        ui = loader.load(ui_file, parent)
        ui_file.close()

        if not ui:
            raise RuntimeError("Failed to load UI")

        return ui
