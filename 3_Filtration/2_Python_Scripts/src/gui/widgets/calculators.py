from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QFrame, QVBoxLayout, QGridLayout, QLabel
import math

from src.gui.widgets.nudge_spinbox import NudgeSpinBox

#     def __init__(self, minimum: float, maximum: float, decimals: int, step: float, suffix: str, value: float):
class ExperimentSetupWidget(QFrame):

    setup_changed = Signal()
    setup_calculated = Signal(float, float)
    ramp_calculated = Signal(int, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "card")

        self._current_bnnt_ml = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(15)

        lbl_p0 = QLabel("PHASE 0: BACKWASH")
        lbl_p0.setStyleSheet("font-size: 11px; font-weight: bold; color: #EC4899; letter-spacing: 1.5px; border: none; font-family: 'Consolas', monospace;")
        lay.addWidget(lbl_p0)
        
        grid0 = QGridLayout()
        grid0.setSpacing(10)

        self.sp_area = NudgeSpinBox(1.0, 2000.0, 1, 10.0, " mm²", 1134.0)
        self.sp_calib = NudgeSpinBox(0.01, 100.0, 4, 0.1, " nm/µl", 2.5)
        self.sp_thickness = NudgeSpinBox(1.0, 1000.0, 1, 1.0, " nm", 100.0)
        self.sp_h2o = NudgeSpinBox(0.0, 10000.0, 2, 100.0, " ml", 1400.0)

        grid0.addWidget(self._mk_lbl("Film Area (A)"), 0, 0); grid0.addWidget(self.sp_area, 0, 1)
        grid0.addWidget(self._mk_lbl("Calibration (C)"), 1, 0); grid0.addWidget(self.sp_calib, 1, 1)
        grid0.addWidget(self._mk_lbl("Desired Thickness (FT)"), 2, 0); grid0.addWidget(self.sp_thickness, 2, 1)
        grid0.addWidget(self._mk_lbl("H2O Volume"), 3, 0); grid0.addWidget(self.sp_h2o, 3, 1)
        lay.addLayout(grid0)

        self.lbl_bnnt_res = QLabel("Req. BNNT: - ml")
        self.lbl_bnnt_res.setStyleSheet("color: #00E676; font-family: 'Consolas', monospace; font-size: 13px; font-weight: bold;")
        lay.addWidget(self.lbl_bnnt_res)

        lbl_pa = QLabel("PHASE A: RAMP UP")
        lbl_pa.setStyleSheet("font-size: 11px; font-weight: bold; color: #8B5CF6; letter-spacing: 1.5px; border: none; font-family: 'Consolas', monospace; padding-top: 10px;")
        lay.addWidget(lbl_pa)

        gridA = QGridLayout()
        gridA.setSpacing(10)

        self.sp_target_p = NudgeSpinBox(0.0, 2000.0, 0, 100.0, " mbar", 2000.0)
        self.sp_step_size = NudgeSpinBox(1.0, 250.0, 0, 10.0, " mbar", 250.0)
        self.sp_step_time = NudgeSpinBox(0.1, 120.0, 1, 1.0, " min", 2.0)

        gridA.addWidget(self._mk_lbl("Target Pressure"), 0, 0); gridA.addWidget(self.sp_target_p, 0, 1)
        gridA.addWidget(self._mk_lbl("Step Size"), 1, 0); gridA.addWidget(self.sp_step_size, 1, 1)
        gridA.addWidget(self._mk_lbl("Time per Step"), 2, 0); gridA.addWidget(self.sp_step_time, 2, 1)
        lay.addLayout(gridA)

        self.lbl_ramp_res = QLabel("Total: - Steps | ETA: - min")
        self.lbl_ramp_res.setStyleSheet("color: #00E5FF; font-family: 'Consolas', monospace; font-size: 13px; font-weight: bold;")
        lay.addWidget(self.lbl_ramp_res)

        for w in [self.sp_area, self.sp_calib, self.sp_thickness, self.sp_h2o]:
            w.valueChanged.connect(self._recalc_phase0)
        for w in [self.sp_target_p, self.sp_step_size, self.sp_step_time]:
            w.valueChanged.connect(self._recalc_phaseA)

        self._recalc_phase0()
        self._recalc_phaseA()

    def _mk_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #A0AEC0; font-size: 11px; font-family: 'Consolas', monospace; border: none;")
        return lbl
    
    @Slot()
    def _recalc_phase0(self):
        a, c, ft, h2o = self.sp_area.value(), self.sp_calib.value(), self.sp_thickness.value(), self.sp_h2o.value()
        if c == 0: return
        v_bnnt_ul = (ft / c) * (a / 1134.0)
        v_bnnt_ml = v_bnnt_ul / 1000.0
        self._current_bnnt_ml = v_bnnt_ml
        self.lbl_bnnt_res.setText(f"Req. BNNT: {v_bnnt_ml:.4f} ml")
        self.setup_calculated.emit(v_bnnt_ml, h2o)
        self.setup_changed.emit()

    @Slot()
    def _recalc_phaseA(self):
        target, step, t_min = self.sp_target_p.value(), self.sp_step_size.value(), self.sp_step_time.value()
        if step == 0: return

        num_steps = math.ceil(target / step)
        total_time_min = num_steps * t_min
        self.lbl_ramp_res.setText(f"Total: {num_steps} Steps | ETA: {total_time_min:.2f} min")
        self.ramp_calculated.emit(num_steps, total_time_min * 60)
        self.setup_changed.emit()

    def get_v_bnnt_ml(self) -> float:
        return self._current_bnnt_ml

    def setEnabled(self, val: bool):
        super().setEnabled(val)
        for w in [self.sp_area, self.sp_calib, self.sp_thickness, self.sp_h2o, self.sp_target_p, self.sp_step_size, self.sp_step_time]:
            w.setEnabled(val)