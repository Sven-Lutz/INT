from __future__ import annotations

import logging
import os
import pandas as pd
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib as mpl

# Matplotlib Stealth-Konfiguration
mpl.rcParams['toolbar'] = 'None'
mpl.rcParams['font.family'] = 'Consolas'
plt.style.use('dark_background')

logger = logging.getLogger(__name__)

class StatBox(Qtw.QFrame):
    """Kleine High-Tech Box für statistische Auswertungen."""
    def __init__(self, title: str, value: str, unit: str, color: str):
        super().__init__()
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #0B1120;
                border: 1px solid #1E293B;
                border-left: 4px solid {color};
                border-radius: 4px;
                padding: 5px;
            }}
        """)
        lay = Qtw.QVBoxLayout(self)
        lay.setSpacing(0)
        
        lbl_t = Qtw.QLabel(title.upper())
        lbl_t.setStyleSheet("color: #64748B; font-size: 9px; font-weight: bold; letter-spacing: 1px; border: none;")
        
        lbl_v = Qtw.QLabel(f"{value} <span style='font-size: 10px; color: #475569;'>{unit}</span>")
        lbl_v.setStyleSheet(f"color: #F8FAFC; font-size: 16px; font-weight: bold; font-family: 'Consolas'; border: none;")
        
        lay.addWidget(lbl_t)
        lay.addWidget(lbl_v)

class AnalysisFrame(Qtw.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.current_file_path = None

        root = Qtw.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- 1. ACTION BAR (Top) ---
        self.top_bar = Qtw.QFrame()
        self.top_bar.setFixedHeight(70)
        self.top_bar.setStyleSheet("background-color: #050914; border-bottom: 1px solid #1E2937;")
        top_lay = Qtw.QHBoxLayout(self.top_bar)
        top_lay.setContentsMargins(20, 0, 20, 0)

        # Import Button
        self.btn_load = Qtw.QPushButton(" 📂 IMPORT DATA STREAM ")
        self.btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load.setStyleSheet("""
            QPushButton { 
                background-color: #111827; color: #00E5FF; border: 1px solid #00E5FF; 
                font-family: 'Consolas'; font-weight: bold; font-size: 11px; border-radius: 4px; padding: 10px 20px;
            }
            QPushButton:hover { background-color: #00E5FF; color: #000; }
        """)
        self.btn_load.clicked.connect(self._load_file)

        # File Info Label
        self.lbl_file_info = Qtw.QLabel("SYSTEM READY // NO STREAM LOADED")
        self.lbl_file_info.setStyleSheet("color: #475569; font-family: 'Consolas'; font-size: 11px; letter-spacing: 1px; margin-left: 15px;")

        # PDF Export Button (Styled like a premium feature)
        self.btn_pdf = Qtw.QPushButton(" 📑 GENERATE REPORT (.PDF) ")
        self.btn_pdf.setEnabled(False)
        self.btn_pdf.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pdf.setStyleSheet("""
            QPushButton { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC4899, stop:1 #8B5CF6);
                color: white; border: none; font-family: 'Consolas'; font-weight: bold; font-size: 11px;
                border-radius: 4px; padding: 10px 20px;
            }
            QPushButton:hover { opacity: 0.9; }
            QPushButton:disabled { background: #1F2937; color: #4B5563; }
        """)
        self.btn_pdf.clicked.connect(self._generate_pdf)

        top_lay.addWidget(self.btn_load)
        top_lay.addWidget(self.lbl_file_info)
        top_lay.addStretch()
        top_lay.addWidget(self.btn_pdf)
        root.addWidget(self.top_bar)

        # --- 2. STATISTICS BOARD ---
        self.stats_board = Qtw.QFrame()
        self.stats_board.setFixedHeight(80)
        self.stats_board.setStyleSheet("background-color: #020617; border-bottom: 1px solid #0F172A;")
        self.stats_lay = Qtw.QHBoxLayout(self.stats_board)
        self.stats_lay.setContentsMargins(20, 10, 20, 10)
        self.stats_lay.setSpacing(15)
        
        # Platzhalter für Stats
        self._clear_stats()
        root.addWidget(self.stats_board)

        # --- 3. GRAPH AREA (Visualisierungen) ---
        self.figure = Figure(facecolor='#020617')
        self.canvas = FigureCanvas(self.figure)
        
        # Subplots initialisieren
        self.ax_p = self.figure.add_subplot(211)
        self.ax_f = self.figure.add_subplot(212)
        self.figure.tight_layout(pad=3.0)

        root.addWidget(self.canvas)

    def _clear_stats(self):
        while self.stats_lay.count():
            child = self.stats_lay.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        self.stats_lay.addStretch()

    def _apply_ax_style(self, ax, title):
        ax.set_facecolor('#020617')
        ax.set_title(title, color='#94A3B8', loc='left', fontsize=10, fontweight='bold', pad=10)
        ax.tick_params(colors='#475569', labelsize=8)
        for spine in ax.spines.values(): spine.set_color('#1E293B')
        ax.grid(True, color='#0F172A', linestyle='--', alpha=0.5)

    def _load_file(self):
        file_path, _ = Qtw.QFileDialog.getOpenFileName(self, "LOAD PELLIKAN LOG", "logs", "CSV Files (*.csv)")
        if not file_path: return

        try:
            self.data = pd.read_csv(file_path)
            self.current_file_path = file_path
            self._update_view()
            self.lbl_file_info.setText(f"DATA STREAM LOADED: {os.path.basename(file_path).upper()}")
            self.btn_pdf.setEnabled(True)
        except Exception as e:
            Qtw.QMessageBox.critical(self, "DATA ERROR", f"STREAM CORRUPTED: {e}")

    def _update_view(self):
        if self.data is None: return
        
        # 1. Datenvorbereitung
        cols = {c.lower(): c for c in self.data.columns}
        t = self.data[cols.get('t_s', self.data.columns[1])]
        p1 = self.data[cols.get('p1_meas', self.data.columns[4])]
        p2 = self.data[cols.get('p2_meas', self.data.columns[5])]
        flow = self.data[cols.get('flow', self.data.columns[3])]

        # 2. Stats Board aktualisieren
        self._clear_stats()
        self.stats_lay.insertWidget(0, StatBox("Peak Pressure", f"{p1.max():.0f}", "mbar", "#EC4899"))
        self.stats_lay.insertWidget(1, StatBox("Avg Flow", f"{flow.mean():.3f}", "mL/min", "#00E5FF"))
        self.stats_lay.insertWidget(2, StatBox("Duration", f"{t.max()/60:.1f}", "min", "#8B5CF6"))
        self.stats_lay.addStretch()

        # 3. Plots zeichnen
        self.ax_p.clear()
        self.ax_f.clear()

        # Druck-Plot
        self.ax_p.plot(t, p1, color='#EC4899', linewidth=1.5, label='Main P1')
        self.ax_p.plot(t, p2, color='#8B5CF6', linewidth=1.2, label='Backwash P2', linestyle='--')
        self.ax_p.fill_between(t, p1, color='#EC4899', alpha=0.05)
        self._apply_ax_style(self.ax_p, "PRESSURE TELEMETRY (MBAR)")
        self.ax_p.legend(facecolor='#050914', edgecolor='#1E2937', fontsize=8)

        # Flow-Plot
        self.ax_f.plot(t, flow, color='#00E5FF', linewidth=1.5)
        self.ax_f.fill_between(t, flow, color='#00E5FF', alpha=0.1)
        self._apply_ax_style(self.ax_f, "FLOW DYNAMICS (ML/MIN)")
        self.ax_f.set_xlabel("TIME (S)", color='#475569', fontsize=8)

        self.canvas.draw()

    def _generate_pdf(self):
        if self.data is None or not self.current_file_path: return
        save_path, _ = Qtw.QFileDialog.getSaveFileName(self, "SAVE SCIENTIFIC REPORT", "", "PDF Files (*.pdf)")
        if not save_path: return

        try:
            # Wir nutzen den "White-Mode" für den Export (Drucker-freundlich)
            with plt.style.context('default'):
                fig_print = plt.figure(figsize=(8.5, 11))
                fig_print.suptitle(f"PELLIKAN OS // FILTRATION REPORT\nFile: {os.path.basename(self.current_file_path)}", 
                                 fontsize=14, fontweight='bold', fontfamily='monospace')

                ax1 = fig_print.add_subplot(211)
                ax2 = fig_print.add_subplot(212)

                t = self.data.iloc[:, 1] # t_s
                ax1.plot(t, self.data['p1_meas'], color='#EC4899', label='P1 Main')
                ax1.plot(t, self.data['p2_meas'], color='#8B5CF6', label='P2 Backwash', linestyle='--')
                ax1.set_ylabel("Pressure (mbar)")
                ax1.grid(True, alpha=0.2)
                ax1.legend()

                ax2.plot(t, self.data['flow'], color='#0284C7')
                ax2.set_ylabel("Flow Rate (mL/min)")
                ax2.set_xlabel("Time (s)")
                ax2.grid(True, alpha=0.2)

                fig_print.tight_layout(pad=4.0)
                fig_print.savefig(save_path)
                plt.close(fig_print)

            Qtw.QMessageBox.information(self, "REPORT SECURED", f"The protocol has been exported successfully to:\n{save_path}")
        except Exception as e:
            Qtw.QMessageBox.critical(self, "EXPORT FAILED", f"PDF Engine Error: {e}")