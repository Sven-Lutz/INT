from PySide6.QtCore import QObject, Signal

class AllSignals(QObject):

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class OperationSignals(QObject):
    add_signal = Signal()
    remove_signal = Signal()
    fill_signal = Signal()
    empty_signal = Signal()
    automatic_signal = Signal()
    pause_signal = Signal()
    operation_done = Signal()
    stop_operation = Signal()

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class UISignals(QObject):
    """
    stop_clicked = Signal()
    pause_clicked = Signal()"""
    container_changed = Signal(str)
    config_changed = Signal(str, str, object, bool)                # str and object are representing key, new_value
    start_operation = Signal(str)

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
operation_signals = OperationSignals()
ui_signals = UISignals()
data_signals = DataSignals()
hardware_signals = HardwareSignals()
