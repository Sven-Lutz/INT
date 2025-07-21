import logging
from core.signals import ui_signals, experiment_signals, data_signals

logger = logging.getLogger(__name__)

def get_callable_name(callable_obj):
    if hasattr(callable_obj, "__name__"):
        return callable_obj.__name__
    elif hasattr(callable_obj, "__class__"):
        return callable_obj.__class__.__name__
    else:
        return str(callable_obj)

class SignalBinder:
    def bind_signals(self, ui, experiment_manager):
        """
        def on_start_clicked():
            print("Start button clicked (print test)")
            logger.info("Start button clicked")
            # Emit signal with selected experiment string
            ui_signals.start_clicked.emit(ui.selected_experiment())
            return

        def log_start_signal(*args, **kwargs):
            logger.info(f"UISignals.start_clicked emitted with args: {args}, kwargs: {kwargs}")
            return

        def on_stop_clicked():
            logger.info("Stop button clicked")
            ui_signals.stop_clicked.emit()
            return

        def log_stop_signal(*args, **kwargs):
            logger.info(f"UISignals.stop_clicked emitted with args: {args}, kwargs: {kwargs}")
            return

        # Connect UI buttons to emit signals and log clicks
        ui.start_button.clicked.connect(on_start_clicked)
        ui.stop_button.clicked.connect(on_stop_clicked)

        # Connect signals to log their emission
        ui_signals.start_clicked.connect(log_start_signal)
        ui_signals.stop_clicked.connect(log_stop_signal)

        # Connect signals to experiment manager methods
        ui_signals.start_clicked.connect(experiment_manager.start_experiment)
        ui_signals.stop_clicked.connect(experiment_signals.stop_experiment)

        return
        """
        logger.debug(type(ui))
        logger.debug(type(experiment_manager))
        # Map signals to their slots
        logger.debug(ui.selected_experiment())
        bindings = {
            ui.start_button.clicked: lambda: (logger.debug("Start button clicked"), ui_signals.start_clicked.emit(ui.selected_experiment())),
            ui.stop_button.clicked: lambda: (logger.debug("Stop button clicked"), ui_signals.stop_clicked.emit()),

            ui_signals.start_clicked: experiment_manager.start_experiment,
            ui_signals.stop_clicked: experiment_signals.stop_experiment,

            data_signals.update_status: ui.set_status,
            data_signals.update_measurement: ui.set_measurement,
        }

        for signal, slot in bindings.items():
            try:
                signal.connect(slot)
                sig_name = type(signal).__name__
                slot_name = get_callable_name(slot)
                logger.info(f"Connected signal '{sig_name}' to slot '{slot_name}'")
            except Exception as e:
                sig_name = type(signal).__name__
                slot_name = get_callable_name(slot)
                logger.error(f"Failed to connect signal '{sig_name}' to slot '{slot_name}': {e}")

