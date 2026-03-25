from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont, QColor


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
    """Parse a telemetry CSV with columns t_s, p1_meas, volume_ml.

    Lines starting with '#' are treated as comments and skipped.
    Returns a TelemetryRun dataclass.  Raises ValueError on total failure.
    """
    times: list[float] = []
    pressures: list[float] = []
    volumes: list[float] = []
    skipped = 0

    path = Path(filepath)
    with path.open(mode="r", encoding="utf-8") as fh:
        # Strip comment lines before handing to DictReader
        clean_lines = (line for line in fh if not line.startswith("#"))
        reader = csv.DictReader(clean_lines)
        for row in reader:
            try:
                t = float(row.get("t_s") or 0)
                p = float(row.get("p1_meas") or 0)
                v = float(row.get("volume_ml") or 0)
            except (ValueError, TypeError):
                skipped += 1
                continue
            times.append(t)
            pressures.append(p)
            volumes.append(v)

    if not times:
        raise ValueError(f"No valid data rows found in {path.name}")

    return TelemetryRun(
        filepath=path,
        time_s=np.asarray(times, dtype=np.float64),
        pressure_mbar=np.asarray(pressures, dtype=np.float64),
        volume_ml=np.asarray(volumes, dtype=np.float64),
        skipped_rows=skipped,
    )


# ─── COLOUR PALETTE ───────────────────────────────────────────────────────────

class _Palette:
    """Central colour constants — change once, update everywhere."""
    BG_DEEP    = "#050914"
    BG_PANEL   = "#0A1020"
    BG_PLOT    = "#090F1A"
    GRID       = "#1A2340"
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


# ─── STYLESHEET FRAGMENTS ─────────────────────────────────────────────────────

_BTN_STYLE = f"""
QPushButton {{
    background-color: {PAL.BG_PANEL};
    color: {PAL.ACCENT_2};
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 12px;
    font-weight: 600;
    padding: 7px 14px;
    border: 1px solid {PAL.BORDER};
    border-radius: 3px;
}}
QPushButton:hover {{
    background-color: {PAL.HOVER_BG};
    color: {PAL.WHITE};
    border-color: {PAL.ACCENT_2};
}}
QPushButton:pressed {{
    background-color: {PAL.ACCENT_2};
    color: {PAL.BG_DEEP};
}}
QPushButton:disabled {{
    color: {PAL.TEXT_DIM};
    border-color: {PAL.BG_PANEL};
}}
"""

_LABEL_DIM = f"color: {PAL.TEXT_DIM}; font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px;"
_LABEL_MID = f"color: {PAL.TEXT_MID}; font-family: 'JetBrains Mono', 'Consolas', monospace; font-size: 11px;"


# ─── CROSSHAIR OVERLAY ────────────────────────────────────────────────────────

class _Crosshair:
    """Vertical-line + readout that follows the mouse across the plot."""

    def __init__(self, plot_item: pg.PlotItem, vb_secondary: pg.ViewBox):
        self._plot = plot_item
        self._vb2 = vb_secondary

        pen = pg.mkPen(color=PAL.TEXT_DIM, width=1, style=Qt.PenStyle.DashLine)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pen)
        plot_item.addItem(self.vline, ignoreBounds=True)

        self.label = pg.TextItem(anchor=(0, 1), color=PAL.TEXT_MID)
        self.label.setFont(QFont("JetBrains Mono", 9))
        plot_item.addItem(self.label, ignoreBounds=True)

        self._curves_primary: list[pg.PlotDataItem] = []
        self._curves_secondary: list[pg.PlotDataItem] = []

        # Connect mouse-move on the scene
        self._proxy = pg.SignalProxy(
            plot_item.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse
        )

    def register(
        self,
        primary: Sequence[pg.PlotDataItem],
        secondary: Sequence[pg.PlotDataItem],
    ):
        self._curves_primary = list(primary)
        self._curves_secondary = list(secondary)

    def _on_mouse(self, args):
        pos = args[0]
        if not self._plot.sceneBoundingRect().contains(pos):
            return
            
        # BUGFIX (Fehler 1 & 6): Prüfen, ob die ViewBox existiert
        if self._plot.vb is None:
            return

        mouse_point = self._plot.vb.mapSceneToView(pos)
        x = mouse_point.x()
        self.vline.setPos(x)

        parts = [f"t = {x:.3f} s"]
        
        # BUGFIX (Fehler 2, 3, 4, 5): Prüfen, ob xd und yd existieren
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
    """Post-run telemetry analysis panel with dual-axis plotting."""

    # Emitted after a successful load so parent widgets can react.
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

        # Primary plot (left axis — pressure)
        self.plot = self.gfx.addPlot(row=0, col=0)  # type: ignore[attr-defined]
        self.plot.setTitle(
            "POST-RUN ANALYSIS",
            color=PAL.TEXT_HI, size="11pt",
        )
        self.plot.showGrid(x=True, y=True, alpha=0.08)
        self.plot.setLabel("bottom", "Time", units="s", color=PAL.TEXT_MID)
        self.plot.setLabel("left", "Pressure", units="mbar", color=PAL.ACCENT_1)
        self.plot.getAxis("left").setPen(pg.mkPen(PAL.ACCENT_1, width=1))
        self.plot.getAxis("bottom").setPen(pg.mkPen(PAL.TEXT_DIM, width=1))

        # Secondary axis (right — volume)
        self.plot.showAxis("right")  # Die eingebaute rechte Achse aktivieren!
        self.axis_vol = self.plot.getAxis("right")
        self.axis_vol.setLabel("Volume", units="ml", color=PAL.ACCENT_2)
        self.axis_vol.setPen(pg.mkPen(PAL.ACCENT_2, width=1))

        self.vb_vol = pg.ViewBox()
        self.plot.scene().addItem(self.vb_vol)
        self.axis_vol.linkToView(self.vb_vol)
        self.vb_vol.setXLink(self.plot)

        self.plot.vb.sigResized.connect(self._sync_viewboxes)

        # Crosshair
        self._crosshair = _Crosshair(self.plot, self.vb_vol)

        # ── STATS BAR ─────────────────────────────────────────────────────
        self.lbl_stats = Qtw.QLabel("")
        self.lbl_stats.setStyleSheet(_LABEL_MID)
        self.lbl_stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.lbl_stats)

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_button(text: str) -> Qtw.QPushButton:
        btn = Qtw.QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(_BTN_STYLE)
        return btn

    # ── view-sync ──────────────────────────────────────────────────────────

    @Slot()
    def _sync_viewboxes(self):
        """Keep the secondary ViewBox geometry in sync with the primary."""
        self.vb_vol.setGeometry(self.plot.vb.sceneBoundingRect())
        self.vb_vol.linkedViewChanged(self.plot.vb, self.vb_vol.XAxis)

    # ── plotting ───────────────────────────────────────────────────────────

    def _plot_run(self, run: TelemetryRun):
        """Render a TelemetryRun onto the dual-axis graph."""
        # 1. Clear previous
        self.plot.clear()
        self.vb_vol.clear()

        # 2. Rebuild legend (avoids duplication bug)
        if self.plot.legend is not None:
            self.plot.legend.scene().removeItem(self.plot.legend)
        self.plot.addLegend(
            offset=(10, 10),
            brush=pg.mkBrush(PAL.BG_PANEL + "CC"),
            pen=pg.mkPen(PAL.BORDER),
            labelTextColor=PAL.TEXT_MID,
        )

        # 3. Pressure curve (primary axis)
        pen_p = pg.mkPen(color=PAL.ACCENT_1, width=2)
        curve_p = self.plot.plot(
            run.time_s, run.pressure_mbar,
            pen=pen_p, name="Pressure (mbar)",
        )

        # 4. Volume curve (secondary axis)
        pen_v = pg.mkPen(color=PAL.ACCENT_2, width=2)
        curve_v = pg.PlotDataItem(run.time_s, run.volume_ml, pen=pen_v)
        self.vb_vol.addItem(curve_v)
        self.plot.legend.addItem(curve_v, "Volume (ml)")

        # 5. Auto-range both axes
        self.plot.enableAutoRange(axis=pg.ViewBox.YAxis)
        self.vb_vol.enableAutoRange(axis=pg.ViewBox.YAxis)

        # 6. Force geometry sync now (fixes first-render blank right axis)
        self._sync_viewboxes()
        
        # NEU: Das Fadenkreuz-Overlay in den Vordergrund zwingen
        self._crosshair.vline.setZValue(10)
        self._crosshair.label.setZValue(10)

        # 7. Register crosshair curves
        self._crosshair.register(primary=[curve_p], secondary=[curve_v])

        # 8. Re-add crosshair items (they were cleared)
        self.plot.addItem(self._crosshair.vline, ignoreBounds=True)
        self.plot.addItem(self._crosshair.label, ignoreBounds=True)

    # ── slots ──────────────────────────────────────────────────────────────

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
            self.lbl_status.setStyleSheet(f"color: {PAL.ACCENT_WARN}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
            return

        self._run = run
        self._plot_run(run)
        self.lbl_status.setText(f"✓  {run.filepath.name}")
        self.lbl_status.setStyleSheet(f"color: {PAL.ACCENT_2}; font-family: 'JetBrains Mono', monospace; font-size: 11px;")
        self.lbl_stats.setText(run.summary)
        self.btn_export_png.setEnabled(True)
        self.btn_export_csv.setEnabled(True)
        self.dataLoaded.emit(run)

    @Slot()
    def _export_png(self):
        if self._run is None:
            return
        default = self._run.filepath.with_suffix(".png")
        path, _ = Qtw.QFileDialog.getSaveFileName(
            self, "Export Plot as PNG", str(default), "PNG Image (*.png)"
        )
        if path:
            exporter = pyqtgraph.exporters.ImageExporter(self.plot)
            exporter.parameters()["width"] = 2400
            exporter.export(path)
            self.lbl_status.setText(f"Exported → {Path(path).name}")

    @Slot()
    def _export_csv(self):
        if self._run is None:
            return
        default = self._run.filepath.with_name(self._run.filepath.stem + "_export.csv")
        path, _ = Qtw.QFileDialog.getSaveFileName(
            self, "Export Data as CSV", str(default), "CSV Files (*.csv)"
        )
        if not path:
            return
        run = self._run
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["t_s", "p1_meas_mbar", "volume_ml"])
            for i in range(run.n_points):
                writer.writerow([run.time_s[i], run.pressure_mbar[i], run.volume_ml[i]])
        self.lbl_status.setText(f"Exported → {Path(path).name}")


# ─── STANDALONE LAUNCHER ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    app = Qtw.QApplication(sys.argv)
    app.setStyle("Fusion")
    win = Qtw.QMainWindow()
    win.setWindowTitle("Telemetry Analysis")
    win.resize(1200, 700)
    win.setCentralWidget(AnalysisFrame())
    win.show()
    sys.exit(app.exec())