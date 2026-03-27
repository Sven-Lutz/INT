from __future__ import annotations

import logging
import threading
import time
import random
import math
from collections import deque
from typing import Deque, Optional, Set, Tuple, Any

import PySide6.QtWidgets as Qtw
from PySide6.QtCore import (
    QObject, QEvent, Qt, QThread, QTimer, Signal,
    QPropertyAnimation, QByteArray, QEasingCurve, Property, QRectF, Slot
)
from PySide6.QtGui import (
    QMouseEvent, QColor, QPainter, QPixmap,
    QBrush, QPen, QRadialGradient, QPainterPath
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMessageBox, QGraphicsOpacityEffect

from src.gui.data.worker import ExperimentConfig
from src.gui.data import ExperimentWorker, RunParams, worker
from src.gui.monitor.server import MonitorServer
from src.gui.health import HealthEvaluator, HealthRules, SystemHealth
from src.gui.style.theme import apply_theme
from src.utils.config_manager import ConfigManager
from src.utils.path_utils import ensure_dir, project_root, resolve_under

from .frames.left_frame import LeftFrame
from .frames.right_frame import RightFrame
from .frames.top_frame import TopFrame
from .frames.analysis_frame import AnalysisFrame

logger = logging.getLogger(__name__)

MAIN_CH = 1
BACKWASH_CH = 2

def _unwrap_sensor(val) -> float:
    if val is None: return 0.0
    if isinstance(val, (list, tuple)):
        return float(val[-1])
    return float(val)

def _safe_float(val) -> float:
    try: return float(val)
    except Exception: return 0.0

def _get_nested(d: dict, path: str, default=None):
    cur = d
    for key in (path or "").split("."):
        if not isinstance(cur, dict) or key not in cur: return default
        cur = cur[key]
    return cur

def _first_present(*vals, default=None):
    for v in vals:
        if v is not None: return v
    return default

class _GlobalInputFilter(QObject):
    hold_started = Signal()
    hold_stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._space_down = False
        self.main_window = parent

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseMove:
            if self.main_window and hasattr(self.main_window, 'hud') and self.main_window.hud.isVisible():
                pos = event.globalPosition()
                w = self.main_window.width()
                h = self.main_window.height()
                if w > 0 and h > 0:
                    dx = (w / 2 - pos.x()) / (w / 2)
                    dy = (h / 2 - pos.y()) / (h / 2)
                    self.main_window.hud.target_dx = dx * 20
                    self.main_window.hud.target_dy = dy * 20

        if event.type() == QEvent.Type.KeyPress and getattr(event, "key", lambda: None)() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if not self._space_down:
                self._space_down = True
                self.hold_started.emit()
            return True
        if event.type() == QEvent.Type.KeyRelease and getattr(event, "key", lambda: None)() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self._space_down:
                self._space_down = False
                self.hold_stopped.emit()
            return True
        return False

    def force_release(self):
        if self._space_down:
            self._space_down = False
            self.hold_stopped.emit()

class CustomTitleBar(Qtw.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self.setStyleSheet("background-color: #050914; border-bottom: 1px solid #1F2937;")
        lay = Qtw.QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 0, 0)

        lbl_title = Qtw.QLabel("LITTLE CHONKER // COMMAND NODE")
        lbl_title.setStyleSheet("color: #64748B; font-size: 11px; font-weight: bold; letter-spacing: 1.5px; border: none;")
        lay.addWidget(lbl_title)
        lay.addStretch(1)

        btn_style = "QPushButton { background: transparent; border: none; color: #64748B; font-size: 16px; } QPushButton:hover { background: #111827; color: #F8FAFC; }"
        close_style = "QPushButton { background: transparent; border: none; color: #64748B; font-size: 16px; } QPushButton:hover { background: #FF1744; color: #F8FAFC; }"

        self.btn_min = Qtw.QPushButton("—")
        self.btn_min.setFixedSize(46, 32)
        self.btn_min.setStyleSheet(btn_style)
        self.btn_min.clicked.connect(self.window().showMinimized)

        self.btn_max = Qtw.QPushButton("◻")
        self.btn_max.setFixedSize(46, 32)
        self.btn_max.setStyleSheet(btn_style)
        self.btn_max.clicked.connect(self._toggle_maximize)

        self.btn_close = Qtw.QPushButton("✕")
        self.btn_close.setFixedSize(46, 32)
        self.btn_close.setStyleSheet(close_style)
        self.btn_close.clicked.connect(self.window().close)

        lay.addWidget(self.btn_min)
        lay.addWidget(self.btn_max)
        lay.addWidget(self.btn_close)
        self._drag_pos = None

    def _toggle_maximize(self):
        if self.window().isMaximized():
            self.window().showNormal()
            self.btn_max.setText("◻")
        else:
            self.window().showMaximized()
            self.btn_max.setText("❐")

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.window().move(self.window().pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()

class ShockwaveOverlay(Qtw.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._radius = 0.0
        self._opacity = 0.0

    def get_radius(self): return self._radius
    def set_radius(self, v): self._radius = v; self.update()
    radius = Property(float, get_radius, set_radius)

    def get_opacity(self): return self._opacity
    def set_opacity(self, v): self._opacity = v; self.update()
    op = Property(float, get_opacity, set_opacity)

    def start_pulse(self):
        self.anim_group = QPropertyAnimation(self, b"radius")
        self.anim_group.setDuration(1200)
        self.anim_group.setStartValue(0)
        self.anim_group.setEndValue(max(self.width(), self.height()) * 1.5)
        self.anim_group.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.anim_op = QPropertyAnimation(self, b"op")
        self.anim_op.setDuration(1200)
        self.anim_op.setStartValue(1.0)
        self.anim_op.setEndValue(0.0)
        self.anim_op.setEasingCurve(QEasingCurve.Type.OutQuad)

        self.anim_group.start()
        self.anim_op.start()

    def paintEvent(self, e):
        if self._opacity > 0 and self._radius > 0:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setOpacity(self._opacity)
            p.setPen(QPen(QColor(0, 229, 255, 150), 30))
            p.drawEllipse(QRectF(self.width() / 2 - self._radius, self.height() / 2 - self._radius, self._radius * 2, self._radius * 2))
            p.setPen(QPen(QColor(255, 255, 255, 255), 4))
            p.drawEllipse(QRectF(self.width() / 2 - self._radius, self.height() / 2 - self._radius, self._radius * 2, self._radius * 2))
            p.end()

class ScanlineOverlay(Qtw.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.pix = QPixmap(10, 8)
        self.pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(self.pix)
        p.setPen(QColor(0, 229, 255, 20))
        p.drawLine(0, 0, 10, 0)
        p.end()
        self._offset = 0

    def tick(self):
        self._offset = (self._offset + 1) % 8
        self.update()

    def paintEvent(self, e):
        if self.width() > 0 and self.height() > 0:
            p = QPainter(self)
            p.drawTiledPixmap(0, self._offset, self.width(), self.height(), self.pix)
            p.end()

class Particle:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.start_x = x
        self.vy = random.uniform(-1.0, -3.0)
        self.size = random.uniform(3, 7)
        base_color = random.choice(["#FFFFFF", "#00E5FF", "#EC4899", "#8B5CF6", "#00FF66"])
        self.color = QColor(base_color)
        self.color.setAlpha(random.randint(150, 255))
        self.phase = random.uniform(0, math.pi * 2)
        self.speed = random.uniform(0.05, 0.15)
        self.drift = random.uniform(-0.5, 0.5)

class LiquidPelicanWidget(Qtw.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(500, 380)
        self._fill_lvl = 0.0
        self._phase = 0.0
        self.particles = []

        polygons = """
        <polygon points="130,60 145,55 195,80 140,90 120,80" />
        <polygon points="120,80 110,110 60,110 80,75" />
        <polygon points="80,75 30,10 50,55 65,85" />
        <polygon points="65,85 20,40 45,75 60,95" />
        <polygon points="60,110 30,125 40,130 75,115" />
        """

        svg_empty = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150"><g stroke="#1E293B" stroke-width="2" fill="none" stroke-linejoin="round">{polygons}</g></svg>"""
        svg_full = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150"><defs><linearGradient id="g" x1="0%" y1="100%" x2="0%" y2="0%"><stop offset="0%" style="stop-color:#EC4899;stop-opacity:0.95" /><stop offset="40%" style="stop-color:#8B5CF6;stop-opacity:0.95" /><stop offset="70%" style="stop-color:#00E5FF;stop-opacity:0.95" /><stop offset="100%" style="stop-color:#00FF66;stop-opacity:0.95" /></linearGradient></defs><g stroke="#00E5FF" stroke-width="2.5" fill="url(#g)" stroke-linejoin="round">{polygons}</g></svg>"""
        svg_mask = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 150"><g stroke="#FFFFFF" stroke-width="2.5" fill="#FFFFFF" stroke-linejoin="round">{polygons}</g></svg>"""

        self.pix_empty = QPixmap(self.size()); self.pix_empty.fill(Qt.GlobalColor.transparent)
        QSvgRenderer(QByteArray(svg_empty.encode())).render(QPainter(self.pix_empty))

        self.pix_full = QPixmap(self.size()); self.pix_full.fill(Qt.GlobalColor.transparent)
        QSvgRenderer(QByteArray(svg_full.encode())).render(QPainter(self.pix_full))

        self.pix_mask = QPixmap(self.size()); self.pix_mask.fill(Qt.GlobalColor.transparent)
        QSvgRenderer(QByteArray(svg_mask.encode())).render(QPainter(self.pix_mask))

        self.anim = QPropertyAnimation(self, b"fill_level")

    def get_fill(self) -> float: return self._fill_lvl
    def set_fill(self, val: float): self._fill_lvl = val; self.update()
    fill_level = Property(float, get_fill, set_fill)

    def target_fill(self, duration: int):
        self.anim.stop()
        self.anim.setDuration(duration)
        self.anim.setStartValue(self._fill_lvl)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.start()

    def update_physics(self):
        self._phase += 0.1
        if self._fill_lvl <= 0.01 or not self.isVisible(): return

        y_base = self.height() * (1.0 - self._fill_lvl)
        if len(self.particles) < 80:
            spawn_rate = 4 if self._fill_lvl < 1.0 else 1
            for _ in range(spawn_rate):
                if random.random() < 0.5:
                    self.particles.append(Particle(random.uniform(60, 440), random.uniform(y_base + 30, self.height() - 20)))

        alive = []
        for p in self.particles:
            p.x = p.start_x + math.sin(p.phase + p.y * p.speed) * 10 + p.drift
            p.y += p.vy
            if p.y > y_base + math.sin((p.x * 0.02) + self._phase) * 10: alive.append(p)
        self.particles = alive
        self.update()

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0: return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self.pix_empty)
        
        if self._fill_lvl <= 0.0: p.end(); return

        y_base = self.height() * (1.0 - self._fill_lvl)
        clip_path = QPainterPath()
        clip_path.moveTo(0, self.height())
        clip_path.lineTo(0, y_base)
        for x in range(0, self.width() + 10, 20):
            clip_path.lineTo(x, y_base + math.sin((x * 0.02) + self._phase) * 10)
        clip_path.lineTo(self.width(), self.height())
        clip_path.closeSubpath()

        p.save()
        p.setClipPath(clip_path)
        p.drawPixmap(0, 0, self.pix_full)

        part_layer = QPixmap(self.size()); part_layer.fill(Qt.GlobalColor.transparent)
        pp = QPainter(part_layer); pp.setRenderHint(QPainter.RenderHint.Antialiasing); pp.setPen(Qt.PenStyle.NoPen)
        for pt in self.particles:
            grad = QRadialGradient(pt.x, pt.y, pt.size)
            grad.setColorAt(0.0, QColor(255, 255, 255, 255)); grad.setColorAt(0.4, pt.color); grad.setColorAt(1.0, QColor(pt.color.red(), pt.color.green(), pt.color.blue(), 0))
            pp.setBrush(QBrush(grad))
            pp.drawEllipse(QRectF(pt.x - pt.size * 1.5, pt.y - pt.size * 1.5, pt.size * 3, pt.size * 3))
        pp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        pp.drawPixmap(0, 0, self.pix_mask)
        pp.end()

        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.drawPixmap(0, 0, part_layer)
        p.restore()

        if 0.01 < self._fill_lvl < 0.99:
            surface_path = QPainterPath()
            surface_path.moveTo(0, y_base + math.sin(self._phase) * 10)
            for x in range(0, self.width() + 10, 20):
                surface_path.lineTo(x, y_base + math.sin((x * 0.02) + self._phase) * 10)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.setPen(QPen(QColor(236, 72, 153, 90), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(surface_path)
            p.setPen(QPen(QColor(255, 255, 255), 2))
            p.drawPath(surface_path)
        p.end()

class PelicanHUD(Qtw.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.target_dx = 0.0; self.target_dy = 0.0
        self.current_dx = 0.0; self.current_dy = 0.0

        self.box = Qtw.QFrame(self)
        self.box.setFixedSize(650, 520)
        self.box.setStyleSheet("QFrame { background-color: rgba(5, 9, 20, 230); border: 2px solid rgba(236, 72, 153, 60); border-radius: 12px; }")

        self.scanlines = ScanlineOverlay(self.box); self.scanlines.setFixedSize(650, 520)
        
        # Style für die Eck-Diagnostik
        tel_style = "color: #0284C7; font-family: 'Consolas'; font-size: 10px; font-weight: bold; background: transparent; border: none;"

        self.tel_tl = Qtw.QLabel("SYS_THREADS: --", self.box)
        self.tel_tl.setStyleSheet(tel_style); self.tel_tl.move(25, 25)
        
        self.tel_tr = Qtw.QLabel("FLOW_BASE: --", self.box)
        self.tel_tr.setStyleSheet(tel_style); self.tel_tr.move(530, 25)
        
        self.tel_bl = Qtw.QLabel("PRESS_BASE: --", self.box)
        self.tel_bl.setStyleSheet(tel_style); self.tel_bl.move(25, 480)
        
        self.tel_br = Qtw.QLabel("USB_LATENCY: --", self.box)
        self.tel_br.setStyleSheet(tel_style); self.tel_br.move(530, 480)

        box_lay = Qtw.QVBoxLayout(self.box)
        box_lay.setContentsMargins(75, 60, 75, 60); box_lay.setSpacing(25)

        self.logo = LiquidPelicanWidget()
        self.title = Qtw.QLabel("PELLIKAN // OS")
        self.title.setStyleSheet("color: #F8FAFC; font-family: 'Consolas', monospace; font-size: 32px; font-weight: 900; letter-spacing: 12px; background: transparent; border: none;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.bar = Qtw.QProgressBar()
        self.bar.setFixedSize(500, 4); self.bar.setTextVisible(False)
        self.bar.setStyleSheet("QProgressBar { background: rgba(17, 24, 39, 200); border: none; } QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC4899, stop:0.4 #8B5CF6, stop:0.7 #00E5FF, stop:1 #00FF66); }")

        self.status = Qtw.QLabel("")
        self.status.setStyleSheet("color: #00E5FF; font-family: 'Consolas'; font-size: 13px; font-weight: bold; letter-spacing: 2px; background: transparent; border: none;")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        box_lay.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignCenter)
        box_lay.addWidget(self.title, 0, Qt.AlignmentFlag.AlignCenter)
        box_lay.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignCenter)
        box_lay.addWidget(self.status, 0, Qt.AlignmentFlag.AlignCenter)

        self.op_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.op_effect)
        self.op_effect.setOpacity(0.0)

        self.anim_fade_in = QPropertyAnimation(self.op_effect, b"opacity")
        self.anim_fade_in.setDuration(800)
        self.anim_fade_in.setStartValue(0.0)
        self.anim_fade_in.setEndValue(1.0)
        self.anim_fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._master_timer = QTimer(self)
        self._master_timer.timeout.connect(self._master_tick)
        self._master_tick_counter = 0

        self._tw_target = ""; self._tw_current = ""; self._tw_idx = 0
        self._cursor_visible = True

    def play_intro(self):
        self.anim_fade_in.start()
        self._master_timer.start(33)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.box.move(int((self.width() - self.box.width()) / 2), int((self.height() - self.box.height()) / 2))

    # 🚀 NEUE WISSENSCHAFTLICHE METHODE FÜR ECHTE DIAGNOSTIK
    def update_real_diagnostics(self, p_base: float, flow_base: float, usb_latency: float):
        import threading
        threads = threading.active_count()
        
        self.tel_tl.setText(f"SYS_THREADS: {threads}")
        self.tel_tr.setText(f"FLOW_BASE: {flow_base:.3f}")
        self.tel_bl.setText(f"PRESS_BASE: {p_base:.2f} mb")
        self.tel_br.setText(f"USB_LATENCY: {usb_latency:.1f} ms")

    def _master_tick(self):
        self._master_tick_counter += 1
        
        self.current_dx += (self.target_dx - self.current_dx) * 0.1
        self.current_dy += (self.target_dy - self.current_dy) * 0.1
        w, h = self.width(), self.height()
        if w > 100 and h > 100:
            self.box.move(int((w - self.box.width()) / 2 + self.current_dx), int((h - self.box.height()) / 2 + self.current_dy))

        self.logo.update_physics()
        if self._master_tick_counter % 2 == 0: 
            self.scanlines.tick()

        if self._tw_idx < len(self._tw_target):
            self._tw_current += self._tw_target[self._tw_idx]
            self._tw_idx += 1
            self._render_text()

        if self._master_tick_counter % 10 == 0:
            self._cursor_visible = not self._cursor_visible
            self._render_text()

    def lock_telemetry(self):
        pass

    def _render_text(self):
        cursor = " █" if self._cursor_visible else "  "
        self.status.setText(self._tw_current + cursor)

    def start_smooth_fill(self, duration: int):
        self.anim_bar = QPropertyAnimation(self.bar, b"value")
        self.anim_bar.setDuration(duration)
        self.anim_bar.setStartValue(0)
        self.anim_bar.setEndValue(100)
        self.anim_bar.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim_bar.start()
        
        self.logo.target_fill(duration)

    def update_text(self, text):
        self._tw_target = text.upper()
        self._tw_current = ""
        self._tw_idx = 0

    def stop(self):
        self._master_timer.stop()

class MainWindow(Qtw.QMainWindow):
    REALTIME_POLL_MS = 200
    HOLD_SETPOINT_RATE_MS = 100
    DEFAULT_TREND_WINDOW_S = 3.0
    DEFAULT_TREND_DEADBAND = 2.0
    HISTORY_MAX_SECONDS = 8.0

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.showMaximized()
        self.setMouseTracking(True)

        self.central_bg = Qtw.QWidget()
        self.central_bg.setMouseTracking(True)
        self.setCentralWidget(self.central_bg)

        # 🚀 DER HARDWARE-MUTEX: Verhindert, dass Threads gleichzeitig den Port abschießen
        self._hw_mutex = threading.RLock()

        self.master_grid = Qtw.QGridLayout(self.central_bg)
        self.master_grid.setContentsMargins(0, 0, 0, 0)

        self.main_container = Qtw.QWidget()
        self.main_container.setMouseTracking(True)
        self.main_layout = Qtw.QVBoxLayout(self.main_container)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)
        self.main_layout.addWidget(self.title_bar)

        content_wrapper = Qtw.QWidget()
        content_wrapper.setMouseTracking(True)
        content_layout = Qtw.QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(8, 8, 8, 8)
        content_layout.setSpacing(0)

        try:
            self.setStatusBar(Qtw.QStatusBar(self))
            if self.statusBar() is not None:
                self.statusBar().setStyleSheet("QStatusBar { background: transparent; color: #64748B; font-family: 'Consolas'; font-weight: bold; border: none; font-size: 11px; }")
        except Exception:
            pass

        self.cfg_manager = ConfigManager()
        self.config = self.cfg_manager.load_config("general") or {}

        self.dev = None
        self._simulation_mode = False
        self._init_device_manager_best_effort()

        self._thread: Optional[QThread] = None
        self._worker: Optional[ExperimentWorker] = None
        self._current_step: str = "IDLE"
        self._hold_active: bool = False
        self._hold_sources: Set[str] = set()
        self._last_good_comm_ts: Optional[float] = None
        self._is_booting = True

        health_cfg = _get_nested(self.config, "health", {})
        if not isinstance(health_cfg, dict): health_cfg = {}
        alarm_default = float(health_cfg.get("pressure_alarm_mbar") or self.config.get("pressure_alarm_mbar", 8000.0))

        val_idle = _first_present(health_cfg.get("idle_pressure_warn_mbar"), self.config.get("idle_pressure_warn_mbar"), default=200.0)
        val_flow = _first_present(health_cfg.get("flow_low_warn"), self.config.get("flow_low_warn"), default=0.05)
        val_comm = _first_present(health_cfg.get("comm_timeout_s"), self.config.get("comm_timeout_s"), default=2.0)

        self._health = HealthEvaluator(
            HealthRules(
                idle_pressure_warn_mbar=float(val_idle) if val_idle is not None else 200.0,
                pressure_alarm_mbar=alarm_default,
                flow_low_warn=float(val_flow) if val_flow is not None else 0.05,
                comm_timeout_s=float(val_comm) if val_comm is not None else 2.0,
            )
        )

        self._last_error_short = ""
        self._last_error_full = ""
        self._safe_state_forced = False
        self._rt_p1 = self._rt_p2 = self._rt_flow = self._rt_valves = None
        self._rt_hw_lock = threading.Lock()
        self._rt_hw_reading = False
        self._p1_hist: Deque[Tuple[float, float]] = deque(maxlen=256)
        self._p2_hist: Deque[Tuple[float, float]] = deque(maxlen=256)
        self._last_trend_mode: Tuple[bool, bool, str, str] = (False, False, "—", "—")
        self._last_manual_state_fp = None
        self._rt_t0: Optional[float] = None

        self.tabs = Qtw.QTabWidget()
        self.tabs.setMouseTracking(True)
        content_layout.addWidget(self.tabs)
        self.main_layout.addWidget(content_wrapper)

        self.tab_live = Qtw.QWidget()
        self.tab_live.setProperty("surface", "panel")
        layout_live = Qtw.QVBoxLayout(self.tab_live)
        layout_live.setContentsMargins(8, 12, 8, 8)
        layout_live.setSpacing(10)

        self.top = self._construct_frame(TopFrame, self.config)
        self.left = self._construct_frame(LeftFrame, self.config)
        self.right = self._construct_frame(RightFrame, self.config)

        layout_live.addWidget(self.top)

        left_scroll = Qtw.QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(Qtw.QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(self.left)

        splitter = Qtw.QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self.right)
        
        sizes = _get_nested(self.config, "ui.splitter_sizes", [450, 750])
        if isinstance(sizes, list):
            splitter.setSizes(sizes)

        layout_live.addWidget(splitter, 1)
        self.tabs.addTab(self.tab_live, "LIVE CONTROL")

        self.tab_analysis = AnalysisFrame()
        self.tabs.addTab(self.tab_analysis, "RUN ANALYSIS")

        apply_theme(self, "dark")

        self.master_grid.addWidget(self.main_container, 0, 0)

        self.frozen_overlay = Qtw.QWidget()
        self.frozen_overlay.setStyleSheet("background-color: rgba(2, 6, 23, 220);")
        self.frozen_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay_op = QGraphicsOpacityEffect(self.frozen_overlay)
        self.frozen_overlay.setGraphicsEffect(self.overlay_op)
        self.master_grid.addWidget(self.frozen_overlay, 0, 0)

        self.shockwave = ShockwaveOverlay()
        self.shockwave.hide()
        self.master_grid.addWidget(self.shockwave, 0, 0)

        self.hud = PelicanHUD()
        self.hud.setMouseTracking(True)
        self.master_grid.addWidget(self.hud, 0, 0)

        self.left.setEnabled(False)
        self.right.btn_start.setEnabled(False)

        self._rt_timer = QTimer(self)
        self._rt_timer.timeout.connect(self._poll_realtime)

        self._hold_setpoint_timer = QTimer(self)
        self._hold_setpoint_timer.setSingleShot(True)
        self._hold_setpoint_timer.timeout.connect(self._push_hold_setpoint_now)

        self.monitor: Optional[MonitorServer] = None
        self._start_monitor()

        self._global_filter = _GlobalInputFilter(self)
        app = Qtw.QApplication.instance()
        if app is not None:
            app.installEventFilter(self._global_filter)
            self._global_filter.hold_started.connect(self._on_space_pressed)
            self._global_filter.hold_stopped.connect(self._on_space_released)

        self.right.start_clicked.connect(self._start_experiment)
        self.right.ok_clicked.connect(self._send_ok)
        self.right.stop_clicked.connect(self._abort_run)
        self.left.btn_hold.hold_started.connect(lambda: self._hold_source_set("mouse", True))
        self.left.btn_hold.hold_ended.connect(lambda: self._hold_source_set("mouse", False))
        
        try:
            self.left.sp_hold_p.valueChanged.connect(self._schedule_hold_setpoint_push)
        except Exception:
            pass

        self.left.valve_command_requested.connect(self._on_valve_command)
        self.left.relay_toggle_requested.connect(self._on_relay_toggle)

        # Trapezoid-Widget mit Live-Parametern verknüpfen
        def _update_trapezoid(rp):
            try:
                self.right.trapezoid.update_profile(
                    target_mbar=float(rp.phase_a_target_mbar),
                    rate_a_mbar_min=float(rp.phase_a_rate_mbar_min),
                    rate_c_mbar_min=float(rp.phase_c_rate_mbar_min),
                )
            except Exception:
                pass
        self.left.params_changed.connect(_update_trapezoid)

        self._set_running_ui(False, reason="init")
        self._render_manual_state(reason="init")
        self._update_health_banner()

        QTimer.singleShot(100, self.hud.play_intro)
        QTimer.singleShot(1000, self._play_boot_sequence)

    def _play_boot_sequence(self):
        duration = 4000
        self.hud.start_smooth_fill(duration)

        steps = [
            ("Initializing Quantum Core", 0, "#64748B"),
            ("Energizing Containment", 800, "#EC4899"),
            ("Calibrating Flow", 1600, "#8B5CF6"),
            (f"Sim-Link: {'ACTIVE' if self._simulation_mode else 'OFF'}", 2400, "#00E5FF"),
            ("System Online", 3200, "#00E676")
        ]

        for text, delay, col in steps:
            QTimer.singleShot(delay, lambda t=text, c=col: self._boot_step_text(t, c))

        QTimer.singleShot(duration + 800, self._finish_boot)

    def _boot_step_text(self, text, col):
        self.hud.update_text(text)
        self.right.append_log(f"=> {text.upper()}", col)

    def _finish_boot(self):
        self._is_booting = False
        self.hud.stop() 

        self.shockwave.show()
        self.shockwave.start_pulse()

        self.fade_hud = QPropertyAnimation(self.hud.op_effect, b"opacity")
        self.fade_hud.setDuration(600)
        self.fade_hud.setStartValue(1.0)
        self.fade_hud.setEndValue(0.0)

        self.fade_overlay = QPropertyAnimation(self.overlay_op, b"opacity")
        self.fade_overlay.setDuration(900)
        self.fade_overlay.setStartValue(1.0)
        self.fade_overlay.setEndValue(0.0)

        self.fade_hud.finished.connect(self.hud.hide)
        self.fade_overlay.finished.connect(self.frozen_overlay.hide)
        self.fade_overlay.finished.connect(self.shockwave.hide)

        self.fade_hud.start()
        self.fade_overlay.start()

        self.left.setEnabled(True)
        self.right.btn_start.setEnabled(True)
        self.right.append_log("PELLIKAN OS ONLINE.", "#00E676")

        if self._simulation_mode:
            self.right.append_log(">>> RUNNING IN VIRTUAL SIMULATION MODE <<<", "#F59E0B")

        status_text = "SIMULATION: IDLE" if self._simulation_mode else "HARDWARE: IDLE"
        self.top.update_status(status_text)

        self._rt_timer.start(self.REALTIME_POLL_MS)

    def _on_space_pressed(self):
        if self.left.btn_hold.isEnabled():
            self._hold_source_set("space", True)

    def _on_space_released(self):
        self._hold_source_set("space", False)

    def _build_experiment_config(self) -> ExperimentConfig:
        root = project_root(__file__)
        log_dir = resolve_under(root, "logs")
        ensure_dir(log_dir)

        return ExperimentConfig(
            initial_volume_ml=float(self.config.get("initial_volume_ml", 0.0)),
            min_volume_ml=float(self.config.get("min_volume_ml", 0.0)),
            sample_period_s=float(self.config.get("sample_period_s", 0.2)),
            log_dir=str(log_dir),
            log_name_prefix="run",
            flow_is_ml_per_min=bool(self.config.get("flow_is_ml_per_min", True)),
            pressure_full_scale_mbar=float(self.config.get("pressure_full_scale_mbar", 8000.0)),
            ramp_update_dt_s=float(self.config.get("ramp_update_dt_s", 0.15)),
            base_backwash_remove_ml=float(self.config.get("base_backwash_remove_ml", 0.0)),
        )

    def _attach_device_manager_to_worker(self, worker: ExperimentWorker) -> None:
        if self.dev is None: return
        try:
            if hasattr(worker, 'set_device'): 
                getattr(worker, 'set_device')(self.dev)
            elif hasattr(worker, 'set_device_manager'): 
                getattr(worker, 'set_device_manager')(self.dev)
            else: 
                setattr(worker, 'dev', self.dev)
        except Exception as e:
            logger.warning(f"Could not attach hardware device to worker: {e}")

    def _start_experiment(self) -> None:
        if self._experiment_running(): return
        self._force_release_all("start")
        self.reset_safe_state()
        self.right.reset_state()
        
        setattr(self.left, '_loss_ml', 0.0)

        try:
            self.right.append_log(">>> INITIATING SEQUENCE <<<", "#10B981")
        except Exception:
            pass

        try:
            worker = ExperimentWorker(self._build_experiment_config())
            worker.set_params(self.left.get_run_params())
            self._attach_device_manager_to_worker(worker)

            thread = QThread(self)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)

            worker.request_ok.connect(self._on_request_ok)
            worker.status.connect(self._on_status)
            worker.step_changed.connect(self._on_step_changed)
            worker.log_msg.connect(self.right.append_log)
            worker.loss_updated.connect(self.right.set_loss_ml)

            worker.step_changed.connect(self._on_step_changed_with_pressure)
            worker.step_changed.connect(self.top.update_phase)
            worker.status.connect(self.top.update_status)
            worker.telemetry.connect(self.top.update_telemetry)
            worker.telemetry.connect(self.right.update_telemetry)
            worker.loss_updated.connect(self.top.set_loss_ml)

            # Filling-Banner Verbindungen
            worker.filling_requested.connect(self.right.show_filling_banner)
            self.right.filling_confirmed.connect(
                lambda ml: (
                    worker.set_filling_amount(ml),
                    worker.confirm_ok(),
                    self.right.hide_filling_banner()
                )
            )

            # B1/B2 Phasen-Detail
            worker.phase_detail_updated.connect(self.right.update_phase_detail)

            # Progress-Target für die TopFrame-Anzeige setzen
            run_p = self.left.get_run_params()
            target_vol = float(run_p.v_bnnt_ml) + float(run_p.phase_b1_target_ml)
            self.top.set_progress_target(target_vol)
            self.right.set_progress_target(target_vol)
            self._monitor_target_ml = target_vol

            if self.monitor is not None:
                worker.status.connect(self.monitor.update_status)
                worker.step_changed.connect(self.monitor.update_step)
                worker.loss_updated.connect(self.monitor.update_loss)
                worker.telemetry.connect(self._push_worker_telemetry_to_monitor)

            try:
                pw = getattr(self.tab_analysis, "plot_widget", None)
                if pw is not None and hasattr(pw, "plot"):
                    worker.telemetry.connect(pw.plot)
            except Exception:
                pass

            worker.finished.connect(self._on_finished)
            worker.failed.connect(self._on_failed)

            self._worker = worker
            self._thread = thread
            self._set_running_ui(True)
            thread.start()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    @Slot(dict)
    def _push_worker_telemetry_to_monitor(self, sample: dict):
        if not self.monitor: return
        pressures = sample.get("pressure", {})
        p1_data = pressures.get(1, pressures.get("1", {}))
        p2_data = pressures.get(2, pressures.get("2", {}))
        
        self.monitor.update_metrics(
            flow=_safe_float(sample.get("flow")),
            p1_meas=_safe_float(sample.get("p1_meas") if sample.get("p1_meas") is not None else p1_data.get("meas")),
            p1_set=_safe_float(sample.get("p1_set") if sample.get("p1_set") is not None else p1_data.get("set")),
            p2_meas=_safe_float(sample.get("p2_meas") if sample.get("p2_meas") is not None else p2_data.get("meas")),
            p2_set=_safe_float(sample.get("p2_set") if sample.get("p2_set") is not None else p2_data.get("set")),
            valves=str(sample.get("valves", "—"))
        )

        # Progress an Monitor pushen
        if hasattr(self, '_monitor_target_ml') and self._monitor_target_ml > 0.01:
            loss = abs(_safe_float(sample.get("loss_ml")) or 0.0)
            pct = min(100.0, loss / self._monitor_target_ml * 100.0)
            self.monitor.update_progress(pct, f"{loss:.1f}/{self._monitor_target_ml:.1f} mL")

    def _on_request_ok(self, step, reason):
        # FILLING step is handled by the dedicated filling banner; skip generic banner
        if str(step).upper() != "FILLING":
            self.right.set_ok_banner(step=str(step), reason=str(reason), show=True)
            self._set_ok_enabled(True)
        try:
            color = "#00E5FF" if str(step).upper() == "FILLING" else "#F59E0B"
            self.right.append_log(f"ACTION REQUIRED: {reason}", color)
        except Exception:
            pass

    def _send_ok(self):
        self._set_ok_enabled(False)
        if self._worker: self._worker.confirm_ok()
        self.right.set_ok_banner(step="", reason="", show=False)

    def _on_status(self, msg):
        self.right.set_status(msg)

    def _on_step_changed(self, step):
        self._current_step = step
        self.right.set_step(step)
        self._render_manual_state()

    def _on_step_changed_with_pressure(self, step):
        """Leitet step_changed an LeftFrame weiter, mit aktuellem Ist-Druck für ETA."""
        current_p = 0.0
        try:
            if self.dev is not None and getattr(self.dev, "pressure_controller", None) is not None:
                current_p = _safe_float(_unwrap_sensor(self.dev.get_pressure_mbar(MAIN_CH)))
        except Exception:
            pass
        self.left.update_active_step_highlight(str(step), current_pressure_mbar=current_p)

    @Slot(str)
    def _on_valve_command(self, mode: str):
        """Manuelle Ventilsteuerung aus dem LeftFrame Valve Panel (auch während Experiment möglich)."""
        dev = self.dev
        if dev is None:
            self.right.append_log("ERROR: No device connected.", "#FF1744")
            return

        try:
            from src.gui.data.worker import robust_switch_valves
            robust_switch_valves(dev, mode)
            self.left.update_valve_state(mode)
            if self._experiment_running():
                self.right.append_log(f"⚠ MANUELLER VENTIL-OVERRIDE: {mode}", "#F59E0B")
            else:
                self.right.append_log(f"MANUAL: Valves → {mode}", "#0EA5E9")
        except Exception as e:
            self.right.append_log(f"VALVE ERROR: {e}", "#FF1744")

    @Slot(int, bool)
    def _on_relay_toggle(self, relay_num: int, target_on: bool):
        """Direktes Schalten eines einzelnen Relais (auch während Experiment möglich)."""
        dev = self.dev
        if dev is None:
            self.right.append_log("ERROR: No device connected.", "#FF1744")
            return

        try:
            vc = getattr(dev, "valve_controller", None)
            if vc is not None and hasattr(vc, "relais"):
                if target_on:
                    vc.relais.relay_on(relay_num)
                else:
                    vc.relais.relay_off(relay_num)
                # Internen State des ValveControllers auf UNKNOWN setzen,
                # da wir an ihm vorbei direkt aufs Relais zugreifen
                vc._state = vc._state.__class__("UNKNOWN") if hasattr(vc._state, '__class__') else "UNKNOWN"
                state_str = "ON" if target_on else "OFF"
                self.right.append_log(f"DEBUG: Relay {relay_num} → {state_str}", "#F59E0B")
            elif hasattr(dev, "set_valve_state"):
                # Fallback: kein direkter Relais-Zugriff
                self.right.append_log("WARN: No direct relay access, use preset modes.", "#F59E0B")
            else:
                self.right.append_log("ERROR: No valve controller found.", "#FF1744")
        except Exception as e:
            self.right.append_log(f"RELAY ERROR: {e}", "#FF1744")

    def _on_finished(self):
        try:
            self.right.append_log("=== SEQUENCE COMPLETE ===", "#0EA5E9")
        except Exception:
            pass
        self._set_running_ui(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait(2000)
        self._worker = None
        self._thread = None

    def _on_failed(self, err):
        self._stop_deterministic(reason=str(err))
        QMessageBox.critical(self, "Error", str(err))

    def _abort_run(self) -> None:
        try:
            self.right.append_log("!!! ABORT TRIGGERED !!!", "#FF1744")
        except Exception: pass
        
        self.right.set_ok_banner(step="", reason="", show=False)
        self._set_ok_enabled(False)

        if self._thread is None:
            self._toast("Stop: forcing SAFE_STATE.")
            try: self._force_safe_state_now()
            except Exception: pass
            return

        self._toast("STOP: aborting + SAFE_STATE")
        self._stop_deterministic(reason="User abort")
        self.right.reset_state()
        self._current_step = "IDLE"
        self.right.set_step("IDLE")
        self._render_manual_state()
        
        try:
            self.top.set_loss_ml(0.0)
            status_text = "SIMULATION: IDLE" if self._simulation_mode else "SYSTEM: IDLE / READY"
            self.top.update_status(status_text)
        except Exception:
            pass

    def _stop_deterministic(self, *, reason: str) -> None:
        self._set_running_ui(False, reason=f"stop_deterministic: {reason}")
        if self._worker is not None:
            try: 
                stop_fn = getattr(self._worker, "stop", getattr(self._worker, "abort", None))
                if callable(stop_fn):
                    stop_fn(reason)
            except Exception: pass
            
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(1000)
            except Exception: pass
            
        self._worker = None
        self._thread = None
        
        try: self._force_safe_state_now()
        except Exception: pass

    def event(self, e):
        try:
            if e.type() == QEvent.Type.WindowDeactivate:
                self._force_release_all("window_deactivate")
            elif e.type() == QEvent.Type.KeyPress:
                if getattr(e, "key", lambda: None)() == Qt.Key.Key_Escape and not e.isAutoRepeat():
                    self._force_release_all("esc")
                    return True
        except Exception: pass
        return super().event(e)

    def _set_running_ui(self, running: bool, *, reason: str = "") -> None:
        if running:
            pass 
        else:
            self._rt_t0 = None
            if hasattr(self, '_rt_timer') and not self._rt_timer.isActive():
                self._rt_timer.start(self.REALTIME_POLL_MS)

        try: self.left.set_running(bool(running))
        except Exception: pass
        try: self.right.set_running(bool(running))
        except Exception: pass
        try: self.right.enable_ok(False)
        except Exception: pass
        
        self._render_manual_state(reason="running_ui")
        self._update_health_banner()

    def _set_ok_enabled(self, enabled: bool) -> None:
        try: self.right.enable_ok(bool(enabled))
        except Exception: pass

    def _experiment_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def _toast(self, msg: str, *, ms: int = 2500) -> None:
        try:
            sb = self.statusBar()
            if sb is not None: sb.showMessage(msg, ms)
        except Exception: pass

    def reset_safe_state(self) -> None:
        self._safe_state_forced = False
        try: self._health.reset_safe_state()
        except Exception: pass
        self._update_health_banner()

    def _force_safe_state_now(self) -> None:
        self._safe_state_forced = True
        self._update_health_banner()
        if self.dev is None: return
        
        with self._hw_mutex:
            try: self._dev_set_pressure_setpoint_best_effort(channel=MAIN_CH, value_mbar=0.0, ramp=False)
            except Exception: pass
            try: self._dev_set_pressure_setpoint_best_effort(channel=BACKWASH_CH, value_mbar=0.0, ramp=False)
            except Exception: pass

            try: self._dev_set_valve_state("VENTING")
            except Exception: pass

            try:
                fn = getattr(self.dev, "vent_all", None)
                if callable(fn): fn()
            except Exception: pass

    def _hold_is_allowed_now(self) -> bool:
        if not self._experiment_running(): return True
        step = (self._current_step or "").strip().upper()
        return step in ("BACKWASH_HOLD", "BACKWASH_INITIAL")

    def _manual_reason_hint(self) -> Tuple[bool, str, str]:
        allowed = self._hold_is_allowed_now()
        if self._hold_active: return True, "ACTIVE", "Release SPACE to stop HOLD."
        if allowed:
            if self._experiment_running(): return True, "Allowed", "Hold SPACE to manually run backwash."
            return True, "Allowed", "Hold SPACE to manually control backwash (idle)."
        if self._experiment_running(): return False, "Blocked", "HOLD only allowed in BACKWASH_HOLD step."
        return True, "Allowed", "Hold SPACE to manually control backwash (idle)."

    def _render_manual_state(self, *, reason: str = "") -> None:
        allowed, r, hint = self._manual_reason_hint()
        active = bool(self._hold_active)
        try:
            self.left.set_hold_active(active)
            self.left.set_hold_affordance(bool(allowed), str(hint if not active else "MANUAL HOLD ACTIVE"))
        except Exception: pass

    def _trim_history(self, hist: Deque[Tuple[float, float]], *, now: float) -> None:
        cutoff = now - float(self.HISTORY_MAX_SECONDS)
        while hist and hist[0][0] < cutoff: hist.popleft()

    def _push_hist(self, hist: Deque[Tuple[float, float]], *, t: float, v: Optional[float]) -> None:
        if v is None: return
        try: hist.append((float(t), float(v)))
        except Exception: return
        self._trim_history(hist, now=float(t))

    def _slope_over_window(self, hist: Deque[Tuple[float, float]], *, window_s: float) -> Optional[float]:
        if len(hist) < 2: return None
        t_end, v_end = hist[-1]
        t_start_min = t_end - float(window_s)
        idx = None
        for i in range(len(hist) - 1, -1, -1):
            if hist[i][0] <= t_start_min:
                idx = i
                break
        t0, v0 = hist[idx if idx is not None else 0]
        dt = float(t_end - t0)
        return float((v_end - v0) / dt) if dt > 1e-6 else None

    def _update_trend_arrows(self) -> None:
        pass 

    def _update_health_banner(self, *, new_run_started: bool = False) -> None:
        dev = self.dev
        p1 = p2 = q = None
        p1_set = None
        vstate = None

        if dev is not None:
            try: p1 = _safe_float(_unwrap_sensor(dev.get_pressure_mbar(MAIN_CH)))
            except Exception: pass
            try: p2 = _safe_float(_unwrap_sensor(dev.get_pressure_mbar(BACKWASH_CH)))
            except Exception: pass
            try: p1_set = _safe_float(dev.get_pressure_setpoint_mbar(MAIN_CH))
            except Exception: pass
            try:
                fn = getattr(dev, "get_valve_state", getattr(dev, "get_state", None))
                if callable(fn): vstate = str(fn())
            except Exception: pass
            try: q = _safe_float(_unwrap_sensor(dev.read_flow()))
            except Exception: pass

        # Vorherigen Druck für Drop-Erkennung
        p1_prev = getattr(self, '_health_p1_prev', None)
        self._health_p1_prev = p1

        snap = self._health.evaluate(
            device_ok=(dev is not None),
            worker_running=self._experiment_running(),
            last_error_short=self._last_error_short,
            last_error_full=self._last_error_full,
            safe_state_forced=self._safe_state_forced,
            manual_hold=self._hold_active,
            p1_mbar=p1,
            p2_mbar=p2,
            p1_set_mbar=p1_set,
            p1_prev_mbar=p1_prev,
            flow=q,
            valves=vstate,
            last_good_comm_ts=self._last_good_comm_ts,
            new_run_started=new_run_started,
        )

        # Banner im TopFrame anzeigen wenn WARNING oder ERROR
        if snap.health in (SystemHealth.WARNING, SystemHealth.ERROR, SystemHealth.NO_COMM):
            try:
                self.top.lbl_title.setText(f"{snap.title}: {snap.detail[:60]}")
                color = "#FF1744" if snap.health == SystemHealth.ERROR else "#F59E0B"
                self.top.lbl_title.setStyleSheet(
                    f"color: {color}; font-weight: 900; font-size: 14px; letter-spacing: 2px;")
            except Exception:
                pass
        else:
            try:
                self.top.lbl_title.setText("PELLIKAN OS")
                self.top.lbl_title.setStyleSheet(
                    "color: #F8FAFC; font-weight: 900; font-size: 14px; letter-spacing: 2px;")
            except Exception:
                pass

    def _ui_backwash_pressure_mbar(self) -> float:
        try: return float(max(0.0, self.left.sp_hold_p.value()))
        except Exception: return 0.0

    def _init_device_manager_best_effort(self) -> None:
        try:
            from src.backend.core.device_manager import DeviceManager, DeviceManagerOptions
            
            opts = DeviceManagerOptions(enable_pressure=True, enable_flow=True, simulate=False)
            self.dev = DeviceManager(opts)
            self._simulation_mode = False
            
        except Exception as e:
            logger.warning(f"Could not load hardware. Entering simulation mode. Error: {e}")
            self._simulation_mode = True
            self.dev = None

    def _dev_set_valve_state(self, state: str) -> None:
        if self._simulation_mode: return
        if self.dev is None: raise RuntimeError("DeviceManager not available")
        st = (state or "").strip().upper()
        fn = getattr(self.dev, "set_valve_state", None)
        if callable(fn): fn(st); return
        if st in ("VENTING", "VENT"):
            for n in ("venting", "valves_venting"):
                f = getattr(self.dev, n, None)
                if callable(f): f(); return

    def _dev_set_pressure_setpoint(self, *, channel: int, value_mbar: float, ramp: bool = True) -> None:
        if self._simulation_mode: return
        if self.dev is None: raise RuntimeError("DeviceManager not available")
        fn = getattr(self.dev, "set_pressure_setpoint_mbar", None)
        if callable(fn): fn(channel=int(channel), setpoint_mbar=float(value_mbar), ramp=bool(ramp))

    def _dev_set_pressure_setpoint_best_effort(self, *, channel: int, value_mbar: float, ramp: bool = True) -> int:
        if self._simulation_mode: return channel
        try:
            self._dev_set_pressure_setpoint(channel=channel, value_mbar=value_mbar, ramp=ramp)
            return channel
        except Exception:
            if channel != 1:
                self._dev_set_pressure_setpoint(channel=1, value_mbar=value_mbar, ramp=ramp)
                return 1
            raise

    def _dev_read_pressure(self, *, channel: int) -> float:
        if self._simulation_mode: return 0.0
        if self.dev is None: raise RuntimeError("DeviceManager not available")
        fn: Any = getattr(self.dev, "get_pressure_mbar", None)
        if callable(fn): 
            v: Any = fn(int(channel))
            return float(v)
        raise AttributeError("No readable pressure source")

    def _hold_source_set(self, source: str, active: bool) -> None:
        if str(source).lower() not in ("space", "mouse"): return
        before = bool(self._hold_sources)
        if active: self._hold_sources.add(str(source).lower())
        else: self._hold_sources.discard(str(source).lower())
        after = bool(self._hold_sources)
        if (not before) and after:
            if not self._hold_is_allowed_now():
                self._hold_sources.clear()
                self._hold_active = False
                self._toast("HOLD blocked")
                return
            self._begin_manual_hold()
        elif before and (not after):
            self._end_manual_hold()
        elif self._hold_active:
            self._schedule_hold_setpoint_push()

    def _begin_manual_hold(self) -> None:
        self._hold_active = True
        self._render_manual_state(reason="hold_down")
        try:
            self._hold_begin_actions()
            self._push_hold_setpoint_now()
        except Exception:
            self._hold_active = False
            self._render_manual_state(reason="failed")

    def _end_manual_hold(self) -> None:
        self._hold_active = False
        self._render_manual_state(reason="hold_up")
        try:
            self._hold_end_actions()
        except Exception:
            pass

    def _force_release_all(self, reason: str) -> None:
        self._hold_sources.clear()
        try: self._global_filter.force_release()
        except Exception: pass
        if self._hold_active: self._end_manual_hold()

    def _hold_begin_actions(self) -> None:
        p = self._ui_backwash_pressure_mbar()
        if self._experiment_running():
            if self._worker is not None: self._worker_hold_start_best_effort(self._worker, p)
        else:
            logger.debug("MANUAL HOLD: Requesting BACKWASH")
            threading.Thread(target=self._bg_hw_hold_start, args=(p,), daemon=True).start()

    def _bg_hw_hold_start(self, p: float):
        with self._hw_mutex:
            dev = getattr(self, 'dev', None)
            if dev is not None:
                try:
                    if hasattr(dev, "all_valves_shut"): dev.all_valves_shut()
                    if hasattr(dev, "valves_backwash"): dev.valves_backwash()
                    elif hasattr(dev, "set_valve_state"): dev.set_valve_state("BACKWASH")
                    else: logger.error("HW ERROR: No backwash method found on device")
                except Exception as e:
                    logger.error(f"HW VALVE ERROR: {e}")
            self._dev_set_pressure_setpoint_best_effort(channel=2, value_mbar=p)

    def _hold_end_actions(self) -> None:
        if self._experiment_running():
            if self._worker is not None: self._worker_hold_stop_best_effort(self._worker)
        else:
            logger.debug("MANUAL HOLD RELEASED: Shutting all valves")
            threading.Thread(target=self._bg_hw_hold_stop, daemon=True).start()

    def _bg_hw_hold_stop(self):
        with self._hw_mutex:
            self._dev_set_pressure_setpoint_best_effort(channel=BACKWASH_CH, value_mbar=0.0, ramp=False)
            
            dev = getattr(self, 'dev', None)
            if dev is not None:
                try:
                    if hasattr(dev, "set_valve_state"): dev.set_valve_state("ALL_SHUT")
                    elif hasattr(dev, "all_shut"): dev.all_shut()
                    elif hasattr(dev, "all_valves_shut"): dev.all_valves_shut()
                except Exception as e:
                    logger.error(f"HW VALVE ERROR: {e}")

    def _schedule_hold_setpoint_push(self, *args) -> None:
        if self._hold_active and not self._hold_setpoint_timer.isActive():
            self._hold_setpoint_timer.start(self.HOLD_SETPOINT_RATE_MS)

    def _push_hold_setpoint_now(self) -> None:
        if not self._hold_active: return
        p = self._ui_backwash_pressure_mbar()
        if self._experiment_running() and self._worker:
            self._worker_hold_update_pressure_best_effort(self._worker, p)
        else:
            with self._hw_mutex:
                self._dev_set_pressure_setpoint_best_effort(channel=BACKWASH_CH, value_mbar=p)

    def _worker_hold_start_best_effort(self, w, p) -> None:
        fn = getattr(w, "start_backwash_hold", None)
        if callable(fn): fn(float(p))

    def _worker_hold_stop_best_effort(self, w) -> None:
        fn = getattr(w, "stop_backwash_hold", None)
        if callable(fn): fn()

    def _worker_hold_update_pressure_best_effort(self, w, p) -> None:
        fn = getattr(w, "update_backwash_hold_pressure", getattr(w, "start_backwash_hold", None))
        if callable(fn): fn(float(p))

    def _start_monitor(self) -> None:
        if not bool(self.config.get("monitor_enabled", True)): return
        try:
            self.monitor = MonitorServer(host=str(self.config.get("monitor_host", "0.0.0.0")), port=int(self.config.get("monitor_port", 8765)))
            self.monitor.start()
            QTimer.singleShot(2000, self._print_monitor_url)
        except Exception:
            self.monitor = None

    def _print_monitor_url(self):
        mon = self.monitor
        if mon is not None and hasattr(mon, "url"):
            link = mon.url()
            try:
                self.right.append_log("TELEMETRY SERVER ONLINE:", "#10B981")
                self.right.append_log(f"-> {link}", "#00E5FF")
                if hasattr(self, "left") and hasattr(self.left, "update_server_url"):
                    self.left.update_server_url(link)
            except Exception: pass

    def _poll_realtime(self) -> None:
        now = time.monotonic()
        if self._rt_t0 is None:
            self._rt_t0 = now
        t_elapsed = now - self._rt_t0

        with self._rt_hw_lock:
            p1_val = float(self._rt_p1) if self._rt_p1 is not None else 0.0
            p2_val = float(self._rt_p2) if self._rt_p2 is not None else 0.0
            f_val  = float(self._rt_flow) if self._rt_flow is not None else 0.0
            v_val  = str(self._rt_valves) if self._rt_valves is not None else "UNKNOWN"
            latency = getattr(self, '_rt_hw_latency_ms', 0.0)

        dev = getattr(self, 'dev', None)
        p1_set = dev.get_pressure_setpoint_mbar(1) if dev and hasattr(dev, "get_pressure_setpoint_mbar") else 0.0
        p2_set = dev.get_pressure_setpoint_mbar(2) if dev and hasattr(dev, "get_pressure_setpoint_mbar") else 0.0

        sample = {
            "t": t_elapsed, 
            "p1_meas": p1_val, 
            "p2_meas": p2_val,
            "flow": f_val, 
            "step": self._current_step,
            "pressure": {
                1: {"meas": p1_val, "set": p1_set},
                2: {"meas": p2_val, "set": p2_set},
                "1": {"meas": p1_val, "set": p1_set}, # String-Key für RightFrame
                "2": {"meas": p2_val, "set": p2_set}
            }
        }

        if hasattr(self, "top"): self.top.update_telemetry(sample)
        # RightFrame nur im Idle-Modus direkt füttern — während eines Runs
        # kommt die Telemetrie über worker.telemetry → right.update_telemetry
        if hasattr(self, "right") and not self._experiment_running():
            self.right.update_telemetry(sample)
        
        if self.monitor:
            self.monitor.update_metrics(flow=f_val, p1_meas=p1_val, p2_meas=p2_val, valves=v_val)

        if getattr(self, '_is_booting', False) and hasattr(self, 'hud'):
            self.hud.update_real_diagnostics(p1_val, f_val, latency)

        if not self._rt_hw_reading:
            self._rt_hw_reading = True
            threading.Thread(target=self._do_hw_poll_bg, daemon=True).start()

        # Periodischer Health-Check (alle 200ms via RT-Timer)
        if not getattr(self, '_is_booting', False):
            self._update_health_banner()

    def _do_hw_poll_bg(self) -> None:
        t0 = time.perf_counter()

        dev = getattr(self, 'dev', None)
        p1, p2, flow, valves = 0.0, 0.0, 0.0, "UNKNOWN"

        if dev is not None:
            with self._hw_mutex:
                # 1. FLOW SENSOR
                try:
                    if hasattr(dev, "read_flow"):
                        flow = _unwrap_sensor(dev.read_flow())
                    elif hasattr(dev, "get_flow"):
                        flow = _unwrap_sensor(dev.get_flow())
                except Exception as e:
                    logger.warning(f"HW ERROR (Flow): {e}")

                # 2. PRESSURE CONTROLLER
                try:
                    if hasattr(dev, "get_pressure_mbar"):
                        p1 = _unwrap_sensor(dev.get_pressure_mbar(1))
                        p2 = _unwrap_sensor(dev.get_pressure_mbar(2))
                    elif hasattr(dev, "get_pressure"):
                        p1 = _unwrap_sensor(dev.get_pressure(1))
                        p2 = _unwrap_sensor(dev.get_pressure(2))
                    elif hasattr(dev, "read_pressure"):
                        p1 = _unwrap_sensor(dev.read_pressure(1))
                        p2 = _unwrap_sensor(dev.read_pressure(2))
                except Exception as e:
                    logger.warning(f"HW ERROR (Pressure): {e}")

                # 3. VALVES
                try:
                    fn_valve = getattr(dev, "get_valve_state", getattr(dev, "get_state", None))
                    if callable(fn_valve):
                        valves = str(fn_valve())
                except Exception:
                    pass

        t1 = time.perf_counter() 

        with self._rt_hw_lock:
            self._rt_p1 = p1
            self._rt_p2 = p2
            self._rt_flow = flow
            self._rt_valves = valves
            self._rt_hw_latency_ms = (t1 - t0) * 1000.0
            self._rt_hw_reading = False

    def _construct_frame(self, cls, config):
        try: return cls(config)
        except TypeError: return cls()

    def closeEvent(self, event):
        if hasattr(self, '_rt_timer'): self._rt_timer.stop()
        if hasattr(self, '_hold_setpoint_timer'): self._hold_setpoint_timer.stop()
        self._force_release_all("close")
        if getattr(self, '_thread', None): self._stop_deterministic(reason="close")
        if getattr(self, 'monitor', None) and self.monitor: self.monitor.stop()
        if getattr(self, 'dev', None) and self.dev: self.dev.disconnect()
        super().closeEvent(event)