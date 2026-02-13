from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from src.backend.core.experimentator import Experimentator
from src.backend.core.device_manager import DeviceManager, DeviceManagerOptions
from src.backend.core.experimentator import ExperimentConfig


class Step(str, Enum):
    BACKWASH_INITIAL = "BACKWASH_INITIAL"
    FILLING = "FILLING"
    FILTRATION = "FILTRATION"
    VENTING = "VENTING"
    BACKWASH_FINAL = "BACKWASH_FINAL"
    FINISHED = "FINISHED"


@dataclass
class RunParams:
    backwash1_duration_s: float
    backwash1_pressure_mbar: Optional[float]

    filling_target_mbar: float
    filling_ramp_s: float
    filling_hold_s: float

    filtration_duration_s: float
    filtration_pressure_mbar: Optional[float]

    venting_duration_s: float

    backwash2_base_remove_ml: float
    backwash2_pressure_mbar: Optional[float]
    backwash2_max_duration_s: float


class ExperimentWorker(QObject):
    request_ok = Signal(str, str)
    status = Signal(str)
    step_changed = Signal(str)
    loss_updated = Signal(float)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, cfg: ExperimentConfig):
        super().__init__()
        self.cfg = cfg
        self._ok_event = threading.Event()
        self._ok_event.clear()
        self._params: Optional[RunParams] = None

    def set_params(self, params: RunParams) -> None:
        self._params = params

    def confirm_ok(self) -> None:
        self._ok_event.set()

    def _wait_ok(self, step: Step, reason: str) -> None:
        self._ok_event.clear()
        self.step_changed.emit(step.value)
        self.status.emit(f"Waiting for OK: {reason}")
        self.request_ok.emit(step.value, reason)
        self._ok_event.wait()

    def run(self) -> None:
        try:
            if self._params is None:
                raise RuntimeError("RunParams not set")

            p = self._params

            opts = DeviceManagerOptions(enable_pressure=True, enable_flow=True)
            self.status.emit("Initializing DeviceManager")
            with DeviceManager(opts) as dev:
                exp = Experimentator(dev, self.cfg)

                try:
                    self._wait_ok(Step.BACKWASH_INITIAL, "Perform initial backwash (setup check) and confirm")
                    self.status.emit("Running initial backwash")
                    exp.step_backwash_manual_then_run(
                        ok_fn=lambda: True,
                        duration_s=p.backwash1_duration_s,
                        pressure_mbar=p.backwash1_pressure_mbar,
                    )

                    self._wait_ok(Step.FILLING, "Confirm filling parameters and start filling")
                    self.status.emit("Running filling")
                    exp.step_filling_with_linear_ramp(
                        target_pressure_mbar=p.filling_target_mbar,
                        ramp_duration_s=p.filling_ramp_s,
                        hold_duration_s=p.filling_hold_s,
                    )

                    self._wait_ok(Step.FILTRATION, "Confirm filtration parameters and start filtration")
                    self.status.emit("Running filtration")
                    exp._run_timed_step(
                        mode="FILTRATION",
                        duration_s=p.filtration_duration_s,
                        pressure_channel=1 if dev.pressure_controller is not None else None,
                        net_sign=-1.0,
                        set_valves=dev.valves_filtration,
                        event_start="START_FILTRATION_UI",
                        event_end="END_FILTRATION_UI",
                    )

                    self._wait_ok(Step.VENTING, "Confirm venting duration and start venting")
                    self.status.emit("Running venting")
                    exp._run_timed_step(
                        mode="VENTING",
                        duration_s=p.venting_duration_s,
                        pressure_channel=None,
                        net_sign=-1.0,
                        set_valves=dev.venting,
                        event_start="START_VENTING_UI",
                        event_end="END_VENTING_UI",
                    )

                    loss_ml = exp.last_filtration_venting_loss_ml
                    self.loss_updated.emit(loss_ml)

                    self._wait_ok(Step.BACKWASH_FINAL, "Confirm final backwash target (base + loss) and start")
                    self.status.emit("Running final backwash (remove volume)")
                    removed = exp.step_backwash_remove_volume(
                        base_remove_ml=p.backwash2_base_remove_ml,
                        add_previous_loss=True,
                        max_duration_s=p.backwash2_max_duration_s,
                        backwash_pressure_mbar=p.backwash2_pressure_mbar,
                    )
                    self.status.emit(f"Final backwash completed (removed {removed:.3f} mL)")

                finally:
                    exp.close()

            self.step_changed.emit(Step.FINISHED.value)
            self.status.emit("Process finished")
            self.finished.emit()

        except Exception as e:
            self.failed.emit(str(e))
