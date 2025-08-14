import logging
import os
import PySide6.QtWidgets as Qtw

from utils.config_manager import ConfigManager
from utils.widget_finder import WidgetFinder

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
        self._init_ui()  # Set up the user interface
        self._init_signals()                                    # Initialize signals and hardware devices

        #self._list_widgets()
        return

    def _init_config(self):                                     # Private method to load configuration
        cfg_manager = ConfigManager()                           # Create a ConfigManager instance
        self.config = cfg_manager.general_config                # Load the "general" configuration section
        return

    def _init_devices(self):
        self.device_manager = DeviceManager()
        self.operation_manager = OperationManager(self.device_manager)
        return

    def _init_ui(self):                                                                                # Private method to build the UI
        ui_path = os.path.join(self.config.get("Project Path"),"ui","main_window.ui")
        self.ui = UiBuilder.load_ui(ui_path, self)
        self.setCentralWidget(self.ui)

        self.binder = SignalBinder(self.ui, operation_manager=self.operation_manager, device_manager=self.device_manager, config=self.config)       # Start signal binding
        self.binder.bind_signals()

        self._populate_ui()
        self._disable_ui()
        return

    def _populate_ui(self):
        self.ui.projectPathLineEdit.setText(self.config.get("Project Path", "No Path Found"))       # Load project path

        cfg = ConfigManager().load_config("container_selector")
        container_names = cfg["Containers"].keys()                                                  # Load container names
        self.ui.containerComboBox.addItems(container_names)                                         # Connect container names with ComboBox

        selected_container = cfg.get("Selected Container", "No Container Found")                    # Set initial container to latest selection
        index = self.ui.containerComboBox.findText(selected_container)
        if index >= 0:
            self.ui.containerComboBox.setCurrentIndex(index)

        self.ui.soakTimeLineEdit.setText(str(self.config.get("PVA Waiting Time", "No Time Found")))  # Set soakTime

        operations_names = self.config["Operations"]
        self.ui.operationComboBox.addItems(operations_names)

        selected_operation = self.config.get("Selected Operation", "No Operation Found")            # Set initial operation to latest selection
        index = self.ui.operationComboBox.findText(selected_operation)
        if index >= 0:
            self.ui.operationComboBox.setCurrentIndex(index)

        self.ui.containerVolLineEdit.setText(f"{self.config.get("Container Volume", "No Volume Found"):.2f} uL")
        self.ui.setFlowLineEdit.setText(f"{self.config.get("Default Flow"):.2f} uL/min")
        self.ui.bottleVolLineEdit.setText(f"{self.config.get("Remaining Bottle Volume", "No Bottle Found"):.2f} mL")

        cfg = ConfigManager().load_config("valves")
        self.ui.liquidToggleSwitch.setChecked(bool(cfg["Valves"]["Liquid"]["State"]))
        self.ui.ventingToggleSwitch.setChecked(bool(cfg["Valves"]["Venting"]["State"]))
        self.ui.containerToggleSwitch.setChecked(bool(cfg["Valves"]["Container"]["State"]))

        self.ui.progressBar.setValue(0)
        self.ui.remainingTimeLabel.setText("Remaining Time: 00:00")
        return

    def _disable_ui(self):
        self.ui.stopPushButton.setEnabled(False)
        self.ui.pausePushButton.setEnabled(False)
        return

    def _init_signals(self):

        data_signals.set_start_enabled.connect(self.ui.startPushButton.setEnabled)
        data_signals.set_stop_enabled.connect(self.ui.stopPushButton.setEnabled)
        data_signals.set_pause_enabled.connect(self.ui.pausePushButton.setEnabled)
        data_signals.set_pause_enabled.connect(self.binder.reset_pause_button)

        data_signals.set_flush_enabled.connect(self.ui.flushPushButton.setEnabled)

        data_signals.set_reset_container_enabled.connect(self.ui.resetContPushButton.setEnabled)
        data_signals.set_bottle_volume_enabled.connect(self.ui.setBottlePushButton.setEnabled)

        data_signals.set_start_enabled.connect(self.ui.containerComboBox.setEnabled)
        data_signals.set_stop_enabled.connect(self.ui.soakTimeLineEdit.setReadOnly)
        data_signals.set_start_enabled.connect(self.ui.operationComboBox.setEnabled)

        return

    def cleanup(self):
        logger.info("Cleaning up MainWindow resources")
        if hasattr(self, "operation_manager"):
            self.operation_manager.shutdown()  # Implement shutdown logic
        if hasattr(self, "device_manager"):
            self.device_manager.shutdown()  # Implement shutdown logic
        return

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)
        return

    def _list_widgets(self):
        from PySide6.QtWidgets import QLabel
        wgf = WidgetFinder(self.ui)
        wgf.list_widgets_of_type(QLabel)
        return