from __future__ import annotations

import csv
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
        self._csv_fp: Any = None
        self._csv_w: Any = None

        # High-Performance Deques für ruckelfreie Darstellung
        self._t = deque(maxlen=max_points)
        self._flow = deque(maxlen=max_points)
        self._p1 = deque(maxlen=max_points)
        self._p2 = deque(maxlen=max_points)

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        # --- PLOT CONFIGURATION ---
        pg.setConfigOptions(antialias=True, useOpenGL=True) # OpenGL für maximale Performance
        
        # 1. Plot für Druck (P1 & P2)
        self.plot_p = pg.PlotWidget()
        self._style_plot(self.plot_p, "PRESSURE TELEMETRY", "mbar")
        
        # 2. Plot für Flussrate
        self.plot_flow = pg.PlotWidget()
        self._style_plot(self.plot_flow, "FLOW DYNAMICS", "mL/min")

        # Verknüpfung der X-Achsen (Zooming/Panning synchronisiert)
        self.plot_flow.setXLink(self.plot_p)

        # --- CURVES & GRADIENTS ---
        # Flow Curve (Neon Pink)
        pen_flow = pg.mkPen(color='#EC4899', width=2)
        self.curve_flow = self.plot_flow.plot(pen=pen_flow, name="Flow")
        # Subtiler Glow/Fill für Flow
        fill_flow = pg.FillBetweenItem(self.plot_flow.plot(), self.curve_flow, brush=QColor(236, 72, 153, 20))
        self.plot_flow.addItem(fill_flow)

        # P1 Curve (Purple)
        pen_p1 = pg.mkPen(color='#8B5CF6', width=2)
        self.curve_p1 = self.plot_p.plot(pen=pen_p1, name="P1 Main")
        
        # P2 Curve (Cyan Dashed)
        pen_p2 = pg.mkPen(color='#00E5FF', width=1.5, style=Qt.PenStyle.DashLine)
        self.curve_p2 = self.plot_p.plot(pen=pen_p2, name="P2 Backwash")

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
        # Verhindert Zittern der Achsen
        pw.getViewBox().setLimits(minXRange=5)

    def start_logging(self, run_name_prefix: str = "run") -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self._log_dir / f"{run_name_prefix}_{ts}_telemetry.csv"
        try:
            self._csv_fp = open(path, "w", newline="", encoding="utf-8")
            self._csv_w = csv.writer(self._csv_fp)
            self._csv_w.writerow(["t_unix", "t_s", "step", "flow", "p1_meas", "p2_meas", "valves"])
            
            self._t0 = None
            self._t.clear()
            self._flow.clear()
            self._p1.clear()
            self._p2.clear()

            self.lbl_status.setText("● RECORDING LIVE DATA")
            self.lbl_status.setStyleSheet("color: #FF1744; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
            self.lbl_path.setText(str(path.name))
        except Exception as e:
            logger.error(f"Failed to start logging: {e}")

    def stop_logging(self) -> None:
        if self._csv_fp:
            self._csv_fp.close()
            self._csv_fp = None
            self._csv_w = None
        self.lbl_status.setText("📡 TELEMETRY: IDLE")
        self.lbl_status.setStyleSheet("color: #64748B; font-family: 'Consolas'; font-size: 9px; font-weight: bold;")
        self.lbl_path.setText("")

    @Slot(dict)
    def ingest_telemetry(self, payload: dict) -> None:
        raw_t = payload.get("t", time.time())
        if self._t0 is None: self._t0 = raw_t
        
        ts = raw_t - self._t0
        flow = _to_float(payload.get("flow"))
        p1 = _to_float(payload.get("p1_meas"))
        p2 = _to_float(payload.get("p2_meas"))
        
        # Daten in Deques schieben
        self._t.append(ts)
        self._flow.append(_nan(flow))
        self._p1.append(_nan(p1))
        self._p2.append(_nan(p2))

        # Plots aktualisieren (direkt von den Deques)
        self.curve_flow.setData(list(self._t), list(self._flow))
        self.curve_p1.setData(list(self._t), list(self._p1))
        self.curve_p2.setData(list(self._t), list(self._p2))

        # CSV Writing
        if self._csv_w and self._csv_fp:
            step = str(payload.get("step", "—"))
            valves = str(payload.get("valves", "—"))
            self._csv_w.writerow([raw_t, f"{ts:.3f}", step, flow, p1, p2, valves])

def _to_float(x: Any) -> Optional[float]:
    try: return float(x) if x is not None else None
    except: return None

def _nan(x: Optional[float]) -> float:
    return float("nan") if x is None else x