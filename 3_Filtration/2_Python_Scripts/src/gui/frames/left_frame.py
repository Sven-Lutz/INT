from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QLineEdit,
    QLabel,
    QHBoxLayout,
)


class LeftFrame(QFrame):
    start_clicked = Signal()
    ok_clicked = Signal()
    compute_clicked = Signal()

    def __init__(self, config: dict):
        super().__init__()
        self.config = config

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._build_backwash1(root)
        self._build_filling(root)
        self._build_filtration(root)
        self._build_venting(root)
        self._build_backwash2(root)
        self._build_controls(root)

        root.addStretch(1)

    def _gb(self, title: str) -> QGroupBox:
        gb = QGroupBox(title)
        gb.setStyleSheet(
            "QGroupBox { font-weight: 600; } "
            "QLineEdit { padding: 4px; } "
            "QLabel { padding: 2px; }"
        )
        return gb

    def _row(self, grid: QGridLayout, r: int, label: str, w) -> None:
        grid.addWidget(QLabel(label), r, 0)
        grid.addWidget(w, r, 1)

    def _build_backwash1(self, root: QVBoxLayout) -> None:
        gb = self._gb("1) Initial Backwash (manual OK before start)")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.ed_backwash1_duration = QLineEdit(str(self.config.get("backwash1_duration_s", 10)))
        self.ed_backwash1_pressure = QLineEdit(str(self.config.get("backwash1_pressure_mbar", 0)))

        self._row(grid, 0, "Duration (s)", self.ed_backwash1_duration)
        self._row(grid, 1, "Pressure (mbar, 0 = none)", self.ed_backwash1_pressure)

        root.addWidget(gb)

    def _build_filling(self, root: QVBoxLayout) -> None:
        gb = self._gb("2) Filling (linear pressure ramp)")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.ed_fill_target = QLineEdit(str(self.config.get("filling_target_mbar", 300)))
        self.ed_fill_ramp = QLineEdit(str(self.config.get("filling_ramp_s", 10)))
        self.ed_fill_hold = QLineEdit(str(self.config.get("filling_hold_s", 10)))

        self._row(grid, 0, "Target pressure (mbar)", self.ed_fill_target)
        self._row(grid, 1, "Ramp duration (s)", self.ed_fill_ramp)
        self._row(grid, 2, "Hold duration (s)", self.ed_fill_hold)

        self.lbl_fill_target_pct = QLabel("Target %: —")
        self.lbl_fill_slope = QLabel("Ramp slope: —")
        self.lbl_fill_suggest = QLabel("Suggested ramp: —")

        grid.addWidget(self.lbl_fill_target_pct, 3, 0, 1, 2)
        grid.addWidget(self.lbl_fill_slope, 4, 0, 1, 2)
        grid.addWidget(self.lbl_fill_suggest, 5, 0, 1, 2)

        root.addWidget(gb)

    def _build_filtration(self, root: QVBoxLayout) -> None:
        gb = self._gb("3) Filtration")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.ed_filtration_duration = QLineEdit(str(self.config.get("filtration_duration_s", 30)))
        self.ed_filtration_pressure = QLineEdit(str(self.config.get("filtration_pressure_mbar", 300)))

        self._row(grid, 0, "Duration (s)", self.ed_filtration_duration)
        self._row(grid, 1, "Pressure (mbar, 0 = none)", self.ed_filtration_pressure)

        root.addWidget(gb)

    def _build_venting(self, root: QVBoxLayout) -> None:
        gb = self._gb("4) Venting")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.ed_venting_duration = QLineEdit(str(self.config.get("venting_duration_s", 10)))
        self._row(grid, 0, "Duration (s)", self.ed_venting_duration)

        root.addWidget(gb)

    def _build_backwash2(self, root: QVBoxLayout) -> None:
        gb = self._gb("5) Final Backwash (base + loss)")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.ed_backwash2_base_remove = QLineEdit(str(self.config.get("backwash2_base_remove_ml", 0)))
        self.ed_backwash2_pressure = QLineEdit(str(self.config.get("backwash2_pressure_mbar", 0)))
        self.ed_backwash2_max_duration = QLineEdit(str(self.config.get("backwash2_max_duration_s", 300)))

        self._row(grid, 0, "Base remove (mL)", self.ed_backwash2_base_remove)
        self._row(grid, 1, "Pressure (mbar, 0 = none)", self.ed_backwash2_pressure)
        self._row(grid, 2, "Max duration (s)", self.ed_backwash2_max_duration)

        root.addWidget(gb)

    def _build_controls(self, root: QVBoxLayout) -> None:
        box = QGroupBox("Run")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(10)

        self.btn_compute = QPushButton("Compute Filling Output")
        self.btn_start = QPushButton("Start")
        self.btn_ok = QPushButton("OK / Proceed")
        self.btn_ok.setEnabled(False)

        self.btn_compute.clicked.connect(self.compute_clicked.emit)
        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_ok.clicked.connect(self.ok_clicked.emit)

        lay.addWidget(self.btn_compute)
        lay.addWidget(self.btn_start)
        lay.addWidget(self.btn_ok)

        root.addWidget(box)

    def enable_ok(self, enabled: bool) -> None:
        self.btn_ok.setEnabled(bool(enabled))
