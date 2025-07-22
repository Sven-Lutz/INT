import logging                                                  # Import logging to record app events
import PySide6.QtWidgets as Qtw                                 # Import Qt widgets with an alias for convenience
from PySide6.QtWidgets import QWidget, QLineEdit

from utils.config_manager import ConfigManager                  # Import configuration manager for loading settings

from builders.signal_binder import SignalBinder
from builders.ui_builder import UiBuilder

from core.signals import ui_signals
from core.experiment_manager import ExperimentManager


logger = logging.getLogger(__name__)                            # Create a logger for this module

class MainWindow(Qtw.QMainWindow):                              # Define the main window class inheriting from QMainWindow
    def __init__(self):                                         # Constructor method
        super().__init__()                                      # Call the base class constructor

        self._init_config()                                     # Load configuration settings
        self._init_ui_defaults()                                         # Set up the user interface
        #self._init_signals_and_devices()                        # Initialize signals and hardware devices

        return

    def _init_config(self):                                     # Private method to load configuration
        cfg_manager = ConfigManager()                           # Create a ConfigManager instance
        self.config = cfg_manager.general_config                # Load the "general" configuration section

        self.experiment_manager = ExperimentManager()
        return

    def _init_ui_defaults(self):                                                             # Private method to build the UI
        self.ui = UiBuilder.load_ui("widgets.ui", self)
        self.setCentralWidget(self.ui)

        self.binder = SignalBinder(self.ui, experiment_manager=self.experiment_manager, config=self.config)
        self.binder.bind_signals()

        self.ui.projectPathLineEdit.setText(self.config.get("Project Path", "No Path Found"))

        container_names = self.config["Containers"].keys()
        self.ui.containerComboBox.clear()
        self.ui.containerComboBox.addItems(container_names)

        default_container = self.config.get("Default Container", "1 Sample")
        index = self.ui.containerComboBox.findText(default_container)
        if index >= 0:
            self.ui.containerComboBox.setCurrentIndex(index)

        self.ui.soakTimeLineEdit.setText(str(self.config.get("PVA Waiting Time", "No Time Found")))

        ui_signals.config_changed.connect(ConfigManager().update_config)

        return

    def _init_signals_and_devices(self):
        return

    def _update_volume_field(self, container_name):
        volume = self.config["Containers"].get(container_name, {}).get("Maximum Volume", "")
        self.ui.maxVolLineEdit.setText(str(volume))







