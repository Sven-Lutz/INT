from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont


# ─── DATA MODEL ────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class TelemetryRun:
    """Immutable container for one loaded CSV run."""
    filepath: Path
    time_s: np.ndarray
    pressure_mbar: np.ndarray
    volume_ml: np.ndarray
    skipped_rows: int = 0

    @property
    def n_points(self) -> int:
        return len(self.time_s)

    @property
    def duration_s(self) -> float:
        return float(self.time_s[-1] - self.time_s[0]) if self.n_points > 1 else 0.0

    @property
    def summary(self) -> str:
        return (
            f"{self.filepath.name}  ·  {self.n_points:,} pts  ·  "
            f"{self.duration_s:.1f} s  ·  "
            f"P [{np.min(self.pressure_mbar):.1f} – {np.max(self.pressure_mbar):.1f}] mbar  ·  "
            f"V [{np.min(self.volume_ml):.1f} – {np.max(self.volume_ml):.1f}] ml"
            + (f"  ·  ⚠ {self.skipped_rows} rows skipped" if self.skipped_rows else "")
        )

def parse_telemetry_csv(filepath: str | Path) -> TelemetryRun:
    """Bulletproof CSV Parser: Handles German Excel (; and ,) and standard formats."""
    times: list[float] = []
    pressures: list[float] = []
    volumes: list[float] = []
    skipped = 0

    path = Path(filepath)
    # utf-8-sig entfernt unsichtbare Zeichen (BOM), die Excel gerne hinzufügt
    with path.open(mode="r", encoding="utf-8-sig") as fh:
        # Preamble/Kommentare filtern
        clean_lines = [line for line in fh if not line.startswith("#") and line.strip()]
        
        if not clean_lines:
            raise ValueError(f"File {path.name} is empty or only contains comments.")
            
        # 🚀 BUGFIX: Erkennung des deutschen Excel-Formats (; vs ,)
        delimiter = ";" if ";" in clean_lines[0] else ","
        reader = csv.DictReader(clean_lines, delimiter=delimiter)
        
        current_t = 0.0
        
        for row in reader:
            try:
                # 🚀 BUGFIX: Hilfsfunktion für Komma-Dezimalzahlen (z.B. "12,5" -> 12.5)
                def parse_val(possible_keys):
                    for k in possible_keys:
                        if k in row and row[k] and str(row[k]).strip():
                            val_str = str(row[k]).strip().replace(",", ".")
                            return float(val_str)
                    return 0.0

                # 1. TIME: Akkumuliert dt_s (Alter Logger) oder nimmt t_s (Neuer Logger)
                if "t_s" in row and str(row["t_s"]).strip():
                    t = parse_val(["t_s"])
                elif "dt_s" in row and str(row["dt_s"]).strip():
                    current_t += parse_val(["dt_s"])
                    t = current_t
                else:
                    t = parse_val(["t"])

                # 2. PRESSURE: Fallback für verschiedene Logger-Versionen
                p = parse_val(["pressure_meas_mbar", "p1_meas_mbar", "p1_meas"])
                
                # 3. VOLUME: Fallback für verschiedene Logger-Versionen
                v = parse_val(["volume_ml_est", "volume_ml"])

            except (ValueError, TypeError):
                skipped += 1
                continue

            times.append(t)
            pressures.append(p)
            volumes.append(v)

    if not times:
        raise ValueError(f"No valid data rows found in {path.name}. Check headers.")

    return TelemetryRun(
        filepath=path,
        time_s=np.asarray(times, dtype=np.float64),
        pressure_mbar=np.asarray(pressures, dtype=np.float64),
        volume_ml=np.asarray(volumes, dtype=np.float64),
        skipped_rows=skipped,
    )


# ─── COLOUR PALETTE ───────────────────────────────────────────────────────────

class _Palette:
    BG_DEEP    = "#050914"
    BG_PANEL   = "#0A1020"
    BG_PLOT    = "#090F1A"
    BORDER     = "#162040"
    TEXT_DIM   = "#4A5E80"
    TEXT_MID   = "#8095B8"
    TEXT_HI    = "#C8D6E8"
    ACCENT_1   = "#8B5CF6"   # violet — pressure
    ACCENT_2   = "#00E5FF"   # cyan — volume
    ACCENT_WARN = "#F59E0B"  # amber — warnings
    HOVER_BG   = "#111D35"
    WHITE      = "#FFFFFF"

PAL = _Palette

_BTN_STYLE = f"""
QPushButton {{
    background-color: {PAL.BG_PANEL}; color: {PAL.ACCENT_2};
    font-family: 'Consolas', monospace; font-size: 12px; font-weight: 600;
    padding: 7px 14px; border: 1px solid {PAL.BORDER}; border-radius: 3px;
}}
QPushButton:hover {{ background-color: {PAL.HOVER_BG}; color: {PAL.WHITE}; border-color: {PAL.ACCENT_2}; }}
QPushButton:disabled {{ color: {PAL.TEXT_DIM}; border-color: {PAL.BG_PANEL}; }}
"""
_LABEL_DIM = f"color: {PAL.TEXT_DIM}; font-family: 'Consolas', monospace; font-size: 11px;"
_LABEL_MID = f"color: {PAL.TEXT_MID}; font-family: 'Consolas', monospace; font-size: 11px;"


# ─── CROSSHAIR OVERLAY ────────────────────────────────────────────────────────

class _Crosshair:
    def __init__(self, plot_item_primary: pg.PlotItem, plot_item_secondary: pg.PlotItem):
        self._plot = plot_item_primary
        self._plot_sec = plot_item_secondary

        pen = pg.mkPen(color=PAL.TEXT_DIM, width=1, style=Qt.PenStyle.DashLine)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        
        self.label = pg.TextItem(anchor=(0, 1), color=PAL.TEXT_MID)
        self.label.setFont(QFont("Consolas", 9))
        
        self._curves_primary: list[pg.PlotDataItem] = []
        self._curves_secondary: list[pg.PlotDataItem] = []

        self._proxy = pg.SignalProxy(self._plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse)

    def register(self, primary: Sequence[pg.PlotDataItem], secondary: Sequence[pg.PlotDataItem]):
        self._curves_primary = list(primary)
        self._curves_secondary = list(secondary)

    def _on_mouse(self, args):
        pos = args[0]
        if not self._plot.sceneBoundingRect().contains(pos):
            return
            
        if self._plot.vb is None:
            return

        mouse_point = self._plot.vb.mapSceneToView(pos)
        x = mouse_point.x()
        self.vline.setPos(x)

        parts = [f"t = {x:.3f} s"]
        
        for c in self._curves_primary:
            xd, yd = c.getData()
            if xd is not None and yd is not None and len(xd) > 0 and len(yd) > 0:
                idx = int(np.clip(np.searchsorted(xd, x), 0, len(yd) - 1))
                parts.append(f"P = {yd[idx]:.2f} mbar")
                
        for c in self._curves_secondary:
            xd, yd = c.getData()
            if xd is not None and yd is not None and len(xd) > 0 and len(yd) > 0:
                idx = int(np.clip(np.searchsorted(xd, x), 0, len(yd) - 1))
                parts.append(f"V = {yd[idx]:.2f} ml")

        self.label.setText("  ".join(parts))
        self.label.setPos(mouse_point.x(), self._plot.vb.viewRange()[1][1])


# ─── MAIN WIDGET ───────────────────────────────────────────────────────────────

class AnalysisFrame(Qtw.QFrame):
    dataLoaded = Signal(TelemetryRun)

    def __init__(self, parent: Qtw.QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {PAL.BG_DEEP};")
        self._run: TelemetryRun | None = None

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(8)

        # ── TOOLBAR ────────────────────────────────────────────────────────
        toolbar = Qtw.QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_load = self._make_button("▸  LOAD CSV")
        self.btn_load.clicked.connect(self._on_load)

        self.btn_export_png = self._make_button("⎙  PNG")
        self.btn_export_png.setEnabled(False)
        self.btn_export_png.clicked.connect(self._export_png)

        self.btn_export_csv = self._make_button("↓  CSV")
        self.btn_export_csv.setEnabled(False)
        self.btn_export_csv.clicked.connect(self._export_csv)

        self.lbl_status = Qtw.QLabel("No file loaded")
        self.lbl_status.setStyleSheet(_LABEL_DIM)

        toolbar.addWidget(self.btn_load)
        toolbar.addWidget(self.btn_export_png)
        toolbar.addWidget(self.btn_export_csv)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.lbl_status, stretch=1)
        root.addLayout(toolbar)

        # ── PLOT AREA ──────────────────────────────────────────────────────
        pg.setConfigOptions(antialias=True)

        self.gfx = pg.GraphicsLayoutWidget()
        self.gfx.setBackground(PAL.BG_PLOT)
        root.addWidget(self.gfx, stretch=1)

        # 1. GRAPH: DRUCK (Oben)
        self.plot_p = self.gfx.addPlot(row=0, col=0) # type: ignore[attr-defined]
        self.plot_p.setTitle("POST-RUN ANALYSIS: PRESSURE", color=PAL.TEXT_HI, size="11pt")
        self.plot_p.showGrid(x=True, y=True, alpha=0.08)
        
        # 🚀 BUGFIX: "GBAR" verhindern, indem wir 'units' weglassen und es hart in den Text schreiben!
        self.plot_p.setLabel("left", "Pressure [mbar]", color=PAL.ACCENT_1)
        self.plot_p.getAxis("left").setPen(pg.mkPen(PAL.ACCENT_1, width=1))

        # 2. GRAPH: VOLUMEN (Unten)
        self.plot_v = self.gfx.addPlot(row=1, col=0) # type: ignore[attr-defined]
        self.plot_v.setTitle("VOLUME", color=PAL.TEXT_HI, size="11pt")
        self.plot_v.showGrid(x=True, y=True, alpha=0.08)
        
        # 🚀 BUGFIX: Auch hier Einheiten fest in den Text schreiben!
        self.plot_v.setLabel("bottom", "Time [s]", color=PAL.TEXT_MID)
        self.plot_v.setLabel("left", "Volume [ml]", color=PAL.ACCENT_2)
        self.plot_v.getAxis("left").setPen(pg.mkPen(PAL.ACCENT_2, width=1))
        self.plot_v.getAxis("bottom").setPen(pg.mkPen(PAL.TEXT_DIM, width=1))

        self.plot_v.setXLink(self.plot_p)

        self._crosshair = _Crosshair(self.plot_p, self.plot_v)

        self.lbl_stats = Qtw.QLabel("")
        self.lbl_stats.setStyleSheet(_LABEL_MID)
        self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.lbl_stats)

    @staticmethod
    def _make_button(text: str) -> Qtw.QPushButton:
        btn = Qtw.QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_BTN_STYLE)
        return btn

    def _plot_run(self, run: TelemetryRun):
        self.plot_p.clear()
        self.plot_v.clear()

        pen_p = pg.mkPen(color=PAL.ACCENT_1, width=2)
        curve_p = self.plot_p.plot(run.time_s, run.pressure_mbar, pen=pen_p, name="Pressure")

        pen_v = pg.mkPen(color=PAL.ACCENT_2, width=2)
        curve_v = self.plot_v.plot(run.time_s, run.volume_ml, pen=pen_v, name="Volume")

        self.plot_p.enableAutoRange(axis=pg.ViewBox.YAxis)
        self.plot_v.enableAutoRange(axis=pg.ViewBox.YAxis)
        self.plot_p.autoRange()
        self.plot_v.autoRange()

        self._crosshair.register(primary=[curve_p], secondary=[curve_v])
        self.plot_p.addItem(self._crosshair.vline, ignoreBounds=True)
        self.plot_p.addItem(self._crosshair.label, ignoreBounds=True)

    @Slot()
    def _on_load(self):
        base = Path(__file__).resolve().parents[3] / "logs"
        if not base.is_dir():
            base = Path.home()

        path, _ = Qtw.QFileDialog.getOpenFileName(
            self, "Select Telemetry CSV", str(base), "CSV Files (*.csv)"
        )
        if not path:
            return

        self.lbl_status.setText(f"Loading {Path(path).name} …")
        self.lbl_status.setStyleSheet(_LABEL_MID)

        try:
            run = parse_telemetry_csv(path)
        except Exception as exc:
            self.lbl_status.setText(f"✗  {exc}")
            self.lbl_status.setStyleSheet(f"color: {PAL.ACCENT_WARN}; font-family: 'Consolas', monospace; font-size: 11px;")
            return

        self._run = run
        self._plot_run(run)
        self.lbl_status.setText(f"✓  {run.filepath.name}")
        self.lbl_status.setStyleSheet(f"color: {PAL.ACCENT_2}; font-family: 'Consolas', monospace; font-size: 11px;")
        self.lbl_stats.setText(run.summary)
        self.btn_export_png.setEnabled(True)
        self.btn_export_csv.setEnabled(True)
        self.dataLoaded.emit(run)

    @Slot()
    def _export_png(self):
        if self._run is None: return
        default = self._run.filepath.with_suffix(".png")
        path, _ = Qtw.QFileDialog.getSaveFileName(self, "Export Plot as PNG", str(default), "PNG Image (*.png)")
        if path:
            exporter = pyqtgraph.exporters.ImageExporter(self.gfx.scene())
            exporter.parameters()["width"] = 2400
            exporter.export(path)
            self.lbl_status.setText(f"Exported → {Path(path).name}")

    @Slot()
    def _export_csv(self):
        if self._run is None: return
        default = self._run.filepath.with_name(self._run.filepath.stem + "_export.csv")
        path, _ = Qtw.QFileDialog.getSaveFileName(self, "Export Data as CSV", str(default), "CSV Files (*.csv)")
        if not path: return
        run = self._run
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["t_s", "p1_meas_mbar", "volume_ml"])
            for i in range(run.n_points):
                writer.writerow([run.time_s[i], run.pressure_mbar[i], run.volume_ml[i]])
        self.lbl_status.setText(f"Exported → {Path(path).name}")