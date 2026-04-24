from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import numpy as np
import pyqtgraph as pg
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont

from src.gui.frames.analysis_frame import parse_telemetry_csv, TelemetryRun
from src.utils.path_utils import project_root

logger = logging.getLogger(__name__)

_PALETTE = [
    "#8B5CF6", "#10B981", "#F59E0B", "#0EA5E9",
    "#EC4899", "#EF4444", "#A3E635", "#38BDF8",
]

_BTN_STYLE = (
    "QPushButton { background: #111827; color: #10B981; border: 1px solid #10B981; "
    "border-radius: 3px; padding: 4px 8px; font-family: 'Consolas'; font-size: 10px; "
    "font-weight: bold; } "
    "QPushButton:hover { background: #10B981; color: #000; } "
    "QPushButton:disabled { background: #050914; color: #334155; border-color: #1E293B; }"
)


class CompareFrame(Qtw.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._runs: List[TelemetryRun] = []

        splitter = Qtw.QSplitter(Qt.Orientation.Horizontal)
        outer = Qtw.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(splitter)

        # ── LEFT PANEL ────────────────────────────────────────────────────
        left = Qtw.QFrame()
        left_lay = Qtw.QVBoxLayout(left)
        left_lay.setContentsMargins(8, 8, 8, 8)
        left_lay.setSpacing(6)

        lbl = Qtw.QLabel("RUN LIBRARY")
        lbl.setStyleSheet(
            "color: #0EA5E9; font-family: 'Consolas'; font-size: 10px; "
            "font-weight: bold; letter-spacing: 1px;")
        left_lay.addWidget(lbl)

        self.run_list = Qtw.QListWidget()
        self.run_list.setSelectionMode(
            Qtw.QAbstractItemView.SelectionMode.MultiSelection)
        self.run_list.setStyleSheet(
            "QListWidget { background: #090B10; color: #94A3B8; "
            "font-family: 'Consolas'; font-size: 10px; border: 1px solid #1E293B; }"
            "QListWidget::item:selected { background: #1E3A5F; color: #E2E8F0; }"
            "QListWidget::item:hover { background: #111827; }")
        left_lay.addWidget(self.run_list, 1)

        btn_row = Qtw.QHBoxLayout()
        self.btn_refresh = Qtw.QPushButton("REFRESH")
        self.btn_compare = Qtw.QPushButton("COMPARE SELECTED")
        for b in (self.btn_refresh, self.btn_compare):
            b.setStyleSheet(_BTN_STYLE)
        btn_row.addWidget(self.btn_refresh)
        btn_row.addWidget(self.btn_compare)
        left_lay.addLayout(btn_row)

        self.kpi_table = Qtw.QTableWidget()
        self.kpi_table.setMinimumHeight(140)
        self.kpi_table.setStyleSheet(
            "QTableWidget { background: #090B10; color: #94A3B8; "
            "font-family: 'Consolas'; font-size: 9px; "
            "gridline-color: #1E293B; border: 1px solid #1E293B; }"
            "QHeaderView::section { background: #111827; color: #0EA5E9; "
            "font-size: 9px; font-weight: bold; border: none; padding: 2px; }")
        left_lay.addWidget(self.kpi_table)

        self.lbl_status = Qtw.QLabel("Select runs, then click COMPARE SELECTED.")
        self.lbl_status.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 9px;")
        self.lbl_status.setWordWrap(True)
        left_lay.addWidget(self.lbl_status)

        left.setFixedWidth(290)
        splitter.addWidget(left)

        # ── RIGHT PANEL (plots) ────────────────────────────────────────────
        right = Qtw.QFrame()
        right_lay = Qtw.QVBoxLayout(right)
        right_lay.setContentsMargins(0, 4, 0, 0)
        right_lay.setSpacing(2)

        pg.setConfigOptions(antialias=True, useOpenGL=False)

        self.plot_p = pg.PlotWidget()
        self.plot_v = pg.PlotWidget()
        self.plot_vp = pg.PlotWidget()

        self._style_plot(self.plot_p, "Pressure [mbar]")
        self._style_plot(self.plot_v, "Volume [mL]")
        self._style_plot(self.plot_vp, "Volume [mL]",
                         x_label="Pressure [mbar]", show_x_label=True)

        for pw in (self.plot_p, self.plot_v):
            pw.addLegend(offset=(60, 10), labelTextSize="7pt",
                         brush=QColor(15, 23, 42, 200), pen=QColor(30, 41, 59))

        right_lay.addWidget(self.plot_p, stretch=2)
        right_lay.addWidget(self.plot_v, stretch=2)
        right_lay.addWidget(self.plot_vp, stretch=2)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)

        self.btn_refresh.clicked.connect(self._refresh_run_list)
        self.btn_compare.clicked.connect(self._run_comparison)
        self._refresh_run_list()

    # ── helpers ──────────────────────────────────────────────────────────

    def _style_plot(self, pw: pg.PlotWidget, y_label: str,
                    x_label: str = "Time [s]", show_x_label: bool = False):
        pw.setBackground("#090B10")
        pw.showGrid(x=True, y=True, alpha=0.06)
        pw.enableAutoRange()
        ax_l = pw.getAxis("left")
        ax_l.setLabel(y_label, color="#94A3B8")
        ax_l.setTickFont(QFont("Consolas", 7))
        ax_l.setTextPen("#64748B")
        ax_l.setWidth(60)
        ax_b = pw.getAxis("bottom")
        ax_b.setTickFont(QFont("Consolas", 7))
        ax_b.setTextPen("#64748B")
        if show_x_label:
            ax_b.setLabel(x_label, color="#94A3B8")
        else:
            ax_b.setStyle(showValues=False)
            ax_b.setHeight(0)

    # ── slots ─────────────────────────────────────────────────────────────

    @Slot()
    def _refresh_run_list(self):
        self.run_list.clear()
        try:
            runs_dir = project_root() / "logs" / "runs"
            if not runs_dir.is_dir():
                self.lbl_status.setText("No runs directory found yet.")
                return
            dirs = sorted(
                (d for d in runs_dir.iterdir() if (d / "telemetry.csv").is_file()),
                reverse=True,
            )
            for d in dirs:
                item = Qtw.QListWidgetItem(d.name)
                item.setData(Qt.ItemDataRole.UserRole, str(d / "telemetry.csv"))
                self.run_list.addItem(item)
            self.lbl_status.setText(
                f"{len(dirs)} run(s) found. Select to compare.")
        except Exception as exc:
            logger.warning("CompareFrame: could not list runs: %s", exc)
            self.lbl_status.setText(f"Error: {exc}")

    @Slot()
    def _run_comparison(self):
        selected = self.run_list.selectedItems()
        if not selected:
            self.lbl_status.setText("No runs selected.")
            return

        self.plot_p.clear()
        self.plot_v.clear()
        self.plot_vp.clear()
        self._runs.clear()

        for pw in (self.plot_p, self.plot_v):
            pw.addLegend(offset=(60, 10), labelTextSize="7pt",
                         brush=QColor(15, 23, 42, 200), pen=QColor(30, 41, 59))

        kpi_data: list[dict] = []

        for i, item in enumerate(selected):
            csv_path = item.data(Qt.ItemDataRole.UserRole)
            if not csv_path:
                continue
            try:
                run = parse_telemetry_csv(csv_path)
            except Exception as exc:
                logger.warning("CompareFrame: could not parse %s: %s", csv_path, exc)
                continue

            self._runs.append(run)
            color = _PALETTE[i % len(_PALETTE)]
            name = item.text()[:24]
            t = run.time_s - run.time_s[0]

            self.plot_p.plot(t, run.pressure_mbar,
                             pen=pg.mkPen(color, width=2), name=name)
            self.plot_v.plot(t, run.volume_ml,
                             pen=pg.mkPen(color, width=2), name=name)
            self.plot_vp.plot(
                run.pressure_mbar, run.volume_ml,
                pen=pg.mkPen(color, width=1.5,
                              style=Qt.PenStyle.SolidLine))

            max_p = float(np.max(run.pressure_mbar))
            max_v = float(np.max(run.volume_ml))
            kpi_data.append({
                "run": name,
                "dur": f"{run.duration_s:.1f} s",
                "max_p": f"{max_p:.1f}",
                "max_v": f"{max_v:.1f}",
                "pts": f"{run.n_points:,}",
            })

        self._populate_kpi_table(kpi_data)
        self.lbl_status.setText(
            f"Showing {len(self._runs)} run(s). "
            "Top: P vs time | Mid: V vs time | Bot: V vs P")

    def _populate_kpi_table(self, kpi_data: list):
        cols = ["Run", "Duration", "Max P [mbar]", "Max V [mL]", "Points"]
        self.kpi_table.setColumnCount(len(cols))
        self.kpi_table.setHorizontalHeaderLabels(cols)
        self.kpi_table.setRowCount(len(kpi_data))
        self.kpi_table.horizontalHeader().setStretchLastSection(False)
        for r, row in enumerate(kpi_data):
            for c, val in enumerate(row.values()):
                cell = Qtw.QTableWidgetItem(val)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.kpi_table.setItem(r, c, cell)
        self.kpi_table.resizeColumnsToContents()

    def refresh(self):
        """Public method to refresh run list (called when a new run completes)."""
        self._refresh_run_list()
