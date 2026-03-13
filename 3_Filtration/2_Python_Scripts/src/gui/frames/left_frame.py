from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
import math
from PySide6.QtCore import Signal, Slot, Qt, QTimer
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QGridLayout, QWidget, QComboBox, QPushButton
)
from src.gui.data.worker import RunParams
from src.gui.widgets.hold_button import HoldButton
from src.gui.widgets.nudge_spinbox import NudgeSpinBox

class EliteModule(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, accent_color: str, checkable: bool = False, default_checked: bool = True):
        super().__init__()
        self.accent = accent_color
        self.checkable = checkable
        self._is_active = default_checked if checkable else True
        self._is_running_highlight = False

        self.main_lay = QVBoxLayout(self)
        self.main_lay.setContentsMargins(0, 0, 0, 0)
        self.main_lay.setSpacing(0)

        self.header = QFrame()
        self.header.setFixedHeight(26)
        if self.checkable:
            self.header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.header.mousePressEvent = self._on_header_click

        self.h_lay = QHBoxLayout(self.header)
        self.h_lay.setContentsMargins(12, 0, 12, 0)

        self.lbl_title = QLabel(title.upper())
        self.lbl_status = QLabel("ACTIVE" if self._is_active else "SKIPPED")
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        if not self.checkable:
            self.lbl_status.setText("LOCKED")

        self.h_lay.addWidget(self.lbl_title)
        self.h_lay.addStretch()
        if self.checkable:
            self.h_lay.addWidget(self.lbl_status)

        self.main_lay.addWidget(self.header)

        self.content = QFrame()
        self.content.setStyleSheet("background-color: transparent; border: none;")
        self.content_lay = QGridLayout(self.content)
        self.content_lay.setContentsMargins(12, 12, 12, 12)
        self.content_lay.setSpacing(6)
        self.main_lay.addWidget(self.content)

        self._apply_state_styles()

    def _on_header_click(self, event):
        if not self.checkable: return
        self._is_active = not self._is_active
        self._apply_state_styles()
        self.toggled.emit(self._is_active)

    def _apply_state_styles(self):
        if self._is_running_highlight:
            head_bg = self.accent
            head_text = "#000000"
            status_text = "RUNNING"
            status_col = "#000000"
            border_col = self.accent
            border_width = "2px"
        elif self._is_active:
            head_bg = "#111827" 
            head_text = self.accent
            status_text = "ACTIVE"
            status_col = self.accent
            border_col = self.accent
            border_width = "1px"
        else:
            head_bg = "#050914"
            head_text = "#334155"
            status_text = "SKIPPED"
            status_col = "#334155"
            border_col = "#1E293B"
            border_width = "1px"

        self.header.setStyleSheet(f"background-color: {head_bg}; border-top-left-radius: 3px; border-top-right-radius: 3px; border-bottom: 1px solid {border_col};")
        self.lbl_title.setStyleSheet(f"color: {head_text}; font-family: 'Consolas'; font-size: 10px; font-weight: bold; letter-spacing: 1px; border: none; background: transparent;")
        if self.checkable:
            self.lbl_status.setText(status_text)
            self.lbl_status.setStyleSheet(f"color: {status_col}; font-family: 'Consolas'; font-size: 9px; font-weight: bold; border: none; background: transparent;")
        
        self.setStyleSheet(f"EliteModule {{ background-color: #090F16; border: {border_width} solid {border_col}; border-radius: 4px; margin-bottom: 6px; }}")

        for i in range(self.content_lay.count()):
            item = self.content_lay.itemAt(i)
            if item is None: continue
            w = item.widget()
            if w:
                w.setEnabled(self._is_active)
                if isinstance(w, QLabel) and not w.property("is_dynamic_result"):
                    w.setStyleSheet(f"color: {'#94A3B8' if self._is_active else '#334155'}; font-family: 'Consolas'; font-size: 11px; border: none;")

    def setHighlight(self, is_running: bool):
        self._is_running_highlight = is_running
        self._apply_state_styles()

    def isChecked(self) -> bool:
        return self._is_active

    def addRow(self, row: int, label_text: str, widget: QWidget):
        lbl = QLabel(label_text)
        lbl.setStyleSheet("color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.content_lay.addWidget(lbl, row, 0)
        self.content_lay.addWidget(widget, row, 1)


class LeftFrame(QFrame):
    params_changed = Signal(RunParams)
    server_toggle_requested = Signal(bool) # Signal für die main.py

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")
        
        self._hold_active = False
        self._hold_allowed = True
        self._is_running = False

        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._on_countdown_tick)
        self._active_phase_key = ""
        self._time_left_s = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(6)

        # MANUAL HOLD
        self.grp_manual = QFrame()
        self.grp_manual.setStyleSheet("QFrame { background: #0B1120; border-radius: 4px; border: 1px solid #1E293B; border-top: 2px solid #EC4899; margin-bottom: 4px; }")
        lay_manual = QVBoxLayout(self.grp_manual)
        lay_manual.setContentsMargins(12, 12, 12, 12)
        lay_manual.setSpacing(8)
        
        self.btn_hold = HoldButton("HOLD SPACE TO BACKWASH")
        self.btn_hold.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sp_hold_p = NudgeSpinBox(0, 8000, 0, 25, " mbar", 300.0)
        
        lay_manual.addWidget(self.btn_hold)
        h_row = QHBoxLayout()
        lbl_p = QLabel("Pressure:")
        lbl_p.setStyleSheet("color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        h_row.addWidget(lbl_p); h_row.addWidget(self.sp_hold_p)
        lay_manual.addLayout(h_row)
        root.addWidget(self.grp_manual)

        # BNNT KALIBRIERUNG
        self.mod_calc = EliteModule("BNNT PARAMETERS", "#64748B", checkable=False)
        self.sp_area = NudgeSpinBox(1.0, 70000.0, 1, 10.0, " mm²", 49480.0)
        self.sp_calib = NudgeSpinBox(0.001, 10.0, 8, 0.1, " nm/µl", 0.06314815)
        self.sp_thick = NudgeSpinBox(1.0, 1000.0, 1, 1.0, " nm", 100.0)
        
        self.mod_calc.addRow(0, "Film Area (A):", self.sp_area)
        self.mod_calc.addRow(1, "Calibration (C):", self.sp_calib)
        self.mod_calc.addRow(2, "Desired Thick.:", self.sp_thick)
        
        self.lbl_bnnt = QLabel("Req. BNNT: — ml")
        self.lbl_bnnt.setProperty("is_dynamic_result", True)
        self.lbl_bnnt.setStyleSheet("color: #10B981; font-weight: bold; font-family: 'Consolas'; font-size: 12px; border: none; padding-top: 4px;")
        self.mod_calc.content_lay.addWidget(self.lbl_bnnt, 3, 0, 1, 2)
        root.addWidget(self.mod_calc)

        # STATE 0: FILLING SOLUTION
        self.mod_p0 = EliteModule("STATE 0: FILLING SOLUTION", "#00E5FF", checkable=True)
        
        self.cmb_fill_mode = QComboBox()
        self.cmb_fill_mode.addItems(["Auto (Fill Target Vol)", "Continuous (Wait for Click)"])
        self.cmb_fill_mode.setStyleSheet("background: #0F172A; color: #FFF; border: 1px solid #1E293B; font-family: 'Consolas'; padding: 2px;")
        
        self.sp_h2o = NudgeSpinBox(0.0, 10000.0, 2, 100.0, " ml", 1400.0)
        self.sp_fill_p = NudgeSpinBox(0.0, 2000.0, 0, 10.0, " mbar", 300.0)
        self.sp_est_flow = NudgeSpinBox(0.1, 500.0, 1, 5.0, " ml/min", 15.0) 
        
        self.mod_p0.addRow(0, "Fill Mode:", self.cmb_fill_mode)
        self.mod_p0.addRow(1, "H2O Volume:", self.sp_h2o)
        self.mod_p0.addRow(2, "Fill Pressure:", self.sp_fill_p)
        self.mod_p0.addRow(3, "Est. Flow:", self.sp_est_flow)
        
        self.lbl_total_vol = QLabel("Target Vol: — ml | ETA: — min")
        self.lbl_total_vol.setProperty("is_dynamic_result", True)
        self.lbl_total_vol.setStyleSheet("color: #00E5FF; font-weight: bold; font-family: 'Consolas'; font-size: 11px; border: none; padding-top: 4px;")
        self.mod_p0.content_lay.addWidget(self.lbl_total_vol, 4, 0, 1, 2)
        root.addWidget(self.mod_p0)

        # 🚀 PHASE A: RAMP UP (NEUES STUFENLOSES DESIGN)
        self.mod_pa = EliteModule("PHASE A: RAMP UP", "#8B5CF6", checkable=True)
        
        self.cmb_ramp_mode = QComboBox()
        self.cmb_ramp_mode.addItems(["Auto (Continuous Rate)", "Manual (Click for Step)"])
        self.cmb_ramp_mode.setStyleSheet("background: #0F172A; color: #FFF; border: 1px solid #1E293B; font-family: 'Consolas'; padding: 2px;")

        self.sp_target_p = NudgeSpinBox(0.0, 8000.0, 0, 100.0, " mbar", 2000.0)
        self.sp_a_rate = NudgeSpinBox(1.0, 5000.0, 0, 10.0, " mbar/min", 125.0) # Für Auto
        self.sp_a_step = NudgeSpinBox(1.0, 1000.0, 0, 10.0, " mbar", 250.0) # Für Manual
        
        self.mod_pa.addRow(0, "Ramp Mode:", self.cmb_ramp_mode)
        self.mod_pa.addRow(1, "Target Pres.:", self.sp_target_p)
        self.mod_pa.addRow(2, "Auto Rate:", self.sp_a_rate)
        self.mod_pa.addRow(3, "Manual Step:", self.sp_a_step)
        
        self.lbl_pa_info = QLabel("Mode: CONTINUOUS | ETA: — min")
        self.lbl_pa_info.setProperty("is_dynamic_result", True)
        self.lbl_pa_info.setStyleSheet("color: #8B5CF6; font-weight: bold; font-family: 'Consolas'; font-size: 11px; border: none; padding-top: 4px;")
        self.mod_pa.content_lay.addWidget(self.lbl_pa_info, 4, 0, 1, 2)
        root.addWidget(self.mod_pa)

        # PHASE B
        self.mod_pb = EliteModule("PHASE B: STEADY STATE", "#F59E0B", checkable=True)
        lbl_b1 = QLabel("B1 holds until 'Target Vol' is reached.")
        lbl_b1.setStyleSheet("color: #64748B; font-size: 10px; font-family: 'Arial'; border: none;")
        self.mod_pb.content_lay.addWidget(lbl_b1, 0, 0, 1, 2)
        
        self.sp_v_extra = NudgeSpinBox(0.0, 5000.0, 2, 10.0, " ml", 0.0)
        self.mod_pb.addRow(1, "B2 V_Extra:", self.sp_v_extra)
        root.addWidget(self.mod_pb)

        # PHASE C
        self.mod_pc = EliteModule("PHASE C: RAMP DOWN", "#EC4899", checkable=True)
        self.sp_dn_rate = NudgeSpinBox(1.0, 5000.0, 0, 50.0, " mbar/min", 500.0)
        self.mod_pc.addRow(0, "Ramp Rate:", self.sp_dn_rate)
        
        self.lbl_pc_info = QLabel("ETA: — min")
        self.lbl_pc_info.setProperty("is_dynamic_result", True)
        self.lbl_pc_info.setStyleSheet("color: #EC4899; font-weight: bold; font-family: 'Consolas'; font-size: 11px; border: none; padding-top: 4px;")
        self.mod_pc.content_lay.addWidget(self.lbl_pc_info, 1, 0, 1, 2)
        root.addWidget(self.mod_pc)

        # 🚀 NEU: TELEMETRY SERVER MODUL
        self.mod_srv = EliteModule("NETWORK MONITOR SERVER", "#10B981", checkable=False)
        
        self.btn_toggle_srv = QPushButton("START SERVER")
        self.btn_toggle_srv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_srv.setStyleSheet("background: #0F172A; color: #10B981; border: 1px solid #1E293B; padding: 4px; font-weight: bold; border-radius: 3px;")
        self.btn_toggle_srv.setCheckable(True)
        self.btn_toggle_srv.toggled.connect(self._on_server_toggled)

        self.btn_open_web = QPushButton("OPEN DASHBOARD")
        self.btn_open_web.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_web.setStyleSheet("background: #0F172A; color: #94A3B8; border: 1px solid #1E293B; padding: 4px; font-weight: bold; border-radius: 3px;")
        self.btn_open_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("http://127.0.0.1:8000")))

        srv_lay = QHBoxLayout()
        srv_lay.addWidget(self.btn_toggle_srv)
        srv_lay.addWidget(self.btn_open_web)
        self.mod_srv.content_lay.addLayout(srv_lay, 0, 0, 1, 2)
        root.addWidget(self.mod_srv)

        root.addStretch()
        self._current_bnnt_ml = 0.0
        self._wire_signals()
        self._recalc_math()

    def _on_server_toggled(self, checked: bool):
        if checked:
            self.btn_toggle_srv.setText("SERVER RUNNING")
            self.btn_toggle_srv.setStyleSheet("background: #10B981; color: #000; border: none; padding: 4px; font-weight: bold; border-radius: 3px;")
        else:
            self.btn_toggle_srv.setText("START SERVER")
            self.btn_toggle_srv.setStyleSheet("background: #0F172A; color: #10B981; border: 1px solid #1E293B; padding: 4px; font-weight: bold; border-radius: 3px;")
        self.server_toggle_requested.emit(checked)

    def _wire_signals(self):
        widgets = [
            self.sp_area, self.sp_calib, self.sp_thick, self.sp_h2o,
            self.sp_fill_p, self.sp_est_flow, self.sp_target_p, self.sp_a_rate, 
            self.sp_a_step, self.sp_v_extra, self.sp_dn_rate,
            self.cmb_fill_mode, self.cmb_ramp_mode
        ]
        for w in widgets: 
            if isinstance(w, QComboBox): w.currentIndexChanged.connect(self._recalc_math)
            else: w.valueChanged.connect(self._recalc_math)
        
        self.modules = [self.mod_p0, self.mod_pa, self.mod_pb, self.mod_pc]
        for m in self.modules: m.toggled.connect(self._recalc_math)

    @Slot()
    def _recalc_math(self):
        if self._is_running: return 

        c = self.sp_calib.value()
        if c > 0:
            self._current_bnnt_ml = ((self.sp_thick.value() / c) * (self.sp_area.value() / 1134.0) / 1000.0) 
            self.lbl_bnnt.setText(f"Req. BNNT: {self._current_bnnt_ml:.4f} ml")
        
        tot = self._current_bnnt_ml + self.sp_h2o.value()
        
        if self.cmb_fill_mode.currentIndex() == 1:
            self.lbl_total_vol.setText("Target Vol: MANUAL STOP")
        else:
            est_flow = self.sp_est_flow.value()
            eta_m = (tot / est_flow) if est_flow > 0 else 0
            self.lbl_total_vol.setText(f"Target: {tot:.2f} ml | ETA: {eta_m:.1f} min")

        # 🚀 NEU: Logik für Stufenlos vs Steps
        if self.cmb_ramp_mode.currentIndex() == 0:
            rate = self.sp_a_rate.value()
            eta = self.sp_target_p.value() / rate if rate > 0 else 0
            self.lbl_pa_info.setText(f"Mode: CONTINUOUS | ETA: {eta:.1f} min")
        else:
            step_size = self.sp_a_step.value()
            steps = math.ceil(self.sp_target_p.value() / step_size) if step_size > 0 else 0
            self.lbl_pa_info.setText(f"Mode: MANUAL STEPS | Clicks req.: {steps}")

        rate_c = self.sp_dn_rate.value()
        if rate_c > 0:
            c_min = self.sp_target_p.value() / rate_c
            self.lbl_pc_info.setText(f"ETA: {c_min:.1f} min")

        self.params_changed.emit(self.get_run_params())

    def get_run_params(self) -> RunParams:
        p = RunParams(
            v_bnnt_ml=self._current_bnnt_ml, v_h2o_ml=self.sp_h2o.value(),
            run_phase_0=self.mod_p0.isChecked(), phase_0_pressure_mbar=self.sp_fill_p.value(),
            run_phase_a=self.mod_pa.isChecked(), phase_a_target_mbar=self.sp_target_p.value(),
            phase_a_rate_mbar_min=self.sp_a_rate.value(), phase_a_step_mbar=self.sp_a_step.value(),
            run_phase_b=self.mod_pb.isChecked(), v_extra_ml=self.sp_v_extra.value(),
            run_phase_c=self.mod_pc.isChecked(), phase_c_rate_mbar_min=self.sp_dn_rate.value()
        )
        p.phase_0_mode = "auto" if self.cmb_fill_mode.currentIndex() == 0 else "continuous"
        p.phase_a_mode = "auto" if self.cmb_ramp_mode.currentIndex() == 0 else "manual"
        return p

    def set_running(self, running: bool):
        self._is_running = running
        for m in self.modules + [self.mod_calc, self.mod_srv]:
            m.setEnabled(not running)
        if not running:
            self.countdown_timer.stop()
            self._recalc_math() 
            self.update_active_step_highlight("IDLE")
            
    def update_active_step_highlight(self, current_step_str: str):
        for m in self.modules: m.setHighlight(False)
        self._active_phase_key = current_step_str
        
        if "PHASE_A" in current_step_str: 
            self.mod_pa.setHighlight(True)
            if self.cmb_ramp_mode.currentIndex() == 0:
                rate = self.sp_a_rate.value()
                self._time_left_s = (self.sp_target_p.value() / rate * 60) if rate > 0 else 0
            else:
                self._time_left_s = 0
        elif "PHASE_B" in current_step_str: 
            self.mod_pb.setHighlight(True)
        elif "PHASE_C" in current_step_str: 
            self.mod_pc.setHighlight(True)
            rate = self.sp_dn_rate.value()
            self._time_left_s = (self.sp_target_p.value() / rate * 60) if rate > 0 else 0
        elif "FILLING" in current_step_str or "0" in current_step_str:
            self.mod_p0.setHighlight(True)
            tot = self._current_bnnt_ml + self.sp_h2o.value()
            est_flow = self.sp_est_flow.value()
            if self.cmb_fill_mode.currentIndex() == 0 and est_flow > 0:
                self._time_left_s = (tot / est_flow) * 60
            else:
                self._time_left_s = 0

        if self._time_left_s > 0 and self._is_running:
            self.countdown_timer.start(1000)
        else:
            self.countdown_timer.stop()

    def _on_countdown_tick(self):
        if self._time_left_s > 0:
            self._time_left_s -= 1
            m = int(self._time_left_s // 60)
            s = int(self._time_left_s % 60)
            ts = f"{m:02d}:{s:02d}"
            
            if "PHASE_A" in self._active_phase_key:
                self.lbl_pa_info.setText(f"ACTION: RAMPING | REM: {ts}")
            elif "PHASE_C" in self._active_phase_key:
                self.lbl_pc_info.setText(f"ACTION: RAMPING | REM: {ts}")
            elif "FILLING" in self._active_phase_key or "0" in self._active_phase_key:
                self.lbl_total_vol.setText(f"ACTION: FILLING | REM: {ts}")

    @Slot(bool)
    def set_hold_active(self, active: bool):
        self._hold_active = active
        self._update_hold_style()

    def set_hold_affordance(self, allowed: bool, hint: str):
        self._hold_allowed = allowed
        if not self._hold_active: self._update_hold_style()

    def _update_hold_style(self):
        base = "font-family: 'Consolas'; font-size: 11px; font-weight: bold; letter-spacing: 1px; padding: 8px; border-radius: 4px; "
        if self._hold_active:
            self.btn_hold.setText(">>> BACKWASH ACTIVE <<<")
            self.btn_hold.setStyleSheet(base + "background: #EC4899; color: #FFF; border: none;")
        elif not self._hold_allowed:
            self.btn_hold.setText("MANUAL UNAVAILABLE")
            self.btn_hold.setStyleSheet(base + "background: #000; color: #334155; border: 1px solid #1E293B;")
        else:
            self.btn_hold.setText("HOLD SPACE TO BACKWASH")
            self.btn_hold.setStyleSheet(base + "background: transparent; color: #EC4899; border: 1px solid #EC4899;")