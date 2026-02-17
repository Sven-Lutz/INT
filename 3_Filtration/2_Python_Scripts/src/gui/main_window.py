# src/gui/main_window.py
from __future__ import annotations

import logging
from typing import Optional

import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import QMessageBox

from src.backend.core.experimentator import ExperimentConfig
from src.gui.data import ExperimentWorker, RunParams
from src.gui.data.parser import FillingInputs, compute_filling
from src.gui.monitor.server import MonitorServer
from src.utils.config_manager import ConfigManager
from src.utils.path_utils import ensure_dir, project_root, resolve_under

from .frames.left_frame import LeftFrame
from .frames.right_frame import RightFrame
from .frames.top_frame import TopFrame

logger = logging.getLogger(__name__)


class MainWindow(Qtw.QMainWindow):
    """
    Main GUI window.
    - Uses src.utils.path_utils to resolve project root and logs directory.
    - LeftFrame computes filling outputs locally; MainWindow keeps in sync debounced.
    - Robust error handling: filling compute never crashes UI.
    - Deterministic thread lifecycle cleanup.
    """

    FILLING_DEBOUNCE_MS = 200

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Little Chonker")
        self.resize(980, 700)

        # -------- config --------
        self.cfg_manager = ConfigManager()
        self.config = self.cfg_manager.load_config("general")

        # -------- UI root --------
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
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(self.left)

        splitter = Qtw.QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self.right)
        splitter.setSizes([560, 380])
        layout.addWidget(splitter, 1)

        # -------- worker thread --------
        self._thread: Optional[QThread] = None
        self._worker: Optional[ExperimentWorker] = None

        # -------- filling debounce --------
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.timeout.connect(self._on_fill_timer_timeout)

        # -------- monitor --------
        self.monitor: Optional[MonitorServer] = None
        self._start_monitor()

        # -------- signals --------
        self.left.start_clicked.connect(self._start_experiment)
        self.left.ok_clicked.connect(self._send_ok)

        # LeftFrame already computes locally; we use this only to keep MainWindow-side compute in sync (debounced)
        self.left.compute_clicked.connect(self._schedule_filling_compute)

        self._apply_style()

        # Initial compute (silent; safe even if LeftFrame already did it)
        self._compute_filling_ui(silent=True)

    # ---------------- UI styling ----------------

    def _apply_style(self) -> None:
        self.setStyleSheet(
            "QMainWindow { background: #f6f7fb; }"
            "QGroupBox { background: white; border: 1px solid #e5e7eb; border-radius: 10px; margin-top: 8px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }"
            "QScrollArea { background: transparent; }"
            "QFrame { background: transparent; }"
        )

    # ---------------- Monitor ----------------

    def _start_monitor(self) -> None:
        enabled = bool(self.config.get("monitor_enabled", True))
        if not enabled:
            return

        host = str(self.config.get("monitor_host", "0.0.0.0"))
        port = int(self.config.get("monitor_port", 8765))

        try:
            self.monitor = MonitorServer(host=host, port=port)
            self.monitor.start()
            try:
                self.right.set_qr_url(self.monitor.url())
            except Exception:
                logger.exception("Monitor started, but RightFrame.set_qr_url failed.")
        except Exception:
            logger.exception("Monitor start failed (host=%s, port=%s). Disabling monitor.", host, port)
            self.monitor = None

    # ---------------- Filling helper ----------------

    def _on_fill_timer_timeout(self) -> None:
        self._compute_filling_ui(silent=True)

    def _schedule_filling_compute(self, *args, **kwargs) -> None:
        self._fill_timer.start(self.FILLING_DEBOUNCE_MS)

    def _compute_filling_ui(self, *, silent: bool = False) -> None:
        """
        Compute filling outputs purely from UI values (no hardware).
        This is a UI consistency feature; LeftFrame also computes locally.
        """
        try:
            target_sb = getattr(self.left, "sb_fill_target", None)
            ramp_sb = getattr(self.left, "sb_fill_ramp", None)
            hold_sb = getattr(self.left, "sb_fill_hold", None)
            if target_sb is None or ramp_sb is None or hold_sb is None:
                return

            inputs = FillingInputs(
                target_mbar=float(target_sb.value()),
                ramp_s=float(ramp_sb.value()),
                hold_s=float(hold_sb.value()),
            )

            full_scale = float(self.config.get("pressure_full_scale_mbar", 8000.0))
            if full_scale <= 0:
                full_scale = 8000.0

            comp = compute_filling(inputs, full_scale_mbar=full_scale)

            if hasattr(self.left, "set_filling_outputs"):
                self.left.set_filling_outputs(
                    target_pct=float(comp.target_pct),
                    slope_mbar_s=float(comp.slope_mbar_per_s),
                    suggested_ramp_s=float(comp.suggested_ramp_s),
                )
            else:
                getattr(self.left, "lbl_fill_target_pct").setText(f"Target %: {comp.target_pct:.3f}%")
                getattr(self.left, "lbl_fill_slope").setText(f"Ramp slope: {comp.slope_mbar_per_s:.3f} mbar/s")
                getattr(self.left, "lbl_fill_suggest").setText(f"Suggested ramp: {comp.suggested_ramp_s:.1f} s")

        except Exception as e:
            logger.exception("Filling compute failed.")
            try:
                if hasattr(self.left, "set_filling_outputs"):
                    self.left.set_filling_outputs(target_pct=None, slope_mbar_s=None, suggested_ramp_s=None)
                else:
                    getattr(self.left, "lbl_fill_target_pct").setText("Target %: —")
                    getattr(self.left, "lbl_fill_slope").setText("Ramp slope: —")
                    getattr(self.left, "lbl_fill_suggest").setText("Suggested ramp: —")
            except Exception:
                pass

            if not silent:
                QMessageBox.critical(self, "Compute error", str(e))

    # ---------------- Experiment config ----------------

    def _read_run_params(self) -> RunParams:
        p = self.left.params()
        return RunParams(
            backwash1_duration_s=float(p["backwash1_duration_s"]),
            backwash1_pressure_mbar=p["backwash1_pressure_mbar"],
            filling_target_mbar=float(p["filling_target_mbar"]),
            filling_ramp_s=float(p["filling_ramp_s"]),
            filling_hold_s=float(p["filling_hold_s"]),
            filtration_duration_s=float(p["filtration_duration_s"]),
            filtration_pressure_mbar=p["filtration_pressure_mbar"],
            venting_duration_s=float(p["venting_duration_s"]),
            backwash2_base_remove_ml=float(p["backwash2_base_remove_ml"]),
            backwash2_pressure_mbar=p["backwash2_pressure_mbar"],
            backwash2_max_duration_s=float(p["backwash2_max_duration_s"]),
        )

    def _build_experiment_config(self) -> ExperimentConfig:
        # IMPORTANT: project_root expects an anchor; pass __file__ of THIS file.
        root = project_root(__file__)

        # logs folder at repo root
        log_dir = resolve_under(root, "logs")
        ensure_dir(log_dir)

        return ExperimentConfig(
            initial_volume_ml=float(self.config.get("initial_volume_ml", 0.0)),
            min_volume_ml=float(self.config.get("min_volume_ml", 0.0)),
            sample_period_s=float(self.config.get("sample_period_s", 0.2)),
            log_dir=str(log_dir),
            log_name_prefix="run",
            flow_is_ml_per_min=bool(self.config.get("flow_is_ml_per_min", True)),
            pressure_full_scale_mbar=float(self.config.get("pressure_full_scale_mbar", 8000.0)),
            ramp_update_dt_s=float(self.config.get("ramp_update_dt_s", 0.15)),
            base_backwash_remove_ml=float(self.config.get("base_backwash_remove_ml", 0.0)),
        )

    # ---------------- Run control ----------------

    def _start_experiment(self) -> None:
        if self._thread is not None:
            QMessageBox.warning(self, "Already running", "An experiment is already running.")
            return

        try:
            run_params = self._read_run_params()
            exp_cfg = self._build_experiment_config()

            thread = QThread(self)
            worker = ExperimentWorker(exp_cfg)
            worker.set_params(run_params)
            worker.moveToThread(thread)

            thread.started.connect(worker.run)

            worker.request_ok.connect(self._on_request_ok)
            worker.status.connect(self._on_status)
            worker.step_changed.connect(self._on_step_changed)
            worker.loss_updated.connect(self.right.set_loss)

            if hasattr(worker, "telemetry") and hasattr(self.right, "ingest_telemetry"):
                try:
                    worker.telemetry.connect(self.right.ingest_telemetry)  # type: ignore[attr-defined]
                except Exception:
                    logger.exception("Telemetry connect failed (non-fatal).")

            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)

            worker.finished.connect(self._on_finished)
            worker.failed.connect(self._on_failed)

            self._thread = thread
            self._worker = worker

            self.right.set_busy(True)
            self.left.btn_start.setEnabled(False)
            self.left.enable_ok(False)

            thread.start()

        except Exception as e:
            logger.exception("Start experiment failed.")
            QMessageBox.critical(self, "Start error", str(e))
            self._cleanup_thread()

    def _on_request_ok(self, step: str, reason: str) -> None:
        self.right.set_status(f"Manual OK required: {reason}")
        self.left.enable_ok(True)
        QMessageBox.information(self, f"OK required: {step}", reason)

    def _send_ok(self) -> None:
        if self._worker is None:
            return
        self.left.enable_ok(False)
        try:
            self._worker.confirm_ok()
        except Exception:
            logger.exception("confirm_ok failed.")
            QMessageBox.critical(self, "Error", "Failed to send OK to the worker.")

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

    # ---------------- Cleanup ----------------

    def _cleanup_thread(self) -> None:
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None

        if worker is not None:
            try:
                t = worker.thread()
                if isinstance(t, QThread):
                    t.requestInterruption()
            except Exception:
                pass

        if thread is not None:
            try:
                thread.quit()
                thread.wait(2000)
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        try:
            self._fill_timer.stop()
        except Exception:
            pass

        self._cleanup_thread()

        try:
            if self.monitor is not None:
                try:
                    self.monitor.stop()
                except Exception:
                    logger.exception("Monitor stop failed (non-fatal).")
                self.monitor = None
        finally:
            super().closeEvent(event)
