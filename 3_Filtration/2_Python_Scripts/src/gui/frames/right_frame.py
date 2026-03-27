from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import pyqtgraph as pg
from PySide6.QtCore import Signal, Slot, Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QLinearGradient, QFont
)
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextBrowser, QWidget, QTabWidget, QProgressBar
)
from src.utils.path_utils import ensure_dir, project_root, resolve_under
from src.gui.widgets.nudge_spinbox import NudgeSpinBox


# =========================================================================
# VISUALISIERUNG 1: SPHERICAL REACTOR (DIGITAL TWIN)
# =========================================================================
class ReactorSphereWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 200)
        self.setStyleSheet("background: transparent;")
        self._fill_pct = 0.5  # 0.5 bedeutet exakt auf Membran-Höhe
        self._color = QColor("#00E5FF")
        self._volume_ml = 0.0
        self._phase_label = ""

    def set_state(self, target_fill: float, phase: str):
        # FLUID-DYNAMICS: Weiche Annäherung an den Zielwert
        diff = target_fill - self._fill_pct
        if abs(diff) < 0.005:
            self._fill_pct = target_fill
        else:
            self._fill_pct += diff * 0.1

        phase_up = phase.upper()
        self._phase_label = phase_up
        if "FILL" in phase_up or "0" in phase_up:
            self._color = QColor("#00E5FF")
        elif "PHASE" in phase_up or "FILTRATION" in phase_up:
            self._color = QColor("#8B5CF6")
        elif "VENT" in phase_up:
            self._color = QColor("#10B981")
        elif "BACKWASH" in phase_up:
            self._color = QColor("#EC4899")
        else:
            self._color = QColor("#0EA5E9")

        self.update()

    def set_volume(self, vol_ml: float):
        self._volume_ml = float(vol_ml)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        radius = min(w, h) * 0.38
        cx = w / 2
        cy = (h - 20) / 2

        sphere_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        # 1. HINTERGRUND: Dunkles Kugel-Innere
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 23, 42, 200))
        p.drawEllipse(sphere_rect)

        # 2. FLÜSSIGKEIT
        if self._fill_pct > 0.01:
            liquid_h = (radius * 2) * self._fill_pct
            liquid_rect = QRectF(cx - radius, (cy + radius) - liquid_h, radius * 2, liquid_h)

            grad = QLinearGradient(0, liquid_rect.top(), 0, liquid_rect.bottom())
            grad.setColorAt(0.0, self._color)
            grad.setColorAt(1.0, self._color.darker(300))

            p.save()
            clip_path = QPainterPath()
            clip_path.addEllipse(sphere_rect)
            p.setClipPath(clip_path)
            p.setBrush(grad)
            p.drawRect(liquid_rect)

            # Meniskus
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawEllipse(QRectF(cx - radius, liquid_rect.top() - 3, radius * 2, 6))
            p.restore()

        # 3. KUGEL-OUTLINE
        p.setPen(QPen(QColor(71, 85, 105, 180), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(sphere_rect)

        # 4. MEMBRAN
        p.setPen(QPen(QColor(248, 250, 252, 150), 2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(cx - radius - 5, cy), QPointF(cx + radius + 5, cy))
        p.setPen(QColor("#64748B"))
        p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        p.drawText(QRectF(cx + radius + 8, cy - 10, 60, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MEMBRANE")

        # 5. VOLUMEN-READOUT (zentriert in der Kugel)
        p.setPen(QColor("#F8FAFC"))
        p.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        vol_text = f"{self._volume_ml:.0f}" if self._volume_ml >= 10 else f"{self._volume_ml:.1f}"
        p.drawText(QRectF(cx - radius, cy - 20, radius * 2, 25),
                   Qt.AlignmentFlag.AlignCenter, f"{vol_text} mL")

        # Prozent-Anzeige
        p.setPen(QColor(255, 255, 255, 120))
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        pct_text = f"{self._fill_pct * 100:.0f}%"
        p.drawText(QRectF(cx - radius, cy + 5, radius * 2, 15),
                   Qt.AlignmentFlag.AlignCenter, pct_text)

        # 6. LABEL
        p.setPen(QColor("#94A3B8"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy + radius + 15, w, 15), Qt.AlignmentFlag.AlignCenter, "CELL STATE")


# =========================================================================
# VISUALISIERUNG 2: ELITE PRESSURE PROFILE (RAMP HUD)
# =========================================================================
class TrapezoidWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 200)
        self.setStyleSheet("background: transparent;")
        self._current_p = 0.0
        self._setpoint_p = 0.0
        self._peak_p = 2000.0
        self._phase = "IDLE"
        # Dynamische Profil-Fraktionen (Anteil A / B / C an Gesamtbreite)
        self._frac_a = 0.28
        self._frac_b = 0.44
        self._frac_c = 0.28

    def update_profile(self, target_mbar: float, rate_a_mbar_min: float, rate_c_mbar_min: float):
        """Aktualisiert die Rampensteilheit anhand echter Parameter."""
        if target_mbar > 0:
            self._peak_p = float(target_mbar)
        rate_a = max(1.0, float(rate_a_mbar_min))
        rate_c = max(1.0, float(rate_c_mbar_min))
        time_a = self._peak_p / rate_a        # Minuten für Ramp Up
        time_c = self._peak_p / rate_c        # Minuten für Ramp Down
        time_b = max(time_a * 1.5, 10.0)     # Haltephase (geschätzt)
        total = time_a + time_b + time_c
        if total > 0:
            self._frac_a = time_a / total
            self._frac_b = time_b / total
            self._frac_c = time_c / total
        self.update()

    def set_state(self, current_p: float, setpoint: float, phase: str):
        self._current_p = max(0.0, current_p)
        self._setpoint_p = max(0.0, setpoint)
        self._phase = phase.upper()
        # _peak_p is owned exclusively by update_profile(); never grow it here
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        pad_x, pad_y = 25, 30
        plot_w = w - 2 * pad_x
        plot_h = h - 2 * pad_y

        # 1. X-Achse
        p.setPen(QPen(QColor(30, 41, 59), 3))
        p.drawLine(pad_x, h - pad_y, w - pad_x, h - pad_y)

        # Ideale Rampe (dynamisch aus _frac_a/_frac_b/_frac_c)
        x_a_end = pad_x + plot_w * self._frac_a
        x_b_end = pad_x + plot_w * (self._frac_a + self._frac_b)
        path = QPainterPath()
        pt1 = QPointF(pad_x, h - pad_y)
        pt2 = QPointF(x_a_end, pad_y)
        pt3 = QPointF(x_b_end, pad_y)
        pt4 = QPointF(pad_x + plot_w, h - pad_y)

        path.moveTo(pt1)
        path.lineTo(pt2)
        path.lineTo(pt3)
        path.lineTo(pt4)

        # 2. Füllung
        grad_bg = QLinearGradient(0, pad_y, 0, h - pad_y)
        grad_bg.setColorAt(0.0, QColor(139, 92, 246, 50))
        grad_bg.setColorAt(1.0, QColor(139, 92, 246, 0))

        bg_path = QPainterPath(path)
        bg_path.lineTo(pt1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad_bg)
        p.drawPath(bg_path)

        # 3. Kontur
        p.setPen(QPen(QColor(139, 92, 246, 200), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Phase-Labels auf der X-Achse (dynamisch positioniert)
        p.setPen(QColor("#64748B"))
        p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        label_y = h - pad_y + 14
        p.drawText(QPointF(pad_x + plot_w * (self._frac_a * 0.5), label_y), "A")
        p.drawText(QPointF(pad_x + plot_w * (self._frac_a + self._frac_b * 0.5), label_y), "B")
        p.drawText(QPointF(pad_x + plot_w * (self._frac_a + self._frac_b + self._frac_c * 0.5), label_y), "C")

        # 4. SETPOINT-LINIE (horizontal, gestrichelt)
        disp_max = max(self._peak_p, 100.0)
        if self._setpoint_p > 0:
            norm_sp = min(1.0, self._setpoint_p / disp_max)
            sp_y = (h - pad_y) - (norm_sp * plot_h)
            p.setPen(QPen(QColor(248, 250, 252, 60), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(pad_x, sp_y), QPointF(w - pad_x, sp_y))
            p.setPen(QColor(248, 250, 252, 100))
            p.setFont(QFont("Consolas", 7))
            p.drawText(QPointF(w - pad_x + 4, sp_y + 4), f"{int(self._setpoint_p)}")

        # 5. LIVE TRACKER
        norm_p = min(1.0, max(0.0, self._current_p / disp_max))

        if "PHASE_A" in self._phase:
            dot_x = pad_x + (norm_p * plot_w * self._frac_a)
        elif "PHASE_B" in self._phase:
            dot_x = pad_x + plot_w * (self._frac_a + self._frac_b * 0.5)
        elif "PHASE_C" in self._phase:
            down_progress = 1.0 - norm_p
            dot_x = pad_x + plot_w * (self._frac_a + self._frac_b) + (down_progress * plot_w * self._frac_c)
        else:
            dot_x = pad_x
            norm_p = 0.0

        dot_y = (h - pad_y) - (norm_p * plot_h)

        # Crosshair
        p.setPen(QPen(QColor(0, 229, 255, 120), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(pad_x, dot_y), QPointF(dot_x, dot_y))
        p.drawLine(QPointF(dot_x, dot_y), QPointF(dot_x, h - pad_y))

        # Glow Point
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 229, 255, 60))
        p.drawEllipse(QPointF(dot_x, dot_y), 12, 12)
        p.setBrush(QColor("#00E5FF"))
        p.drawEllipse(QPointF(dot_x, dot_y), 5, 5)

        # Druck-Label am Punkt
        p.setPen(QColor("#F8FAFC"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Black))
        p.drawText(QPointF(dot_x + 10, dot_y - 10), f"{int(self._current_p)}")

        # 6. Y-Achse Beschriftung (mbar)
        p.setPen(QColor("#64748B"))
        p.setFont(QFont("Consolas", 7))
        p.drawText(QPointF(2, pad_y + 5), f"{int(disp_max)}")
        p.drawText(QPointF(2, h - pad_y - 2), "0")

        # 7. TITEL
        p.setPen(QColor("#94A3B8"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRectF(0, h - 15, w, 15), Qt.AlignmentFlag.AlignCenter, "PRESSURE PROFILE")


def _to_float(x) -> float:
    if x is None: return 0.0
    try:
        if isinstance(x, dict): return 0.0
        v = float(x)
        return v if v == v else 0.0
    except Exception:
        return 0.0


# =========================================================================
# RIGHT FRAME MAIN
# =========================================================================
class RightFrame(QFrame):
    start_clicked = Signal()
    stop_clicked = Signal()
    manual_vent_clicked = Signal()
    ok_clicked = Signal()
    filling_confirmed = Signal(float)  # Bediener hat Filling bestätigt: Menge in ml

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")
        self._running = False
        
        self._ui_phase = "IDLE"
        
        # 🚀 GROUND TRUTH CALIBRATION STATES
        self._current_vol_ml = 0.0
        self._membrane_vol_ml = 3500.0  # Fallback: Exakt die Mitte von 7 Litern
        self.MAX_CELL_VOLUME_ML = 7000.0 

        root_path = project_root(__file__)
        ensure_dir(resolve_under(root_path, "logs"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        # 1. PHYSICAL MODEL (direkt, ohne Tabs)
        viz_frame = QFrame()
        viz_frame.setStyleSheet("background-color: #050914; border: 1px solid #1E293B; border-radius: 6px;")
        viz_lay = QHBoxLayout(viz_frame)
        viz_lay.setContentsMargins(8, 8, 8, 8)

        # Linker Block: Kugel + Kalibrierungs-Button
        left_viz_widget = QWidget()
        left_viz_widget.setStyleSheet("background: transparent;")
        left_viz_lay = QVBoxLayout(left_viz_widget)
        left_viz_lay.setContentsMargins(0, 0, 0, 0)

        self.sandglass = ReactorSphereWidget()
        left_viz_lay.addWidget(self.sandglass)

        self.btn_calib = QPushButton("⌖ SET MEMBRANE")
        self.btn_calib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_calib.setStyleSheet("""
            QPushButton {
                background: transparent; color: #64748B;
                font-family: 'Consolas'; font-size: 9px; font-weight: bold;
                border: 1px solid #1E293B; border-radius: 4px; padding: 4px 8px;
            }
            QPushButton:hover { background: #0F172A; color: #00E5FF; border: 1px solid #00E5FF; }
        """)
        self.btn_calib.clicked.connect(self._calibrate_membrane)
        left_viz_lay.addWidget(self.btn_calib, alignment=Qt.AlignmentFlag.AlignHCenter)

        viz_lay.addWidget(left_viz_widget)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setStyleSheet("color: #1E293B;")
        viz_lay.addWidget(separator)

        self.trapezoid = TrapezoidWidget()
        viz_lay.addWidget(self.trapezoid)

        lay.addWidget(viz_frame, stretch=3)

        # 2. TERMINAL
        term_lay = QVBoxLayout()
        term_lay.setSpacing(2)
        lbl_term = QLabel("SYSTEM TERMINAL")
        lbl_term.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-weight: bold; font-size: 10px; letter-spacing: 2px;")
        term_lay.addWidget(lbl_term)

        self.console = QTextBrowser()
        self.console.document().setMaximumBlockCount(1000)
        self.console.setStyleSheet("""
            QTextBrowser {
                background-color: #090F16;
                color: #94A3B8;
                font-family: 'Consolas';
                font-size: 11px;
                border: 1px solid #1E293B;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        term_lay.addWidget(self.console)
        lay.addLayout(term_lay, stretch=2)

        # 2b. PHASE PROGRESS PANEL (erweitert: B1/B2 Unterscheidung)
        self._progress_target_ml = 0.0
        self._progress_current_ml = 0.0
        self._b1_target_ml = 0.0
        self._b1_current_ml = 0.0
        self._b2_target_ml = 0.0
        self._b2_current_ml = 0.0

        self.frm_progress = QFrame()
        self.frm_progress.setStyleSheet(
            "background: #0B1120; border: 1px solid #1E293B; border-radius: 4px;")
        prog_lay = QVBoxLayout(self.frm_progress)
        prog_lay.setContentsMargins(12, 8, 12, 8)
        prog_lay.setSpacing(4)

        # Zeile 1: Phase-Label + Gesamtwerte
        prog_top = QHBoxLayout()
        self.lbl_prog_phase = QLabel("IDLE")
        self.lbl_prog_phase.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; letter-spacing: 1px; border: none;")
        self.lbl_prog_values = QLabel("")
        self.lbl_prog_values.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_prog_values.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 10px; font-weight: bold; border: none;")
        prog_top.addWidget(self.lbl_prog_phase)
        prog_top.addStretch()
        prog_top.addWidget(self.lbl_prog_values)
        prog_lay.addLayout(prog_top)

        # Haupt-Progressbar
        self.bar_progress = QProgressBar()
        self.bar_progress.setRange(0, 1000)
        self.bar_progress.setValue(0)
        self.bar_progress.setTextVisible(False)
        self.bar_progress.setFixedHeight(6)
        self.bar_progress.setStyleSheet("""
            QProgressBar { background: #0F172A; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: qlineargradient(
                x1:0, y1:0, x2:1, y2:0,
                stop:0 #8B5CF6, stop:0.5 #00E5FF, stop:1 #10B981
            ); border-radius: 3px; }
        """)
        prog_lay.addWidget(self.bar_progress)

        # B1/B2 Detail-Reihe
        b_detail_lay = QHBoxLayout()
        b_detail_lay.setSpacing(12)
        self.lbl_b1_detail = QLabel("B1: —")
        self.lbl_b1_detail.setStyleSheet(
            "color: #F59E0B; font-family: 'Consolas'; font-size: 10px; font-weight: bold; border: none;")
        self.lbl_b2_detail = QLabel("")
        self.lbl_b2_detail.setStyleSheet(
            "color: #10B981; font-family: 'Consolas'; font-size: 10px; font-weight: bold; border: none;")
        self.lbl_b2_detail.hide()
        b_detail_lay.addWidget(self.lbl_b1_detail)
        b_detail_lay.addWidget(self.lbl_b2_detail)
        b_detail_lay.addStretch()
        prog_lay.addLayout(b_detail_lay)

        # B1-Bar
        self.bar_b1 = QProgressBar()
        self.bar_b1.setRange(0, 1000)
        self.bar_b1.setValue(0)
        self.bar_b1.setTextVisible(False)
        self.bar_b1.setFixedHeight(4)
        self.bar_b1.setStyleSheet("""
            QProgressBar { background: #0F172A; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #F59E0B; border-radius: 2px; }
        """)
        self.bar_b1.hide()
        prog_lay.addWidget(self.bar_b1)

        self.frm_progress.hide()
        lay.addWidget(self.frm_progress)

        # 3a. FILLING BANNER (cyan – manuelles Filling)
        self.banner_filling = QFrame()
        self.banner_filling.setStyleSheet(
            "background-color: #0C2A3A; border: 2px solid #00E5FF; border-radius: 4px;")
        fill_banner_lay = QVBoxLayout(self.banner_filling)
        fill_banner_lay.setContentsMargins(12, 8, 12, 8)
        fill_banner_lay.setSpacing(6)

        fill_title_row = QHBoxLayout()
        lbl_fill_title = QLabel("MANUELLES FILLING ERFORDERLICH")
        lbl_fill_title.setStyleSheet(
            "color: #00E5FF; font-weight: bold; font-family: 'Consolas'; font-size: 12px; border: none;")
        fill_title_row.addWidget(lbl_fill_title)
        fill_title_row.addStretch()
        fill_banner_lay.addLayout(fill_title_row)

        fill_input_row = QHBoxLayout()
        self.lbl_fill_recommend = QLabel("Empfohlen: — ml")
        self.lbl_fill_recommend.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_fill_amount = NudgeSpinBox(0.0, 10000.0, 1, 100.0, " ml", 0.0)
        lbl_fill_ml = QLabel("Eingefüllt:")
        lbl_fill_ml.setStyleSheet("color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")

        self.btn_filling_done = QPushButton("FILLING COMPLETE → CONTINUE")
        self.btn_filling_done.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filling_done.setStyleSheet("""
            QPushButton {
                background-color: #052E16; color: #10B981;
                font-family: 'Consolas'; font-weight: bold; font-size: 11px;
                border: 1px solid #10B981; border-radius: 3px; padding: 6px 14px;
            }
            QPushButton:hover { background-color: #10B981; color: #000; }
        """)
        self.btn_filling_done.clicked.connect(self._on_filling_done)

        fill_input_row.addWidget(self.lbl_fill_recommend)
        fill_input_row.addStretch()
        fill_input_row.addWidget(lbl_fill_ml)
        fill_input_row.addWidget(self.sp_fill_amount)
        fill_input_row.addWidget(self.btn_filling_done)
        fill_banner_lay.addLayout(fill_input_row)

        self.banner_filling.hide()
        lay.addWidget(self.banner_filling)

        # 3b. ACTION BANNER (amber – generische Phase-Gates)
        self.banner_ok = QFrame()
        self.banner_ok.setStyleSheet("background-color: #F59E0B; border-radius: 4px;")
        banner_lay = QHBoxLayout(self.banner_ok)
        banner_lay.setContentsMargins(10, 5, 10, 5)

        self.lbl_banner_reason = QLabel("")
        self.lbl_banner_reason.setStyleSheet(
            "color: #000000; font-weight: bold; font-family: 'Consolas'; font-size: 12px;")

        self.btn_ok = QPushButton("CONFIRM [OK]")
        self.btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #000000; color: #F59E0B; font-weight: bold; font-family: 'Consolas';
                border: 1px solid #000000; border-radius: 3px; padding: 5px 15px;
            }
            QPushButton:hover { background-color: #111827; color: #FFF; }
        """)
        self.btn_ok.clicked.connect(self.ok_clicked.emit)

        banner_lay.addWidget(self.lbl_banner_reason, 1)
        banner_lay.addWidget(self.btn_ok)
        self.banner_ok.hide()
        lay.addWidget(self.banner_ok)

        # 4. KONTROLL-BUTTONS (Bereinigt)
        ctrl_lay = QHBoxLayout()
        ctrl_lay.setSpacing(10)

        self.btn_start = self._action_btn("START SEQUENCE", "#10B981")
        self.btn_start.clicked.connect(self.start_clicked.emit)

        self.btn_stop = self._action_btn("EMERGENCY ABORT", "#FF1744")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_stop.setEnabled(False)

        # Der Kalibrierungs-Button wurde hier entfernt!
        ctrl_lay.addWidget(self.btn_start)
        ctrl_lay.addWidget(self.btn_stop)
        lay.addLayout(ctrl_lay)

    def _action_btn(self, text: str, color: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFixedHeight(40)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #111827;
                color: {color};
                font-family: 'Consolas'; font-weight: bold; font-size: 12px; letter-spacing: 1px;
                border: 1px solid #1E293B; border-bottom: 2px solid {color}; border-radius: 4px;
            }}
            QPushButton:hover:enabled {{ background-color: #1E293B; color: #FFF; }}
            QPushButton:disabled {{ background-color: #050914; color: #334155; border: 1px solid #0F172A; }}
        """)
        return btn

    @Slot()
    def reset_state(self):
        self.console.clear()
        self.banner_ok.hide()
        self.banner_filling.hide()
        self._ui_phase = "IDLE"
        self._current_vol_ml = 0.0
        self._progress_target_ml = 0.0
        self._progress_current_ml = 0.0
        self._b1_target_ml = 0.0
        self._b2_target_ml = 0.0
        self.sandglass.set_state(0.5, "IDLE")
        self.trapezoid.set_state(0.0, 0.0, "IDLE")
        self.frm_progress.hide()
        self.bar_progress.setValue(0)

    @Slot(str)
    def set_step(self, step: str):
        self._ui_phase = step.upper()
        self.append_log(f"--- STEP TRANSITION: {self._ui_phase} ---", "#8B5CF6")
        self._update_progress_phase(self._ui_phase)

    @Slot(str)
    def set_status(self, msg: str):
        pass

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        self._loss_ml = loss_ml
        self._progress_current_ml = abs(float(loss_ml))
        self._update_progress_bar()

    def set_progress_target(self, target_ml: float):
        """Wird vom MainWindow beim Run-Start aufgerufen."""
        self._progress_target_ml = max(0.01, float(target_ml))
        self.frm_progress.show()
        self._update_progress_bar()

    def _update_progress_phase(self, phase: str):
        """Aktualisiert Phase-Label und Farbe des Fortschrittsbalkens."""
        phase_colors = {
            "FILLING": ("#00E5FF", "PHASE 0: FILLING"),
            "PHASE_A": ("#8B5CF6", "PHASE A: RAMP UP"),
            "PHASE_B": ("#F59E0B", "PHASE B: STEADY STATE"),
            "PHASE_C": ("#EC4899", "PHASE C: RAMP DOWN"),
            "FINISHED": ("#10B981", "COMPLETE"),
            "ABORTED": ("#FF1744", "ABORTED"),
        }

        color, label = "#64748B", phase
        for key, (c, l) in phase_colors.items():
            if key in phase:
                color, label = c, l
                break

        self.lbl_prog_phase.setText(label)
        self.lbl_prog_phase.setStyleSheet(
            f"color: {color}; font-family: 'Consolas'; font-size: 10px; "
            f"font-weight: bold; letter-spacing: 1px; border: none;")

        # Gradient-Farbe des Balkens an die Phase anpassen
        self.bar_progress.setStyleSheet(f"""
            QProgressBar {{ background: #0F172A; border: none; border-radius: 4px; }}
            QProgressBar::chunk {{ background: {color}; border-radius: 4px; }}
        """)

        if phase in ("FINISHED", "ABORTED", "IDLE"):
            if phase == "FINISHED":
                self.bar_progress.setValue(1000)
                self.lbl_prog_values.setText("DONE")
            elif phase == "ABORTED":
                self.lbl_prog_values.setText("STOPPED")

    def _update_progress_bar(self):
        """Aktualisiert Balken und Zahlenwerte."""
        if self._progress_target_ml < 0.01:
            self.lbl_prog_values.setText(f"{self._progress_current_ml:.2f} mL")
            self.bar_progress.setValue(0)
            return

        pct = min(100.0, self._progress_current_ml / self._progress_target_ml * 100.0)
        self.bar_progress.setValue(int(pct * 10))  # 0-1000 Range für Smoothness
        self.lbl_prog_values.setText(
            f"{self._progress_current_ml:.1f} / {self._progress_target_ml:.1f} mL ({pct:.0f}%)"
        )
        self.lbl_prog_values.setStyleSheet(
            "color: #F8FAFC; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")

    def set_base_remove_ml(self, base_ml: float):
        pass

    @Slot(str, str)
    def append_log(self, msg: str, color: str = "#94A3B8"):
        ts = time.strftime("%H:%M:%S")
        html = f'<span style="color: #64748B;">[{ts}]</span> <span style="color: {color};">{msg}</span>'
        self.console.append(html)
        vs = self.console.verticalScrollBar()
        vs.setValue(vs.maximum())

    def enable_ok(self, enabled: bool):
        self.btn_ok.setEnabled(enabled)

    def set_running(self, running: bool):
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

        if running:
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #0F172A; color: #334155;
                    font-family: 'Consolas'; font-weight: bold; font-size: 12px; letter-spacing: 1px;
                    border: 1px solid #1E293B; border-bottom: 2px solid #1E293B; border-radius: 4px;
                }
            """)
        else:
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #111827; color: #10B981;
                    font-family: 'Consolas'; font-weight: bold; font-size: 12px; letter-spacing: 1px;
                    border: 1px solid #1E293B; border-bottom: 2px solid #10B981; border-radius: 4px;
                }
                QPushButton:hover { background-color: #1E293B; color: #FFF; }
            """)

    @Slot()
    def _calibrate_membrane(self):
        """Setzt das aktuell gemessene Volumen als exakten 50% Punkt der Zelle."""
        self._membrane_vol_ml = self._current_vol_ml
        self.append_log(f"SYS: Membrane visual calibration set to {self._membrane_vol_ml:.2f} mL", "#00E5FF")
        # Direkter Trigger um das UI an den neuen Ankerpunkt anzupassen
        self.update_telemetry({"volume_ml": self._current_vol_ml, "step": self._ui_phase})

    @Slot(dict)
    def update_telemetry(self, sample: dict):
        if not isinstance(sample, dict):
            return
        
        pressures = sample.get("pressure")
        if not isinstance(pressures, dict): 
            pressures = {}

        p1_data = pressures.get(1, pressures.get("1", {}))
        if not isinstance(p1_data, dict):
            p1_data = {}

        p1_raw = sample.get("p1_meas") if sample.get("p1_meas") is not None else p1_data.get("meas", 0.0)
        p1 = _to_float(p1_raw)

        p1_set_raw = sample.get("p1_set") if sample.get("p1_set") is not None else p1_data.get("set", 0.0)
        p1_set = _to_float(p1_set_raw)
        
        vol = _to_float(sample.get("volume_ml", 0.0))
        self._current_vol_ml = vol  # Speichern für Kalibrierung
        self.sandglass.set_volume(vol)
        
        step = str(sample.get("step", "IDLE")).upper()

        self.trapezoid.set_state(p1, p1_set, self._ui_phase)

        # 🚀 Visuelle Non-lineare Skalierung anhand des kalibrierten Membran-Punkts
        if "FILLING" in step or "BACKWASH" in step or "FILTRATION" in step or "PHASE" in self._ui_phase:
            if vol <= self._membrane_vol_ml:
                # Volumen unterhalb der Membran (0% bis 50% im UI)
                if self._membrane_vol_ml > 0:
                    fill_pct = (vol / self._membrane_vol_ml) * 0.5
                else:
                    fill_pct = 0.0
            else:
                # Volumen oberhalb der Membran (50% bis 100% im UI)
                upper_capacity = self.MAX_CELL_VOLUME_ML - self._membrane_vol_ml
                if upper_capacity > 0:
                    fill_pct = 0.5 + ((vol - self._membrane_vol_ml) / upper_capacity) * 0.5
                else:
                    fill_pct = 1.0
            
            # Clamp zwischen 0.0 und 1.0 um Überläufe bei der Animation zu verhindern
            fill_pct = max(0.0, min(1.0, fill_pct))
            self.sandglass.set_state(fill_pct, step if "PHASE" not in self._ui_phase else self._ui_phase)
            
        elif step == "VENTING":
            self.sandglass.set_state(0.5, "VENTING")
        else:
            self.sandglass.set_state(0.5, "IDLE")

        pass  # Telemetrie vollständig in TopFrame und Worker-CSV verarbeitet

    # -----------------------------------------------------------------
    # FILLING BANNER
    # -----------------------------------------------------------------
    @Slot(float)
    def show_filling_banner(self, recommended_ml: float):
        """Zeigt das Filling-Banner mit empfohlenem Füllvolumen."""
        rec = max(0.0, float(recommended_ml))
        self.lbl_fill_recommend.setText(f"Empfohlen: {rec:.1f} ml (letzte Zyklus-Verluste)")
        self.sp_fill_amount.setValue(rec)
        self.banner_filling.show()
        self.append_log(
            f"FILLING REQUIRED — Recommended: {rec:.1f} ml", "#00E5FF"
        )

    @Slot()
    def hide_filling_banner(self):
        """Versteckt das Filling-Banner."""
        self.banner_filling.hide()

    @Slot()
    def _on_filling_done(self):
        """Bediener hat Filling bestätigt — emittiert Signal mit eingegebener Menge."""
        ml = float(self.sp_fill_amount.value())
        self.append_log(f"FILLING CONFIRMED: {ml:.1f} ml eingefüllt", "#10B981")
        self.filling_confirmed.emit(ml)

    def set_ok_banner(self, step: str, reason: str, show: bool):
        # Filling wird über banner_filling abgewickelt — generischen Banner überspringen
        if show and str(step).upper() == "FILLING":
            return
        if show:
            self.lbl_banner_reason.setText(f"WAITING: {reason.upper()}")
            self.banner_ok.show()
        else:
            self.banner_ok.hide()

    # -----------------------------------------------------------------
    # PHASE DETAIL (B1 / B2 Fortschritt)
    # -----------------------------------------------------------------
    @Slot(str, float, float)
    def update_phase_detail(self, phase_id: str, current: float, target: float):
        """Aktualisiert B1/B2 Detail-Labels und Balken."""
        pid = phase_id.upper()
        if pid == "B1":
            self._b1_current_ml = float(current)
            self._b1_target_ml = float(target)
            if target > 0:
                pct = min(100.0, current / target * 100.0)
                self.lbl_b1_detail.setText(
                    f"B1: {current:.1f} / {target:.1f} ml ({pct:.0f}%)"
                )
                self.bar_b1.setValue(int(pct * 10))
            else:
                self.lbl_b1_detail.setText(f"B1: {current:.1f} ml")
                self.bar_b1.setValue(0)
            self.bar_b1.show()
        elif pid == "B2":
            self._b2_current_ml = float(current)
            self._b2_target_ml = float(target)
            if target > 0:
                pct = min(100.0, current / target * 100.0)
                self.lbl_b2_detail.setText(
                    f"B2: {current:.1f} / {target:.1f} ml ({pct:.0f}%)"
                )
            else:
                self.lbl_b2_detail.setText(f"B2: {current:.1f} ml")
            self.lbl_b2_detail.show()