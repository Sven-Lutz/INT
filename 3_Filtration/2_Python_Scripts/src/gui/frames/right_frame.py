from __future__ import annotations

import time
from typing import Optional
from pathlib import Path
import csv
from dataclasses import dataclass

import pyqtgraph as pg
from PySide6.QtCore import Signal, Slot, Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath, QLinearGradient, QFont
)
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextBrowser, QWidget, QTabWidget
)
from src.utils.path_utils import ensure_dir, project_root, resolve_under

# =========================================================================
# VISUALISIERUNG 1: DIE SANDUHR (CELL FILL LEVEL)
# =========================================================================
class SandglassWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 150)
        self.setStyleSheet("background: transparent;")
        self._fill_pct = 0.0
        self._color = QColor("#00E5FF")

    def set_state(self, fill_pct: float, phase: str):
        self._fill_pct = max(0.0, min(1.0, fill_pct))
        
        # Farbwechsel je nach Phase
        if "FILL" in phase: self._color = QColor("#00E5FF")
        elif "PHASE" in phase: self._color = QColor("#8B5CF6")
        elif "VENT" in phase: self._color = QColor("#10B981")
        elif "BACKWASH" in phase: self._color = QColor("#EC4899")
        
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        glass_w = w * 0.5
        glass_h = h * 0.8
        
        # 1. Sanduhr-Pfad zeichnen
        path = QPainterPath()
        path.moveTo(cx - glass_w/2, cy - glass_h/2) # Oben links
        path.lineTo(cx + glass_w/2, cy - glass_h/2) # Oben rechts
        path.lineTo(cx + 5, cy)                     # Mitte rechts
        path.lineTo(cx + glass_w/2, cy + glass_h/2) # Unten rechts
        path.lineTo(cx - glass_w/2, cy + glass_h/2) # Unten links
        path.lineTo(cx - 5, cy)                     # Mitte links
        path.closeSubpath()

        # Füllung (Flüssigkeit) im unteren Bereich (simuliert)
        fill_h = (glass_h/2) * self._fill_pct
        fill_rect = QRectF(cx - glass_w/2, cy + glass_h/2 - fill_h, glass_w, fill_h)
        
        p.save()
        p.setClipPath(path)
        grad = QLinearGradient(0, cy, 0, cy + glass_h/2)
        grad.setColorAt(0, self._color.darker(150))
        grad.setColorAt(1, self._color)
        p.fillRect(fill_rect, grad)
        p.restore()

        # Outline zeichnen (Neon Glow)
        p.setPen(QPen(QColor(30, 41, 59, 200), 4))
        p.drawPath(path)
        p.setPen(QPen(QColor(248, 250, 252, 100), 1))
        p.drawPath(path)
        
        # Text Overlay
        p.setPen(QColor("#94A3B8"))
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.drawText(QRectF(0, h - 15, w, 15), Qt.AlignmentFlag.AlignCenter, "CELL VOL")

# =========================================================================
# VISUALISIERUNG 2: DAS TRAPEZ (PRESSURE RAMP PROFILE)
# =========================================================================
class TrapezoidWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 150)
        self.setStyleSheet("background: transparent;")
        self._current_p = 0.0
        self._max_p = 2000.0

    def set_pressure(self, current: float, max_p: float):
        self._current_p = max(0.0, current)
        self._max_p = max(1.0, max_p)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        
        pad_x, pad_y = 20, 20
        plot_w = w - 2 * pad_x
        plot_h = h - 2 * pad_y
        
        # Achsen
        p.setPen(QPen(QColor("#1E293B"), 2))
        p.drawLine(pad_x, h - pad_y, w - pad_x, h - pad_y) # X-Achse
        
        # Ideales Trapez (A -> B -> C)
        path = QPainterPath()
        p1 = QPointF(pad_x, h - pad_y)                   # Start
        p2 = QPointF(pad_x + plot_w*0.3, pad_y)          # Ende Ramp Up (Phase A)
        p3 = QPointF(pad_x + plot_w*0.7, pad_y)          # Ende Steady (Phase B)
        p4 = QPointF(pad_x + plot_w, h - pad_y)          # Ende Ramp Down (Phase C)
        
        path.moveTo(p1); path.lineTo(p2); path.lineTo(p3); path.lineTo(p4)
        
        p.setPen(QPen(QColor(100, 116, 139, 100), 2, Qt.PenStyle.DashLine))
        p.drawPath(path)

        # Aktueller Druck als leuchtender Punkt auf der Y-Achse interpoliert
        norm_p = min(1.0, self._current_p / self._max_p)
        dot_y = (h - pad_y) - (norm_p * plot_h)
        
        # Wir bewegen den Punkt künstlich nach rechts basierend auf dem Druck (nur optische Hilfestellung)
        if norm_p < 0.95: dot_x = pad_x + (norm_p * plot_w * 0.3)
        else: dot_x = pad_x + plot_w * 0.5 # In der Mitte bei Steady State

        # Glow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(139, 92, 246, 50))
        p.drawEllipse(QPointF(dot_x, dot_y), 12, 12)
        p.setBrush(QColor("#8B5CF6"))
        p.drawEllipse(QPointF(dot_x, dot_y), 5, 5)

        # Text Overlay
        p.setPen(QColor("#94A3B8"))
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.drawText(QRectF(0, h - 15, w, 15), Qt.AlignmentFlag.AlignCenter, "PRESSURE PROFILE")

# =========================================================================
# VISUALISIERUNG 3: REAL TIME MONITOR TAB (ELITE LEVEL)
# =========================================================================
def _to_float(x) -> Optional[float]:
    try: return None if x is None else float(x)
    except Exception: return None

def _nan(x: Optional[float]) -> float:
    return float("nan") if x is None else float(x)

class MonitorTab(QFrame):
    def __init__(self, parent=None, max_points: int = 2000) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._max_points = int(max_points)

        self._t0: Optional[float] = None
        self._t = []
        self._flow = []
        self._p1 = []
        self._p2 = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        pg.setConfigOptions(antialias=True)
        pg.setConfigOption('background', '#050914') # Dark Theme passend zum RightFrame
        pg.setConfigOption('foreground', '#94A3B8')

        self.plot_p = pg.PlotWidget(title="PRESSURE TELEMETRY (mbar)")
        self.plot_flow = pg.PlotWidget(title="FLOW DYNAMICS (mL/min)")

        self.plot_flow.showGrid(x=False, y=True, alpha=0.1)
        self.plot_p.showGrid(x=False, y=True, alpha=0.1)

        # Limits setzen, um wildes Zoomen zu verhindern
        self.plot_flow.getViewBox().setLimits(minYRange=1.0, minXRange=10.0)
        self.plot_p.getViewBox().setLimits(minYRange=100.0, minXRange=10.0)

        # 🚀 CHROMA GRADIENT: Neon Pink zu Transparent für Flow 🚀
        grad_flow = QLinearGradient(0, 0, 0, 1)
        grad_flow.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad_flow.setColorAt(0.0, QColor(236, 72, 153, 100)) # Pink
        grad_flow.setColorAt(1.0, QColor(236, 72, 153, 0))
        brush_flow = QBrush(grad_flow)

        pen_flow = pg.mkPen(color='#EC4899', width=2.5) # Neon Pink Line
        self.curve_flow = self.plot_flow.plot([], [], pen=pen_flow, fillLevel=0, brush=brush_flow)

        # 🚀 CHROMA GRADIENT: Violett/Cyan für Pressure 🚀
        grad_p1 = QLinearGradient(0, 0, 0, 1)
        grad_p1.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad_p1.setColorAt(0.0, QColor(139, 92, 246, 80)) # Purple
        grad_p1.setColorAt(1.0, QColor(139, 92, 246, 0))
        brush_p1 = QBrush(grad_p1)

        pen_p1 = pg.mkPen(color='#8B5CF6', width=2.5) # Purple Line
        self.curve_p1 = self.plot_p.plot([], [], pen=pen_p1, fillLevel=0, brush=brush_p1, name="P1 Main")

        pen_p2 = pg.mkPen(color='#00E5FF', width=2, style=Qt.PenStyle.DashLine) # Cyan Line
        self.curve_p2 = self.plot_p.plot([], [], pen=pen_p2, name="P2 Backwash")

        root.addWidget(self.plot_p, 1)
        root.addWidget(self.plot_flow, 1)

    def reset_plot(self):
        self._t0 = None
        self._t.clear()
        self._flow.clear()
        self._p1.clear()
        self._p2.clear()
        self.curve_flow.setData([], [])
        self.curve_p1.setData([], [])
        self.curve_p2.setData([], [])

    @Slot(dict)
    def ingest_telemetry(self, payload: dict) -> None:
        t = payload.get("t", time.time())
        flow = _to_float(payload.get("flow"))
        p1 = _to_float(payload.get("p1_meas"))
        p2 = _to_float(payload.get("p2_meas"))

        if self._t0 is None: self._t0 = t
        ts = t - self._t0

        self._t.append(ts)
        self._flow.append(flow)
        self._p1.append(p1)
        self._p2.append(p2)

        if len(self._t) > self._max_points:
            self._t = self._t[-self._max_points :]
            self._flow = self._flow[-self._max_points :]
            self._p1 = self._p1[-self._max_points :]
            self._p2 = self._p2[-self._max_points :]

        self.curve_flow.setData(self._t, [_nan(v) for v in self._flow])
        self.curve_p1.setData(self._t, [_nan(v) for v in self._p1])
        self.curve_p2.setData(self._t, [_nan(v) for v in self._p2])

# =========================================================================
# RIGHT FRAME MAIN
# =========================================================================
class RightFrame(QFrame):
    start_clicked = Signal()
    stop_clicked = Signal()
    manual_vent_clicked = Signal()
    ok_clicked = Signal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")
        self._running = False
        self._loss_ml = 0.0  

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        # 1. TABS (Visualisierung & Graphen)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #1E293B; border-radius: 6px; background: #050914; }
            QTabBar::tab { background: #0F172A; color: #64748B; padding: 6px 12px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; font-family: 'Consolas'; font-weight: bold; font-size: 10px; }
            QTabBar::tab:selected { background: #1E293B; color: #00E5FF; }
        """)

        # Tab 1: Abstrakt
        tab_viz = QWidget()
        viz_lay = QHBoxLayout(tab_viz)
        self.sandglass = SandglassWidget()
        self.trapezoid = TrapezoidWidget()
        viz_lay.addWidget(self.sandglass)
        separator = QFrame(frameShape=QFrame.Shape.VLine)
        separator.setStyleSheet("color: #1E293B;")
        viz_lay.addWidget(separator)
        viz_lay.addWidget(self.trapezoid)
        
        # Tab 2: Echtzeit-Graphen
        self.realtime_plot = MonitorTab()

        self.tabs.addTab(tab_viz, "PHYSICAL MODEL")
        self.tabs.addTab(self.realtime_plot, "LIVE TELEMETRY")
        
        lay.addWidget(self.tabs, stretch=3)

        # 2. TERMINAL KONSOLEN-BEREICH
        term_lay = QVBoxLayout()
        term_lay.setSpacing(2)
        lbl_term = QLabel("SYSTEM TERMINAL")
        lbl_term.setStyleSheet("color: #64748B; font-family: 'Consolas'; font-weight: bold; font-size: 10px; letter-spacing: 2px;")
        term_lay.addWidget(lbl_term)

        self.console = QTextBrowser()
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

        # 3. ACTION BANNER (Für "OK" Klicks)
        self.banner_ok = QFrame()
        self.banner_ok.setStyleSheet("background-color: #F59E0B; border-radius: 4px;")
        banner_lay = QHBoxLayout(self.banner_ok)
        banner_lay.setContentsMargins(10, 5, 10, 5)
        
        self.lbl_banner_reason = QLabel("")
        self.lbl_banner_reason.setStyleSheet("color: #000000; font-weight: bold; font-family: 'Consolas'; font-size: 12px;")
        
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

        # 4. KONTROLL-BUTTONS
        ctrl_lay = QHBoxLayout()
        ctrl_lay.setSpacing(10)

        self.btn_start = self._action_btn("START SEQUENCE", "#10B981")
        self.btn_start.clicked.connect(self.start_clicked.emit)
        
        self.btn_stop = self._action_btn("EMERGENCY ABORT", "#FF1744")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_stop.setEnabled(False)

        self.btn_vent = self._action_btn("MANUAL VENT", "#64748B")
        self.btn_vent.clicked.connect(self.manual_vent_clicked.emit)

        ctrl_lay.addWidget(self.btn_start)
        ctrl_lay.addWidget(self.btn_stop)
        ctrl_lay.addWidget(self.btn_vent)
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
        self._loss_ml = 0.0
        self.sandglass.set_state(0.0, "IDLE")
        self.trapezoid.set_pressure(0.0, 2000.0)
        self.realtime_plot.reset_plot()

    @Slot(str)
    def set_step(self, step: str):
        self.append_log(f"--- STEP TRANSITION: {step} ---", "#8B5CF6")

    @Slot(str)
    def set_status(self, msg: str):
        pass # Status wird jetzt im TopFrame schön angezeigt

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        self._loss_ml = loss_ml

    def set_base_remove_ml(self, base_ml: float):
        pass # Nur für main_window compatibility

    @Slot(str, str)
    def append_log(self, msg: str, color: str = "#94A3B8"):
        ts = time.strftime("%H:%M:%S")
        html = f'<span style="color: #64748B;">[{ts}]</span> <span style="color: {color};">{msg}</span>'
        self.console.append(html)
        vs = self.console.verticalScrollBar()
        vs.setValue(vs.maximum())

    def set_ok_banner(self, step: str, reason: str, show: bool):
        if show:
            self.lbl_banner_reason.setText(f"WAITING: {reason.upper()}")
            self.banner_ok.show()
        else:
            self.banner_ok.hide()

    def enable_ok(self, enabled: bool):
        self.btn_ok.setEnabled(enabled)

    def set_running(self, running: bool):
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        
        if running:
            self.btn_start.setStyleSheet(self.btn_start.styleSheet().replace("color: #10B981;", "color: #334155;").replace("border-bottom: 2px solid #10B981;", "border-bottom: 2px solid #1E293B;"))
        else:
            self.btn_start.setStyleSheet(self.btn_start.styleSheet().replace("color: #334155;", "color: #10B981;").replace("border-bottom: 2px solid #1E293B;", "border-bottom: 2px solid #10B981;"))

    @Slot(dict)
    def update_telemetry(self, sample: dict):
        # 1. Update abstrakte Visuals
        p1 = sample.get("p1_meas", 0.0)
        max_p = sample.get("p1_set", 2000.0)
        if max_p is None or max_p < 1: max_p = 2000.0
        
        step = sample.get("step", "")
        
        self.trapezoid.set_pressure(p1, max_p)
        
        fill = min(1.0, max(0.0, p1 / max_p)) if max_p > 0 else 0.0
        self.sandglass.set_state(fill, step)

        # 2. Update Live-Plot!
        self.realtime_plot.ingest_telemetry(sample)