import csv
import pyqtgraph as pg
import PySide6.QtWidgets as Qtw
from PySide6.QtCore import Qt, Slot
from pathlib import Path

class AnalysisFrame(Qtw.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #050914;")
        
        lay = Qtw.QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(10)

        # 1. KONTROLL-PANEL (Oben)
        ctrl_panel = Qtw.QFrame()
        ctrl_lay = Qtw.QHBoxLayout(ctrl_panel)
        ctrl_lay.setContentsMargins(0, 0, 0, 0)
        
        self.btn_load = Qtw.QPushButton("📂 LOAD RUN DATA (CSV)")
        self.btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load.setStyleSheet("""
            QPushButton {
                background-color: #111827; color: #00E5FF;
                font-family: 'Consolas'; font-weight: bold; padding: 8px 15px;
                border: 1px solid #1E293B; border-radius: 4px;
            }
            QPushButton:hover { background-color: #1E293B; color: #FFF; }
        """)
        self.btn_load.clicked.connect(self._load_csv)
        
        self.lbl_file_info = Qtw.QLabel("No file loaded.")
        self.lbl_file_info.setStyleSheet("color: #64748B; font-family: 'Consolas';")
        
        ctrl_lay.addWidget(self.btn_load)
        ctrl_lay.addWidget(self.lbl_file_info)
        ctrl_lay.addStretch()
        lay.addWidget(ctrl_panel)

        # 2. PLOT-WIDGET
        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget(title="POST-RUN ANALYSIS")
        self.plot_widget.setBackground('#090F16')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.1)
        self.plot_widget.addLegend()
        
        # Achsen-Beschriftung
        self.plot_widget.setLabel('bottom', "Time [s]", color='#94A3B8')
        self.plot_widget.setLabel('left', "Pressure [mbar]", color='#8B5CF6')
        
        lay.addWidget(self.plot_widget, stretch=1)

    @Slot()
    def _load_csv(self):
        """Öffnet einen Dialog zur Auswahl der Telemetrie-CSV und plottet die Daten."""
        # Suche im lokalen logs/runs Verzeichnis
        base_dir = Path(__file__).resolve().parents[3] / "logs"
        
        file_path, _ = Qtw.QFileDialog.getOpenFileName(
            self, "Select Telemetry CSV", str(base_dir), "CSV Files (*.csv)"
        )
        
        if not file_path:
            return  # Abbruch durch User
            
        self.lbl_file_info.setText(f"Loading: {Path(file_path).name}...")
        self._parse_and_plot(file_path)

    def _parse_and_plot(self, filepath: str):
        times = []
        pressures = []
        volumes = []
        
        try:
            with open(filepath, mode='r', encoding='utf-8') as f:
                # Ignoriere Preamble (Zeilen mit #) falls vorhanden
                # CSV.DictReader sucht sich automatisch die Spaltennamen
                reader = csv.DictReader(row for row in f if not row.startswith('#'))
                
                for row in reader:
                    # Wir sichern uns ab, falls Felder leer sind
                    try:
                        # Hier nutzen wir die Spaltennamen aus deinem RunTelemetryStore
                        t = float(row.get('t_s', 0))
                        p = float(row.get('p1_meas', 0) or 0)
                        v = float(row.get('volume_ml', 0) or 0)
                        
                        times.append(t)
                        pressures.append(p)
                        volumes.append(v)
                    except ValueError:
                        continue # Überspringe kaputte Zeilen
            
            # Plot zurücksetzen und neu zeichnen
            self.plot_widget.clear()
            
            # Druckverlauf zeichnen (Lila)
            pen_p = pg.mkPen(color='#8B5CF6', width=2)
            self.plot_widget.plot(times, pressures, pen=pen_p, name="Main Pressure (mbar)")
            
            # 💡 HINWEIS: Volumen (V) hat eigentlich eine andere Einheit (ml). 
            # Für eine schnelle Visualisierung plotten wir es erstmal mit rein.
            pen_v = pg.mkPen(color='#00E5FF', width=2)
            self.plot_widget.plot(times, volumes, pen=pen_v, name="Volume (ml)")
            
            self.lbl_file_info.setText(f"Loaded: {Path(filepath).name} | Data points: {len(times)}")
            
        except Exception as e:
            self.lbl_file_info.setText(f"Error loading file: {e}")