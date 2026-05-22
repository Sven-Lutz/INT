from __future__ import annotations

import collections
import logging
import math
import random
import time
from typing import Optional

from PySide6.QtCore import Signal, Slot, Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import (
    QPainter, QColor, QPen, QPainterPath,
    QLinearGradient, QRadialGradient, QFont,
)
from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTextBrowser, QWidget, QProgressBar, QInputDialog, QSizePolicy,
)
from src.utils.path_utils import ensure_dir, project_root, resolve_under
from src.gui.widgets.nudge_spinbox import NudgeSpinBox

logger = logging.getLogger(__name__)


# =========================================================================
# WIDGET 1: SPHERICAL REACTOR — animated digital twin of the filter cell
# =========================================================================
class ReactorSphereWidget(QFrame):
    """Animated digital twin of the filter cell.

    Single public entry point is ``update_state(vol_ml, phase)`` —
    volume text and fill graphic are always derived from the same input.
    ``set_state`` / ``set_volume`` remain as back-compat shims.
    """

    _DEFAULT_MEMBRANE_ML = 3500.0
    _DEFAULT_MAX_ML = 7000.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 210)
        self.setStyleSheet("background: transparent;")
        self._fill_pct = 0.0
        self._fill_target = 0.0
        self._color = QColor("#00E5FF")
        self._color_target = QColor("#00E5FF")
        self._calibrated: bool = False   # True once calibration is set from a run or SET MEMBRANE
        self._volume_ml = 0.0
        self._phase_label = "IDLE"
        self._wave_phase = 0.0
        self._membrane_ml = 3500.0
        self._max_ml = 7000.0
        self._flow_ml_min: float = 0.0   # signed: + = filtration/drain, - = backwash/fill

        self._bubbles: list = []
        self._bubble_spawn_accum: float = 0.0
        self._overflow_pulse: float = 0.0

        self._p_setpoint: float = 0.0
        self._p_meas: float = 0.0
        self._target_vol_ml: float = 0.0

        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)      # ~12 fps — smooth enough, low CPU
        self._dirty = True

    def sizeHint(self) -> QSize:
        return QSize(210, 240)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return int(width * 1.15)

    def _tick(self):
        prev_fill = self._fill_pct
        diff = self._fill_target - self._fill_pct
        if abs(diff) > 0.002:
            self._fill_pct += diff * 0.10
        else:
            self._fill_pct = self._fill_target

        self._wave_phase += 0.05

        # Smooth phase-color transition.
        if self._color != self._color_target:
            cr = int(self._color.red() + (self._color_target.red() - self._color.red()) * 0.18)
            cg = int(
                self._color.green()
                + (self._color_target.green() - self._color.green()) * 0.18)
            cb = int(self._color.blue() + (self._color_target.blue() - self._color.blue()) * 0.18)
            if (abs(cr - self._color_target.red()) < 3 and
                    abs(cg - self._color_target.green()) < 3 and
                    abs(cb - self._color_target.blue()) < 3):
                self._color = QColor(self._color_target)
            else:
                self._color = QColor(cr, cg, cb)
            self._dirty = True

        if abs(self._fill_pct - prev_fill) > 0.0005:
            self._dirty = True

        if self._dirty:
            self._dirty = False
            self.update()

    def configure_calibration(self, membrane_ml: float, max_ml: float) -> None:
        self._membrane_ml = max(1.0, float(membrane_ml))
        self._max_ml = max(self._membrane_ml + 1.0, float(max_ml))
        self._calibrated = True

    @staticmethod
    def _volume_to_fill(vol_ml: float, membrane_ml: float, max_ml: float) -> float:
        """Map volume to 0..1 fill level anchored at the membrane.

        0 mL → 0.0, membrane_ml → 0.5, max_ml → 1.0, clamped.
        """
        v = max(0.0, float(vol_ml))
        if membrane_ml <= 0 or max_ml <= membrane_ml:
            return 0.0
        if v <= membrane_ml:
            return max(0.0, 0.5 * v / membrane_ml)
        upper = max_ml - membrane_ml
        return min(1.0, 0.5 + 0.5 * (v - membrane_ml) / upper)

    def update_state(self, vol_ml: float, phase: str, *,
                     membrane_ml: float | None = None,
                     max_ml: float | None = None) -> None:
        """Single authoritative entry point — volume drives both text and fill graphic."""
        if membrane_ml is not None:
            self._membrane_ml = max(1.0, float(membrane_ml))
        if max_ml is not None:
            self._max_ml = max(self._membrane_ml + 1.0, float(max_ml))
        v = max(0.0, float(vol_ml))
        self._volume_ml = v
        fill = self._volume_to_fill(v, self._membrane_ml, self._max_ml)
        self.set_state(fill, phase)

    def set_state(self, target_fill: float, phase: str):
        """Set fill target and phase color."""
        self._phase_label = str(phase).upper()
        self._color_target = self._phase_color(self._phase_label)
        self._fill_target = max(0.0, min(1.0, float(target_fill)))

    def set_volume(self, vol_ml: float):
        """Legacy API: update volume text and recompute fill from current caps."""
        v = max(0.0, float(vol_ml))
        self._volume_ml = v
        self._fill_target = self._volume_to_fill(v, self._membrane_ml, self._max_ml)

    def set_target_volume(self, target_ml: float):
        """Set the B1 target-fill dashed gold indicator."""
        self._target_vol_ml = max(0.0, float(target_ml))

    def set_flow(self, flow_ml_min: float) -> None:
        """Pass signed flow for the in-sphere direction indicator."""
        self._flow_ml_min = float(flow_ml_min)
        self._dirty = True

    @staticmethod
    def _short_phase(phase: str) -> str:
        up = str(phase).upper()
        if "FILL" in up or "PHASE_0" in up or "BACKWASH" in up:
            return "P0"
        if "PHASE_A" in up:
            return "A"
        if "PHASE_B1" in up:
            return "B1"
        if "PHASE_B2" in up:
            return "B2"
        if "PHASE_B" in up:
            return "B"
        if "PHASE_C" in up:
            return "C"
        if "VENT" in up:
            return "VENT"
        if "FILTRATION" in up:
            return "FILT"
        return ""

    @staticmethod
    def _phase_color(phase: str) -> QColor:
        phase_up = str(phase).upper()
        if "FILL" in phase_up or "PHASE_0" in phase_up or "BACKWASH" in phase_up:
            return QColor("#00E5FF")
        if "PHASE_A" in phase_up:
            return QColor("#8B5CF6")
        if "PHASE_B" in phase_up:
            return QColor("#F59E0B")
        if "PHASE_C" in phase_up:
            return QColor("#EC4899")
        if "FILTRATION" in phase_up or "PHASE" in phase_up:
            return QColor("#8B5CF6")
        if "VENT" in phase_up:
            return QColor("#10B981")
        return QColor("#0EA5E9")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        radius = min(w, h * 0.85) * 0.38
        cx = w / 2
        cy = (h - 30) / 2
        sphere_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        # 1. Outer glow rings (pressure-reactive alpha)
        ref = self._p_setpoint if self._p_setpoint > 1.0 else 2000.0
        pr_factor = max(0.35, min(1.6, self._p_meas / ref)) if ref > 0 else 0.35
        p.setPen(Qt.PenStyle.NoPen)
        for alpha, extra in ((12, 20), (22, 12), (38, 6)):
            gc = QColor(self._color)
            gc.setAlpha(max(4, min(200, int(alpha * pr_factor))))
            p.setBrush(gc)
            p.drawEllipse(QRectF(cx - radius - extra, cy - radius - extra,
                                 (radius + extra) * 2, (radius + extra) * 2))

        # 2. Sphere background — radial gradient (3D depth)
        rad_bg = QRadialGradient(cx - radius * 0.25, cy - radius * 0.3, radius * 1.25)
        rad_bg.setColorAt(0.0, QColor(28, 38, 72, 245))
        rad_bg.setColorAt(0.55, QColor(13, 20, 40, 248))
        rad_bg.setColorAt(1.0, QColor(4, 7, 16, 255))
        p.setBrush(rad_bg)
        p.drawEllipse(sphere_rect)

        # 3. Liquid fill with animated sine-wave surface
        if self._fill_pct > 0.01:
            liquid_top_y = (cy + radius) - (radius * 2) * self._fill_pct
            wave_amp = radius * 0.028 * \
                math.sin(math.pi * min(1.0, self._fill_pct * 2)) * min(1.0, self._fill_pct * 6)

            liq_grad = QLinearGradient(0, liquid_top_y, 0, cy + radius)
            c_top = QColor(self._color)
            c_top.setAlpha(210)
            c_bot = QColor(self._color).darker(300)
            c_bot.setAlpha(170)
            liq_grad.setColorAt(0.0, c_top)
            liq_grad.setColorAt(1.0, c_bot)

            liq_path = QPainterPath()
            liq_path.moveTo(cx - radius, cy + radius)
            liq_path.arcTo(sphere_rect, 180, 180)
            liq_path.lineTo(cx + radius, liquid_top_y)
            steps = 20
            for i in range(steps, -1, -1):
                t = i / steps
                wx = (cx - radius) + t * (radius * 2)
                wy = liquid_top_y + math.sin(self._wave_phase + t * math.pi * 2.5) * wave_amp * 0.4
                liq_path.lineTo(wx, wy)
            liq_path.closeSubpath()

            clip_path = QPainterPath()
            clip_path.addEllipse(sphere_rect)

            p.save()
            p.setClipPath(clip_path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(liq_grad)
            p.drawPath(liq_path)
            p.setBrush(QColor(255, 255, 255, 22))
            p.drawRect(QRectF(cx - radius, liquid_top_y - 2, radius * 2, 4))
            p.restore()

        # 4. Tick marks at 25% / 50% / 75%
        for tick_pct in (0.25, 0.50, 0.75):
            ty = (cy + radius) - (radius * 2) * tick_pct
            tick_alpha = 130 if tick_pct == 0.50 else 70
            p.setPen(QPen(QColor(100, 116, 139, tick_alpha), 1))
            p.drawLine(QPointF(cx - radius - 4, ty), QPointF(cx - radius + 6, ty))
            p.setPen(QColor(71, 85, 105, tick_alpha))
            p.setFont(QFont("Consolas", 6))
            p.drawText(QRectF(cx - radius - 30, ty - 6, 24, 12),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{int(tick_pct * 200)}%")

        # 5. Membrane line (dashed, at 50%) — glows when near membrane level
        near_membrane = abs(self._fill_pct - 0.5) < 0.06
        if near_membrane:
            mem_alpha = int(180 + 75 * math.sin(self._wave_phase * 3.0))
            mem_color = QColor(0, 229, 255, max(100, min(255, mem_alpha)))
            p.setPen(QPen(mem_color, 2.0, Qt.PenStyle.DashLine))
        else:
            p.setPen(QPen(QColor(248, 250, 252, 110), 1.5, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(cx - radius - 5, cy), QPointF(cx + radius + 5, cy))
        if near_membrane:
            p.setPen(QColor(0, 229, 255, 220))
        else:
            p.setPen(QColor(71, 85, 105, 150))
        p.setFont(QFont("Consolas", 6, QFont.Weight.Bold))
        p.drawText(QRectF(cx + radius + 7, cy - 8, 55, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "MEM")

        # 5b. B1 target-fill indicator (dashed gold, only if target is set)
        if self._target_vol_ml > 0.0:
            tgt_frac = self._volume_to_fill(
                self._target_vol_ml, self._membrane_ml, self._max_ml)
            if 0.02 < tgt_frac < 0.98:
                ty = (cy + radius) - (radius * 2) * tgt_frac
                p.setPen(QPen(QColor("#F59E0B"), 1.2, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(cx - radius - 2, ty), QPointF(cx + radius + 2, ty))
                p.setPen(QColor("#F59E0B"))
                p.setFont(QFont("Consolas", 6, QFont.Weight.Bold))
                p.drawText(QRectF(cx + radius + 7, ty - 8, 55, 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "TGT")

        # 6. Sphere outline — phase-colored always
        out_c = QColor(self._color)
        out_c.setAlpha(100)
        p.setPen(QPen(out_c, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(sphere_rect)

        # 7. Specular highlight (top-left lens flare)
        clip2 = QPainterPath()
        clip2.addEllipse(sphere_rect)
        p.save()
        p.setClipPath(clip2)
        spec = QRadialGradient(cx - radius * 0.32, cy - radius * 0.38, radius * 0.52)
        spec.setColorAt(0.0, QColor(255, 255, 255, 55))
        spec.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(spec)
        p.drawEllipse(sphere_rect)
        p.restore()

        # 7b. Phase pill tag above volume number
        short = self._short_phase(self._phase_label)
        if short:
            pill_w, pill_h = 36.0, 13.0
            pill_x = cx - pill_w / 2
            pill_y = cy - 38
            pill_bg = QColor(self._color)
            pill_bg.setAlpha(55)
            p.setPen(QPen(QColor(self._color), 1))
            p.setBrush(pill_bg)
            p.drawRoundedRect(QRectF(pill_x, pill_y, pill_w, pill_h), 5, 5)
            p.setPen(QColor(self._color).lighter(160))
            p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
            p.drawText(QRectF(pill_x, pill_y, pill_w, pill_h),
                       Qt.AlignmentFlag.AlignCenter, short)

        # 8. Volume readout (centered in sphere)
        p.setPen(QColor("#F8FAFC"))
        p.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        vol_text = f"{self._volume_ml:.0f}" if self._volume_ml >= 10 else f"{self._volume_ml:.1f}"
        p.drawText(QRectF(cx - radius, cy - 20, radius * 2, 24),
                   Qt.AlignmentFlag.AlignCenter, f"{vol_text} mL")

        if self._calibrated and self._membrane_ml > 0:
            # 100% = membrane level (backwash target). Going above is normal.
            mem_pct = self._volume_ml / self._membrane_ml * 100.0
            pct_color = QColor("#00FF66") if mem_pct > 100.0 else QColor(self._color).lighter(140)
            p.setPen(pct_color)
            p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            p.drawText(QRectF(cx - radius, cy + 5, radius * 2, 14),
                       Qt.AlignmentFlag.AlignCenter, f"{mem_pct:.0f}%")

        # 9. Flow direction indicator (below sphere, above bottom label)
        flow = self._flow_ml_min
        if abs(flow) >= 0.5:
            if flow < 0:           # negative = backwash = cell filling
                arrow, flow_color = "▲", QColor("#00E5FF")
            else:                  # positive = filtration = cell draining
                arrow, flow_color = "▼", QColor("#F59E0B")
            flow_color.setAlpha(210)
            p.setPen(flow_color)
            p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            p.drawText(QRectF(0, cy + radius + 2, w, 16),
                       Qt.AlignmentFlag.AlignCenter, f"{arrow} {abs(flow):.1f} ml/min")
        else:
            # Bottom label only when no flow
            p.setPen(QColor("#64748B"))
            p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            p.drawText(QRectF(0, cy + radius + 2, w, 16),
                       Qt.AlignmentFlag.AlignCenter, "CELL STATE")


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
        self._b_progress_frac = 0.0   # 0→1 across Phase B (tracks B1 volume fraction)
        # Dynamische Profil-Fraktionen (Anteil A / B / C an Gesamtbreite)
        self._frac_a = 0.28
        self._frac_b = 0.44
        self._frac_c = 0.28
        self._time_b_s: float = 600.0          # estimated phase B duration in seconds
        self._phase_b_start_ts: float = 0.0    # monotonic ts when B began
        self._last_phase: str = "IDLE"
        # Pressure history trail (dot_x_frac, p_mbar) — last ~90 updates ≈ 18 s
        self._trace: collections.deque = collections.deque(maxlen=90)

    def update_profile(self, target_mbar: float, rate_a_mbar_min: float, rate_c_mbar_min: float):
        if target_mbar > 0:
            self._peak_p = float(target_mbar)
        rate_a = max(1.0, float(rate_a_mbar_min))
        rate_c = max(1.0, float(rate_c_mbar_min))
        time_a = self._peak_p / rate_a
        time_c = self._peak_p / rate_c
        time_b = max(time_a * 1.5, 10.0)
        self._time_b_s = time_b * 60.0
        total = time_a + time_b + time_c
        if total > 0:
            self._frac_a = time_a / total
            self._frac_b = time_b / total
            self._frac_c = time_c / total
        self._trace.clear()
        self.update()

    def set_state(self, current_p: float, setpoint: float, phase: str):
        self._current_p = max(0.0, current_p)
        self._setpoint_p = max(0.0, setpoint)
        new_phase = phase.upper()

        # Track when phase B starts so we can move the dot in real time
        if new_phase != self._last_phase:
            if "PHASE_B" in new_phase:
                self._phase_b_start_ts = time.monotonic()
            self._last_phase = new_phase
            self._trace.clear()

        self._phase = new_phase
        self.update()

    def set_b_progress(self, frac: float):
        """Update Phase B dot position; frac = B1_current / B1_target (0→1)."""
        self._b_progress_frac = max(0.0, min(1.0, frac))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        pad_left, pad_top, pad_bot = 36, 14, 26
        plot_w = w - pad_left - 8
        plot_h = h - pad_top - pad_bot
        disp_max = max(self._peak_p, 100.0)
        orig_x = pad_left
        base_y = h - pad_bot

        def mbar_to_y(mbar: float) -> float:
            return base_y - (mbar / disp_max) * plot_h

        # Phase boundaries
        x_a_end = orig_x + plot_w * self._frac_a
        x_b_end = orig_x + plot_w * (self._frac_a + self._frac_b)
        x_c_end = orig_x + plot_w

        phase_a_active = "PHASE_A" in self._phase
        phase_b_active = "PHASE_B" in self._phase
        phase_c_active = "PHASE_C" in self._phase
        any_active = phase_a_active or phase_b_active or phase_c_active

        # 1. Horizontal grid lines + Y-axis labels
        grid_step = 500 if disp_max >= 1000 else 250
        p.setFont(QFont("Consolas", 7))
        mbar_val = 0
        while mbar_val <= disp_max:
            gy = mbar_to_y(mbar_val)
            p.setPen(QPen(QColor(30, 41, 59, 160), 1))
            p.drawLine(QPointF(orig_x, gy), QPointF(x_c_end, gy))
            p.setPen(QColor(71, 85, 105, 160))
            p.drawText(QRectF(0, gy - 7, orig_x - 4, 14),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       str(mbar_val))
            mbar_val += grid_step

        # 2. X-axis baseline
        p.setPen(QPen(QColor(30, 41, 59, 220), 2))
        p.drawLine(QPointF(orig_x, base_y), QPointF(x_c_end, base_y))

        # 3. Phase fill segments — dimmed unless active
        p.setPen(Qt.PenStyle.NoPen)

        def _fill_alpha(phase_active: bool) -> int:
            if not any_active:
                return 45
            return 80 if phase_active else 12

        # Phase A (ramp up) — purple
        a_path = QPainterPath()
        a_path.moveTo(orig_x, base_y)
        a_path.lineTo(x_a_end, pad_top)
        a_path.lineTo(x_a_end, base_y)
        a_path.closeSubpath()
        grad_a = QLinearGradient(orig_x, pad_top, x_a_end, base_y)
        grad_a.setColorAt(0.0, QColor(139, 92, 246, _fill_alpha(phase_a_active)))
        grad_a.setColorAt(1.0, QColor(139, 92, 246, 0))
        p.setBrush(grad_a)
        p.drawPath(a_path)

        # Phase B (hold) — amber
        b_path = QPainterPath()
        b_path.moveTo(x_a_end, pad_top)
        b_path.lineTo(x_b_end, pad_top)
        b_path.lineTo(x_b_end, base_y)
        b_path.lineTo(x_a_end, base_y)
        b_path.closeSubpath()
        grad_b = QLinearGradient(0, pad_top, 0, base_y)
        grad_b.setColorAt(0.0, QColor(245, 158, 11, _fill_alpha(phase_b_active)))
        grad_b.setColorAt(1.0, QColor(245, 158, 11, 0))
        p.setBrush(grad_b)
        p.drawPath(b_path)

        # Phase C (ramp down) — pink
        c_path = QPainterPath()
        c_path.moveTo(x_b_end, pad_top)
        c_path.lineTo(x_c_end, base_y)
        c_path.lineTo(x_b_end, base_y)
        c_path.closeSubpath()
        grad_c = QLinearGradient(x_b_end, pad_top, x_c_end, base_y)
        grad_c.setColorAt(0.0, QColor(236, 72, 153, _fill_alpha(phase_c_active)))
        grad_c.setColorAt(1.0, QColor(236, 72, 153, 0))
        p.setBrush(grad_c)
        p.drawPath(c_path)

        # 4. Trapezoid outline — color shifts with active phase
        if phase_a_active:
            outline_c = QColor(139, 92, 246, 230)
        elif phase_b_active:
            outline_c = QColor(245, 158, 11, 230)
        elif phase_c_active:
            outline_c = QColor(236, 72, 153, 230)
        else:
            outline_c = QColor(100, 116, 139, 160)

        contour = QPainterPath()
        contour.moveTo(orig_x, base_y)
        contour.lineTo(x_a_end, pad_top)
        contour.lineTo(x_b_end, pad_top)
        contour.lineTo(x_c_end, base_y)
        p.setPen(QPen(outline_c, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(contour)

        # Active-phase underline bar (3 px below baseline)
        if phase_a_active:
            p.setPen(QPen(QColor(139, 92, 246), 3))
            p.drawLine(QPointF(orig_x, base_y + 3), QPointF(x_a_end, base_y + 3))
        elif phase_b_active:
            p.setPen(QPen(QColor(245, 158, 11), 3))
            p.drawLine(QPointF(x_a_end, base_y + 3), QPointF(x_b_end, base_y + 3))
        elif phase_c_active:
            p.setPen(QPen(QColor(236, 72, 153), 3))
            p.drawLine(QPointF(x_b_end, base_y + 3), QPointF(x_c_end, base_y + 3))

        # 5. Phase labels on X-axis
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        for label, lx1, lx2, col_act, col_dim in (
            ("A", orig_x, x_a_end, "#8B5CF6", "#374151"),
            ("B", x_a_end, x_b_end, "#F59E0B", "#374151"),
            ("C", x_b_end, x_c_end, "#EC4899", "#374151"),
        ):
            is_active = (label == "A" and phase_a_active) or \
                        (label == "B" and phase_b_active) or \
                        (label == "C" and phase_c_active)
            p.setPen(QColor(col_act if (is_active or not any_active) else col_dim))
            p.drawText(QRectF(lx1, base_y + 3, lx2 - lx1, 14), Qt.AlignmentFlag.AlignCenter, label)

        # 6. Setpoint dashed line
        if self._setpoint_p > 0:
            sp_y = mbar_to_y(self._setpoint_p)
            p.setPen(QPen(QColor(248, 250, 252, 45), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(orig_x, sp_y), QPointF(x_c_end, sp_y))
            p.setPen(QColor(148, 163, 184, 100))
            p.setFont(QFont("Consolas", 7))
            p.drawText(QRectF(x_c_end + 2, sp_y - 7, 40, 14),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{int(self._setpoint_p)}")

        # 7. Live tracker dot with history trail
        norm_p = min(1.0, max(0.0, self._current_p / disp_max))

        if phase_a_active:
            dot_x = orig_x + (norm_p * plot_w * self._frac_a)
        elif phase_b_active:
            dot_x = orig_x + plot_w * (self._frac_a + self._frac_b * self._b_progress_frac)
        elif phase_c_active:
            down_prog = 1.0 - norm_p
            dot_x = x_b_end + (down_prog * plot_w * self._frac_c)
        else:
            dot_x = orig_x
            norm_p = 0.0

        dot_y = mbar_to_y(self._current_p if norm_p > 0 else 0)

        # Append to history trail when active
        if any_active and norm_p > 0:
            self._trace.append((dot_x, dot_y))

        # 7a. Draw history trail (older = more transparent)
        n = len(self._trace)
        if n >= 2:
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(1, n):
                alpha = int(15 + 55 * (i / n))
                tc = QColor(0, 229, 255, alpha)
                pen_w = 1.0 + (i / n) * 1.2
                p.setPen(QPen(tc, pen_w))
                p.drawLine(QPointF(*self._trace[i - 1]), QPointF(*self._trace[i]))

        if any_active:
            # Crosshair
            p.setPen(QPen(QColor(0, 229, 255, 70), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(orig_x, dot_y), QPointF(dot_x, dot_y))
            p.drawLine(QPointF(dot_x, dot_y), QPointF(dot_x, base_y))

            # Glow rings
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 229, 255, 18))
            p.drawEllipse(QPointF(dot_x, dot_y), 20, 20)
            p.setBrush(QColor(0, 229, 255, 45))
            p.drawEllipse(QPointF(dot_x, dot_y), 11, 11)
            p.setBrush(QColor("#00E5FF"))
            p.drawEllipse(QPointF(dot_x, dot_y), 5, 5)

            # Pressure label next to dot
            p.setPen(QColor("#F8FAFC"))
            p.setFont(QFont("Consolas", 9, QFont.Weight.Black))
            p.drawText(QPointF(dot_x + 13, dot_y - 4), f"{int(self._current_p)}")

        # 8. Rotated Y-axis "mbar" label
        p.save()
        p.setPen(QColor(71, 85, 105, 140))
        p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        p.translate(9, pad_top + plot_h / 2)
        p.rotate(-90)
        p.drawText(QRectF(-25, -8, 50, 16), Qt.AlignmentFlag.AlignCenter, "mbar")
        p.restore()

        # 9. Title
        p.setPen(QColor("#64748B"))
        p.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        p.drawText(QRectF(0, h - pad_bot + 5, w, 14),
                   Qt.AlignmentFlag.AlignCenter, "PRESSURE PROFILE")


def _to_float(x) -> float:
    if x is None:
        return 0.0
    try:
        if isinstance(x, dict):
            return 0.0
        v = float(x)
        return v if v == v else 0.0
    except Exception:
        return 0.0




# =========================================================================
# PHASE SEGMENT BAR — shows A / B1 / B2 / C as coloured segments in one bar
# =========================================================================
class PhaseSegmentBar(QWidget):
    """Horizontal progress bar that splits into phase-coloured segments.

    Segments grow independently as each phase accumulates filtrate.
    All measurements in mL; the bar renders proportionally against _target.
    """
    _SEG_COLORS = (
        ("a",  QColor(139, 92, 246)),   # Phase A — purple
        ("b1", QColor(245, 158, 11)),   # Phase B1 — amber
        ("b2", QColor(251, 191, 36)),   # Phase B2 — lighter amber
        ("c",  QColor(236, 72, 153)),   # Phase C — pink
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._target = 1.0
        self._segs: dict[str, float] = {k: 0.0 for k, _ in self._SEG_COLORS}

    def set_target(self, ml: float):
        self._target = max(1.0, ml)
        self.update()

    def set_segment(self, **kwargs: float):
        for k, v in kwargs.items():
            if k in self._segs:
                self._segs[k] = max(0.0, v)
        self.update()

    def reset(self):
        for k in self._segs:
            self._segs[k] = 0.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Clip to rounded rect so all segments get rounded ends automatically
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 4, 4)
        painter.setClipPath(clip)

        # Background track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(15, 23, 42))
        painter.drawRect(0, 0, w, h)

        x = 0.0
        for key, color in self._SEG_COLORS:
            ml = self._segs[key]
            if ml <= 0:
                continue
            seg_w = min(ml / self._target * w, w - x)
            if seg_w < 0.5:
                continue
            painter.setBrush(color)
            painter.drawRect(QRectF(x, 0, seg_w, h))
            x += seg_w
        painter.end()


# =========================================================================
# RIGHT FRAME MAIN
# =========================================================================
class RightFrame(QFrame):
    start_clicked = Signal()
    stop_clicked = Signal()
    manual_vent_clicked = Signal()
    ok_clicked = Signal()
    filling_confirmed = Signal(float)  # Bediener hat Filling bestätigt: Menge in ml
    annotation_requested = Signal(str)  # operator mark: (text,)

    _ETA_EMA_ALPHA = 0.12  # α ≈ 6 s smoothing at 5 Hz telemetry rate

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")
        self._running = False
        self._ui_phase = "IDLE"

        # Calibration anchor: volume [ml] at the 50% fill line (membrane level).
        # Fallback is half of a 7 L cell; overridden by SET MEMBRANE button or auto-calibration.
        self._current_vol_ml = 0.0
        self._cell_volume_ml = 0.0        # flow-integrated persistent cell volume
        self._flow_integrate_ts: Optional[float] = None  # last integration timestamp
        self._membrane_vol_ml = 3500.0
        self.MAX_CELL_VOLUME_ML = 7000.0

        # Persistent cell volume — integrated from flow sensor continuously so
        # the sphere shows the actual physical state even outside of a run.
        self._cell_volume_ml: float = 0.0
        self._flow_integrate_ts: Optional[float] = None

        # Elapsed-time tracking: monotonic timestamp set on run start, None at rest.
        self._run_start: Optional[float] = None
        self._clock_timer = QTimer(self)

        # Rolling window (30 samples) for stable ETA calculation.
        self._flow_history: collections.deque = collections.deque(maxlen=30)
        # EMA flow for trend ETA
        self._flow_ema: Optional[float] = None
        self._clock_timer.setInterval(1000)  # 1 s resolution is sufficient
        self._clock_timer.timeout.connect(self._tick_elapsed)

        root_path = project_root(__file__)
        ensure_dir(resolve_under(root_path, "logs"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(12)

        # 1. PHYSICAL MODEL (direkt, ohne Tabs)
        viz_frame = QFrame()
        viz_frame.setStyleSheet(
            "background-color: #050914; border: 1px solid #1E293B; border-radius: 6px;")
        viz_lay = QHBoxLayout(viz_frame)
        viz_lay.setContentsMargins(8, 8, 8, 8)

        # Linker Block: Kugel + Kalibrierungs-Button
        left_viz_widget = QWidget()
        left_viz_widget.setStyleSheet("background: transparent;")
        left_viz_lay = QVBoxLayout(left_viz_widget)
        left_viz_lay.setContentsMargins(0, 0, 0, 0)

        self.sandglass = ReactorSphereWidget()
        self.sandglass.configure_calibration(self._membrane_vol_ml, self.MAX_CELL_VOLUME_ML)
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
            "color: #64748B; font-family: 'Consolas'; font-weight: bold; "
            "font-size: 10px; letter-spacing: 2px;")
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
        # Phase snapshots: running total at phase boundaries (for segment colouring)
        self._snap_a_end_ml = 0.0   # total loss when Phase B starts
        self._snap_b_end_ml = 0.0   # total loss when Phase C starts

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
            "color: #94A3B8; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
        prog_top.addWidget(self.lbl_prog_phase)
        prog_top.addStretch()
        prog_top.addWidget(self.lbl_prog_values)
        prog_lay.addLayout(prog_top)

        # Elapsed run time — updated every second by _clock_timer
        self.lbl_elapsed = QLabel("")
        self.lbl_elapsed.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_elapsed.setStyleSheet(
            "color: #475569; font-family: 'Consolas'; font-size: 9px; border: none;")
        prog_lay.addWidget(self.lbl_elapsed)

        # Phase-segmented progress bar (A=purple / B1=amber / B2=light-amber / C=pink)
        self.seg_bar = PhaseSegmentBar()
        prog_lay.addWidget(self.seg_bar)

        # Thin fallback bar used only for ABORTED/FINISHED state flash
        self.bar_progress = QProgressBar()
        self.bar_progress.setRange(0, 1000)
        self.bar_progress.setValue(0)
        self.bar_progress.setTextVisible(False)
        self.bar_progress.setFixedHeight(3)
        self.bar_progress.setStyleSheet("""
            QProgressBar { background: transparent; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #64748B; border-radius: 2px; }
        """)
        self.bar_progress.hide()
        prog_lay.addWidget(self.bar_progress)

        # B1/B2 Detail-Reihe
        b_detail_lay = QHBoxLayout()
        b_detail_lay.setSpacing(12)
        self.lbl_b1_detail = QLabel("B1: —")
        self.lbl_b1_detail.setStyleSheet(
            "color: #F59E0B; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
        self.lbl_b2_detail = QLabel("")
        self.lbl_b2_detail.setStyleSheet(
            "color: #10B981; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
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

        # B2-Bar (Drying phase — shown when v_extra_ml > 0)
        self.bar_b2 = QProgressBar()
        self.bar_b2.setRange(0, 1000)
        self.bar_b2.setValue(0)
        self.bar_b2.setTextVisible(False)
        self.bar_b2.setFixedHeight(4)
        self.bar_b2.setStyleSheet("""
            QProgressBar { background: #0F172A; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #FBBF24; border-radius: 2px; }
        """)
        self.bar_b2.hide()
        prog_lay.addWidget(self.bar_b2)

        # Phase C row (ramp-down loss — tracked for completeness, not counted in target)
        c_detail_lay = QHBoxLayout()
        c_detail_lay.setSpacing(12)
        self.lbl_c_detail = QLabel("")
        self.lbl_c_detail.setStyleSheet(
            "color: #EC4899; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
        self.lbl_c_detail.hide()
        c_detail_lay.addWidget(self.lbl_c_detail)
        c_detail_lay.addStretch()
        prog_lay.addLayout(c_detail_lay)

        self.bar_c = QProgressBar()
        self.bar_c.setRange(0, 1000)
        self.bar_c.setValue(0)
        self.bar_c.setTextVisible(False)
        self.bar_c.setFixedHeight(4)
        self.bar_c.setStyleSheet("""
            QProgressBar { background: #0F172A; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #EC4899; border-radius: 2px; }
        """)
        self.bar_c.hide()
        prog_lay.addWidget(self.bar_c)

        # Flow / ETA row
        flow_eta_lay = QHBoxLayout()
        flow_eta_lay.setSpacing(12)
        self.lbl_flow_rate = QLabel("FLOW: —")
        self.lbl_flow_rate.setStyleSheet(
            "color: #00FF66; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
        self.lbl_eta = QLabel("")
        self.lbl_eta.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_eta.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
        self.lbl_eta_trend = QLabel("")
        self.lbl_eta_trend.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_eta_trend.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 9px; border: none;")
        flow_eta_lay.addWidget(self.lbl_flow_rate)
        flow_eta_lay.addStretch()
        flow_eta_lay.addWidget(self.lbl_eta)
        flow_eta_lay.addWidget(self.lbl_eta_trend)
        prog_lay.addLayout(flow_eta_lay)

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
        lbl_fill_title = QLabel("MANUAL FILLING REQUIRED")
        lbl_fill_title.setStyleSheet(
            "color: #00E5FF; font-weight: bold; font-family: 'Consolas'; "
            "font-size: 12px; border: none;")
        fill_title_row.addWidget(lbl_fill_title)
        fill_title_row.addStretch()
        fill_banner_lay.addLayout(fill_title_row)

        fill_input_row = QHBoxLayout()
        self.lbl_fill_recommend = QLabel("Recommended: — ml")
        self.lbl_fill_recommend.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 11px; border: none;")
        self.sp_fill_amount = NudgeSpinBox(0.0, 10000.0, 1, 100.0, " ml", 0.0)
        lbl_fill_ml = QLabel("Amount added:")
        lbl_fill_ml.setStyleSheet(
            "color: #94A3B8; font-family: 'Consolas'; font-size: 11px; border: none;")

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
                background-color: #000000; color: #F59E0B;
                font-weight: bold; font-family: 'Consolas';
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

        self.btn_stop = self._action_btn("STOP", "#FF1744")
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        self.btn_stop.setEnabled(False)

        ctrl_lay.addWidget(self.btn_start)
        ctrl_lay.addWidget(self.btn_stop)
        lay.addLayout(ctrl_lay)

        mark_row = QHBoxLayout()
        mark_row.addStretch()
        self.btn_mark = QPushButton("MARK EVENT")
        self.btn_mark.setFixedHeight(26)
        self.btn_mark.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mark.setEnabled(False)
        self.btn_mark.setStyleSheet(
            "QPushButton { background: #1E0B30; color: #8B5CF6; "
            "border: 1px solid #8B5CF6; border-radius: 3px; "
            "padding: 2px 12px; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; } "
            "QPushButton:hover:enabled { background: #8B5CF6; color: #FFF; } "
            "QPushButton:disabled { background: #050914; color: #334155; "
            "border-color: #1E293B; }")
        self.btn_mark.clicked.connect(self._on_mark_clicked)
        mark_row.addWidget(self.btn_mark)
        lay.addLayout(mark_row)

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
            QPushButton:disabled {{ background-color: #050914; color: #334155;
                border: 1px solid #0F172A; }}
        """)
        return btn

    @Slot()
    def reset_state(self):
        self.console.clear()
        self.banner_ok.hide()
        self.banner_filling.hide()
        self._ui_phase = "IDLE"
        self._current_vol_ml = 0.0
        self._flow_integrate_ts = None
        self._progress_target_ml = 0.0
        self._progress_current_ml = 0.0
        self._b1_target_ml = 0.0
        self._b2_target_ml = 0.0
        # _cell_volume_ml and _flow_integrate_ts intentionally NOT reset —
        # the sphere shows actual cell fill level between runs.
        self.sandglass.update_state(self._cell_volume_ml, "IDLE")
        self.trapezoid.set_state(0.0, 0.0, "IDLE")
        self.trapezoid.set_b_progress(0.0)
        self.frm_progress.hide()
        self.bar_progress.hide()
        self.bar_progress.setValue(0)
        self.bar_b1.setValue(0)
        self.bar_b1.hide()
        self.bar_b2.setValue(0)
        self.bar_b2.hide()
        self.bar_c.setValue(0)
        self.bar_c.hide()
        self.lbl_c_detail.hide()
        self.lbl_flow_rate.setText("FLOW: —")
        self.lbl_flow_rate.setStyleSheet(
            "color: #00FF66; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; border: none;")
        self.lbl_eta.setText("")
        self.lbl_eta_trend.setText("")
        self._flow_history.clear()
        self._flow_ema = None
        self._run_start = None
        self._clock_timer.stop()
        self.lbl_elapsed.setText("")

    _PHASE_BANNER: dict = {
        "FILLING": ("#00E5FF", "PHASE 0 ❄  FILLING"),
        "PHASE_A": ("#8B5CF6", "PHASE A ▲  RAMP UP"),
        "PHASE_B": ("#F59E0B", "PHASE B ◆  STEADY STATE"),
        "PHASE_C": ("#EC4899", "PHASE C ▼  RAMP DOWN"),
        "FINISHED": ("#10B981", "✔  RUN COMPLETE"),
        "ABORTED":  ("#FF1744", "✖  RUN ABORTED"),
    }
    _BANNER_WIDTH = 46

    @Slot(str)
    def set_step(self, step: str):
        prev_phase = self._ui_phase
        self._ui_phase = step.upper()
        color, label = "#64748B", self._ui_phase
        for key, (c, lbl) in self._PHASE_BANNER.items():
            if key in self._ui_phase:
                color, label = c, lbl
                break

        pad = max(0, self._BANNER_WIDTH - len(label) - 4)
        left = "═" * (pad // 2 + pad % 2)
        right = "═" * (pad // 2)
        banner = f"{left}  {label}  {right}"
        self.append_log(banner, color)

        # Phase boundary snapshots for segment bar colouring
        if "PHASE_B" in self._ui_phase and "PHASE_A" in prev_phase:
            self._snap_a_end_ml = self._progress_current_ml
            self.seg_bar.set_segment(a=self._snap_a_end_ml)
        elif "PHASE_C" in self._ui_phase and "PHASE_B" in prev_phase:
            self._snap_b_end_ml = self._progress_current_ml
            b_total = self._snap_b_end_ml - self._snap_a_end_ml
            self.seg_bar.set_segment(
                b1=self._b1_current_ml,
                b2=max(0.0, b_total - self._b1_current_ml),
            )

        self._update_progress_phase(self._ui_phase)

    @Slot(str)
    def set_status(self, msg: str):
        pass

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        self._loss_ml = loss_ml
        self._progress_current_ml = abs(float(loss_ml))
        self._update_progress_bar()
        # Drive segment bar live — only for phases that are the "accumulating" phase
        phase = self._ui_phase
        if "PHASE_A" in phase:
            self.seg_bar.set_segment(a=self._progress_current_ml)
        elif "PHASE_C" in phase:
            c_ml = max(0.0, self._progress_current_ml - self._snap_b_end_ml)
            self.seg_bar.set_segment(c=c_ml)

    def set_progress_target(self, target_ml: float):
        """Called by MainWindow when a run starts with the B1 volume target."""
        self._progress_target_ml = max(0.01, float(target_ml))
        self.seg_bar.set_target(self._progress_target_ml)
        self.frm_progress.show()
        self._update_progress_bar()

    def _update_progress_phase(self, phase: str):
        """Updates the phase label and handles terminal states (FINISHED / ABORTED)."""
        phase_colors = {
            "FILLING": ("#00E5FF", "PHASE 0: FILLING"),
            "PHASE_A": ("#8B5CF6", "PHASE A: RAMP UP"),
            "PHASE_B": ("#F59E0B", "PHASE B: STEADY STATE"),
            "PHASE_C": ("#EC4899", "PHASE C: RAMP DOWN"),
            "FINISHED": ("#10B981", "COMPLETE"),
            "ABORTED":  ("#FF1744", "ABORTED"),
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
                self.lbl_prog_values.setText(
                    f"DONE  {self._progress_current_ml:.1f} mL"
                )
            elif phase == "ABORTED":
                if self._progress_target_ml > 0.01:
                    pct = min(100.0, self._progress_current_ml / self._progress_target_ml * 100.0)
                    self.lbl_prog_values.setText(
                        f"STOPPED  {self._progress_current_ml:.1f} / "
                        f"{self._progress_target_ml:.1f} mL ({pct:.0f}%)"
                    )
                else:
                    self.lbl_prog_values.setText(
                        f"STOPPED  {self._progress_current_ml:.1f} mL"
                    )

    def _update_progress_bar(self):
        """Updates the value label; seg_bar handles the visual fill."""
        if self._progress_target_ml < 0.01:
            self.lbl_prog_values.setText(f"{self._progress_current_ml:.2f} mL")
            return

        pct = min(100.0, self._progress_current_ml / self._progress_target_ml * 100.0)
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
        html = (f'<span style="color: #64748B;">[{ts}]</span> '
                f'<span style="color: {color};">{msg}</span>')
        self.console.append(html)
        vs = self.console.verticalScrollBar()
        vs.setValue(vs.maximum())

    def enable_ok(self, enabled: bool):
        self.btn_ok.setEnabled(enabled)

    @Slot()
    def _on_mark_clicked(self):
        text, ok = QInputDialog.getText(self, "Mark Event", "Annotation:")
        if ok and text.strip():
            self.annotation_requested.emit(text.strip())

    def set_running(self, running: bool):
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.btn_mark.setEnabled(running)

        if running:
            self._run_start = time.monotonic()
            self._clock_timer.start()
            logger.info("Run started — elapsed timer started.")
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #0F172A; color: #334155;
                    font-family: 'Consolas'; font-weight: bold;
                    font-size: 12px; letter-spacing: 1px;
                    border: 1px solid #1E293B;
                    border-bottom: 2px solid #1E293B; border-radius: 4px;
                }
            """)
        else:
            self._clock_timer.stop()
            logger.info("Run stopped — elapsed timer stopped.")
            self.btn_start.setStyleSheet("""
                QPushButton {
                    background-color: #111827; color: #10B981;
                    font-family: 'Consolas'; font-weight: bold;
                    font-size: 12px; letter-spacing: 1px;
                    border: 1px solid #1E293B;
                    border-bottom: 2px solid #10B981; border-radius: 4px;
                }
                QPushButton:hover { background-color: #1E293B; color: #FFF; }
            """)

    @Slot()
    def _tick_elapsed(self):
        """Update the elapsed-time label every second while a run is active."""
        if self._run_start is None:
            return
        elapsed = int(time.monotonic() - self._run_start)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            text = f"ELAPSED  {hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            text = f"ELAPSED  {minutes:02d}:{seconds:02d}"
        self.lbl_elapsed.setText(text)

    @Slot()
    def _calibrate_membrane(self):
        """Pin the current cell volume as the 50% fill anchor; derive max as 2× that.

        Also re-anchors the persistent cell volume estimate to the current reading
        so any integration drift is corrected.
        """
        anchor = max(1.0, self._cell_volume_ml)
        self._membrane_vol_ml = anchor
        self.MAX_CELL_VOLUME_ML = anchor * 2.0
        # Re-anchor the persistent estimate so any drift is corrected
        self._cell_volume_ml = anchor
        self.sandglass.configure_calibration(self._membrane_vol_ml, self.MAX_CELL_VOLUME_ML)
        logger.info("Membrane calibrated: %.1f mL = 50%%, max = %.1f mL",
                    self._membrane_vol_ml, self.MAX_CELL_VOLUME_ML)
        self.append_log(
            f"SYS: Membrane → {self._membrane_vol_ml:.1f} mL = 50%  "
            f"(max {self.MAX_CELL_VOLUME_ML:.1f} mL)", "#00E5FF")
        self.sandglass.update_state(self._cell_volume_ml, self._ui_phase)

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

        # --- Persistent cell volume via flow integration (always, running or not) ---
        flow_raw = _to_float(sample.get("flow", 0.0))
        now = time.monotonic()
        if self._flow_integrate_ts is not None:
            dt = now - self._flow_integrate_ts
            if 0.0 < dt < 2.0:   # ignore stale gaps > 2 s (app pause, etc.)
                # Positive flow = filtration = cell draining → subtract
                # Negative flow = backwash   = cell filling → subtract a negative = add
                delta = flow_raw * (dt / 60.0)
                self._cell_volume_ml -= delta
                self._cell_volume_ml = max(
                    0.0, min(self.MAX_CELL_VOLUME_ML * 1.5, self._cell_volume_ml))
        self._flow_integrate_ts = now

        p1_raw = sample.get("p1_meas") if sample.get(
            "p1_meas") is not None else p1_data.get("meas", 0.0)
        p1 = _to_float(p1_raw)

        p1_set_raw = sample.get("p1_set") if sample.get(
            "p1_set") is not None else p1_data.get("set", 0.0)
        p1_set = _to_float(p1_set_raw)

        # Only accept volume from telemetry while a run is active. Stale queued
        # signals from a just-stopped worker would otherwise toggle the sphere
        # back after reset_state() has already zeroed it.
        if self._running:
            vol = _to_float(sample.get("volume_ml", 0.0))
            self._current_vol_ml = vol
        else:
            vol = self._current_vol_ml
        step = str(sample.get("step", "IDLE")).upper()

        self.trapezoid.set_state(p1, p1_set, self._ui_phase)

        # Sphere always shows persistent cell volume; pass signed flow for direction indicator
        display_phase = self._ui_phase if self._ui_phase not in ("IDLE", "") else step
        self.sandglass.update_state(self._cell_volume_ml, display_phase)
        self.sandglass.set_flow(flow_raw)

        # Live flow rate + ETA display in progress panel
        if flow_raw is not None:
            flow_signed = float(flow_raw)         # keep sign for direction
            flow_abs = abs(flow_signed)
            # Red for negative (reverse/backwash), green for forward filtration
            flow_color = "#FF1744" if flow_signed < -0.1 else "#00FF66"
            # Dead-band: only update label if flow changed by > 0.2 ml/min
            prev_flow = getattr(self, "_disp_flow_right", None)
            if prev_flow is None or abs(flow_abs - abs(prev_flow if prev_flow else 0)) >= 0.2:
                self._disp_flow_right = flow_signed
                self.lbl_flow_rate.setText(f"FLOW: {flow_signed:.1f} ml/min")
                self.lbl_flow_rate.setStyleSheet(
                    f"color: {flow_color}; font-family: 'Consolas'; font-size: 10px; "
                    f"font-weight: bold; border: none;")
            if flow_abs > 0.1:
                self._flow_history.append(flow_abs)
            avg_flow = sum(self._flow_history) / len(self._flow_history) if self._flow_history else 0.0
            target_known = self._progress_target_ml > 0.01
            below_target = self._progress_current_ml < self._progress_target_ml
            if target_known and below_target and avg_flow > 0.1:
                remaining = self._progress_target_ml - self._progress_current_ml
                eta_min = remaining / avg_flow

                # Trend ETA from EMA flow
                trend_eta_min = (
                    remaining / self._flow_ema
                    if self._flow_ema and self._flow_ema > 0.1
                    else eta_min
                )

                # Only update linear ETA label when it changes by > 1 min
                prev_eta = getattr(self, "_disp_eta_min", None)
                if prev_eta is None or abs(eta_min - prev_eta) >= 1.0:
                    self._disp_eta_min = eta_min
                    eta_m = int(eta_min)
                    eta_s = int((eta_min - eta_m) * 60)
                    self.lbl_eta.setText(f"ETA: {eta_m} min {eta_s:02d} s")
            else:
                if getattr(self, "_disp_eta_min", None) is not None:
                    self._disp_eta_min = None
                    self._disp_eta_trend_min = None
                    self.lbl_eta.setText("")
                    self.lbl_eta_trend.setText("")

    # -----------------------------------------------------------------
    # FILLING BANNER
    # -----------------------------------------------------------------
    @Slot(float)
    def show_filling_banner(self, recommended_ml: float):
        """Zeigt das Filling-Banner mit empfohlenem Füllvolumen."""
        rec = max(0.0, float(recommended_ml))
        self.lbl_fill_recommend.setText(f"Recommended: {rec:.1f} ml (last cycle losses)")
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
        self.append_log(f"FILLING CONFIRMED: {ml:.1f} ml added", "#10B981")

        # Anchor membrane at current backwash-residual volume.
        # After Phase B1 drains exactly ml mL, _cell_volume_ml returns to bw_vol = membrane level.
        bw_vol = max(10.0, self._cell_volume_ml)
        self._membrane_vol_ml = bw_vol
        self._cell_volume_ml = bw_vol + ml
        self.MAX_CELL_VOLUME_ML = self._cell_volume_ml
        self.sandglass.configure_calibration(self._membrane_vol_ml, self.MAX_CELL_VOLUME_ML)
        self.sandglass.update_state(self._cell_volume_ml, "FILLING")
        self.append_log(
            f"SYS: Sphere → membrane={bw_vol:.0f} mL (50%) full={self._cell_volume_ml:.0f} mL",
            "#00E5FF",
        )
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
        pid = phase_id.upper()
        if pid == "P0":
            self.frm_progress.show()
            if target > 0:
                pct = min(100.0, current / target * 100.0)
                self.lbl_b1_detail.setText(f"FILL: {current:.1f} / {target:.1f} ml ({pct:.0f}%)")
                self.bar_b1.setValue(int(pct * 10))
                self.lbl_prog_values.setText(f"{current:.1f} / {target:.1f} mL ({pct:.0f}%)")
            else:
                self.lbl_b1_detail.setText(f"FILL: {current:.1f} ml")
            self.bar_b1.show()
        elif pid == "B1":
            self._b1_current_ml = float(current)
            self._b1_target_ml = float(target)
            if target > 0:
                pct = min(100.0, current / target * 100.0)
                self.lbl_b1_detail.setText(
                    f"B1: {current:.1f} / {target:.1f} ml ({pct:.0f}%)"
                )
                self.bar_b1.setValue(int(pct * 10))
                self.trapezoid.set_b_progress(current / target)
                self.seg_bar.set_segment(b1=float(current))
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
                self.bar_b2.setValue(int(pct * 10))
            else:
                self.lbl_b2_detail.setText(f"B2: {current:.1f} ml")
                self.bar_b2.setValue(0)
            self.lbl_b2_detail.show()
            self.bar_b2.show()
        elif pid == "C":
            c_ml = float(current)
            if c_ml > 0.0:
                self.lbl_c_detail.setText(f"C ramp-dn: {c_ml:.1f} ml")
                self.lbl_c_detail.show()
                self.bar_c.show()
                # bar_c is decorative — set proportional to 500 mL ceiling so it grows visibly
                self.bar_c.setValue(min(1000, int(c_ml / 500.0 * 1000)))
