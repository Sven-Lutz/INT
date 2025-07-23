from PySide6.QtCore import QObject, Signal

class OperationSignals(QObject):
    operation_done = Signal()
    operation_failed = Signal(str)

    def __init__(self):
        super().__init__()

class UISignals(QObject):
    container_changed = Signal(str)
    config_changed = Signal(str, str, object, bool)                # str and object are representing key, new_value

    start_operation = Signal(str)
    pause_operation = Signal()
    resume_operation = Signal()
    stop_operation = Signal()


    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class HardwareSignals(QObject):
    liquid_valve_changed = Signal(bool)
    container_valve_changed = Signal(bool)
    venting_valve_changed = Signal(bool)
    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class DataSignals(QObject):
    update_status = Signal(str)
    update_measurement = Signal()

    set_start_enabled = Signal(bool)
    set_stop_enabled = Signal(bool)
    set_pause_enabled = Signal(bool)
    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

# Singleton instance
operation_signals = OperationSignals()
ui_signals = UISignals()
data_signals = DataSignals()
hardware_signals = HardwareSignals()
