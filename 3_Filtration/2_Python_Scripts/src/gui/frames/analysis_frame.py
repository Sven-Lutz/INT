# src/gui/frames/analysis_frame.py
import logging
import os
import pandas as pd
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QBrush
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib as mpl

# Wir setzen globale Matplotlib-Styles für den Stealth-Look
mpl.rcParams['toolbar'] = 'None'  # Standard Toolbar weg
mpl.rcParams['font.family'] = 'Consolas'

logger = logging.getLogger(__name__)


class AnalysisFrame(Qtw.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.current_file_path = None

        # Main Layout
        self.main_layout = Qtw.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # 🚀 CUSTOM TOP BAR (STEALTH LOOK)
        self.top_bar = Qtw.QFrame()
        self.top_bar.setFixedHeight(60)
        self.top_bar.setStyleSheet("background-color: #050914; border-bottom: 1px solid #1F2937;")
        top_lay = Qtw.QHBoxLayout(self.top_bar)
        top_lay.setContentsMargins(20, 0, 20, 0)

        self.btn_load = Qtw.QPushButton(" 📂 IMPORT DATA STREAM ")
        self.btn_load.setStyleSheet("""
            QPushButton { 
                background-color: #111827; color: #F8FAFC; border: 1px solid #334155; 
                font-family: 'Consolas'; font-weight: bold; border-radius: 4px; padding: 8px 15px;
            }
            QPushButton:hover { border: 1px solid #00E5FF; background-color: #1F2937; }
        """)
        self.btn_load.clicked.connect(self._load_file)

        self.lbl_file_info = Qtw.QLabel("SYSTEM READY // NO STREAM LOADED")
        self.lbl_file_info.setStyleSheet(
            "color: #64748B; font-family: 'Consolas'; font-size: 11px; letter-spacing: 1px;")

        self.btn_pdf = Qtw.QPushButton(" 📑 GENERATE PROTOCOL (.PDF) ")
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.setStyleSheet("""
            QPushButton { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC4899, stop:1 #8B5CF6);
                color: white; border: none; font-family: 'Consolas'; font-weight: bold; 
                border-radius: 4px; padding: 8px 15px;
            }
            QPushButton:hover { opacity: 0.8; }
            QPushButton:disabled { background: #1F2937; color: #4B5563; }
        """)
        self.btn_pdf.clicked.connect(self._generate_pdf)

        top_lay.addWidget(self.btn_load)
        top_lay.addWidget(self.lbl_file_info)
        top_lay.addStretch()
        top_lay.addWidget(self.btn_pdf)
        self.main_layout.addWidget(self.top_bar)

        # 🚀 GRAPH AREA
        self.figure = Figure(facecolor='#020617', tight_layout=True)
        self.canvas = FigureCanvas(self.figure)

        # Subplots erstellen
        self.ax_p = self.figure.add_subplot(211)
        self.ax_f = self.figure.add_subplot(212)

        self._apply_ax_style(self.ax_p, "PRESSURE TELEMETRY", "mbar")
        self._apply_ax_style(self.ax_f, "FLOW DYNAMICS", "ml/min")

        self.main_layout.addWidget(self.canvas)

    def _apply_ax_style(self, ax, title, ylabel):
        ax.set_facecolor('#020617')
        ax.set_title(title, color='#64748B', loc='left', fontsize=10, fontweight='bold', pad=10)
        ax.set_ylabel(ylabel, color='#64748B', fontsize=9)
        ax.tick_params(colors='#334155', labelsize=8)
        for spine in ax.spines.values():
            spine.set_color('#1F2937')
        ax.grid(True, color='#111827', linestyle='--', alpha=0.5)

    def _load_file(self):
        file_path, _ = Qtw.QFileDialog.getOpenFileName(self, "LOAD PELLIKAN LOG", "logs", "CSV Files (*.csv)")
        if not file_path: return

        try:
            self.data = pd.read_csv(file_path)
            self.current_file_path = file_path
            self._update_plots()
            self.lbl_file_info.setText(f"ACTIVE STREAM: {os.path.basename(file_path).upper()}")
            self.btn_pdf.setEnabled(True)
        except Exception as e:
            Qtw.QMessageBox.critical(self, "DATA ERROR", f"STREAM CORRUPTED: {e}")

    def _update_plots(self):
        self.ax_p.clear()
        self.ax_f.clear()

        # Mapping der Spalten
        cols = {c.lower(): c for c in self.data.columns}
        t = self.data[cols.get('time_s', self.data.columns[1])]

        # Plot Pressure mit Glow-Effekt
        p1 = self.data[cols.get('p1_mbar', self.data.columns[2])]
        p2 = self.data[cols.get('p2_mbar', self.data.columns[3])]

        self.ax_p.plot(t, p1, color='#EC4899', linewidth=2, label='MAIN_P1', zorder=3)
        self.ax_p.plot(t, p2, color='#8B5CF6', linewidth=2, label='BACKWASH_P2', zorder=3)

        # Subtile Glow-Füllung
        self.ax_p.fill_between(t, p1, color='#EC4899', alpha=0.05)

        # Plot Flow Dynamics
        flow = self.data[cols.get('flow_ml_min', self.data.columns[4])]
        self.ax_f.plot(t, flow, color='#00E5FF', linewidth=1.5, label='FLOW_RATE')
        self.ax_f.fill_between(t, flow, color='#00E5FF', alpha=0.1)

        # Style Re-Apply
        self._apply_ax_style(self.ax_p, "PRESSURE TELEMETRY", "mbar")
        self._apply_ax_style(self.ax_f, "FLOW DYNAMICS", "ml/min")
        self.ax_p.legend(facecolor='#050914', edgecolor='#1F2937', labelcolor='#F8FAFC', fontsize=8, framealpha=0.8)

        self.canvas.draw()

    def _generate_pdf(self):
        if self.data is None: return
        save_path, _ = Qtw.QFileDialog.getSaveFileName(self, "EXPORT PROTOCOL", "", "PDF Files (*.pdf)")
        if not save_path: return

        try:
            # Wir erstellen ein sauberes, weißes Dokument für den Druck
            # Aber mit den Neon-Farben für die Daten!
            fig_print = plt.figure(figsize=(8.5, 11))
            fig_print.suptitle(
                f"PELLIKAN OS // FILTRATION PROTOCOL\nSource: {os.path.basename(self.current_file_path)}",
                fontsize=14, fontweight='bold', fontfamily='Consolas')

            ax1 = fig_print.add_subplot(211)
            ax2 = fig_print.add_subplot(212)

            cols = {c.lower(): c for c in self.data.columns}
            t = self.data[cols.get('time_s', self.data.columns[1])]

            ax1.plot(t, self.data[cols.get('p1_mbar', self.data.columns[2])], color='#EC4899', label='P1')
            ax1.plot(t, self.data[cols.get('p2_mbar', self.data.columns[3])], color='#8B5CF6', label='P2')
            ax1.set_ylabel("Pressure (mbar)")
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            ax2.plot(t, self.data[cols.get('flow_ml_min', self.data.columns[4])], color='#00E5FF')
            ax2.set_ylabel("Flow (ml/min)")
            ax2.set_xlabel("Process Time (s)")
            ax2.grid(True, alpha=0.3)

            fig_print.tight_layout(pad=3.0)
            fig_print.savefig(save_path)
            plt.close(fig_print)

            Qtw.QMessageBox.information(self, "EXPORT SUCCESS", f"PROTOCOL SECURED AT:\n{save_path}")
        except Exception as e:
            Qtw.QMessageBox.critical(self, "EXPORT FAILED", f"ERROR: {e}")