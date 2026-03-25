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

        # 2. PLOT-WIDGET SETUP (Zwei Y-Achsen)
        pg.setConfigOptions(antialias=True)
        
        # Anstatt PlotWidget nutzenśmy GraphicsLayoutWidget für mehr Kontrolle
        self.graph_layout = pg.GraphicsLayoutWidget()
        self.graph_layout.setBackground('#090F16')
        lay.addWidget(self.graph_layout, stretch=1)
        
        # Den Hauptplot (Linke Achse für Druck) erstellen
        self.plot_item = self.graph_layout.addPlot(title="POST-RUN ANALYSIS")  # type: ignore        self.plot_item.showGrid(x=True, y=True, alpha=0.1)
        self.plot_item.addLegend(offset=(10, 10))
        
        self.plot_item.setLabel('bottom', "Time", units='s', color='#94A3B8')
        self.plot_item.setLabel('left', "Main Pressure", units='mbar', color='#8B5CF6')
        
        # Die zweite Y-Achse (Rechts für Volumen) erstellen
        self.axis_vol = pg.AxisItem('right')
        self.axis_vol.setLabel("Volume", units='ml', color='#00E5FF')
        self.plot_item.layout.addItem(self.axis_vol, 2, 2)
        
        # ViewBox für das Volumen (legt sich über den Hauptplot)
        self.vb_vol = pg.ViewBox()
        self.plot_item.scene().addItem(self.vb_vol)
        self.axis_vol.linkToView(self.vb_vol)
        self.vb_vol.setXLink(self.plot_item)
        
        # Signale verknüpfen, damit sich beide Viewboxen beim Zoomen synchronisieren
        self.plot_item.vb.sigResized.connect(self._update_views)

    @Slot()
    def _update_views(self):
        """Hält die Geometrie der zweiten ViewBox synchron mit dem Hauptplot."""
        self.vb_vol.setGeometry(self.plot_item.vb.sceneBoundingRect())
        self.vb_vol.linkedViewChanged(self.plot_item.vb, self.vb_vol.XAxis)

    @Slot()
    def _load_csv(self):
        """Öffnet einen Dialog zur Auswahl der Telemetrie-CSV und plottet die Daten."""
        base_dir = Path(__file__).resolve().parents[3] / "logs"
        file_path, _ = Qtw.QFileDialog.getOpenFileName(
            self, "Select Telemetry CSV", str(base_dir), "CSV Files (*.csv)"
        )
        if not file_path:
            return
            
        self.lbl_file_info.setText(f"Loading: {Path(file_path).name}...")
        self._parse_and_plot(file_path)

    def _parse_and_plot(self, filepath: str):
        times = []
        pressures = []
        volumes = []
        
        try:
            with open(filepath, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(row for row in f if not row.startswith('#'))
                for row in reader:
                    try:
                        t = float(row.get('t_s', 0))
                        p = float(row.get('p1_meas', 0) or 0)
                        v = float(row.get('volume_ml', 0) or 0)
                        
                        times.append(t)
                        pressures.append(p)
                        volumes.append(v)
                    except ValueError:
                        continue
            
            # Plot zurücksetzen
            self.plot_item.clear()
            self.vb_vol.clear()
            
            # Druck auf der linken Achse plotten (self.plot_item)
            pen_p = pg.mkPen(color='#8B5CF6', width=2)
            self.plot_item.plot(times, pressures, pen=pen_p, name="Main Pressure (mbar)")
            
            # Volumen auf der rechten Achse plotten (self.vb_vol)
            pen_v = pg.mkPen(color='#00E5FF', width=2)
            curve_v = pg.PlotDataItem(times, volumes, pen=pen_v)
            self.vb_vol.addItem(curve_v)
            
            # Legende manuell updaten (da PlotDataItem in ViewBox nicht automatisch in Legende landet)
            self.plot_item.legend.addItem(curve_v, "Volume (ml)")
            
            self.lbl_file_info.setText(f"Loaded: {Path(filepath).name} | Data points: {len(times)}")
            
        except Exception as e:
            self.lbl_file_info.setText(f"Error loading file: {e}")