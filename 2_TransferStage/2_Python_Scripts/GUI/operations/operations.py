import logging

from PySide6.QtCore import QObject, QTimer

from operations.dummy_operations.dummy_run import DummyOperation

from utils.config_manager import ConfigManager

from core.pid_controller import PIDFlowController
from core.signals import operation_signals, data_signals

logger = logging.getLogger(__name__)                            # Create a logger for this module

class BaseOperation(QObject):
    def __init__(self, device_manager, target_volume: float=0, direction=""):
        super().__init__()
        self._should_pause = False
        self.pid_ctrl = None
        self.target_volume = target_volume
        self.direction = direction
        self.device_manager = device_manager

        self._init_pid()

        #self.dummy = DummyOperation()
        #self.dummy.finished.connect(self._done)

        return

    def _init_pid(self):
        if self.target_volume is not None and self.direction != "":
            self.pid_ctrl = PIDFlowController(device_manager=self.device_manager, target_volume=self.target_volume, direction=self.direction)

            self.pid_ctrl.finished.connect(self._on_controller_done)
        else:
            logger.warning("PID Controller not initialized")
        return

    def start(self):
        cfg = ConfigManager().load_config("container_selector")
        max_volume = float(cfg["Containers"].get(cfg.get("Selected Container")).get("Maximum Volume"))
        cfg = ConfigManager().load_config("general")
        current_volume = cfg.get("Container Volume")


        if self.direction == "positive" and self.target_volume > max_volume:
            logger.warning("Container will overflow. Aborting operation")
            self.stop()
            raise OverflowError("ERROR: Container will overflow. Aborting operation")
        elif self.direction == "negative" and self.target_volume > current_volume:
            logger.warning("Air will be sucked in the system. Aborting operation")
            self.stop()
        else:
            self.device_manager.start_pump()
            if self.pid_ctrl:
                self.pid_ctrl.start()
            else:
                logger.warning("No PID controller configured")
        return

    def pause(self):
        self.device_manager.shut_container()
        self.device_manager.stop_pump()
        self._should_pause = True
        if self.pid_ctrl:
            self.pid_ctrl.pause()
        return

    def resume(self):
        self.device_manager.start_pump()
        self._should_pause = False
        if self.pid_ctrl:
            self.pid_ctrl.resume()
        self.device_manager.open_container()
        return

    def stop(self):
        self.device_manager.shut_container()
        if self.pid_ctrl:
            self.pid_ctrl.stop()
        self.device_manager.set_pressure(0)
        self._finalize("Operation stopped")
        return

    def _finalize(self, message: str = "Operation finished"):
        logger.info(message)
        self.device_manager.safe_state()
        operation_signals.operation_done.emit()
        return

    def _on_controller_done(self):
        self._finalize("PID operation completed")
        return


class AddOperation(BaseOperation):
    def __init__(self, device_manager):
        cfg = ConfigManager().load_config("container_selector")
        small_volume = cfg["Containers"].get(cfg.get("Selected Container")).get("Small Volume")
        super().__init__(device_manager, target_volume=small_volume, direction="positive")


class RemoveOperation(BaseOperation):
    def __init__(self, device_manager):
        cfg = ConfigManager().load_config("container_selector")
        small_volume = cfg["Containers"].get(cfg.get("Selected Container")).get("Small Volume")
        super().__init__(device_manager, target_volume=small_volume, direction="negative")


class FillOperation(BaseOperation):
    def __init__(self, device_manager):
        cfg = ConfigManager().load_config("container_selector")
        max_volume = cfg["Containers"].get(cfg.get("Selected Container")).get("Maximum Volume")
        cfg = ConfigManager().load_config("general")
        current_volume = cfg["Container Volume"]
        super().__init__(device_manager, target_volume=max_volume-current_volume, direction="positive")
        return

class EmptyOperation(BaseOperation):
    def __init__(self, device_manager):
        cfg = ConfigManager().load_config("general")
        current_volume = cfg.get("Container Volume")
        cfg = ConfigManager().load_config("container_selector")
        small_volume = cfg["Containers"].get(cfg.get("Selected Container")).get("Small Volume")
        super().__init__(device_manager, target_volume=current_volume-small_volume, direction="negative")
        return

class AutomaticOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

        cfg = ConfigManager().load_config("general")
        self._soaking_time = cfg.get("PVA Waiting Time")

        self.fill_op = FillOperation(device_manager)
        self.empty_op = EmptyOperation(device_manager)

        # Connect signals
        self.fill_op.pid_ctrl.finished.disconnect(self.fill_op._on_controller_done)
        self.fill_op.pid_ctrl.finished.connect(self._on_fill_done)
        self.empty_op.pid_ctrl.finished.disconnect(self.empty_op._on_controller_done)
        self.empty_op.pid_ctrl.finished.connect(self._on_empty_done)

        self._soak_timer = QTimer()
        self._soak_timer.setInterval(100)  # update every 100ms
        self._soak_timer.timeout.connect(self._on_soak_tick)

        self._soak_elapsed = 0

    def start(self):
        logger.info("AutomaticOperation started")
        logger.debug("Starting FillOperation now...")
        self.fill_op.start()
        return


    def _on_fill_done(self):
        logger.debug("FillOperation completed.")
        #logger.debug(f"Waiting for {self._soaking_time / 1000 :.0f} seconds before EmptyOperation...")
        self.device_manager.safe_state()
        data_signals.automatic_container_filled.emit()

        self._soak_elapsed = 0
        self._soak_timer.start()
        return

    def _on_soak_tick(self):
        self._soak_elapsed += self._soak_timer.interval()
        progress = int((self._soak_elapsed / 1000) / (self._soaking_time * 60) * 100)
        logger.info(f"Progress of soaking {progress}")
        data_signals.progress_updated.emit(progress)

        minutes, seconds = divmod(int(self._soaking_time * 60 - self._soak_elapsed / 1000), 60)
        formatted_time = f"Remaining Time: {minutes:02}:{seconds:02}"
        logger.debug(f"Waiting Time: {formatted_time}")
        data_signals.time_updated.emit(formatted_time)

        if self._soak_elapsed / 1000 >= self._soaking_time * 60:
            self._soak_timer.stop()
            self._start_empty_op()
        return

    def _start_empty_op(self):
        logger.info("Starting EmptyOperation after delay")

        self.empty_op.start()
        return

    def _on_empty_done(self):
        logger.info("EmptyOperation completed")
        self._finalize("AutomaticOperation completed")
        return

    def stop(self):
        logger.info("AutomaticOperation stopped")
        self.fill_op.pid_ctrl.finished.disconnect(self._on_fill_done)
        self.empty_op.pid_ctrl.finished.disconnect(self._on_empty_done)

        self.fill_op.stop()
        self.empty_op.stop()
        self._soak_timer.stop()
        formatted_time = f"Remaining Time: {00:02}:{00:02}"
        data_signals.time_updated.emit(formatted_time)
        self._finalize("AutomaticOperation stopped manually")
        return


class FlushOperation(BaseOperation):
    def __init__(self, device_manager):
        super().__init__(device_manager)

        self._volume = 0
        self._previous_flow = 0
        self.container_vol = None
        self.remaining_bottle_volume = None

        cfg = ConfigManager().load_config("container_selector")
        self.max_volume = cfg["Containers"].get(cfg.get("Selected Container")).get("Maximum Volume")

        self._timer = QTimer()
        self._timer.timeout.connect(self._flush_step)
        self._running = False

    def start(self):
        self._running = True
        self._volume = 0

        cfg = ConfigManager().load_config("general")
        self.container_vol = cfg.get("Container Volume")
        self.remaining_bottle_volume = cfg.get("Remaining Bottle Volume")

        if not self._check_environment():
            return

        logger.info("FlushOperation started")

        self.device_manager.start_pump()
        self.device_manager.filling()
        self.device_manager.set_pressure(4000)

        self._timer.start(100)  # adjust flush frequency (ms)
        return

    def _flush_step(self):
        if not self._check_environment():
            return  # Exit early if environment is not valid

        flow = self.device_manager.get_flow()  # uL/min
        delta_f = flow - self._previous_flow

        data_signals.flow_updated.emit(flow)
        data_signals.pressure_updated.emit(4000)  # fixed pressure

        self._volume += abs((flow + 0.5 * delta_f) * 0.1 * 0.001 / 60)  # 0.1s interval
        self.container_vol += self._volume
        self.remaining_bottle_volume -= self._volume / 1000

        data_signals.bottle_volume_updated.emit(round(self.remaining_bottle_volume, 2))
        data_signals.container_volume_updated.emit(self.container_vol)
        return

    def _check_environment(self):
        if not self._running:
            return False
        if self.container_vol >= self.max_volume:
            logger.warning("Container is full, flushing stopped")
            self.stop()
            return False
        elif self.remaining_bottle_volume == 0:
            logger.warning("Bottle empty, flushing stopped")
            self.stop()
            return False
        return True

    def stop(self):
        logger.info("FlushOperation stopping")
        self._running = False
        self._timer.stop()
        new_container_volume = self.container_vol + self._volume
        if self.direction == "positive":
            data_signals.config_changed.emit("general", "Remaining Bottle Volume", round(self.remaining_bottle_volume, 2), True)
        data_signals.config_changed.emit("general", "Container Volume", round(new_container_volume, 2), True)

        self._finalize("FlushOperation finished")
        return