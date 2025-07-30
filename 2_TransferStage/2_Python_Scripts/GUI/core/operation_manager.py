import logging

from PySide6.QtCore import QObject
from core.signals import ui_signals, operation_signals, data_signals

from operations.operations import FillOperation, EmptyOperation, AddOperation, RemoveOperation, AutomaticOperation, FlushOperation

logger = logging.getLogger(__name__)

class OperationManager(QObject):
    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self.operation = None                                                   # start with no operation
        self.paused = False

        ui_signals.start_operation.connect(self.start_operation)  # <-- connect to UI start signal
        ui_signals.pause_operation.connect(self.pause_operation)
        ui_signals.resume_operation.connect(self.resume_operation)
        ui_signals.stop_operation.connect(self.stop_operation)

        operation_signals.operation_done.connect(self.on_operation_done)

        self._operation_map = {
            "fill": FillOperation,
            "empty": EmptyOperation,
            "add": AddOperation,
            "remove": RemoveOperation,
            "automatic": AutomaticOperation
        }
        return

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

        data_signals.update_status.emit(f"Running: {operation_type}")

        self.operation.start()
        self._update_ui_state()

        return

    def pause_operation(self):
        if self.operation and hasattr(self.operation, 'pause'):
            self.paused = True
            self.operation.pause()
            data_signals.update_status.emit("Paused")
        return

    def resume_operation(self):
        if self.operation and hasattr(self.operation, 'resume'):
            self.paused = False
            self.operation.resume()
            data_signals.update_status.emit("Resumed")

    def stop_operation(self):
        logger.info("Stopping operation")
        if self.operation:
            self.operation.stop()

            data_signals.update_status.emit("Stopped")
            self.operation = None
            self.paused = False
            self._update_ui_state()
        else:
            logger.warning("OperationManager: no active operation to stop")
        return

    def on_operation_done(self):
        self.operation = None
        self.paused = False
        self._update_ui_state()
        return

    def is_busy(self) -> bool:
        return self.operation is not None

    def _update_ui_state(self):

        data_signals.set_start_enabled.emit(not self.is_busy())
        data_signals.set_stop_enabled.emit(self.is_busy())
        data_signals.set_pause_enabled.emit(self.is_busy())

        data_signals.set_flush_enabled.emit(not self.is_busy())

        data_signals.set_reset_container_enabled.emit(not self.is_busy())
        data_signals.set_bottle_volume_enabled.emit(not self.is_busy())
        return

    def start_flush(self):
        if self.is_busy():
            logger.info("Flush ignored: operation already running.")
            return

        self.operation = FlushOperation(self.device_manager)

        self.operation.start()
        data_signals.update_status.emit("Flushing...")
        return

    def stop_flush(self):
        if isinstance(self.operation, FlushOperation):
            self.operation.stop()
            self.operation = None
            data_signals.update_status.emit("Flush stopped")
            data_signals.set_flush_enabled.emit(True)
        return