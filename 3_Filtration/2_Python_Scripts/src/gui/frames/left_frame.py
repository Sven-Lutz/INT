from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QVBoxLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QDoubleSpinBox,
    QAbstractSpinBox,
)


@dataclass(frozen=True)
class _Ranges:
    max_seconds: float = 24 * 60 * 60
    max_mbar: float = 8000.0
    max_ml: float = 5000.0


class LeftFrame(QFrame):
    start_clicked = Signal()
    ok_clicked = Signal()
    compute_clicked = Signal()

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.ranges = _Ranges(
            max_seconds=float(config.get("max_seconds", _Ranges.max_seconds)),
            max_mbar=float(config.get("pressure_full_scale_mbar", _Ranges.max_mbar)),
            max_ml=float(config.get("max_ml", _Ranges.max_ml)),
        )

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
            "QLabel { padding: 2px; } "
            "QDoubleSpinBox { padding: 2px; }"
        )
        return gb

    def _row(self, grid: QGridLayout, r: int, label: str, w) -> None:
        lab = QLabel(label)
        lab.setMinimumWidth(170)
        grid.addWidget(lab, r, 0)
        grid.addWidget(w, r, 1)

    def _spin_common(
        self,
        *,
        decimals: int,
        min_v: float,
        max_v: float,
        default: float,
        step: float,
        suffix: str,
    ) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setDecimals(int(decimals))
        sb.setRange(float(min_v), float(max_v))
        sb.setValue(float(default))
        sb.setSingleStep(float(step))
        sb.setSuffix(suffix)
        sb.setAccelerated(True)
        sb.setKeyboardTracking(False)
        sb.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        sb.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)
        sb.setGroupSeparatorShown(True)
        sb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return sb

    def _spin_s(self, *, default: float, min_v: float = 0.0, max_v: Optional[float] = None, decimals: int = 1) -> QDoubleSpinBox:
        return self._spin_common(
            decimals=decimals,
            min_v=min_v,
            max_v=self.ranges.max_seconds if max_v is None else max_v,
            default=default,
            step=1.0,
            suffix=" s",
        )

    def _spin_mbar(self, *, default: float, min_v: float = 0.0, max_v: Optional[float] = None, decimals: int = 0) -> QDoubleSpinBox:
        return self._spin_common(
            decimals=decimals,
            min_v=min_v,
            max_v=self.ranges.max_mbar if max_v is None else max_v,
            default=default,
            step=10.0,
            suffix=" mbar",
        )

    def _spin_ml(self, *, default: float, min_v: float = 0.0, max_v: Optional[float] = None, decimals: int = 2) -> QDoubleSpinBox:
        return self._spin_common(
            decimals=decimals,
            min_v=min_v,
            max_v=self.ranges.max_ml if max_v is None else max_v,
            default=default,
            step=0.5,
            suffix=" mL",
        )

    def _build_backwash1(self, root: QVBoxLayout) -> None:
        gb = self._gb("1) Initial Backwash (manual OK before start)")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.sb_backwash1_duration = self._spin_s(default=float(self.config.get("backwash1_duration_s", 10.0)), min_v=0.1)
        self.sb_backwash1_pressure = self._spin_mbar(default=float(self.config.get("backwash1_pressure_mbar", 0.0)), min_v=0.0)

        self._row(grid, 0, "Duration", self.sb_backwash1_duration)
        self._row(grid, 1, "Pressure (0 = none)", self.sb_backwash1_pressure)

        root.addWidget(gb)

    def _build_filling(self, root: QVBoxLayout) -> None:
        gb = self._gb("2) Filling (linear pressure ramp)")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.sb_fill_target = self._spin_mbar(default=float(self.config.get("filling_target_mbar", 300.0)), min_v=0.0)
        self.sb_fill_ramp = self._spin_s(default=float(self.config.get("filling_ramp_s", 10.0)), min_v=0.0, decimals=1)
        self.sb_fill_hold = self._spin_s(default=float(self.config.get("filling_hold_s", 10.0)), min_v=0.0, decimals=1)

        self._row(grid, 0, "Target pressure", self.sb_fill_target)
        self._row(grid, 1, "Ramp duration", self.sb_fill_ramp)
        self._row(grid, 2, "Hold duration", self.sb_fill_hold)

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

        self.sb_filtration_duration = self._spin_s(default=float(self.config.get("filtration_duration_s", 30.0)), min_v=0.0)
        self.sb_filtration_pressure = self._spin_mbar(default=float(self.config.get("filtration_pressure_mbar", 300.0)), min_v=0.0)

        self._row(grid, 0, "Duration", self.sb_filtration_duration)
        self._row(grid, 1, "Pressure (0 = none)", self.sb_filtration_pressure)

        root.addWidget(gb)

    def _build_venting(self, root: QVBoxLayout) -> None:
        gb = self._gb("4) Venting")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.sb_venting_duration = self._spin_s(default=float(self.config.get("venting_duration_s", 10.0)), min_v=0.0)

        self._row(grid, 0, "Duration", self.sb_venting_duration)

        root.addWidget(gb)

    def _build_backwash2(self, root: QVBoxLayout) -> None:
        gb = self._gb("5) Final Backwash (base + loss)")
        grid = QGridLayout(gb)
        grid.setColumnStretch(1, 1)

        self.sb_backwash2_base_remove = self._spin_ml(default=float(self.config.get("backwash2_base_remove_ml", 0.0)), min_v=0.0)
        self.sb_backwash2_pressure = self._spin_mbar(default=float(self.config.get("backwash2_pressure_mbar", 0.0)), min_v=0.0)
        self.sb_backwash2_max_duration = self._spin_s(
            default=float(self.config.get("backwash2_max_duration_s", 300.0)),
            min_v=0.0,
            max_v=self.ranges.max_seconds,
            decimals=1,
        )

        self._row(grid, 0, "Base remove", self.sb_backwash2_base_remove)
        self._row(grid, 1, "Pressure (0 = none)", self.sb_backwash2_pressure)
        self._row(grid, 2, "Max duration", self.sb_backwash2_max_duration)

        root.addWidget(gb)

    def _build_controls(self, root: QVBoxLayout) -> None:
        box = self._gb("Run")
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

        lay.addWidget(self.btn_compute, 2)
        lay.addWidget(self.btn_start, 1)
        lay.addWidget(self.btn_ok, 1)

        root.addWidget(box)

    def enable_ok(self, enabled: bool) -> None:
        self.btn_ok.setEnabled(bool(enabled))

    def _opt_zero(self, v: float) -> Optional[float]:
        return None if abs(float(v)) < 1e-12 else float(v)

    def params(self) -> dict:
        return {
            "backwash1_duration_s": float(self.sb_backwash1_duration.value()),
            "backwash1_pressure_mbar": self._opt_zero(self.sb_backwash1_pressure.value()),
            "filling_target_mbar": float(self.sb_fill_target.value()),
            "filling_ramp_s": float(self.sb_fill_ramp.value()),
            "filling_hold_s": float(self.sb_fill_hold.value()),
            "filtration_duration_s": float(self.sb_filtration_duration.value()),
            "filtration_pressure_mbar": self._opt_zero(self.sb_filtration_pressure.value()),
            "venting_duration_s": float(self.sb_venting_duration.value()),
            "backwash2_base_remove_ml": float(self.sb_backwash2_base_remove.value()),
            "backwash2_pressure_mbar": self._opt_zero(self.sb_backwash2_pressure.value()),
            "backwash2_max_duration_s": float(self.sb_backwash2_max_duration.value()),
        }
