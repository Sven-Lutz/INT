# src/gui/frames/left_frame.py
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

# Local, UI-only compute fallback (must never require hardware)
from src.gui.data.parser import FillingInputs, compute_filling

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Ranges:
    max_seconds: float = 24 * 60 * 60
    max_mbar: float = 8000.0
    max_ml: float = 5000.0


@dataclass(frozen=True)
class _SpinSpec:
    decimals: int
    min_v: float
    max_v: float
    default: float
    step: float
    suffix: str


class LeftFrame(QFrame):
    start_clicked = Signal()
    ok_clicked = Signal()
    compute_clicked = Signal()

    _LABEL_MIN_W = 170
    _GB_STYLE = "QGroupBox { font-weight: 600; } QLabel { padding: 2px; }"

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

        # Auto compute + local fallback
        self._wire_filling_autocompute()
        self._compute_filling_local(silent=True)

    # -------------------- UI helpers --------------------

    def _gb(self, title: str) -> QGroupBox:
        gb = QGroupBox(title)
        gb.setStyleSheet(self._GB_STYLE)
        return gb

    def _mk_grid(self, parent: QGroupBox) -> QGridLayout:
        grid = QGridLayout(parent)
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        return grid

    def _row(self, grid: QGridLayout, r: int, label: str, w) -> None:
        lab = QLabel(label)
        lab.setMinimumWidth(self._LABEL_MIN_W)
        grid.addWidget(lab, r, 0)
        grid.addWidget(w, r, 1)

    def _spin(self, spec: _SpinSpec) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setDecimals(int(spec.decimals))
        sb.setRange(float(spec.min_v), float(spec.max_v))
        sb.setValue(float(spec.default))
        sb.setSingleStep(float(spec.step))
        sb.setSuffix(spec.suffix)

        sb.setAccelerated(True)
        sb.setKeyboardTracking(False)
        sb.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        sb.setCorrectionMode(QAbstractSpinBox.CorrectToNearestValue)

        try:
            sb.setGroupSeparatorShown(False)
        except Exception:
            pass

        sb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sb.setFocusPolicy(Qt.StrongFocus)
        sb.setStyleSheet("")  # do not break arrow hitboxes on Windows
        return sb

    def _spin_s(
        self,
        *,
        default: float,
        min_v: float = 0.0,
        max_v: Optional[float] = None,
        decimals: int = 1,
        step: float = 1.0,
    ) -> QDoubleSpinBox:
        return self._spin(
            _SpinSpec(
                decimals=int(decimals),
                min_v=float(min_v),
                max_v=float(self.ranges.max_seconds if max_v is None else max_v),
                default=float(default),
                step=float(step),
                suffix=" s",
            )
        )

    def _spin_mbar(
        self,
        *,
        default: float,
        min_v: float = 0.0,
        max_v: Optional[float] = None,
        decimals: int = 0,
        step: float = 10.0,
    ) -> QDoubleSpinBox:
        return self._spin(
            _SpinSpec(
                decimals=int(decimals),
                min_v=float(min_v),
                max_v=float(self.ranges.max_mbar if max_v is None else max_v),
                default=float(default),
                step=float(step),
                suffix=" mbar",
            )
        )

    def _spin_ml(
        self,
        *,
        default: float,
        min_v: float = 0.0,
        max_v: Optional[float] = None,
        decimals: int = 2,
        step: float = 0.5,
    ) -> QDoubleSpinBox:
        return self._spin(
            _SpinSpec(
                decimals=int(decimals),
                min_v=float(min_v),
                max_v=float(self.ranges.max_ml if max_v is None else max_v),
                default=float(default),
                step=float(step),
                suffix=" mL",
            )
        )

    # -------------------- Filling compute wiring --------------------

    def _wire_filling_autocompute(self) -> None:
        """
        Avoid lambdas here: PySide signal overloads can behave oddly on Windows.
        Directly connect to the slot.
        """
        for sb in (self.sb_fill_target, self.sb_fill_ramp, self.sb_fill_hold):
            try:
                sb.valueChanged.connect(self._on_compute_clicked)  # type: ignore[arg-type]
            except Exception:
                pass

    def _on_compute_clicked(self) -> None:
        """
        Always do local compute, and then (optionally) notify MainWindow.
        """
        logger.info("LeftFrame: Compute Filling Output triggered")

        # 1) local compute (guaranteed)
        self._compute_filling_local(silent=False)

        # 2) notify MainWindow (optional hook)
        try:
            self.compute_clicked.emit()
        except Exception:
            pass

    def _compute_filling_local(self, *, silent: bool) -> None:
        try:
            inputs = FillingInputs(
                target_mbar=float(self.sb_fill_target.value()),
                ramp_s=float(self.sb_fill_ramp.value()),
                hold_s=float(self.sb_fill_hold.value()),
            )
            full_scale = float(self.ranges.max_mbar if self.ranges.max_mbar > 0 else 8000.0)
            comp = compute_filling(inputs, full_scale_mbar=full_scale)

            self.set_filling_outputs(
                target_pct=float(comp.target_pct),
                slope_mbar_s=float(comp.slope_mbar_per_s),
                suggested_ramp_s=float(comp.suggested_ramp_s),
            )
        except Exception:
            # Never throw UI exceptions for this feature
            self.set_filling_outputs(target_pct=None, slope_mbar_s=None, suggested_ramp_s=None)
            if not silent:
                logger.error("LeftFrame: compute_filling failed:\n%s", traceback.format_exc())

    # -------------------- Sections --------------------

    def _build_backwash1(self, root: QVBoxLayout) -> None:
        gb = self._gb("1) Initial Backwash (manual OK before start)")
        grid = self._mk_grid(gb)

        self.sb_backwash1_duration = self._spin_s(
            default=float(self.config.get("backwash1_duration_s", 10.0)),
            min_v=0.1,
            decimals=1,
        )
        self.sb_backwash1_pressure = self._spin_mbar(
            default=float(self.config.get("backwash1_pressure_mbar", 0.0)),
            min_v=0.0,
            decimals=0,
        )

        self._row(grid, 0, "Duration", self.sb_backwash1_duration)
        self._row(grid, 1, "Pressure (0 = none)", self.sb_backwash1_pressure)

        root.addWidget(gb)

    def _build_filling(self, root: QVBoxLayout) -> None:
        gb = self._gb("2) Filling (linear pressure ramp)")
        grid = self._mk_grid(gb)

        self.sb_fill_target = self._spin_mbar(
            default=float(self.config.get("filling_target_mbar", 300.0)),
            min_v=0.0,
            decimals=0,
            step=10.0,
        )
        self.sb_fill_ramp = self._spin_s(
            default=float(self.config.get("filling_ramp_s", 10.0)),
            min_v=0.0,
            decimals=1,
            step=1.0,
        )
        self.sb_fill_hold = self._spin_s(
            default=float(self.config.get("filling_hold_s", 10.0)),
            min_v=0.0,
            decimals=1,
            step=1.0,
        )

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
        grid = self._mk_grid(gb)

        self.sb_filtration_duration = self._spin_s(
            default=float(self.config.get("filtration_duration_s", 30.0)),
            min_v=0.0,
            decimals=1,
        )
        self.sb_filtration_pressure = self._spin_mbar(
            default=float(self.config.get("filtration_pressure_mbar", 300.0)),
            min_v=0.0,
            decimals=0,
        )

        self._row(grid, 0, "Duration", self.sb_filtration_duration)
        self._row(grid, 1, "Pressure (0 = none)", self.sb_filtration_pressure)

        root.addWidget(gb)

    def _build_venting(self, root: QVBoxLayout) -> None:
        gb = self._gb("4) Venting")
        grid = self._mk_grid(gb)

        self.sb_venting_duration = self._spin_s(
            default=float(self.config.get("venting_duration_s", 10.0)),
            min_v=0.0,
            decimals=1,
        )

        self._row(grid, 0, "Duration", self.sb_venting_duration)
        root.addWidget(gb)

    def _build_backwash2(self, root: QVBoxLayout) -> None:
        gb = self._gb("5) Final Backwash (base + loss)")
        grid = self._mk_grid(gb)

        self.sb_backwash2_base_remove = self._spin_ml(
            default=float(self.config.get("backwash2_base_remove_ml", 0.0)),
            min_v=0.0,
            decimals=2,
            step=0.5,
        )
        self.sb_backwash2_pressure = self._spin_mbar(
            default=float(self.config.get("backwash2_pressure_mbar", 0.0)),
            min_v=0.0,
            decimals=0,
        )
        self.sb_backwash2_max_duration = self._spin_s(
            default=float(self.config.get("backwash2_max_duration_s", 300.0)),
            min_v=0.0,
            max_v=self.ranges.max_seconds,
            decimals=1,
            step=1.0,
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

        # Direct connections (avoid lambdas)
        self.btn_compute.clicked.connect(self._on_compute_clicked)
        self.btn_start.clicked.connect(self.start_clicked.emit)
        self.btn_ok.clicked.connect(self.ok_clicked.emit)

        lay.addWidget(self.btn_compute, 2)
        lay.addWidget(self.btn_start, 1)
        lay.addWidget(self.btn_ok, 1)

        root.addWidget(box)

    # -------------------- Public helpers --------------------

    def enable_ok(self, enabled: bool) -> None:
        self.btn_ok.setEnabled(bool(enabled))

    def set_filling_outputs(
        self,
        *,
        target_pct: Optional[float] = None,
        slope_mbar_s: Optional[float] = None,
        suggested_ramp_s: Optional[float] = None,
    ) -> None:
        self.lbl_fill_target_pct.setText(self._fmt_target_pct(target_pct))
        self.lbl_fill_slope.setText(self._fmt_slope(slope_mbar_s))
        self.lbl_fill_suggest.setText(self._fmt_suggested_ramp(suggested_ramp_s))

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

    # -------------------- Formatting helpers --------------------

    @staticmethod
    def _opt_zero(v: float) -> Optional[float]:
        return None if abs(float(v)) < 1e-12 else float(v)

    @staticmethod
    def _fmt_target_pct(v: Optional[float]) -> str:
        return "Target %: —" if v is None else f"Target %: {float(v):.3f}%"

    @staticmethod
    def _fmt_slope(v: Optional[float]) -> str:
        return "Ramp slope: —" if v is None else f"Ramp slope: {float(v):.3f} mbar/s"

    @staticmethod
    def _fmt_suggested_ramp(v: Optional[float]) -> str:
        return "Suggested ramp: —" if v is None else f"Suggested ramp: {float(v):.1f} s"
