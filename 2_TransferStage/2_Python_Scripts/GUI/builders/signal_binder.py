import logging
from core.signals import UISignals, ExperimentSignals, DataSignals

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
        # Map signals to their slots
        bindings = {
            ui.start_button.clicked: lambda: UISignals.start_clicked.emit(ui.selected_experiment()),
            ui.stop_button.clicked: UISignals.stop_clicked,

            #UISignals.start_clicked: experiment_manager.start_experiment,
            #UISignals.stop_clicked: ExperimentSignals.stop_experiment,

            #DataSignals.update_status: ui.set_status,
            #DataSignals.update_measurement: ui.set_measurement,
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