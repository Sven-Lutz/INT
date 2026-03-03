from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyqtgraph as pg
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt
from PySide6.QtGui import QLinearGradient, QColor, QBrush

@dataclass
class TelemetrySample:
    t: float
    step: str
    flow: Optional[float]
    p1: Optional[float]
    p2: Optional[float]
    valves: str

class MonitorTab(Qtw.QFrame):
    def __init__(self, log_dir: Path, *, max_points: int = 2000) -> None:
        super().__init__()
        self._max_points = int(max_points)
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._t0: Optional[float] = None
        self._csv_fp = None
        self._csv_w = None

        self._t = []
        self._flow = []
        self._p1 = []
        self._p2 = []

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(15)

        pg.setConfigOptions(antialias=True)
        pg.setConfigOption('background', '#090B10')
        pg.setConfigOption('foreground', '#94A3B8')

        self.plot_flow = pg.PlotWidget(title="Flow Rate (mL/min)")
        self.plot_p = pg.PlotWidget(title="Pressure Telemetry")

        self.plot_flow.showGrid(x=False, y=True, alpha=0.1)
        self.plot_p.showGrid(x=False, y=True, alpha=0.1)

        # 🚀 FIX: Verhindert, dass das Diagramm bei 0.0 auf 15 Nachkommastellen zoomt 🚀
        self.plot_flow.getViewBox().setLimits(minYRange=1.0, minXRange=10.0)
        self.plot_p.getViewBox().setLimits(minYRange=100.0, minXRange=10.0)

        # 🚀 CHROMA GRADIENT: Neon Pink zu Transparent für Flow 🚀
        grad_flow = QLinearGradient(0, 0, 0, 1)
        grad_flow.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
        grad_flow.setColorAt(0.0, QColor(236, 72, 153, 100)) # Pink
        grad_flow.setColorAt(1.0, QColor(236, 72, 153, 0))
        brush_flow = QBrush(grad_flow)

        pen_flow = pg.mkPen(color='#EC4899', width=2.5) # Neon Pink Line
        self.curve_flow = self.plot_flow.plot([], [], pen=pen_flow, fillLevel=0, brush=brush_flow)

        # 🚀 CHROMA GRADIENT: Violett/Cyan für Pressure 🚀
        grad_p1 = QLinearGradient(0, 0, 0, 1)
        grad_p1.setCoordinateMode(QLinearGradient.ObjectBoundingMode)
        grad_p1.setColorAt(0.0, QColor(139, 92, 246, 80)) # Purple
        grad_p1.setColorAt(1.0, QColor(139, 92, 246, 0))
        brush_p1 = QBrush(grad_p1)

        pen_p1 = pg.mkPen(color='#8B5CF6', width=2.5) # Purple Line
        self.curve_p1 = self.plot_p.plot([], [], pen=pen_p1, fillLevel=0, brush=brush_p1, name="P1 Main")

        pen_p2 = pg.mkPen(color='#00E5FF', width=2, style=Qt.DashLine) # Cyan Line
        self.curve_p2 = self.plot_p.plot([], [], pen=pen_p2, name="P2 Backwash")

        root.addWidget(self.plot_flow, 1)
        root.addWidget(self.plot_p, 1)

        self.lbl = Qtw.QLabel("Telemetry idle.")
        self.lbl.setStyleSheet("color: #64748B; font-family: 'Consolas', monospace; font-size: 11px;")
        self.lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self.lbl)

    def start_logging(self, run_name_prefix: str = "run") -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self._log_dir / f"{run_name_prefix}_{ts}_telemetry.csv"
        self._csv_fp = open(path, "w", newline="", encoding="utf-8")
        self._csv_w = csv.writer(self._csv_fp)
        self._csv_w.writerow(["t_unix", "t_s", "step", "flow", "p1_meas", "p2_meas", "valves"])
        self._csv_fp.flush()
        self.lbl.setText(f"Logging to: {path}")

        self._t0 = None
        self._t.clear()
        self._flow.clear()
        self._p1.clear()
        self._p2.clear()

    def stop_logging(self) -> None:
        try:
            if self._csv_fp:
                self._csv_fp.flush()
                self._csv_fp.close()
        finally:
            self._csv_fp = None
            self._csv_w = None
            self.lbl.setText("Telemetry idle.")

    def ingest_telemetry(self, payload: dict) -> None:
        t = payload.get("t", payload.get("time", time.time()))
        try:
            t = float(t)
        except Exception:
            t = time.time()

        step = str(payload.get("step", payload.get("state", "—")))
        valves = str(payload.get("valves", payload.get("valve_state", "—")))

        flow = _to_float(payload.get("flow", payload.get("flow_ml_min")))
        p1 = _to_float(payload.get("p1_meas", payload.get("p1")))
        p2 = _to_float(payload.get("p2_meas", payload.get("p2")))

        if self._t0 is None:
            self._t0 = t
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

        xf = self._t
        yf = [_nan(v) for v in self._flow]
        y1 = [_nan(v) for v in self._p1]
        y2 = [_nan(v) for v in self._p2]

        self.curve_flow.setData(xf, yf)
        self.curve_p1.setData(xf, y1)
        self.curve_p2.setData(xf, y2)

        if self._csv_w and self._csv_fp:
            self._csv_w.writerow([t, ts, step, flow, p1, p2, valves])
            self._csv_fp.flush()

def _to_float(x) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except Exception:
        return None

def _nan(x: Optional[float]) -> float:
    return float("nan") if x is None else float(x)