from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List
import math
from PySide6.QtCore import Signal, Slot, Qt, QTimer
from PySide6.QtGui import QCursor, QDesktopServices, QImage, QPixmap
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
    server_toggle_requested = Signal(bool)
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
        self.btn_v_filtration.clicked.connect(lambda: self.valve_command_requested.emit("FILTRATION"))
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

        # PHASE A
        self.mod_pa = EliteModule("PHASE A: RAMP UP", "#8B5CF6", checkable=True)
        self.cmb_ramp_mode = QComboBox()
        self.cmb_ramp_mode.addItems(["Auto (Continuous Rate)", "Manual (Click for Step)"])
        self.cmb_ramp_mode.setStyleSheet("background: #0F172A; color: #FFF; border: 1px solid #1E293B; font-family: 'Consolas'; padding: 2px;")
        self.sp_target_p = NudgeSpinBox(0.0, 8000.0, 0, 100.0, " mbar", 2000.0)
        self.sp_a_rate = NudgeSpinBox(1.0, 5000.0, 0, 10.0, " mbar/min", 125.0)
        self.sp_a_step = NudgeSpinBox(1.0, 1000.0, 0, 10.0, " mbar", 250.0)
        
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
        self.sp_b_timeout = NudgeSpinBox(1.0, 60.0, 0, 1.0, " min", 5.0)
        self.mod_pb.addRow(1, "B2 V_Extra:", self.sp_v_extra)
        self.mod_pb.addRow(2, "No-Flow Timeout:", self.sp_b_timeout)
        
        self.lbl_pb_info = QLabel("Safety: stops if no flow for 5 min")
        self.lbl_pb_info.setProperty("is_dynamic_result", True)
        self.lbl_pb_info.setStyleSheet("color: #F59E0B; font-weight: bold; font-family: 'Consolas'; font-size: 11px; border: none; padding-top: 4px;")
        self.mod_pb.content_lay.addWidget(self.lbl_pb_info, 3, 0, 1, 2)
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

        # 🚀 TELEMETRY SERVER & QR CODE
        self.mod_srv = EliteModule("NETWORK MONITOR SERVER", "#10B981", checkable=False)
        
        # IP SICHER ERAHNT (Auch ohne Internet im Labornetzwerk)
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            self.local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            self.local_ip = "127.0.0.1"

        self.server_url = f"http://{self.local_ip}:8000"
        
        self.btn_toggle_srv = QPushButton("START SERVER")
        self.btn_toggle_srv.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_srv.setStyleSheet("background: #0F172A; color: #10B981; border: 1px solid #1E293B; padding: 6px; font-weight: bold; border-radius: 3px;")
        self.btn_toggle_srv.setCheckable(True)
        self.btn_toggle_srv.toggled.connect(self._on_server_toggled)

        self.mod_srv = EliteModule("NETWORK MONITOR SERVER", "#10B981", checkable=False)
        
        self.lbl_url = QLabel("Startet im Hintergrund...")
        self.lbl_url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_url.setStyleSheet("color: #00E5FF; font-weight: bold; font-family: 'Consolas'; font-size: 11px;")

        self.lbl_qr = QLabel()
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_qr.setMinimumHeight(120)
        self.lbl_qr.setStyleSheet("background: #fff; border-radius: 4px; padding: 5px;")
        self.lbl_qr.hide() # Bleibt versteckt, bis die URL kommt

        self.mod_srv.content_lay.addWidget(self.lbl_url, 0, 0, 1, 2)
        self.mod_srv.content_lay.addWidget(self.lbl_qr, 1, 0, 1, 2)
        root.addWidget(self.mod_srv)

        root.addStretch()
        self._current_bnnt_ml = 0.0
        self._wire_signals()
        self._load_last_params()  # Letzten Parametersatz wiederherstellen
        self._recalc_math()

    def _generate_qr(self, url: str):
        """Erzeugt den QR-Code aus der URL und legt ihn ins UI."""
        try:
            import qrcode
            import io
            from PySide6.QtGui import QImage, QPixmap
            
            qr = qrcode.QRCode(version=1, box_size=3, border=1)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = io.BytesIO()
            img.save(buf, "PNG")
            qimg = QImage.fromData(buf.getvalue())
            pixmap = QPixmap.fromImage(qimg)
            self.lbl_qr.setPixmap(pixmap)
            self.lbl_qr.show()  # QR-Code einblenden
            
        except ImportError:
            self.lbl_qr.setText("QR Error:\n'pip install qrcode pillow'\nnot found.")
            self.lbl_qr.setStyleSheet("color: #FF1744; font-weight: bold; font-size: 11px;")
            self.lbl_qr.show()

    def _on_server_toggled(self, checked: bool):
        if checked:
            self.btn_toggle_srv.setText("SERVER RUNNING")
            self.btn_toggle_srv.setStyleSheet("background: #10B981; color: #000; border: none; padding: 6px; font-weight: bold; border-radius: 3px;")
            self._generate_qr(self.server_url)
            self.lbl_qr.show()
        else:
            self.btn_toggle_srv.setText("START SERVER")
            self.btn_toggle_srv.setStyleSheet("background: #0F172A; color: #10B981; border: 1px solid #1E293B; padding: 6px; font-weight: bold; border-radius: 3px;")
            self.lbl_qr.hide()
        self.server_toggle_requested.emit(checked)

    def update_server_url(self, url: str):
        """Wird vom MainWindow aufgerufen, sobald der Server den Token generiert hat."""
        self.lbl_url.setText(url)
        self._generate_qr(url)

    def _wire_signals(self):
        widgets = [
            self.sp_area, self.sp_calib, self.sp_thick, self.sp_h2o,
            self.sp_fill_p, self.sp_est_flow, self.sp_target_p, self.sp_a_rate, 
            self.sp_a_step, self.sp_v_extra, self.sp_b_timeout, self.sp_dn_rate,
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

        # Phase B Info
        timeout_val = self.sp_b_timeout.value()
        extra_val = self.sp_v_extra.value()
        if extra_val > 0:
            self.lbl_pb_info.setText(f"B2: {extra_val:.0f} ml extra | Timeout: {timeout_val:.0f} min")
        else:
            self.lbl_pb_info.setText(f"Safety: stops if no flow for {timeout_val:.0f} min")

        self.params_changed.emit(self.get_run_params())
        self._save_last_params()

    def get_run_params(self) -> RunParams:
        p = RunParams(
            v_bnnt_ml=self._current_bnnt_ml, v_h2o_ml=self.sp_h2o.value(),
            run_phase_0=self.mod_p0.isChecked(), phase_0_pressure_mbar=self.sp_fill_p.value(),
            run_phase_a=self.mod_pa.isChecked(), phase_a_target_mbar=self.sp_target_p.value(),
            phase_a_rate_mbar_min=self.sp_a_rate.value(), phase_a_step_mbar=self.sp_a_step.value(),
            run_phase_b=self.mod_pb.isChecked(), v_extra_ml=self.sp_v_extra.value(),
            phase_b_no_flow_timeout_min=self.sp_b_timeout.value(),
            run_phase_c=self.mod_pc.isChecked(), phase_c_rate_mbar_min=self.sp_dn_rate.value(),
            confirm_between_phases=self.chk_confirm_gates.isChecked()
        )
        p.phase_0_mode = "auto" if self.cmb_fill_mode.currentIndex() == 0 else "continuous"
        p.phase_a_mode = "auto" if self.cmb_ramp_mode.currentIndex() == 0 else "manual"
        return p

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
        for m in self.modules + [self.mod_calc, self.mod_srv]:
            m.setEnabled(not running)
        self.frm_orchestrator.setEnabled(not running)
        self.grp_valves.setEnabled(not running)
            
        if not running:
            self.countdown_timer.stop()
            self._time_left_s = 0.0  # 🚀 FIX: Timer-State sauber zurücksetzen
            self._recalc_math() 
            self.update_active_step_highlight("IDLE")
            
    def update_active_step_highlight(self, current_step_str: str, current_pressure_mbar: float = 0.0):
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
            if self.cmb_ramp_mode.currentIndex() == 0:
                rate = self.sp_a_rate.value()
                # Delta: Wie viel Druck noch aufzubauen ist
                remaining_mbar = max(0.0, self.sp_target_p.value() - current_pressure_mbar)
                self._time_left_s = (remaining_mbar / rate * 60) if rate > 0 else 0
                
        elif "PHASE_B" in current_step_str: 
            self.mod_pb.setHighlight(True)
            
        elif "PHASE_C" in current_step_str: 
            self.mod_pc.setHighlight(True)
            rate = self.sp_dn_rate.value()
            # Delta: Wie viel Druck noch abzubauen ist
            remaining_mbar = current_pressure_mbar if current_pressure_mbar > 0 else self.sp_target_p.value()
            self._time_left_s = (remaining_mbar / rate * 60) if rate > 0 else 0
            
        elif "FILLING" in current_step_str or "0" in current_step_str:
            self.mod_p0.setHighlight(True)
            tot = self._current_bnnt_ml + self.sp_h2o.value()
            est_flow = self.sp_est_flow.value()
            if self.cmb_fill_mode.currentIndex() == 0 and est_flow > 0:
                self._time_left_s = (tot / est_flow) * 60

        # Nur starten, wenn wir wirklich im Run-Modus sind UND es Zeit gibt
        if self._time_left_s > 0 and self._is_running:
            self._update_countdown_labels()
            self.countdown_timer.start(1000)

    def _on_countdown_tick(self):
        if self._time_left_s > 0:
            self._time_left_s -= 1
            self._update_countdown_labels()
        else:
            self.countdown_timer.stop() # 🚀 FIX: Timer stoppen, wenn er 0 erreicht

    def _update_countdown_labels(self):
        """Hilfsfunktion, um die Labels zu zeichnen, getrennt vom reinen 'Tick'."""
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

    # -----------------------------------------------------------------
    # VALVE PANEL
    # -----------------------------------------------------------------
    _VALVE_RELAY_MAP = {
        "FILLING":     (True, False),
        "VENTING":     (True, False),
        "FILTRATION":  (False, True),
        "BACKWASH":    (True, True),
        "ALL_OPEN":    (True, True),
        "ALL_SHUT":    (False, False),
    }

    _VALVE_COLORS = {
        "FILLING":    ("#00E5FF", "#0C447C"),   # Cyan
        "VENTING":    ("#10B981", "#085041"),    # Green
        "FILTRATION": ("#8B5CF6", "#3C3489"),   # Purple
        "BACKWASH":   ("#EC4899", "#72243E"),   # Pink
        "ALL_OPEN":   ("#F59E0B", "#633806"),   # Amber
        "ALL_SHUT":   ("#64748B", "#1E293B"),   # Gray
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
        for btn, on, name in [(self.btn_r1, self._valve_r1_on, "R1"), (self.btn_r2, self._valve_r2_on, "R2")]:
            if on:
                btn.setText(f"{name}: ON")
                btn.setStyleSheet(
                    "color: #10B981; font-family: 'Consolas'; font-size: 10px; font-weight: bold; "
                    "background: #052E16; border: 1px solid #10B981; border-radius: 3px; padding: 3px;")
            else:
                btn.setText(f"{name}: OFF")
                btn.setStyleSheet(
                    "color: #64748B; font-family: 'Consolas'; font-size: 10px; font-weight: bold; "
                    "background: #0F172A; border: 1px solid #1E293B; border-radius: 3px; padding: 3px;")

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
        """Auto-Save: Speichert aktuelle UI-Werte als YAML."""
        if self._is_running:
            return  # Nicht während eines Runs speichern
        try:
            self.get_run_params().save_yaml(self._params_path())
        except Exception:
            pass  # Nicht-kritisch: stille Fehler

    def _load_last_params(self):
        """Auto-Load: Stellt die letzten UI-Werte aus der YAML wieder her."""
        try:
            p = RunParams.load_yaml(self._params_path())
        except Exception:
            return  # Datei existiert nicht oder ist korrupt → Defaults behalten

        # Werte in die Spinboxen schreiben (blockSignals um Cascade zu vermeiden)
        widgets_map = [
            (self.sp_h2o, p.v_h2o_ml),
            (self.sp_fill_p, p.phase_0_pressure_mbar),
            (self.sp_est_flow, 15.0),  # Est. Flow nicht persistiert (ist eine Schätzung)
            (self.sp_target_p, p.phase_a_target_mbar),
            (self.sp_a_rate, p.phase_a_rate_mbar_min),
            (self.sp_a_step, p.phase_a_step_mbar),
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

        # Comboboxen
        try:
            self.cmb_fill_mode.blockSignals(True)
            self.cmb_fill_mode.setCurrentIndex(0 if p.phase_0_mode == "auto" else 1)
            self.cmb_fill_mode.blockSignals(False)
        except Exception:
            pass
        try:
            self.cmb_ramp_mode.blockSignals(True)
            self.cmb_ramp_mode.setCurrentIndex(0 if p.phase_a_mode == "auto" else 1)
            self.cmb_ramp_mode.blockSignals(False)
        except Exception:
            pass

        # Phase-Toggles
        for mod, active in [(self.mod_p0, p.run_phase_0), (self.mod_pa, p.run_phase_a),
                            (self.mod_pb, p.run_phase_b), (self.mod_pc, p.run_phase_c)]:
            try:
                if mod.checkable and mod._is_active != active:
                    mod._is_active = active
                    mod._apply_state_styles()
            except Exception:
                pass

        # Orchestrator Toggle
        try:
            self.chk_confirm_gates.blockSignals(True)
            self.chk_confirm_gates.setChecked(p.confirm_between_phases)
            self._apply_confirm_style(p.confirm_between_phases)
            self.chk_confirm_gates.blockSignals(False)
        except Exception:
            pass