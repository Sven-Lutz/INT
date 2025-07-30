from tokenize import Single

from PySide6.QtCore import QObject, Signal

class OperationSignals(QObject):
    operation_done = Signal()
    operation_failed = Signal(str)

    def __init__(self):
        super().__init__()

class UISignals(QObject):
    container_changed = Signal(str)

    start_operation = Signal(str)
    pause_operation = Signal()
    resume_operation = Signal()
    stop_operation = Signal()
    flush_operation = Signal()

    reset_container = Signal()

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class HardwareSignals(QObject):
    liquid_valve_changed = Signal(bool)
    container_valve_changed = Signal(bool)
    venting_valve_changed = Signal(bool)

    pump_changed = Signal(bool)
    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

class DataSignals(QObject):
    config_changed = Signal(str, str, object, bool)  # str and object are representing key, new_value

    update_status = Signal(str)
    update_measurement = Signal()

    set_start_enabled = Signal(bool)
    set_stop_enabled = Signal(bool)
    set_pause_enabled = Signal(bool)

    set_flush_enabled = Signal(bool)

    set_reset_container_enabled = Signal(bool)
    set_bottle_volume_enabled = Signal(bool)



    flow_updated = Signal(float)
    pressure_updated = Signal(float)
    tbc_volume_updated = Signal(float)
    container_volume_updated = Signal(float)

    bottle_volume_updated = Signal(float)

    progress_updated = Signal(int)
    time_updated = Signal(str)

    def __init__(self):                                         # Constructor
        super().__init__()                                      # Call base class constructor

# Singleton instance
operation_signals = OperationSignals()
ui_signals = UISignals()
data_signals = DataSignals()
hardware_signals = HardwareSignals()
