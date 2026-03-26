from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

import pyqtgraph as pg
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont

logger = logging.getLogger(__name__)

# =====================================================================
# KUGELSICHERER DATENFILTER
# Vernichtet NaN, None und Infinity, bevor pyqtgraph abstürzen kann.
# =====================================================================
def safe_float(x: Any, fallback: float = 0.0) -> float:
    try:
        if x is None: 
            return fallback
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")): 
            return fallback
        return v
    except Exception:
        return fallback

_PHASE_COLORS = {
    "FILLING": "#00E5FF", "PHASE_A": "#8B5CF6", "PHASE_B": "#F59E0B",
    "PHASE_C": "#EC4899", "FINISHED": "#10B981", "ABORTED": "#FF1744",
}

class EliteMonitorTab(Qtw.QFrame):
    """
    Neu aufgebautes, absturzsicheres Realtime-Telemetrie-Widget.
    3 getrennte Plots: Pressure, Flow, Loss.
    """
    BATCH_SIZE = 5

    def __init__(self, log_dir: Path, *, max_points: int = 3000) -> None:
        super().__init__()
        self._max_points = int(max_points)
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # State
        self._t0: float | None = None
        self._sample_count: int = 0
        self._current_phase: str = "IDLE"
        self._phase_start_t: float = 0.0
        self._phase_regions: list = []

        # High-Performance Deques
        self._t = deque(maxlen=max_points)
        self._p1 = deque(maxlen=max_points)
        self._p1_set = deque(maxlen=max_points)
        self._p2 = deque(maxlen=max_points)
        self._p2_set = deque(maxlen=max_points)
        self._flow = deque(maxlen=max_points)
        self._loss = deque(maxlen=max_points)

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        pg.setConfigOptions(antialias=True, useOpenGL=False)

        # ---------------------------------------------------------
        # PLOT 1: PRESSURE (P1 & P2)
        # ---------------------------------------------------------
        self.plot_p = pg.PlotWidget()
        self._style_plot(self.plot_p, "P [mbar]")
        self.plot_p.getViewBox().setLimits(yMin=-50, yMax=10000)
        self.plot_p.addLegend(offset=(60, 10), labelTextSize='8pt', brush=QColor(15, 23, 42, 180), pen=QColor(30, 41, 59))

        self.curve_p1 = self.plot_p.plot(pen=pg.mkPen('#8B5CF6', width=2), name="P1 Ist")
        self.curve_p1_set = self.plot_p.plot(pen=pg.mkPen('#8B5CF6', width=1, style=Qt.PenStyle.DashLine), name="P1 Soll")
        self.curve_p2 = self.plot_p.plot(pen=pg.mkPen('#00E5FF', width=2), name="P2 Ist")
        self.curve_p2_set = self.plot_p.plot(pen=pg.mkPen('#00E5FF', width=1, style=Qt.PenStyle.DashLine), name="P2 Soll")

        # ---------------------------------------------------------
        # PLOT 2: FLOW
        # ---------------------------------------------------------
        self.plot_flow = pg.PlotWidget()
        self._style_plot(self.plot_flow, "Flow [mL/min]")
        self.plot_flow.getViewBox().setLimits(yMin=-10, yMax=500)
        self.curve_flow = self.plot_flow.plot(pen=pg.mkPen('#EC4899', width=2), name="Flow", fillLevel=0, fillBrush=QColor(236, 72, 153, 20))

        # ---------------------------------------------------------
        # PLOT 3: TOTAL LOSS
        # ---------------------------------------------------------
        self.plot_loss = pg.PlotWidget()
        self._style_plot(self.plot_loss, "Loss [mL]", show_bottom_label=True)
        self.plot_loss.getViewBox().setLimits(yMin=-10, yMax=5000)
        self.curve_loss = self.plot_loss.plot(pen=pg.mkPen('#10B981', width=2), name="Total Loss", fillLevel=0, fillBrush=QColor(16, 185, 129, 20))

        # Hinzufügen zum Layout mit Stretch-Faktoren (Druck bekommt etwas mehr Platz)
        root.addWidget(self.plot_p, stretch=3)
        root.addWidget(self.plot_flow, stretch=2)
        root.addWidget(self.plot_loss, stretch=2)

        # ---------------------------------------------------------
        # FOOTER STATUS BAR
        # ---------------------------------------------------------
        self.footer = Qtw.QFrame()
        self.footer.setFixedHeight(22)
        self.footer.setStyleSheet("background-color: #050914; border-top: 1px solid #1E293B;")
        foot_lay = Qtw.QHBoxLayout(self.footer)
        foot_lay.setContentsMargins(12, 0, 12, 0)

        self.lbl_status = Qtw.QLabel("TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet("color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
        self.lbl_samples = Qtw.QLabel("")
        self.lbl_samples.setStyleSheet("color: #334155; font-family: 'Consolas'; font-size: 9px;")
        
        foot_lay.addWidget(self.lbl_status)
        foot_lay.addStretch()
        foot_lay.addWidget(self.lbl_samples)
        root.addWidget(self.footer)

    def _style_plot(self, pw: pg.PlotWidget, y_label: str, show_bottom_label: bool = False):
        pw.setBackground('#090B10')
        pw.showGrid(x=True, y=True, alpha=0.06)
        pw.enableAutoRange(axis='y')
        pw.setMouseEnabled(x=True, y=False) # X-Zoom erlaubt, Y-Zoom gesperrt

        ax_left = pw.getAxis('left')
        ax_left.setLabel(y_label, color='#94A3B8')
        ax_left.setTickFont(QFont("Consolas", 7))
        ax_left.setTextPen('#64748B')
        # 🚀 MAGIC TRICK: Feste Achsenbreite sorgt dafür, dass alle 3 Graphen exakt übereinander liegen!
        ax_left.setWidth(60)

        ax_bottom = pw.getAxis('bottom')
        ax_bottom.setTickFont(QFont("Consolas", 7))
        ax_bottom.setTextPen('#64748B')
        if show_bottom_label:
            ax_bottom.setLabel("Time [s]", color='#64748B')
        else:
            ax_bottom.setStyle(showValues=False)
            ax_bottom.setHeight(0)

    # -----------------------------------------------------------------
    # LIFECYCLE
    # -----------------------------------------------------------------
    def start_logging(self, run_name_prefix: str = "run") -> None:
        self._clear_all()
        self.lbl_status.setText("RECORDING LIVE DATA")
        self.lbl_status.setStyleSheet("color: #FF1744; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")

    def stop_logging(self) -> None:
        if self._t:
            self._update_curves(self._t[-1])
        self.lbl_status.setText("TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet("color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")

    def _clear_all(self):
        self._t0 = None
        self._sample_count = 0
        self._current_phase = "IDLE"
        self._phase_start_t = 0.0
        self._t.clear(); self._p1.clear(); self._p1_set.clear()
        self._p2.clear(); self._p2_set.clear(); self._flow.clear(); self._loss.clear()
        
        self.curve_p1.setData([], []); self.curve_p1_set.setData([], [])
        self.curve_p2.setData([], []); self.curve_p2_set.setData([], [])
        self.curve_flow.setData([], []); self.curve_loss.setData([], [])
        
        for item in self._phase_regions:
            try: self.plot_p.removeItem(item)
            except Exception: pass
        self._phase_regions.clear()
        
        # Alle Achsen auf Startwert setzen
        self.plot_p.setXRange(min=0, max=60, padding=0)       # type: ignore
        self.plot_flow.setXRange(min=0, max=60, padding=0)    # type: ignore
        self.plot_loss.setXRange(min=0, max=60, padding=0)    # type: ignore
        self.lbl_samples.setText("")

    # -----------------------------------------------------------------
    # DATA INGEST
    # -----------------------------------------------------------------
    @Slot(dict)
    def ingest_telemetry(self, payload: dict) -> None:
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now

        ts = now - self._t0
        if self._t and ts <= self._t[-1]:
            ts = self._t[-1] + 0.005

        # Daten sicher extrahieren (verhindert Abstürze)
        flow = safe_float(payload.get("flow"))
        p1 = safe_float(payload.get("p1_meas"))
        p2 = safe_float(payload.get("p2_meas"))
        
        # Loss extrahieren (wird vom RightFrame injiziert)
        loss = safe_float(payload.get("loss_ml", 0.0))

        pressures = payload.get("pressure", {})
        p1_set, p2_set = 0.0, 0.0
        if isinstance(pressures, dict):
            # P1 Setpoint
            p1_data = pressures.get(1, pressures.get("1", {}))
            if isinstance(p1_data, dict): p1_set = safe_float(p1_data.get("set"))
            # P2 Setpoint
            p2_data = pressures.get(2, pressures.get("2", {}))
            if isinstance(p2_data, dict): p2_set = safe_float(p2_data.get("set"))

        step = str(payload.get("step", "IDLE")).upper()
        if step != self._current_phase:
            self._add_phase_region(self._current_phase, self._phase_start_t, ts)
            self._current_phase = step
            self._phase_start_t = ts

        # In die Deques feuern
        self._t.append(ts)
        self._p1.append(p1); self._p1_set.append(p1_set)
        self._p2.append(p2); self._p2_set.append(p2_set)
        self._flow.append(flow)
        self._loss.append(loss)
        
        self._sample_count += 1

        # Render-Update drosseln (für mehr Performance)
        if self._sample_count % self.BATCH_SIZE == 0:
            self._update_curves(ts)

    def _update_curves(self, current_ts: float):
        t_list = list(self._t)
        self.curve_p1.setData(t_list, list(self._p1))
        self.curve_p1_set.setData(t_list, list(self._p1_set))
        self.curve_p2.setData(t_list, list(self._p2))
        self.curve_p2_set.setData(t_list, list(self._p2_set))
        self.curve_flow.setData(t_list, list(self._flow))
        self.curve_loss.setData(t_list, list(self._loss))

        # 🚀 KUGELSICHERES SCROLLING
        # Jeder Graph wird strikt einzeln bewegt. Keine Links, keine Loops.
        window = 60.0
        if current_ts > window:
            t_min, t_max = current_ts - window, current_ts
            self.plot_p.setXRange(min=t_min, max=t_max, padding=0)     # type: ignore
            self.plot_flow.setXRange(min=t_min, max=t_max, padding=0)  # type: ignore
            self.plot_loss.setXRange(min=t_min, max=t_max, padding=0)  # type: ignore

        mins = int(current_ts // 60)
        secs = int(current_ts % 60)
        self.lbl_samples.setText(f"{self._sample_count} samples | {mins:02d}:{secs:02d}")

    def _add_phase_region(self, phase: str, t_start: float, t_end: float):
        if phase == "IDLE" or t_end - t_start < 0.5: return

        color_hex = "#334155"
        for key, c in _PHASE_COLORS.items():
            if key in phase:
                color_hex = c; break

        color = QColor(color_hex)
        color.setAlpha(20)

        # Region nur in den oberen Druck-Graphen zeichnen (verhindert optisches Chaos)
        region = pg.LinearRegionItem(values=[t_start, t_end], movable=False, brush=color, pen=pg.mkPen(color_hex, width=0.5, style=Qt.PenStyle.DotLine))
        region.setZValue(-10)

        short = phase.replace("PHASE_", "").replace("FILLING", "P0")
        label = pg.TextItem(text=short, color=color_hex, anchor=(0, 1))
        label.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        label.setPos(t_start + 1, 0)

        self.plot_p.addItem(region)
        self.plot_p.addItem(label)
        self._phase_regions.append(region)
        self._phase_regions.append(label)