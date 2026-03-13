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
# VISUALISIERUNG 1: SPHERICAL REACTOR (DIGITAL TWIN)
# =========================================================================
class ReactorSphereWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 200)
        self.setStyleSheet("background: transparent;")
        self._fill_pct = 0.5  # Startet bei 50% (Bis zur Membran)
        self._color = QColor("#00E5FF")
        
    def set_state(self, target_fill: float, phase: str):
        # 🚀 FLUID-DYNAMICS: Weiche Annäherung an den Zielwert
        diff = target_fill - self._fill_pct
        if abs(diff) < 0.005:
            self._fill_pct = target_fill
        else:
            self._fill_pct += diff * 0.1 # 10% Annäherung pro Tick
            
        phase_up = phase.upper()
        if "FILL" in phase_up or "0" in phase_up: 
            self._color = QColor("#00E5FF")  # Cyan (Wasser + BNNT)
        elif "A" in phase_up or "B" in phase_up or "C" in phase_up or "FILTRATION" in phase_up: 
            self._color = QColor("#8B5CF6")  # Purple (Druck anliegend)
        elif "VENT" in phase_up: 
            self._color = QColor("#10B981")  # Green (Druckabbau)
        elif "BACKWASH" in phase_up: 
            self._color = QColor("#EC4899")  # Pink (Rückspülung)
        else:
            self._color = QColor("#334155")  # Slate (Idle)
        
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        
        # Abmessungen der Kugel (Sphere)
        radius = min(w, h) * 0.38
        cx = w / 2
        cy = (h - 20) / 2
        
        sphere_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        
        # 1. HINTERGRUND: Dunkles Kugel-Innere
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 23, 42, 200)) # Slate 900
        p.drawEllipse(sphere_rect)
        
        # 2. FLÜSSIGKEIT: In der Kugel geclippt
        if self._fill_pct > 0.01:
            liquid_h = (radius * 2) * self._fill_pct
            liquid_rect = QRectF(cx - radius, (cy + radius) - liquid_h, radius * 2, liquid_h)
            
            grad = QLinearGradient(0, liquid_rect.top(), 0, liquid_rect.bottom())
            grad.setColorAt(0.0, self._color) 
            grad.setColorAt(1.0, self._color.darker(300)) 
            
            p.save()
            # 🚀 WICHTIG: Die Flüssigkeit nimmt die Form der Kugel an!
            clip_path = QPainterPath()
            clip_path.addEllipse(sphere_rect)
            p.setClipPath(clip_path)
            
            p.setBrush(grad)
            p.drawRect(liquid_rect)
            
            # Meniskus (Lichtreflex an der Wasseroberfläche)
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawEllipse(QRectF(cx - radius, liquid_rect.top() - 3, radius * 2, 6))
            p.restore()

        # 3. KUGEL-OUTLINE (Glaswand)
        p.setPen(QPen(QColor(71, 85, 105, 180), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(sphere_rect)
        
        # 4. DIE MEMBRAN (Exakt in der Mitte der Kugel)
        p.setPen(QPen(QColor(248, 250, 252, 150), 2, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(cx - radius - 5, cy), QPointF(cx + radius + 5, cy))
        
        # Kleines Label an der Membran
        p.setPen(QColor("#64748B"))
        p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        p.drawText(QRectF(cx + radius + 8, cy - 10, 50, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MEMBRANE")

        # 5. TEXT OVERLAY
        p.setPen(QColor("#94A3B8"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRectF(0, cy + radius + 15, w, 15), Qt.AlignmentFlag.AlignCenter, "CELL STATE")

# =========================================================================
# VISUALISIERUNG 2: ELITE PRESSURE PROFILE (RAMP HUD)
# =========================================================================
class TrapezoidWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(250, 200) # Höhe an den Reaktor angepasst
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
        
        pad_x, pad_y = 25, 30
        plot_w = w - 2 * pad_x
        plot_h = h - 2 * pad_y
        
        # 1. BASIS: X-Achse (Massiv)
        p.setPen(QPen(QColor(30, 41, 59), 3)) # Slate 800
        p.drawLine(pad_x, h - pad_y, w - pad_x, h - pad_y)
        
        # Geometrie der idealen Rampe berechnen
        path = QPainterPath()
        p1 = QPointF(pad_x, h - pad_y)                   # Start
        p2 = QPointF(pad_x + plot_w*0.3, pad_y)          # Ende Ramp Up
        p3 = QPointF(pad_x + plot_w*0.7, pad_y)          # Ende Steady State
        p4 = QPointF(pad_x + plot_w, h - pad_y)          # Ende Ramp Down
        
        path.moveTo(p1)
        path.lineTo(p2)
        path.lineTo(p3)
        path.lineTo(p4)
        
        # 2. HOLOGRAPHISCHE FÜLLUNG (Unter der Kurve)
        grad_bg = QLinearGradient(0, pad_y, 0, h - pad_y)
        grad_bg.setColorAt(0.0, QColor(139, 92, 246, 50)) # Purple transparent
        grad_bg.setColorAt(1.0, QColor(139, 92, 246, 0))  # Fade into dark
        
        bg_path = QPainterPath(path)
        bg_path.lineTo(p1) # Pfad unten schließen für saubere Füllung
        
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad_bg)
        p.drawPath(bg_path)

        # 3. NEON-KONTUR (Die Soll-Kurve)
        p.setPen(QPen(QColor(139, 92, 246, 200), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        
        # 4. TACTICAL LIVE TRACKER (Wo stehen wir gerade?)
        norm_p = min(1.0, self._current_p / self._max_p)
        dot_y = (h - pad_y) - (norm_p * plot_h)
        
        # Logik: Steigt der Druck, sind wir auf der linken Flanke. Ist er Max, in der Mitte.
        if norm_p < 0.98: 
            dot_x = pad_x + (norm_p * plot_w * 0.3)
        else: 
            dot_x = pad_x + plot_w * 0.5 
            
        # Gestrichelte Ziellinie (Crosshair) zur Y-Achse
        p.setPen(QPen(QColor(0, 229, 255, 120), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(pad_x, dot_y), QPointF(dot_x, dot_y))
        p.drawLine(QPointF(dot_x, dot_y), QPointF(dot_x, h - pad_y))
        
        # Der leuchtende Messpunkt (Cyan)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 229, 255, 60)) # Outer Glow
        p.drawEllipse(QPointF(dot_x, dot_y), 12, 12)
        p.setBrush(QColor("#00E5FF"))       # Inner Core
        p.drawEllipse(QPointF(dot_x, dot_y), 5, 5)
        
        # Fliegendes Label: Exakter Druck über dem Punkt
        p.setPen(QColor("#F8FAFC"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Black))
        # Leicht versetzt oben rechts vom Punkt
        p.drawText(QPointF(dot_x + 10, dot_y - 10), f"{int(self._current_p)}")

        # 5. TITEL
        p.setPen(QColor("#94A3B8"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRectF(0, h - 15, w, 15), Qt.AlignmentFlag.AlignCenter, "PRESSURE PROFILE")

# =========================================================================
# VISUALISIERUNG 3: REAL TIME MONITOR TAB (ELITE LEVEL - CRASH PROOF)
# =========================================================================
def _to_float(x) -> float:
    """Kugelsicher: Keine NaNs, keine Nones, keine Strings."""
    try:
        if x is None: return 0.0
        v = float(x)
        return v if v == v else 0.0  # v == v filtert NaN heraus
    except Exception: 
        return 0.0

class MonitorTab(QFrame):
    def __init__(self, parent=None, max_points: int = 1500) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._max_points = int(max_points)

        self._t0: Optional[float] = None
        self._t = []
        self._flow = []
        self._p1 = []
        self._p2 = []
        
        self._csv_file = None
        self._csv_writer = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        pg.setConfigOptions(antialias=True)
        pg.setConfigOption('background', '#050914') 
        pg.setConfigOption('foreground', '#94A3B8')

        self.plot_p = pg.PlotWidget(title="PRESSURE TELEMETRY (mbar)")
        self.plot_flow = pg.PlotWidget(title="FLOW DYNAMICS (mL/min)")

        # Elite Achsen-Styling
        for plot in [self.plot_p, self.plot_flow]:
            plot.showGrid(x=False, y=True, alpha=0.1)
            plot.getAxis('bottom').setPen(pg.mkPen('#1E293B'))
            plot.getAxis('bottom').setTextPen(pg.mkPen('#64748B'))
            plot.getAxis('left').setPen(pg.mkPen('#1E293B'))
            plot.getAxis('left').setTextPen(pg.mkPen('#64748B'))

        self.plot_flow.getViewBox().setLimits(minYRange=1.0, minXRange=10.0)
        self.plot_p.getViewBox().setLimits(minYRange=100.0, minXRange=10.0)

        # Flow Gradient (Pink)
        grad_flow = QLinearGradient(0, 0, 0, 1)
        grad_flow.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad_flow.setColorAt(0.0, QColor(236, 72, 153, 100))
        grad_flow.setColorAt(1.0, QColor(236, 72, 153, 0))
        brush_flow = QBrush(grad_flow)

        pen_flow = pg.mkPen(color='#EC4899', width=2.5)
        self.curve_flow = self.plot_flow.plot([], [], pen=pen_flow, fillLevel=0, brush=brush_flow)

        # Pressure Gradient (Lila)
        grad_p1 = QLinearGradient(0, 0, 0, 1)
        grad_p1.setCoordinateMode(QLinearGradient.CoordinateMode.ObjectBoundingMode)
        grad_p1.setColorAt(0.0, QColor(139, 92, 246, 80))
        grad_p1.setColorAt(1.0, QColor(139, 92, 246, 0))
        brush_p1 = QBrush(grad_p1)

        pen_p1 = pg.mkPen(color='#8B5CF6', width=2.5)
        self.curve_p1 = self.plot_p.plot([], [], pen=pen_p1, fillLevel=0, brush=brush_p1, name="P1 Main")

        pen_p2 = pg.mkPen(color='#00E5FF', width=2, style=Qt.PenStyle.DashLine)
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

    def start_logging(self, run_name_prefix: str = "Run") -> None:
        self.reset_plot()
        self._csv_file = None
        self._csv_writer = None
        
        log_dir = resolve_under(project_root(__file__), "logs")
        ensure_dir(log_dir)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        csv_path = Path(log_dir) / f"{run_name_prefix}_{timestamp}.csv"
        
        try:
            self._csv_file = open(csv_path, 'w', newline='')
            self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=['t', 'flow', 'p1_meas', 'p2_meas'])
            self._csv_writer.writeheader()
        except Exception as e:
            print(f"Error opening CSV file: {e}")

    def stop_logging(self) -> None:
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception: pass
            finally:
                self._csv_file = None
                self._csv_writer = None

    @Slot(dict)
    def ingest_telemetry(self, payload: dict) -> None:
        import time
        current_time = time.monotonic()

        if self._t0 is None: 
            self._t0 = current_time
            # 🚀 Graphen-Ansicht beim Start auf 0 bis 60 Sekunden zwingen
            self.plot_p.setXRange(0, 60)
            self.plot_flow.setXRange(0, 60)
        
        ts = current_time - self._t0

        if len(self._t) > 0 and ts <= self._t[-1]:
            ts = self._t[-1] + 0.005 

        flow = _to_float(payload.get("flow"))
        
        pressures = payload.get("pressure", {})
        p1_data = pressures.get(1, pressures.get("1", {}))
        p2_data = pressures.get(2, pressures.get("2", {}))

        p1_raw = payload.get("p1_meas") if payload.get("p1_meas") is not None else p1_data.get("meas", 0.0)
        p2_raw = payload.get("p2_meas") if payload.get("p2_meas") is not None else p2_data.get("meas", 0.0)

        p1 = _to_float(p1_raw)
        p2 = _to_float(p2_raw)

        self._t.append(ts)
        self._flow.append(flow)
        self._p1.append(p1)
        self._p2.append(p2)

        if len(self._t) > self._max_points:
            self._t = self._t[-self._max_points :]
            self._flow = self._flow[-self._max_points :]
            self._p1 = self._p1[-self._max_points :]
            self._p2 = self._p2[-self._max_points :]

        # 🚀 Radar-Scrolling: Die X-Achse wandert nach 60 Sekunden automatisch mit
        if ts > 60:
            self.plot_p.setXRange(ts - 60, ts)
            self.plot_flow.setXRange(ts - 60, ts)

        if len(self._t) > 0:
            self.curve_flow.setData(self._t, self._flow)
            self.curve_p1.setData(self._t, self._p1)
            self.curve_p2.setData(self._t, self._p2)
        
        if self._csv_writer is not None and self._csv_file is not None and not self._csv_file.closed:
            try:
                self._csv_writer.writerow({'t': f"{ts:.3f}", 'flow': flow, 'p1_meas': p1, 'p2_meas': p2})
            except Exception: pass


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
        
        root_path = project_root(__file__)
        ensure_dir(resolve_under(root_path, "logs"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        # 1. TABS
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #1E293B; border-radius: 6px; background: #050914; }
            QTabBar::tab { background: #0F172A; color: #64748B; padding: 8px 16px; margin-right: 2px; 
                           border-top-left-radius: 4px; border-top-right-radius: 4px; 
                           font-family: 'Consolas'; font-weight: bold; font-size: 10px; }
            QTabBar::tab:selected { background: #1E293B; color: #00E5FF; border-bottom: 2px solid #00E5FF; }
        """)

        tab_viz = QWidget()
        viz_lay = QHBoxLayout(tab_viz)
        self.sandglass = ReactorSphereWidget()
        self.trapezoid = TrapezoidWidget()
        viz_lay.addWidget(self.sandglass)
        separator = QFrame(frameShape=QFrame.Shape.VLine)
        separator.setStyleSheet("color: #1E293B;")
        viz_lay.addWidget(separator)
        viz_lay.addWidget(self.trapezoid)
        
        self.realtime_plot = MonitorTab()

        self.tabs.addTab(tab_viz, "PHYSICAL MODEL")
        self.tabs.addTab(self.realtime_plot, "LIVE TELEMETRY")
        
        lay.addWidget(self.tabs, stretch=3)

        # 2. TERMINAL
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

        # 3. ACTION BANNER
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
        self.sandglass.set_state(0.0, "IDLE")
        self.trapezoid.set_pressure(0.0, 2000.0)
        self.realtime_plot.stop_logging()

    @Slot(str)
    def set_step(self, step: str):
        self.append_log(f"--- STEP TRANSITION: {step} ---", "#8B5CF6")

    @Slot(str)
    def set_status(self, msg: str):
        pass 

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        self._loss_ml = loss_ml

    def set_base_remove_ml(self, base_ml: float):
        pass 

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
            self.realtime_plot.start_logging(run_name_prefix="PelliKAn_Run")
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #0F172A; color: #334155;
                    font-family: 'Consolas'; font-weight: bold; font-size: 12px; letter-spacing: 1px;
                    border: 1px solid #1E293B; border-bottom: 2px solid #1E293B; border-radius: 4px;
                }
            """)
        else:
            self.realtime_plot.stop_logging()
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #111827; color: #10B981;
                    font-family: 'Consolas'; font-weight: bold; font-size: 12px; letter-spacing: 1px;
                    border: 1px solid #1E293B; border-bottom: 2px solid #10B981; border-radius: 4px;
                }
                QPushButton:hover { background-color: #1E293B; color: #FFF; }
            """)

    @Slot(dict)
    def update_telemetry(self, sample: dict):
        pressures = sample.get("pressure", {})
        p1_data = pressures.get(1, pressures.get("1", {}))

        p1_raw = sample.get("p1_meas") if sample.get("p1_meas") is not None else p1_data.get("meas", 0.0)
        p1_set_raw = sample.get("p1_set") if sample.get("p1_set") is not None else p1_data.get("set", 0.0)

        p1 = _to_float(p1_raw)
        max_p = _to_float(p1_set_raw)

        if max_p is None or max_p < 10:
            max_p = max(abs(p1), 100.0) if p1 > 10 else 2000.0
            
        step = str(sample.get("step", "IDLE")).upper()
        
        self.trapezoid.set_pressure(p1, max_p)

        # ════════════════════════════════════════════════════════════════════
        # 🚀 DIGITAL TWIN LOGIC: Physikalisches Füllvolumen der Kugel
        # Die Membran liegt exakt bei 0.50 (50%).
        # ════════════════════════════════════════════════════════════════════
        if "0" in step or "FILL" in step:
            # Zelle wird mit V_BNNT + V_H2O gefüllt. 
            # Rest nach oben ist Luft (ca 80% Füllstand visuell)
            target_fill = 0.80  
            
        elif "A" in step:
            # Rampe baut Druck auf. Wasser wird durch die Membran gepresst.
            # Flüssigkeit sinkt von 80% in Richtung 50%.
            p_ratio = min(1.0, max(0.0, p1 / max_p)) if max_p > 0 else 0.0
            target_fill = 0.80 - (p_ratio * 0.30) 
            
        elif "B1" in step or ("B" in step and "2" not in step):
            # Phase B1: Zieldruck erreicht, wir pressen weiter bis zur Membran.
            target_fill = 0.50  
            
        elif "B2" in step:
            # Phase B2: Extra-Trocknung (V_extra). 
            # Flüssigkeit verschwindet unter die Membran in den unteren Bereich.
            target_fill = 0.40  
            
        elif "C" in step or "VENT" in step:
            # Phase C: Ramp Down / Venting. Restwasser wird verdrängt (V_rd).
            target_fill = 0.30  
            
        elif "BACKWASH" in step:
            # Backwash drückt Flüssigkeit von unten durch die Membran nach oben.
            target_fill = 0.85
            
        else:
            # IDLE: Grundzustand. Unter der Membran voll, drüber leer.
            target_fill = 0.50  

        # Sende Ziel-Volumen an die Sphäre
        self.sandglass.set_state(target_fill, step)

        if "t" not in sample:
            import time
            sample["t"] = time.time()
            
        self.realtime_plot.ingest_telemetry(sample)