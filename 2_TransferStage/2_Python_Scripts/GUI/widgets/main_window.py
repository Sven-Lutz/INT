import logging
import os
import PySide6.QtWidgets as Qtw


from utils.config_manager import ConfigManager

from builders.signal_binder import SignalBinder
from builders.ui_builder import UiBuilder

from core.signals import ui_signals, data_signals, hardware_signals
from core.operation_manager import OperationManager

from hardware.device_manager import DeviceManager


logger = logging.getLogger(__name__)                            # Create a logger for this module

class MainWindow(Qtw.QMainWindow):                              # Define the main window class inheriting from QMainWindow
    def __init__(self):                                         # Constructor method
        super().__init__()                                      # Call the base class constructor

        self._init_config()                                     # Load configuration settings
        self._init_devices()
        self._init_ui_defaults()                                # Set up the user interface
        self._init_signals()                                    # Initialize signals and hardware devices

        return

    def _init_config(self):                                     # Private method to load configuration
        cfg_manager = ConfigManager()                           # Create a ConfigManager instance
        self.config = cfg_manager.general_config                # Load the "general" configuration section
        return

    def _init_ui_defaults(self):                                                                                # Private method to build the UI
        ui_path = os.path.join(self.config.get("Project Path"),"2_Python_Scripts","GUI","ui","main_window.ui")
        self.ui = UiBuilder.load_ui(ui_path, self)
        self.setCentralWidget(self.ui)

        self.binder = SignalBinder(self.ui, operation_manager=self.operation_manager, config=self.config)       # Start signal binding
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

        self.ui.startPushButton.setEnabled(True)
        self.ui.stopPushButton.setEnabled(False)
        self.ui.pausePushButton.setEnabled(False)

        self.ui.flushPushButton.setEnabled(True)

        self.ui.containerVolLineEdit.setText(f"{self.config.get("Container Volume", "No Volume Found"):.2f} uL")
        self.ui.bottleVolLineEdit.setText(f"{self.config.get("Remaining Bottle Volume", "No Bottle Found"):.2f} mL")
        return

    def _init_devices(self):
        self.device_manager = DeviceManager()
        self.operation_manager = OperationManager(self.device_manager)

    def _init_signals(self):

        ui_signals.config_changed.connect(ConfigManager().update_config)                        # Connect to signals to Configmanager

        data_signals.set_start_enabled.connect(self.ui.startPushButton.setEnabled)
        data_signals.set_stop_enabled.connect(self.ui.stopPushButton.setEnabled)
        data_signals.set_pause_enabled.connect(self.ui.pausePushButton.setEnabled)
        data_signals.set_pause_enabled.connect(self.binder.reset_pause_button)

        data_signals.set_flush_enabled.connect(self.ui.flushPushButton.setEnabled)
        return

    def _update_volume_field(self, container_name):
        volume = self.config["Containers"].get(container_name, {}).get("Maximum Volume", "")
        self.ui.maxVolLineEdit.setText(str(volume))
        return