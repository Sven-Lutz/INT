from __future__ import annotations

import os
from typing import Optional

import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QMessageBox

from .frames.top_frame import TopFrame
from .frames.left_frame import LeftFrame
from .frames.right_frame import RightFrame

from src.utils.config_manager import ConfigManager
from src.gui.data import ExperimentWorker, RunParams
from src.backend.core.experimentator import ExperimentConfig
from src.gui.data.parser import FillingInputs, compute_filling


class MainWindow(Qtw.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Little Chonker")
        self.resize(980, 700)

        self.cfg_manager = ConfigManager()
        self.config = self.cfg_manager.load_config("general")

        central = Qtw.QWidget()
        self.setCentralWidget(central)

        layout = Qtw.QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.top = TopFrame(self.config)
        self.left = LeftFrame(self.config)
        self.right = RightFrame(self.config)

        layout.addWidget(self.top)

        left_scroll = Qtw.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(Qtw.QFrame.NoFrame)
        left_scroll.setWidget(self.left)

        splitter = Qtw.QSplitter(Qt.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self.right)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([560, 380])
        layout.addWidget(splitter, 1)

        self._thread: Optional[QThread] = None
        self._worker: Optional[ExperimentWorker] = None

        self.left.start_clicked.connect(self._start_experiment)
        self.left.ok_clicked.connect(self._send_ok)
        self.left.compute_clicked.connect(self._compute_filling_ui)

    def _compute_filling_ui(self) -> None:
        try:
            inputs = FillingInputs(
                target_mbar=float(self.left.ed_fill_target.text()),
                ramp_s=float(self.left.ed_fill_ramp.text()),
                hold_s=float(self.left.ed_fill_hold.text()),
            )
            full_scale = float(self.config.get("pressure_full_scale_mbar", 8000.0))
            comp = compute_filling(inputs, full_scale_mbar=full_scale)

            self.left.lbl_fill_target_pct.setText(f"Target %: {comp.target_pct:.3f}%")
            self.left.lbl_fill_slope.setText(f"Ramp slope: {comp.slope_mbar_per_s:.3f} mbar/s")
            self.left.lbl_fill_suggest.setText(f"Suggested ramp: {comp.suggested_ramp_s:.1f} s")
        except Exception as e:
            QMessageBox.critical(self, "Compute error", str(e))

    def _start_experiment(self) -> None:
        if self._thread is not None:
            QMessageBox.warning(self, "Already running", "An experiment is already running.")
            return

        try:
            run_params = self._read_run_params()
            exp_cfg = self._build_experiment_config()

            self._thread = QThread(self)
            self._worker = ExperimentWorker(exp_cfg)
            self._worker.set_params(run_params)
            self._worker.moveToThread(self._thread)

            self._thread.started.connect(self._worker.run)

            self._worker.request_ok.connect(self._on_request_ok)
            self._worker.status.connect(self._on_status)
            self._worker.step_changed.connect(self._on_step_changed)
            self._worker.loss_updated.connect(self.right.set_loss)

            self._worker.finished.connect(self._on_finished)
            self._worker.failed.connect(self._on_failed)

            self.right.set_busy(True)
            self.left.btn_start.setEnabled(False)
            self.left.enable_ok(False)

            self._thread.start()

        except Exception as e:
            QMessageBox.critical(self, "Start error", str(e))
            self._cleanup_thread()

    def _read_run_params(self) -> RunParams:
        def f(text: str) -> float:
            return float(text)

        def opt_mbar(text: str) -> Optional[float]:
            v = float(text)
            return None if v == 0.0 else v

        return RunParams(
            backwash1_duration_s=f(self.left.ed_backwash1_duration.text()),
            backwash1_pressure_mbar=opt_mbar(self.left.ed_backwash1_pressure.text()),
            filling_target_mbar=f(self.left.ed_fill_target.text()),
            filling_ramp_s=f(self.left.ed_fill_ramp.text()),
            filling_hold_s=f(self.left.ed_fill_hold.text()),
            filtration_duration_s=f(self.left.ed_filtration_duration.text()),
            filtration_pressure_mbar=opt_mbar(self.left.ed_filtration_pressure.text()),
            venting_duration_s=f(self.left.ed_venting_duration.text()),
            backwash2_base_remove_ml=f(self.left.ed_backwash2_base_remove.text()),
            backwash2_pressure_mbar=opt_mbar(self.left.ed_backwash2_pressure.text()),
            backwash2_max_duration_s=f(self.left.ed_backwash2_max_duration.text()),
        )

    def _build_experiment_config(self) -> ExperimentConfig:
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)

        return ExperimentConfig(
            initial_volume_ml=float(self.config.get("initial_volume_ml", 0.0)),
            min_volume_ml=float(self.config.get("min_volume_ml", 0.0)),
            sample_period_s=float(self.config.get("sample_period_s", 0.2)),
            log_dir=log_dir,
            log_name_prefix="run",
            flow_is_ml_per_min=bool(self.config.get("flow_is_ml_per_min", True)),
            pressure_full_scale_mbar=float(self.config.get("pressure_full_scale_mbar", 8000.0)),
            ramp_update_dt_s=float(self.config.get("ramp_update_dt_s", 0.15)),
            base_backwash_remove_ml=float(self.config.get("base_backwash_remove_ml", 0.0)),
        )

    def _on_request_ok(self, step: str, reason: str) -> None:
        self.right.set_status(f"Manual OK required: {reason}")
        self.left.enable_ok(True)
        QMessageBox.information(self, f"OK required: {step}", reason)

    def _send_ok(self) -> None:
        if self._worker is None:
            return
        self.left.enable_ok(False)
        self._worker.confirm_ok()

    def _on_status(self, msg: str) -> None:
        self.right.set_status(msg)

    def _on_step_changed(self, step: str) -> None:
        self.right.set_step(step)

    def _on_finished(self) -> None:
        self.right.set_busy(False)
        self.left.btn_start.setEnabled(True)
        QMessageBox.information(self, "Finished", "Process finished successfully.")
        self._cleanup_thread()

    def _on_failed(self, err: str) -> None:
        self.right.set_busy(False)
        self.left.btn_start.setEnabled(True)
        QMessageBox.critical(self, "Failed", err)
        self._cleanup_thread()

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def closeEvent(self, event) -> None:
        self._cleanup_thread()
        super().closeEvent(event)
