from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

import pyqtgraph as pg
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont

logger = logging.getLogger(__name__)

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None: return None
        v = float(x)
        if v != v or v in (float("inf"), float("-inf")): return None
        return v
    except Exception:
        return None

def _nan(x: Optional[float]) -> float:
    return float("nan") if x is None else x

_PHASE_COLORS = {
    "FILLING": "#00E5FF", "PHASE_A": "#8B5CF6", "PHASE_B": "#F59E0B",
    "PHASE_C": "#EC4899", "FINISHED": "#10B981", "ABORTED": "#FF1744",
}

class EliteMonitorTab(Qtw.QFrame):
    """
    Hochperformantes Realtime-Telemetrie-Widget.
    """

    BATCH_SIZE = 5

    def __init__(self, log_dir: Path, *, max_points: int = 3000) -> None:
        super().__init__()
        self._max_points = int(max_points)
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._t0: Optional[float] = None
        self._sample_count: int = 0
        self._current_phase: str = "IDLE"
        self._phase_start_t: float = 0.0
        self._phase_regions: list = []

        self._t = deque(maxlen=max_points)
        self._p1 = deque(maxlen=max_points)
        self._p1_set = deque(maxlen=max_points)
        self._p2 = deque(maxlen=max_points)
        self._flow = deque(maxlen=max_points)

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        pg.setConfigOptions(antialias=True, useOpenGL=False)

        # --- DRUCK-PLOT ---
        self.plot_p = pg.PlotWidget()
        self._style_plot(self.plot_p, "P [mbar]")
        self.plot_p.addLegend(offset=(60, 10), labelTextSize='8pt',
                              brush=QColor(15, 23, 42, 180), pen=QColor(30, 41, 59))

        # connect="finite" verhindert wilde Zick-Zack Linien bei Sensor-Ausfällen (NaN)
        self.curve_p1 = self.plot_p.plot(
            pen=pg.mkPen('#8B5CF6', width=2), name="P1 Ist", connect="finite")
        self.curve_p1_set = self.plot_p.plot(
            pen=pg.mkPen('#8B5CF6', width=1, style=Qt.PenStyle.DashLine), name="P1 Soll", connect="finite")
        self.curve_p2 = self.plot_p.plot(
            pen=pg.mkPen('#00E5FF', width=1.5, style=Qt.PenStyle.DashLine), name="P2", connect="finite")

        # --- FLOW-PLOT ---
        self.plot_flow = pg.PlotWidget()
        self._style_plot(self.plot_flow, "Flow [mL/min]", show_bottom_label=True)

        self.curve_flow = self.plot_flow.plot(
            pen=pg.mkPen('#EC4899', width=2), name="Flow",
            fillLevel=0, fillBrush=QColor(236, 72, 153, 15), connect="finite")

        # X-Achsen hart verlinken
        self.plot_flow.setXLink(self.plot_p)

        root.addWidget(self.plot_p, 3)
        root.addWidget(self.plot_flow, 2)

        # --- FOOTER ---
        self.footer = Qtw.QFrame()
        self.footer.setFixedHeight(22)
        self.footer.setStyleSheet("background-color: #050914; border-top: 1px solid #1E293B;")
        foot_lay = Qtw.QHBoxLayout(self.footer)
        foot_lay.setContentsMargins(12, 0, 12, 0)

        self.lbl_status = Qtw.QLabel("TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
        self.lbl_samples = Qtw.QLabel("")
        self.lbl_samples.setStyleSheet(
            "color: #334155; font-family: 'Consolas'; font-size: 9px;")
        self.lbl_samples.setAlignment(Qt.AlignmentFlag.AlignRight)

        foot_lay.addWidget(self.lbl_status)
        foot_lay.addStretch()
        foot_lay.addWidget(self.lbl_samples)
        root.addWidget(self.footer)

    def _style_plot(self, pw: pg.PlotWidget, y_label: str, show_bottom_label: bool = False):
        pw.setBackground('#090B10')
        pw.showGrid(x=True, y=True, alpha=0.06)
        pw.enableAutoRange(axis='y')
        pw.setMouseEnabled(x=True, y=False)

        ax_left = pw.getAxis('left')
        ax_left.setLabel(y_label, color='#94A3B8')
        ax_left.setTickFont(QFont("Consolas", 7))
        ax_left.setTextPen('#64748B')
        ax_left.setWidth(55)

        ax_bottom = pw.getAxis('bottom')
        ax_bottom.setTickFont(QFont("Consolas", 7))
        ax_bottom.setTextPen('#64748B')
        if show_bottom_label:
            ax_bottom.setLabel("Time", units="s", color='#64748B')
        else:
            ax_bottom.setStyle(showValues=False)
            ax_bottom.setHeight(0)

        pw.getViewBox().setLimits(minXRange=5)

    def start_logging(self, run_name_prefix: str = "run") -> None:
        self._clear_all()
        self.lbl_status.setText("RECORDING")
        self.lbl_status.setStyleSheet(
            "color: #FF1744; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")

    def stop_logging(self) -> None:
        if self._t:
            self._update_curves(self._t[-1])
        self.lbl_status.setText("TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")

    def _clear_all(self):
        self._t0 = None
        self._sample_count = 0
        self._current_phase = "IDLE"
        self._phase_start_t = 0.0
        self._t.clear()
        self._p1.clear()
        self._p1_set.clear()
        self._p2.clear()
        self._flow.clear()
        self.curve_p1.setData([], [])
        self.curve_p1_set.setData([], [])
        self.curve_p2.setData([], [])
        self.curve_flow.setData([], [])
        for item in self._phase_regions:
            try: self.plot_p.removeItem(item)
            except Exception: pass
        self._phase_regions.clear()
        
        # Pylance type: ignore verwenden, um Keyword-Arg-Ärger zu vermeiden
        self.plot_p.setXRange(0, 60)  # type: ignore
        self.lbl_samples.setText("")

    @Slot(dict)
    def ingest_telemetry(self, payload: dict) -> None:
        # =========================================================================
        # 🚀 DER WICHTIGSTE FIX: DIE AUTARKE UHR
        # Wir vertrauen keinem Zeitstempel von außen mehr, um die Kollision zu stoppen!
        # =========================================================================
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now

        ts = now - self._t0
        
        # Falls die Ausführung zu schnell ist, minimales Inkrement erzwingen
        if self._t and ts <= self._t[-1]:
            ts = self._t[-1] + 0.005
        # =========================================================================

        flow = _to_float(payload.get("flow"))
        p1 = _to_float(payload.get("p1_meas"))
        p2 = _to_float(payload.get("p2_meas"))

        pressures = payload.get("pressure", {})
        p1_set = None
        if isinstance(pressures, dict):
            p1_data = pressures.get(1, pressures.get("1", {}))
            if isinstance(p1_data, dict):
                p1_set = _to_float(p1_data.get("set"))
        if p1_set is None:
            p1_set = _to_float(payload.get("p1_set"))

        step = str(payload.get("step", "IDLE")).upper()
        if step != self._current_phase:
            self._add_phase_region(self._current_phase, self._phase_start_t, ts)
            self._current_phase = step
            self._phase_start_t = ts

        self._t.append(ts)
        self._p1.append(_nan(p1))
        self._p1_set.append(_nan(p1_set))
        self._p2.append(_nan(p2))
        self._flow.append(_nan(flow))
        self._sample_count += 1

        if self._sample_count % self.BATCH_SIZE == 0:
            self._update_curves(ts)

    def _update_curves(self, current_ts: float):
        t_list = list(self._t)
        self.curve_p1.setData(t_list, list(self._p1))
        self.curve_p1_set.setData(t_list, list(self._p1_set))
        self.curve_p2.setData(t_list, list(self._p2))
        self.curve_flow.setData(t_list, list(self._flow))

        window = 60.0
        if current_ts > window:
            self.plot_p.setXRange(current_ts - window, current_ts)  # type: ignore

        mins = int(current_ts // 60)
        secs = int(current_ts % 60)
        self.lbl_samples.setText(f"{self._sample_count} samples | {mins:02d}:{secs:02d}")

    def _add_phase_region(self, phase: str, t_start: float, t_end: float):
        if phase == "IDLE" or t_end - t_start < 0.5:
            return

        color_hex = "#334155"
        for key, c in _PHASE_COLORS.items():
            if key in phase:
                color_hex = c
                break

        color = QColor(color_hex)
        color.setAlpha(20)

        region = pg.LinearRegionItem(
            values=[t_start, t_end], movable=False,
            brush=color,
            pen=pg.mkPen(color_hex, width=0.5, style=Qt.PenStyle.DotLine))
        region.setZValue(-10)

        short = phase.replace("PHASE_", "").replace("FILLING", "P0")
        label = pg.TextItem(text=short, color=color_hex, anchor=(0, 1))
        label.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        label.setPos(t_start + 1, 0)

        self.plot_p.addItem(region)
        self.plot_p.addItem(label)
        self._phase_regions.append(region)
        self._phase_regions.append(label)