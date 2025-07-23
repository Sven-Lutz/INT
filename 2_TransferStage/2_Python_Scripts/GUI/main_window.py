import logging                                                  # Import logging to record app events
import PySide6.QtWidgets as Qtw                                 # Import Qt widgets with an alias for convenience
from PySide6.QtWidgets import QWidget, QLineEdit

from utils.config_manager import ConfigManager                  # Import configuration manager for loading settings

from builders.signal_binder import SignalBinder
from builders.ui_builder import UiBuilder

from core.signals import ui_signals
from core.operation_manager import OperationManager


logger = logging.getLogger(__name__)                            # Create a logger for this module

class MainWindow(Qtw.QMainWindow):                              # Define the main window class inheriting from QMainWindow
    def __init__(self):                                         # Constructor method
        super().__init__()                                      # Call the base class constructor

        self._init_config()                                     # Load configuration settings
        self._init_ui_defaults()                                         # Set up the user interface
        self._init_signals_and_devices()                        # Initialize signals and hardware devices

        return

    def _init_config(self):                                     # Private method to load configuration
        cfg_manager = ConfigManager()                           # Create a ConfigManager instance
        self.config = cfg_manager.general_config                # Load the "general" configuration section

        self.operation_manager = OperationManager()
        return

    def _init_ui_defaults(self):                                                             # Private method to build the UI
        self.ui = UiBuilder.load_ui("widgets.ui", self)
        self.setCentralWidget(self.ui)

        self.binder = SignalBinder(self.ui, operation_manager=self.operation_manager, config=self.config)     # Start signal bining
        self.binder.bind_signals()



        self.ui.projectPathLineEdit.setText(self.config.get("Project Path", "No Path Found"))                   # Load project path

        container_names = self.config["Containers"].keys()                                                      # Load container names
        self.ui.containerComboBox.addItems(container_names)                                                     # Connect container names with ComboBox

        selected_container = self.config.get("Selected Container", "No Container Found")                        # Set initial container to latest selection
        index = self.ui.containerComboBox.findText(selected_container)
        if index >= 0:
            self.ui.containerComboBox.setCurrentIndex(index)

        self.ui.soakTimeLineEdit.setText(str(self.config.get("PVA Waiting Time", "No Time Found")))             # Set soakTime

        operations_names = self.config["Operations"]
        self.ui.operationComboBox.addItems(operations_names)

        selected_operation = self.config.get("Selected Operation", "No Container Found")                        # Set initial operation to latest selection
        index = self.ui.operationComboBox.findText(selected_operation)
        if index >= 0:
            self.ui.operationComboBox.setCurrentIndex(index)

        return

    def _init_signals_and_devices(self):
        ui_signals.config_changed.connect(ConfigManager().update_config)                        # Connect to signals to Configmanager

        return

    def _update_volume_field(self, container_name):
        volume = self.config["Containers"].get(container_name, {}).get("Maximum Volume", "")
        self.ui.maxVolLineEdit.setText(str(volume))







