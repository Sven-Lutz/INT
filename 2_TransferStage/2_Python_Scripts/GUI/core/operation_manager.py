from PySide6.QtCore import QObject
from core.signals import ui_signals, operation_signals, data_signals

from operations.operations import FillOperation, EmptyOperation, AddOperation, RemoveOperation, AutomaticOperation


class OperationManager(QObject):
    def __init__(self):
        super().__init__()
        self.operation = None

        operation_signals.stop_operation.connect(self.stop_operation)
        ui_signals.start_operation.connect(self.start_operation)  # <-- connect to UI start signal

        # Map operation names to classes
        self._operation_map = {
            "fill": FillOperation,
            "empty": EmptyOperation,
            "add": AddOperation,
            "remove": RemoveOperation,
            "automatic": AutomaticOperation
        }

    def start_operation(self, operation_type):
        if self.operation:
            # Operation is already running, reject or queue
            data_signals.update_status.emit("Operation in progress. Please wait.")
            return

        operation_class = self._operation_map.get(operation_type.lower())
        if not operation_class:
            data_signals.update_status.emit(f"Unknown operation: {operation_type}")
            return
        # Instantiate the appropriate operation object
        self.operation = operation_class()
        data_signals.update_status.emit(f"Running: {operation_type}")

        self.operation.finished.connect(self.on_operation_done)
        self.operation.start()

    def stop_operation(self):
        if self.operation:
            self.operation.stop()
            self.operation = None
            data_signals.update_status.emit("Stopped")

    def on_operation_done(self):
        data_signals.update_status.emit("Done")
        operation_signals.operation_done.emit()
        self.operation = None

    def is_busy(self) -> bool:
        return self.operation is not None
