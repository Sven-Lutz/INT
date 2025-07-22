import logging                                                  # Import logging to record app events
import PySide6.QtWidgets as Qtw                                 # Import Qt widgets with an alias for convenience
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

from qt_plugins.toggle_switch import ToggleSwitch
from utils.config_manager import ConfigManager                  # Import configuration manager for loading settings

from builders.ui_builder import UiBuilder
from builders.signal_binder import SignalBinder

from core.experiment_manager import ExperimentManager
logger = logging.getLogger(__name__)                            # Create a logger for this module

class MainWindow(Qtw.QMainWindow):                              # Define the main window class inheriting from QMainWindow
    def __init__(self):                                         # Constructor method
        super().__init__()                                      # Call the base class constructor

        self._init_config()                                     # Load configuration settings
        self._init_ui()                                         # Set up the user interface
        #self._init_signals_and_devices()                        # Initialize signals and hardware devices

        return

    def _init_config(self):                                     # Private method to load configuration
        cfg_manager = ConfigManager()                           # Create a ConfigManager instance
        self.config = cfg_manager.general_config                # Load the "general" configuration section
        return

    def _init_ui(self):                                                             # Private method to build the UI
        self._load_qt_ui()

        self.ui.projectPathLineEdit.setText(self.config.get("Project Path", "No Path Found"))

        self.setCentralWidget(self.ui)


        return

    def _init_signals_and_devices(self):
        self.experiment_manager = ExperimentManager()
        binder = SignalBinder()
        binder.bind_signals(self.ui["parameter_frame"], self.experiment_manager)
        return

    def _load_qt_ui(self):
        loader = QUiLoader()
        loader.registerCustomWidget(ToggleSwitch)

        nameOfUI = "widgets.ui"
        ui_file = QFile(nameOfUI)
        if not ui_file.open(QFile.ReadOnly):
            logger.error(f"Failed to load {nameOfUI}")
            raise RuntimeError(f"Failed to load {nameOfUI}")

        self.ui = loader.load(ui_file, self)
        ui_file.close()

        if not self.ui:
            raise RuntimeError("Failed to load UI")
        return

