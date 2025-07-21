import logging                                                  # Import logging to record app events
import PySide6.QtWidgets as Qtw                                 # Import Qt widgets with an alias for convenience

from utils.config_manager import ConfigManager                  # Import configuration manager for loading settings

from builders.ui_builder import UiBuilder
from builders.signal_binder import SignalBinder

from core.experiment_manager import ExperimentManager
logger = logging.getLogger(__name__)                            # Create a logger for this module

class MainWindow(Qtw.QMainWindow):                              # Define the main window class inheriting from QMainWindow
    def __init__(self):                                         # Constructor method
        super().__init__()                                      # Call the base class constructor
        self.setWindowTitle("Transfer Stage")                   # Set the window title
        self.resize(800, 600)                                   # Set the initial window size

        self._init_config()                                     # Load configuration settings
        self._init_ui()                                         # Set up the user interface
        self._init_signals_and_devices()                        # Initialize signals and hardware devices
        return

    def _init_config(self):                                     # Private method to load configuration
        cfg_manager = ConfigManager()                           # Create a ConfigManager instance
        self.config = cfg_manager.general_config                # Load the "general" configuration section
        return

    def _init_signals_and_devices(self):
        self.experiment_manager = ExperimentManager
        SignalBinder().bind_signals(self.ui["parameter_frame"], self.experiment_manager)

        return

    def _init_ui(self):                                                             # Private method to build the UI
        self.ui = UiBuilder.build_main_layout(self, self.config)       # Build and return UI components
        #self.top = ui["top"]                                                        # Assign top UI element
        #self.left = ui["left"]                                                      # Assign left UI panel
        #self.right = ui["right"]                                                    # Assign right UI panel
        #self.main_splitter = ui["splitter"]                                         # Assign main splitter (container for layout)

        #self.stacked_layout = ui["stacked_layout"]
        #self.main_view = ui["main_view"]
        return