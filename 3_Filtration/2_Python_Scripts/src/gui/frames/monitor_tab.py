from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any
from collections import deque

import pyqtgraph as pg
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QLinearGradient, QColor, QBrush, QFont

logger = logging.getLogger(__name__)

@dataclass
class TelemetrySample:
    t: float
    step: str
    flow: Optional[float]
    p1: Optional[float]
    p2: Optional[float]
    valves: str

class EliteMonitorTab(Qtw.QFrame):
    def __init__(self, log_dir: Path, *, max_points: int = 5000) -> None:
        super().__init__()
        self._max_points = int(max_points)
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._t0: Optional[float] = None

        # High-Performance Deques für ruckelfreie Darstellung
        self._t = deque(maxlen=max_points)
        self._flow = deque(maxlen=max_points)
        self._p1 = deque(maxlen=max_points)
        self._p1_set = deque(maxlen=max_points)
        self._p2 = deque(maxlen=max_points)

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # --- PLOT CONFIGURATION ---
        pg.setConfigOptions(antialias=True)
        
        # 1. Plot für Druck (P1 Ist, P1 Soll, P2)
        self.plot_p = pg.PlotWidget()
        self._style_plot(self.plot_p, "PRESSURE TELEMETRY", "mbar")
        self.plot_p.setXRange(0, 60)
        self.plot_p.setYRange(-50, 2500)
        self.plot_p.enableAutoRange(axis='y')

        # 2. Plot für Flussrate
        self.plot_flow = pg.PlotWidget()
        self._style_plot(self.plot_flow, "FLOW DYNAMICS", "mL/min")
        self.plot_flow.setXRange(0, 60)
        self.plot_flow.setYRange(-0.5, 30)
        self.plot_flow.enableAutoRange(axis='y')

        # Verknüpfung der X-Achsen (Zooming/Panning synchronisiert)
        self.plot_flow.setXLink(self.plot_p)

        # --- CURVES ---
        # P1 Ist (Purple solid)
        self.curve_p1 = self.plot_p.plot(
            pen=pg.mkPen(color='#8B5CF6', width=2), name="P1 Ist")
        
        # P1 Soll (Purple dashed, dünn)
        self.curve_p1_set = self.plot_p.plot(
            pen=pg.mkPen(color='#8B5CF6', width=1, style=Qt.PenStyle.DashLine), name="P1 Soll")
        
        # P2 (Cyan dashed)
        self.curve_p2 = self.plot_p.plot(
            pen=pg.mkPen(color='#00E5FF', width=1.5, style=Qt.PenStyle.DashLine), name="P2")

        # Flow (Pink mit Fill)
        self.curve_flow = self.plot_flow.plot(
            pen=pg.mkPen(color='#EC4899', width=2), name="Flow",
            fillLevel=0, fillBrush=QColor(236, 72, 153, 20))

        root.addWidget(self.plot_p, 3)
        root.addWidget(self.plot_flow, 2)

        # --- FOOTER / STATUS BAR ---
        self.footer = Qtw.QFrame()
        self.footer.setFixedHeight(25)
        self.footer.setStyleSheet("background-color: #050914; border-top: 1px solid #1E293B;")
        foot_lay = Qtw.QHBoxLayout(self.footer)
        foot_lay.setContentsMargins(15, 0, 15, 0)

        self.lbl_status = Qtw.QLabel("📡 TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet("color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
        
        self.lbl_path = Qtw.QLabel("")
        self.lbl_path.setStyleSheet("color: #334155; font-family: 'Consolas'; font-size: 9px;")
        
        foot_lay.addWidget(self.lbl_status)
        foot_lay.addStretch()
        foot_lay.addWidget(self.lbl_path)
        root.addWidget(self.footer)

    def _style_plot(self, pw: pg.PlotWidget, title: str, unit: str):
        pw.setBackground('#090B10')
        pw.showGrid(x=True, y=True, alpha=0.05)
        pw.getAxis('left').setLabel(title, units=unit, color='#94A3B8', **{'font-size': '8pt'})
        pw.getAxis('bottom').setLabel("Time", units="s", color='#94A3B8', **{'font-size': '8pt'})
        pw.getAxis('left').setTickFont(QFont("Consolas", 7))
        pw.getAxis('bottom').setTickFont(QFont("Consolas", 7))
        # Disable auto-range: we set ranges manually to prevent wild rescaling on real hardware
        pw.enableAutoRange(False)
        pw.getViewBox().setLimits(minXRange=5, minYRange=10)

    def start_logging(self, run_name_prefix: str = "run") -> None:
        # CSV wird jetzt zentral vom Experimentator geschrieben — hier nur Plot-Reset
        self._t0 = None
        self._t.clear()
        self._flow.clear()
        self._p1.clear()
        self._p1_set.clear()
        self._p2.clear()
        self.curve_flow.setData([], [])
        self.curve_p1.setData([], [])
        self.curve_p1_set.setData([], [])
        self.curve_p2.setData([], [])
        self.plot_p.setXRange(0, 60)
        self.plot_flow.setXRange(0, 60)

        self.lbl_status.setText("● RECORDING LIVE DATA")
        self.lbl_status.setStyleSheet("color: #FF1744; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
        self.lbl_path.setText(f"(CSV via Experimentator)")

    def stop_logging(self) -> None:
        # Plot-State zurücksetzen (CSV wird vom Experimentator gehandhabt)
        self._t0 = None
        self._t.clear()
        self._flow.clear()
        self._p1.clear()
        self._p1_set.clear()
        self._p2.clear()
        self.curve_flow.setData([], [])
        self.curve_p1.setData([], [])
        self.curve_p1_set.setData([], [])
        self.curve_p2.setData([], [])
        self.plot_p.setXRange(0, 60)
        self.plot_flow.setXRange(0, 60)
        self.lbl_status.setText("📡 TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet("color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
        self.lbl_path.setText("")

    @Slot(dict)
    def ingest_telemetry(self, payload: dict) -> None:
        raw_t = payload.get("t", time.monotonic())
        if self._t0 is None:
            self._t0 = raw_t
            self.plot_p.setXRange(0, 60)
            self.plot_flow.setXRange(0, 60)

        ts = raw_t - self._t0

        # Monotonic guard: never go backwards in time
        if self._t and ts <= self._t[-1]:
            ts = self._t[-1] + 0.005

        flow = _to_float(payload.get("flow"))
        p1   = _to_float(payload.get("p1_meas"))
        p2   = _to_float(payload.get("p2_meas"))

        # P1 Setpoint aus pressure-Dict oder direkt
        pressures = payload.get("pressure", {})
        if isinstance(pressures, dict):
            p1_data = pressures.get(1, pressures.get("1", {}))
            p1_set = _to_float(p1_data.get("set") if isinstance(p1_data, dict) else None)
        else:
            p1_set = _to_float(payload.get("p1_set"))

        self._t.append(ts)
        self._flow.append(_nan(flow))
        self._p1.append(_nan(p1))
        self._p1_set.append(_nan(p1_set))
        self._p2.append(_nan(p2))

        # Scrolling x-axis after 60 s
        if ts > 60:
            self.plot_p.setXRange(ts - 60, ts)
            self.plot_flow.setXRange(ts - 60, ts)

        t_list = list(self._t)
        self.curve_flow.setData(t_list, list(self._flow))
        self.curve_p1.setData(t_list, list(self._p1))
        self.curve_p1_set.setData(t_list, list(self._p1_set))
        self.curve_p2.setData(t_list, list(self._p2))

def _to_float(x: Any) -> Optional[float]:
    try:
        if x is None: return None
        v = float(x)
        # Filter inf and NaN — pyqtgraph renders NaN as a gap, inf causes axis blowup
        if v != v or v in (float("inf"), float("-inf")): return None
        return v
    except: return None

def _nan(x: Optional[float]) -> float:
    return float("nan") if x is None else x