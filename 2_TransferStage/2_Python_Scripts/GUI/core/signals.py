from PySide6.QtCore import QObject, Signal

class AllSignals(QObject):

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class ExperimentSignals(QObject):
    add_signal = Signal()
    remove_signal = Signal()
    fill_signal = Signal()
    empty_signal = Signal()
    automatic_signal = Signal()
    pause_signal = Signal()
    experiment_done = Signal()
    stop_experiment = Signal()

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class UISignals(QObject):
    start_clicked = Signal(str)
    stop_clicked = Signal()
    pause_clicked = Signal()

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class HardwareSignals(QObject):

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class DataSignals(QObject):
    update_status = Signal(str)
    update_measurement = Signal()
    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

# Singleton instance
experiment_signals = ExperimentSignals()
ui_signals = UISignals()
data_signals = DataSignals()
hardware_signals = HardwareSignals()
