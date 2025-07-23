import logging

from PySide6.QtCore import QObject
from core.signals import ui_signals, operation_signals, data_signals

from operations.operations import FillOperation, EmptyOperation, AddOperation, RemoveOperation, AutomaticOperation

logger = logging.getLogger(__name__)

class OperationManager(QObject):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.operation = None                                                   # start with no operation
        self.paused = False
        self._connected = False

        ui_signals.start_operation.connect(self.start_operation)  # <-- connect to UI start signal

        ui_signals.stop_operation.connect(self.stop_operation)
        operation_signals.operation_done.connect(self.on_operation_done)

        self._operation_map = {
            "fill": FillOperation,
            "empty": EmptyOperation,
            "add": AddOperation,
            "remove": RemoveOperation,
            "automatic": AutomaticOperation
        }

    def start_operation(self, operation_type):
        if self.operation:
            logger.info(f"{operation_type} operation already in progress. Please wait.")
            data_signals.update_status.emit(f"{operation_type} operation already in progress. Please wait.")
            return

        operation_class = self._operation_map.get(operation_type.lower())
        if not operation_class:
            data_signals.update_status.emit(f"Unknown operation: {operation_type}")
            return

        self.operation = operation_class(self.device_manager)
        if not self._connected:
            self.operation.finished.connect(self.on_operation_done)
            self._connected = True

        data_signals.update_status.emit(f"Running: {operation_type}")

        self.operation.start()

        data_signals.set_start_enabled.emit(not self.is_busy())
        data_signals.set_stop_enabled.emit(self.is_busy())
        data_signals.set_pause_enabled.emit(self.is_busy())

        return

    def pause_operation(self):
        if self.operation and hasattr(self.operation, 'pause'):
            self.paused = True
            self.operation.pause()
            data_signals.update_status.emit("Paused")
        return

    def stop_operation(self):
        logger.info("Stopping operation")
        if self.operation:
            self.operation.stop()
            self.operation = None
            self.paused = False
            data_signals.update_status.emit("Stopped")

            data_signals.set_start_enabled.emit(not self.is_busy())
            data_signals.set_stop_enabled.emit(self.is_busy())
            data_signals.set_pause_enabled.emit(self.is_busy())

        else:
            logger.warning("OperationManager: no active operation to stop")
        return

    def on_operation_done(self):
        try:
            logger.info("Operation done")
            data_signals.update_status.emit("Done")

            #operation_signals.operation_done.emit()
            logger.info(f"Operation: {self.is_busy()}")
            self.operation = None
            self._connected = False

            data_signals.set_start_enabled.emit(not self.is_busy())
            data_signals.set_stop_enabled.emit(self.is_busy())
            data_signals.set_pause_enabled.emit(self.is_busy())
        except Exception as e:
            logger.error(f"Error in on_operation_done: {e}")
        return

    def is_busy(self) -> bool:
        return self.operation is not None
