from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import QTimer, QUrl, Signal, Slot, Qt
from PySide6.QtGui import QCursor, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)

from src.gui.data.worker import RunParams
from src.gui.widgets.hold_button import HoldButton
from src.gui.widgets.nudge_spinbox import NudgeSpinBox

logger = logging.getLogger(__name__)


class EliteModule(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, accent_color: str,
                 checkable: bool = False, default_checked: bool = True):
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
        if not self.checkable:
            return
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

        self.header.setStyleSheet(
            f"background-color: {head_bg}; border-top-left-radius: 3px; "
            f"border-top-right-radius: 3px; border-bottom: 1px solid {border_col};")
        self.lbl_title.setStyleSheet(
            f"color: {head_text}; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; letter-spacing: 1px; border: none; background: transparent;")
        if self.checkable:
            self.lbl_status.setText(status_text)
            self.lbl_status.setStyleSheet(
                f"color: {status_col}; font-family: 'Consolas'; font-size: 9px; "
                "font-weight: bold; border: none; background: transparent;")

        self.setStyleSheet(
            f"EliteModule {{ background-color: #090F16; "
            f"border: {border_width} solid {border_col}; "
            "border-radius: 4px; margin-bottom: 6px; }}")

        for i in range(self.content_lay.count()):
            item = self.content_lay.itemAt(i)
            if item is None:
                continue
            w = item.widget()
            if w:
                w.setEnabled(self._is_active)
                if isinstance(w, QLabel) and not w.property("is_dynamic_result"):
                    _lbl_col = '#94A3B8' if self._is_active else '#334155'
                    w.setStyleSheet(
                        f"color: {_lbl_col}; font-family: 'Consolas'; "
                        "font-size: 11px; border: none;")

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
    valve_command_requested = Signal(str)  # "FILLING", "FILTRATION", "BACKWASH", "ALL_SHUT"
    relay_toggle_requested = Signal(int, bool)  # (relay_number, target_on)

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

        # MANUAL HOLD (hidden — kept as attributes for signal compatibility)
        self.btn_hold = HoldButton("HOLD SPACE TO BACKWASH")
        self.btn_hold.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.sp_hold_p = NudgeSpinBox(0, 8000, 0, 25, " mbar", 300.0)

        # VALVE CONTROL PANEL
        self.grp_valves = QFrame()
        self.grp_valves.setStyleSheet(
            "QFrame { background: #0B1120; border-radius: 4px; "
            "border: 1px solid #1E293B; border-top: 2px solid #0EA5E9; margin-bottom: 4px; }")
        lay_valves = QVBoxLayout(self.grp_valves)
        lay_valves.setContentsMargins(12, 10, 12, 10)
        lay_valves.setSpacing(6)

        lbl_valve_title = QLabel("VALVE CONTROL")
        lbl_valve_title.setStyleSheet(
            "color: #0EA5E9; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; letter-spacing: 1px; border: none;")
        lay_valves.addWidget(lbl_valve_title)

        # Status-Anzeige: welcher Zustand gerade aktiv ist
        self.lbl_valve_state = QLabel("STATE: ALL SHUT")
        self.lbl_valve_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_valve_state.setStyleSheet(
            "color: #F8FAFC; font-family: 'Consolas'; font-size: 12px; "
            "font-weight: bold; background: #111827; border: 1px solid #1E293B; "
            "border-radius: 3px; padding: 4px; margin-bottom: 4px;")
        lay_valves.addWidget(self.lbl_valve_state)

        # Relais-Indikator: R1 / R2 — klickbar für direktes Toggling
        self._valve_r1_on = False
        self._valve_r2_on = False
        relay_row = QHBoxLayout()
        self.btn_r1 = QPushButton("R1: OFF")
        self.btn_r1.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_r1.setToolTip("Click to toggle Relay 1")
        self.btn_r2 = QPushButton("R2: OFF")
        self.btn_r2.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_r2.setToolTip("Click to toggle Relay 2")
        relay_row.addWidget(self.btn_r1)
        relay_row.addWidget(self.btn_r2)
        lay_valves.addLayout(relay_row)
        self._update_relay_indicators()

        self.btn_r1.clicked.connect(lambda: self._toggle_relay(1))
        self.btn_r2.clicked.connect(lambda: self._toggle_relay(2))

        # Buttons: 6 Modi als 3×2 Grid
        btn_row1 = QHBoxLayout()
        self.btn_v_filling = QPushButton("FILLING")
        self.btn_v_filtration = QPushButton("FILTRATION")
        self.btn_v_venting = QPushButton("VENTING")
        btn_row1.addWidget(self.btn_v_filling)
        btn_row1.addWidget(self.btn_v_filtration)
        btn_row1.addWidget(self.btn_v_venting)
        lay_valves.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_v_backwash = QPushButton("BACKWASH")
        self.btn_v_shut = QPushButton("ALL SHUT")
        self.btn_v_open = QPushButton("ALL OPEN")
        btn_row2.addWidget(self.btn_v_backwash)
        btn_row2.addWidget(self.btn_v_shut)
        btn_row2.addWidget(self.btn_v_open)
        lay_valves.addLayout(btn_row2)

        for btn in (self.btn_v_filling, self.btn_v_filtration, self.btn_v_venting,
                    self.btn_v_backwash, self.btn_v_shut, self.btn_v_open):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._valve_buttons = {
            "FILLING": self.btn_v_filling,
            "FILTRATION": self.btn_v_filtration,
            "VENTING": self.btn_v_venting,
            "BACKWASH": self.btn_v_backwash,
            "ALL_SHUT": self.btn_v_shut,
            "ALL_OPEN": self.btn_v_open,
        }
        self._current_valve_mode = "ALL_SHUT"
        self._apply_valve_button_styles()

        # Signale
        self.btn_v_filling.clicked.connect(lambda: self.valve_command_requested.emit("FILLING"))
        self.btn_v_filtration.clicked.connect(
            lambda: self.valve_command_requested.emit("FILTRATION"))
        self.btn_v_venting.clicked.connect(lambda: self.valve_command_requested.emit("VENTING"))
        self.btn_v_backwash.clicked.connect(lambda: self.valve_command_requested.emit("BACKWASH"))
        self.btn_v_shut.clicked.connect(lambda: self.valve_command_requested.emit("ALL_SHUT"))
        self.btn_v_open.clicked.connect(lambda: self.valve_command_requested.emit("ALL_OPEN"))

        root.addWidget(self.grp_valves)

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
        self.lbl_bnnt.setStyleSheet(
            "color: #10B981; font-weight: bold; font-family: 'Consolas'; "
            "font-size: 12px; border: none; padding-top: 4px;")
        self.mod_calc.content_lay.addWidget(self.lbl_bnnt, 3, 0, 1, 2)
        root.addWidget(self.mod_calc)

        # PHASE 0: BACKWASH
        self.mod_p0 = EliteModule("PHASE 0: BACKWASH", "#EC4899", checkable=True)
        self._p0_mode = "AUTO"

        _p0_pill_frm, self._p0_btns = self._make_mode_pills(
            ["MANUAL", "CONTINUOUS", "AUTO"], "#EC4899")
        self._p0_btns[2].setChecked(True)
        self.mod_p0.content_lay.addWidget(_p0_pill_frm, 0, 0, 1, 2)

        self._lbl_fill_p = QLabel("Backwash Pressure:")
        self._lbl_fill_p.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_fill_p = NudgeSpinBox(0.0, 2000.0, 0, 10.0, " mbar", 300.0)
        self.mod_p0.content_lay.addWidget(self._lbl_fill_p, 1, 0)
        self.mod_p0.content_lay.addWidget(self.sp_fill_p, 1, 1)

        self._lbl_bw_target = QLabel("BW Target Volume:")
        self._lbl_bw_target.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_bw_target_ml = NudgeSpinBox(0.0, 10000.0, 0, 100.0, " ml", 1400.0)
        self.mod_p0.content_lay.addWidget(self._lbl_bw_target, 2, 0)
        self.mod_p0.content_lay.addWidget(self.sp_bw_target_ml, 2, 1)

        self.lbl_bw_eta = QLabel("ETA: — min (at live flow)")
        self.lbl_bw_eta.setProperty("is_dynamic_result", True)
        self.lbl_bw_eta.setStyleSheet(
            "color: #EC4899; font-weight: bold; font-family: 'Consolas'; "
            "font-size: 11px; border: none; padding-top: 4px;")
        self.mod_p0.content_lay.addWidget(self.lbl_bw_eta, 3, 0, 1, 2)
        root.addWidget(self.mod_p0)

        self._p0_btns[0].clicked.connect(lambda: self._set_p0_mode("MANUAL"))
        self._p0_btns[1].clicked.connect(lambda: self._set_p0_mode("CONTINUOUS"))
        self._p0_btns[2].clicked.connect(lambda: self._set_p0_mode("AUTO"))

        # PHASE A: RAMP UP
        self.mod_pa = EliteModule("PHASE A: RAMP UP", "#8B5CF6", checkable=True)
        self._pa_mode = "SMOOTH"

        _pa_pill_frm, self._pa_btns = self._make_mode_pills(
            ["SMOOTH", "STEPPED"], "#8B5CF6")
        self._pa_btns[0].setChecked(True)
        self.mod_pa.content_lay.addWidget(_pa_pill_frm, 0, 0, 1, 2)

        self.sp_target_p = NudgeSpinBox(0.0, 8000.0, 0, 100.0, " mbar", 2000.0)
        self.mod_pa.addRow(1, "Target Pressure:", self.sp_target_p)

        self._lbl_a_rate = QLabel("Ramp Rate:")
        self._lbl_a_rate.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_a_rate = NudgeSpinBox(1.0, 5000.0, 0, 10.0, " mbar/min", 125.0)
        self.mod_pa.content_lay.addWidget(self._lbl_a_rate, 2, 0)
        self.mod_pa.content_lay.addWidget(self.sp_a_rate, 2, 1)

        self._lbl_a_step = QLabel("Step Size:")
        self._lbl_a_step.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_a_step_mbar = NudgeSpinBox(50.0, 2000.0, 0, 50.0, " mbar", 250.0)
        self.mod_pa.content_lay.addWidget(self._lbl_a_step, 3, 0)
        self.mod_pa.content_lay.addWidget(self.sp_a_step_mbar, 3, 1)

        self._lbl_a_time_step = QLabel("Time/Step:")
        self._lbl_a_time_step.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_a_time_per_step = NudgeSpinBox(0.1, 120.0, 1, 0.5, " min", 2.0)
        self.mod_pa.content_lay.addWidget(self._lbl_a_time_step, 4, 0)
        self.mod_pa.content_lay.addWidget(self.sp_a_time_per_step, 4, 1)

        self.lbl_pa_info = QLabel("ETA: — min")
        self.lbl_pa_info.setProperty("is_dynamic_result", True)
        self.lbl_pa_info.setStyleSheet(
            "color: #8B5CF6; font-weight: bold; font-family: 'Consolas'; "
            "font-size: 11px; border: none; padding-top: 4px;")
        self.mod_pa.content_lay.addWidget(self.lbl_pa_info, 5, 0, 1, 2)
        root.addWidget(self.mod_pa)

        self._pa_btns[0].clicked.connect(lambda: self._set_pa_mode("SMOOTH"))
        self._pa_btns[1].clicked.connect(lambda: self._set_pa_mode("STEPPED"))

        # PHASE B: STEADY STATE
        self.mod_pb = EliteModule("PHASE B: STEADY STATE", "#F59E0B", checkable=True)
        self.sp_h2o = NudgeSpinBox(0.0, 10000.0, 1, 100.0, " ml", 1400.0)
        self.sp_v_extra = NudgeSpinBox(0.0, 5000.0, 1, 10.0, " ml", 0.0)
        self.sp_b_timeout = NudgeSpinBox(1.0, 60.0, 0, 1.0, " min", 5.0)
        self.mod_pb.addRow(0, "H2O Vol (→ B1 target):", self.sp_h2o)
        self.mod_pb.addRow(1, "B2 Extra (Drying):", self.sp_v_extra)
        self.mod_pb.addRow(2, "No-Flow Timeout:", self.sp_b_timeout)
        self.lbl_pb_info = QLabel("B1: — ml | B2: — ml | Total: — ml")
        self.lbl_pb_info.setProperty("is_dynamic_result", True)
        self.lbl_pb_info.setStyleSheet(
            "color: #F59E0B; font-weight: bold; font-family: 'Consolas'; "
            "font-size: 11px; border: none; padding-top: 4px;")
        self.mod_pb.content_lay.addWidget(self.lbl_pb_info, 3, 0, 1, 2)
        root.addWidget(self.mod_pb)

        # PHASE C: RAMP DOWN (Smooth only)
        self.mod_pc = EliteModule("PHASE C: RAMP DOWN", "#EC4899", checkable=True)

        self._lbl_dn_rate = QLabel("Ramp Rate:")
        self._lbl_dn_rate.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_dn_rate = NudgeSpinBox(1.0, 5000.0, 0, 50.0, " mbar/min", 500.0)
        self.mod_pc.content_lay.addWidget(self._lbl_dn_rate, 0, 0)
        self.mod_pc.content_lay.addWidget(self.sp_dn_rate, 0, 1)

        self.lbl_pc_info = QLabel("ETA: — min")
        self.lbl_pc_info.setProperty("is_dynamic_result", True)
        self.lbl_pc_info.setStyleSheet(
            "color: #EC4899; font-weight: bold; font-family: 'Consolas'; "
            "font-size: 11px; border: none; padding-top: 4px;")
        self.mod_pc.content_lay.addWidget(self.lbl_pc_info, 1, 0, 1, 2)
        root.addWidget(self.mod_pc)

        # ORCHESTRATOR: Bestätigungs-Gates
        self.frm_orchestrator = QFrame()
        self.frm_orchestrator.setStyleSheet(
            "QFrame { background: #0B1120; border-radius: 4px; "
            "border: 1px solid #1E293B; border-top: 2px solid #0EA5E9; margin-bottom: 4px; }")
        lay_orch = QHBoxLayout(self.frm_orchestrator)
        lay_orch.setContentsMargins(12, 8, 12, 8)

        lbl_orch = QLabel("CONFIRM BETWEEN PHASES")
        lbl_orch.setStyleSheet(
            "color: #0EA5E9; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; letter-spacing: 1px; border: none;")
        self.chk_confirm_gates = QPushButton("ON")
        self.chk_confirm_gates.setCheckable(True)
        self.chk_confirm_gates.setChecked(True)
        self.chk_confirm_gates.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_confirm_gates.setFixedWidth(50)
        self.chk_confirm_gates.toggled.connect(self._on_confirm_toggle)
        self._apply_confirm_style(True)

        lay_orch.addWidget(lbl_orch)
        lay_orch.addStretch()
        lay_orch.addWidget(self.chk_confirm_gates)
        root.addWidget(self.frm_orchestrator)

        root.addStretch()
        self._current_bnnt_ml = 0.0
        self._wire_signals()
        self._set_p0_mode("AUTO")
        self._set_pa_mode("SMOOTH")
        self._load_last_params()  # Letzten Parametersatz wiederherstellen
        self._recalc_math()

    def _wire_signals(self):
        widgets = [
            self.sp_area, self.sp_calib, self.sp_thick,
            self.sp_fill_p, self.sp_bw_target_ml,
            self.sp_target_p, self.sp_a_rate,
            self.sp_a_step_mbar, self.sp_a_time_per_step,
            self.sp_h2o, self.sp_v_extra, self.sp_b_timeout,
            self.sp_dn_rate,
        ]
        for w in widgets:
            w.valueChanged.connect(self._recalc_math)

        self.modules = [self.mod_p0, self.mod_pa, self.mod_pb, self.mod_pc]
        for m in self.modules:
            m.toggled.connect(self._recalc_math)

    @Slot()
    def _recalc_math(self):
        if self._is_running:
            return

        c = self.sp_calib.value()
        if c > 0:
            self._current_bnnt_ml = ((self.sp_thick.value() / c) *
                                     (self.sp_area.value() / 1134.0) / 1000.0)
            self.lbl_bnnt.setText(f"Req. BNNT: {self._current_bnnt_ml:.4f} ml")

        # Phase A ETA
        if self._pa_mode == "SMOOTH":
            rate_a = self.sp_a_rate.value()
            eta_a = (self.sp_target_p.value() / rate_a) if rate_a > 0 else 0
            self.lbl_pa_info.setText(f"ETA: {eta_a:.1f} min @ {rate_a:.0f} mbar/min")
        else:  # STEPPED
            step = self.sp_a_step_mbar.value()
            t = self.sp_a_time_per_step.value()
            n = max(1, math.ceil(self.sp_target_p.value() / step)) if step > 0 else 0
            self.lbl_pa_info.setText(f"{n} steps · ~{n * t:.1f} min total")

        # Phase C ETA (Smooth only)
        rate_c = self.sp_dn_rate.value()
        c_min = (self.sp_target_p.value() / rate_c) if rate_c > 0 else 0
        self.lbl_pc_info.setText(f"ETA: {c_min:.1f} min")

        # Phase B Info (B1 + B2)
        b1_target = self._current_bnnt_ml + self.sp_h2o.value()
        extra_val = self.sp_v_extra.value()
        timeout_val = self.sp_b_timeout.value()
        total_b = b1_target + extra_val
        self.lbl_pb_info.setText(
            f"B1: {b1_target:.1f} ml | B2: {extra_val:.1f} ml | Total: {total_b:.1f} ml  "
            f"(Timeout: {timeout_val:.0f} min)"
        )

        self.params_changed.emit(self.get_run_params())
        self._save_last_params()

    def get_run_params(self) -> RunParams:
        return RunParams(
            v_bnnt_ml=self._current_bnnt_ml,
            phase_b1_target_ml=self.sp_h2o.value(),
            run_phase_0=self.mod_p0.isChecked(),
            phase_0_pressure_mbar=self.sp_fill_p.value(),
            phase_0_target_ml=self.sp_bw_target_ml.value(),
            phase_0_mode=self._p0_mode,
            run_phase_a=self.mod_pa.isChecked(),
            phase_a_target_mbar=self.sp_target_p.value(),
            phase_a_rate_mbar_min=self.sp_a_rate.value(),
            phase_a_mode=self._pa_mode,
            phase_a_step_mbar=self.sp_a_step_mbar.value(),
            phase_a_time_per_step_min=self.sp_a_time_per_step.value(),
            run_phase_b=self.mod_pb.isChecked(),
            v_extra_ml=self.sp_v_extra.value(),
            phase_b_no_flow_timeout_min=self.sp_b_timeout.value(),
            run_phase_c=self.mod_pc.isChecked(),
            phase_c_rate_mbar_min=self.sp_dn_rate.value(),
            phase_c_mode="SMOOTH",
            confirm_between_phases=self.chk_confirm_gates.isChecked(),
        )

    # ── Pill selector helpers ────────────────────────────────────────────────

    def _make_mode_pills(self, modes: list, accent: str) -> tuple:
        frm = QFrame()
        lay = QHBoxLayout(frm)
        lay.setContentsMargins(0, 0, 0, 2)
        lay.setSpacing(3)
        buttons = []
        for mode in modes:
            btn = QPushButton(mode)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(22)
            lay.addWidget(btn)
            buttons.append(btn)
        return frm, buttons

    def _apply_pill_styles(self, buttons: list, active_idx: int, accent: str):
        for i, btn in enumerate(buttons):
            if i == active_idx:
                btn.setStyleSheet(
                    f"background: {accent}; color: #000; border: none; padding: 2px 6px; "
                    "font-weight: bold; font-family: 'Consolas'; font-size: 10px; border-radius: 3px;")
            else:
                btn.setStyleSheet(
                    "background: #0F172A; color: #94A3B8; border: 1px solid #1E293B; "
                    "padding: 2px 6px; font-weight: bold; font-family: 'Consolas'; "
                    "font-size: 10px; border-radius: 3px;")

    def _set_p0_mode(self, mode: str):
        self._p0_mode = mode
        show_p = mode != "MANUAL"
        show_v = mode == "AUTO"
        for w in (self._lbl_fill_p, self.sp_fill_p):
            w.setVisible(show_p)
        for w in (self._lbl_bw_target, self.sp_bw_target_ml):
            w.setVisible(show_v)
        hints = {
            "MANUAL": "Hold SPACE during run to backwash",
            "CONTINUOUS": "Fills until OK / STOP pressed",
            "AUTO": "ETA: — min (at live flow)",
        }
        self.lbl_bw_eta.setText(hints[mode])
        self._apply_pill_styles(self._p0_btns, ["MANUAL", "CONTINUOUS", "AUTO"].index(mode), "#EC4899")
        self._recalc_math()

    def _set_pa_mode(self, mode: str):
        self._pa_mode = mode
        smooth = mode == "SMOOTH"
        for w in (self._lbl_a_rate, self.sp_a_rate):
            w.setVisible(smooth)
        for w in (self._lbl_a_step, self.sp_a_step_mbar,
                  self._lbl_a_time_step, self.sp_a_time_per_step):
            w.setVisible(not smooth)
        self._apply_pill_styles(self._pa_btns, ["SMOOTH", "STEPPED"].index(mode), "#8B5CF6")
        self._recalc_math()

    # ── Confirm gate ─────────────────────────────────────────────────────────

    def _on_confirm_toggle(self, checked: bool):
        self._apply_confirm_style(checked)

    def _apply_confirm_style(self, checked: bool):
        if checked:
            self.chk_confirm_gates.setText("ON")
            self.chk_confirm_gates.setStyleSheet(
                "background: #0EA5E9; color: #000; border: none; padding: 4px; "
                "font-weight: bold; font-family: 'Consolas'; font-size: 10px; border-radius: 3px;")
        else:
            self.chk_confirm_gates.setText("OFF")
            self.chk_confirm_gates.setStyleSheet(
                "background: #1E293B; color: #64748B; border: 1px solid #334155; padding: 4px; "
                "font-weight: bold; font-family: 'Consolas'; font-size: 10px; border-radius: 3px;")

    def set_running(self, running: bool):
        self._is_running = running
        for m in self.modules + [self.mod_calc]:
            m.setEnabled(not running)
        self.frm_orchestrator.setEnabled(not running)
        # Valve panel bleibt immer aktiv (manuelle Übersteuerung während Experiment)

        if not running:
            self.countdown_timer.stop()
            self._time_left_s = 0.0
            self._recalc_math()
            self.update_active_step_highlight("IDLE")

    def update_active_step_highlight(self, current_step_str: str,
                                     current_pressure_mbar: float = 0.0):
        """
        Markiert das aktive Modul und berechnet den ETA-Countdown.
        current_pressure_mbar: Aktueller Ist-Druck (optional, für präzisere ETA).
        """
        self.countdown_timer.stop()
        self._time_left_s = 0.0

        for m in self.modules:
            m.setHighlight(False)

        self._active_phase_key = current_step_str

        if "PHASE_A" in current_step_str:
            self.mod_pa.setHighlight(True)
            rate = self.sp_a_rate.value()
            remaining_mbar = max(0.0, self.sp_target_p.value() - current_pressure_mbar)
            self._time_left_s = (remaining_mbar / rate * 60) if rate > 0 else 0

        elif "PHASE_B" in current_step_str:
            self.mod_pb.setHighlight(True)

        elif "PHASE_C" in current_step_str:
            self.mod_pc.setHighlight(True)
            rate = self.sp_dn_rate.value()
            # Delta: Wie viel Druck noch abzubauen ist
            remaining_mbar = (current_pressure_mbar
                              if current_pressure_mbar > 0
                              else self.sp_target_p.value())
            self._time_left_s = (remaining_mbar / rate * 60) if rate > 0 else 0

        elif "FILLING" in current_step_str or "0" in current_step_str:
            self.mod_p0.setHighlight(True)
            # Backwash hat keine fixe ETA (stagnationsbasiert)

        # Nur starten, wenn wir wirklich im Run-Modus sind UND es Zeit gibt
        if self._time_left_s > 0 and self._is_running:
            self._update_countdown_labels()
            self.countdown_timer.start(1000)

    def _on_countdown_tick(self):
        if self._time_left_s > 0:
            self._time_left_s -= 1
            self._update_countdown_labels()
        else:
            self.countdown_timer.stop()  # 🚀 FIX: Timer stoppen, wenn er 0 erreicht

    def _update_countdown_labels(self):
        """Hilfsfunktion, um die Labels zu zeichnen, getrennt vom reinen 'Tick'."""
        m = int(self._time_left_s // 60)
        s = int(self._time_left_s % 60)
        ts = f"{m:02d}:{s:02d}"

        if "PHASE_A" in self._active_phase_key:
            self.lbl_pa_info.setText(f"RAMPING | REM: {ts}")
        elif "PHASE_C" in self._active_phase_key:
            self.lbl_pc_info.setText(f"RAMPING | REM: {ts}")

    @Slot(bool)
    def set_hold_active(self, active: bool):
        self._hold_active = active
        self._update_hold_style()

    def set_hold_affordance(self, allowed: bool, hint: str):
        self._hold_allowed = allowed
        if not self._hold_active:
            self._update_hold_style()

    def _update_hold_style(self):
        base = (
            "font-family: 'Consolas'; font-size: 11px; font-weight: bold; "
            "letter-spacing: 1px; padding: 8px; border-radius: 4px; "
        )
        if self._hold_active:
            self.btn_hold.setText(">>> BACKWASH ACTIVE <<<")
            self.btn_hold.setStyleSheet(base + "background: #EC4899; color: #FFF; border: none;")
        elif not self._hold_allowed:
            self.btn_hold.setText("MANUAL UNAVAILABLE")
            self.btn_hold.setStyleSheet(
                base + "background: #000; color: #334155; border: 1px solid #1E293B;")
        else:
            self.btn_hold.setText("HOLD SPACE TO BACKWASH")
            self.btn_hold.setStyleSheet(
                base + "background: transparent; color: #EC4899; border: 1px solid #EC4899;")

    # -----------------------------------------------------------------
    # VALVE PANEL
    # -----------------------------------------------------------------
    _VALVE_RELAY_MAP = {
        "FILLING": (True, False),
        "VENTING": (True, False),
        "FILTRATION": (False, True),
        "BACKWASH": (True, True),
        "ALL_OPEN": (True, True),
        "ALL_SHUT": (False, False),
    }

    _VALVE_COLORS = {
        "FILLING": ("#00E5FF", "#0C447C"),   # Cyan
        "VENTING": ("#10B981", "#085041"),    # Green
        "FILTRATION": ("#8B5CF6", "#3C3489"),   # Purple
        "BACKWASH": ("#EC4899", "#72243E"),   # Pink
        "ALL_OPEN": ("#F59E0B", "#633806"),   # Amber
        "ALL_SHUT": ("#64748B", "#1E293B"),   # Gray
    }

    def update_valve_state(self, state: str):
        """Wird vom MainWindow aufgerufen wenn Ventile geschaltet wurden."""
        mode = str(state).strip().upper()
        if mode not in self._VALVE_COLORS:
            mode = "ALL_SHUT"
        self._current_valve_mode = mode
        self._apply_valve_button_styles()

        # Status-Label
        color = self._VALVE_COLORS[mode][0]
        self.lbl_valve_state.setText(f"STATE: {mode}")
        self.lbl_valve_state.setStyleSheet(
            f"color: {color}; font-family: 'Consolas'; font-size: 12px; "
            f"font-weight: bold; background: #111827; border: 1px solid #1E293B; "
            f"border-radius: 3px; padding: 4px; margin-bottom: 4px;")

        # Relais-Indikatoren
        r1, r2 = self._VALVE_RELAY_MAP.get(mode, (False, False))
        self._valve_r1_on = r1
        self._valve_r2_on = r2
        self._update_relay_indicators()

    def _apply_valve_button_styles(self):
        for name, btn in self._valve_buttons.items():
            if name == self._current_valve_mode:
                color = self._VALVE_COLORS[name][0]
                btn.setStyleSheet(
                    f"background: {color}; color: #000; border: none; "
                    f"padding: 6px 4px; font-weight: bold; font-family: 'Consolas'; "
                    f"font-size: 10px; border-radius: 3px;")
            else:
                btn.setStyleSheet(
                    "background: #0F172A; color: #94A3B8; border: 1px solid #1E293B; "
                    "padding: 6px 4px; font-weight: bold; font-family: 'Consolas'; "
                    "font-size: 10px; border-radius: 3px;")

    def _update_relay_indicators(self):
        for btn, on, name in [(self.btn_r1, self._valve_r1_on, "R1"),
                              (self.btn_r2, self._valve_r2_on, "R2")]:
            if on:
                btn.setText(f"{name}: ON")
                btn.setStyleSheet(
                    "color: #10B981; font-family: 'Consolas'; "
                    "font-size: 10px; font-weight: bold; "
                    "background: #052E16; border: 1px solid #10B981; "
                    "border-radius: 3px; padding: 3px;")
            else:
                btn.setText(f"{name}: OFF")
                btn.setStyleSheet(
                    "color: #64748B; font-family: 'Consolas'; "
                    "font-size: 10px; font-weight: bold; "
                    "background: #0F172A; border: 1px solid #1E293B; "
                    "border-radius: 3px; padding: 3px;")

    def _toggle_relay(self, relay_num: int):
        """Einzelnes Relais direkt umschalten (Debug/Experimentier-Modus)."""
        if relay_num == 1:
            self._valve_r1_on = not self._valve_r1_on
        else:
            self._valve_r2_on = not self._valve_r2_on

        # UI sofort updaten
        self._update_relay_indicators()

        # Zustand erkennen oder als CUSTOM markieren
        combo = (self._valve_r1_on, self._valve_r2_on)
        matched_mode = None
        for mode_name, relay_state in self._VALVE_RELAY_MAP.items():
            if relay_state == combo:
                matched_mode = mode_name
                break

        if matched_mode:
            self._current_valve_mode = matched_mode
        else:
            self._current_valve_mode = "CUSTOM"

        self._apply_valve_button_styles()

        # Status-Label
        if matched_mode:
            color = self._VALVE_COLORS[matched_mode][0]
            self.lbl_valve_state.setText(f"STATE: {matched_mode}")
        else:
            color = "#F59E0B"
            r1_s = "ON" if self._valve_r1_on else "OFF"
            r2_s = "ON" if self._valve_r2_on else "OFF"
            self.lbl_valve_state.setText(f"STATE: CUSTOM (R1={r1_s} R2={r2_s})")

        self.lbl_valve_state.setStyleSheet(
            f"color: {color}; font-family: 'Consolas'; font-size: 12px; "
            f"font-weight: bold; background: #111827; border: 1px solid #1E293B; "
            f"border-radius: 3px; padding: 4px; margin-bottom: 4px;")

        # Signal an MainWindow: Relais direkt schalten
        target_on = self._valve_r1_on if relay_num == 1 else self._valve_r2_on
        self.relay_toggle_requested.emit(relay_num, target_on)

    # -----------------------------------------------------------------
    # RUN PARAMS PERSISTENCE
    # -----------------------------------------------------------------
    _PARAMS_FILE = "last_run_params.yaml"

    def _params_path(self) -> str:
        from src.utils.path_utils import project_root, resolve_under
        try:
            root = project_root(__file__)
            return str(resolve_under(root, self._PARAMS_FILE))
        except Exception:
            return self._PARAMS_FILE

    def _save_last_params(self):
        """Persist current UI values to YAML. Skipped while a run is active."""
        if self._is_running:
            return
        try:
            self.get_run_params().save_yaml(self._params_path())
        except Exception as exc:
            logger.warning("Could not save run params: %s", exc)

    def _load_last_params(self):
        """Restore last UI values from YAML on startup. Falls back to defaults on failure."""
        try:
            p = RunParams.load_yaml(self._params_path())
            self._apply_run_params(p)
        except Exception as exc:
            logger.info("No saved params found (using defaults): %s", exc)

    def _apply_run_params(self, p: RunParams) -> None:
        """Push a RunParams object into all UI spinboxes / toggles."""
        widgets_map = [
            (self.sp_h2o, p.phase_b1_target_ml),
            (self.sp_fill_p, p.phase_0_pressure_mbar),
            (self.sp_bw_target_ml, p.phase_0_target_ml),
            (self.sp_target_p, p.phase_a_target_mbar),
            (self.sp_a_rate, p.phase_a_rate_mbar_min),
            (self.sp_v_extra, p.v_extra_ml),
            (self.sp_b_timeout, p.phase_b_no_flow_timeout_min),
            (self.sp_dn_rate, p.phase_c_rate_mbar_min),
        ]
        for widget, val in widgets_map:
            try:
                widget.blockSignals(True)
                widget.setValue(float(val))
                widget.blockSignals(False)
            except Exception:
                pass
        for mod, active in [(self.mod_p0, p.run_phase_0), (self.mod_pa, p.run_phase_a),
                            (self.mod_pb, p.run_phase_b), (self.mod_pc, p.run_phase_c)]:
            try:
                if mod.checkable and mod._is_active != active:
                    mod._is_active = active
                    mod._apply_state_styles()
            except Exception:
                pass
        try:
            self.chk_confirm_gates.blockSignals(True)
            self.chk_confirm_gates.setChecked(p.confirm_between_phases)
            self._apply_confirm_style(p.confirm_between_phases)
            self.chk_confirm_gates.blockSignals(False)
        except Exception:
            pass
        self._recalc_math()

