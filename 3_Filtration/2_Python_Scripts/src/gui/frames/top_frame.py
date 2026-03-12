from typing import Optional
from PySide6.QtCore import Slot, Qt, Qt as QtEnum
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QProgressBar

class TopFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")
        
        lay = QHBoxLayout(self)
        lay.setContentsMargins(15, 10, 15, 10)
        lay.setSpacing(20)

        # 1. Branding / Status
        self.lbl_title = QLabel("LITTLE CHONKER // COMMAND NODE")
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-weight: 900; font-size: 16px; letter-spacing: 2px;")
        
        self.lbl_status = QLabel("● SIMULATION: IDLE")
        self.lbl_status.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 12px; font-family: 'Consolas';")
        
        box_brand = QVBoxLayout(); box_brand.setSpacing(2)
        box_brand.addWidget(self.lbl_title); box_brand.addWidget(self.lbl_status)
        lay.addLayout(box_brand)
        lay.addStretch()

        # 2. Metriken mit dynamischen Balken (Gauges)
        self.val_p_main, self.bar_p_main = self._add_metric(lay, "MAIN PRESSURE", "0 mbar", "#00E5FF", max_val=3000)
        self.val_p_back, self.bar_p_back = self._add_metric(lay, "BACKWASH", "0 mbar", "#8B5CF6", max_val=1000)
        self.val_flow, self.bar_flow = self._add_metric(lay, "FLOW RATE", "0.000 mL/min", "#00FF66", max_val=10)
        self.val_loss, self.bar_loss = self._add_metric(lay, "VOLUME LOSS", "0.00 mL", "#EC4899", max_val=50)

    def _add_metric(self, parent_layout, title: str, initial_val: str, color: str, max_val: int):
        # Äußerer Rahmen (Cyber-Card mit Gradient und farbigem Top-Rand)
        card = QFrame()
        card.setObjectName("MetricCard")
        card.setStyleSheet(f"""
            QFrame#MetricCard {{ 
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #111827, stop:1 #050914);
                border: 1px solid #1E293B; 
                border-radius: 6px; 
                border-top: 3px solid {color};
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(15, 10, 15, 12)
        lay.setSpacing(6)

        # Titel
        lbl_t = QLabel(title)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 10px; letter-spacing: 1.5px; border: none; background: transparent;")
        lay.addWidget(lbl_t)

        # Wert
        lbl_v = QLabel(initial_val)
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v.setMinimumWidth(120)
        lbl_v.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 18px; font-family: 'Consolas'; border: none; background: transparent;")
        lay.addWidget(lbl_v)

        # Dynamischer Mini-Fortschrittsbalken (Gauge)
        bar = QProgressBar()
        bar.setRange(0, max_val)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(f"""
            QProgressBar {{ background: #0F172A; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background-color: {color}; border-radius: 2px; }}
        """)
        lay.addWidget(bar)

        parent_layout.addWidget(card)
        return lbl_v, bar

    @Slot(dict)
    def update_telemetry(self, sample: dict):
        p1 = sample.get("p1_meas")
        self._set_metric_value(self.val_p_main, self.bar_p_main, p1, "{:.0f} mbar")
        
        p2 = sample.get("p2_meas")
        self._set_metric_value(self.val_p_back, self.bar_p_back, p2, "{:.0f} mbar")
        
        f = sample.get("flow")
        self._set_metric_value(self.val_flow, self.bar_flow, f, "{:.3f} mL/min", is_flow=True)

    def _set_metric_value(self, label: QLabel, bar: QProgressBar, value: Optional[float], format_str: str, is_flow: bool = False):
        if value is None:
            label.setText("---")
            bar.setValue(0)
            label.setStyleSheet(label.styleSheet().replace("color: #00FF66;", "color: #F8FAFC;").replace("color: #FF1744;", "color: #F8FAFC;"))
            return

        prefix = "+" if value > 0 else ""
        text = f"{prefix}{format_str.format(value)}"
        label.setText(text)
        
        # Update den Mini-Balken (absoluter Wert)
        bar.setValue(min(bar.maximum(), int(abs(value))))
        
        # Farbcodierung nur für den Flow-Wert! (Druck ist immer positiv und hat eine feste Farbe)
        if is_flow:
            if value > 0:
                label.setStyleSheet(label.styleSheet().replace("color: #FF1744;", "color: #00FF66;").replace("color: #F8FAFC;", "color: #00FF66;"))
                bar.setStyleSheet(bar.styleSheet().replace("background-color: #FF1744;", "background-color: #00FF66;"))
            elif value < 0:
                label.setStyleSheet(label.styleSheet().replace("color: #00FF66;", "color: #FF1744;").replace("color: #F8FAFC;", "color: #FF1744;"))
                bar.setStyleSheet(bar.styleSheet().replace("background-color: #00FF66;", "background-color: #FF1744;"))
            else:
                label.setStyleSheet(label.styleSheet().replace("color: #00FF66;", "color: #F8FAFC;").replace("color: #FF1744;", "color: #F8FAFC;"))

    @Slot(str)
    def update_status(self, status_text: str):
        # Simuliere eine leuchtende LED neben dem Status
        if "RUNNING" in status_text.upper():
            self.lbl_status.setText(f"● {status_text.upper()}")
            self.lbl_status.setStyleSheet("color: #00FF66; font-weight: bold; font-size: 12px; font-family: 'Consolas';")
        elif "ABORTED" in status_text.upper() or "FAILED" in status_text.upper():
            self.lbl_status.setText(f"● {status_text.upper()}")
            self.lbl_status.setStyleSheet("color: #FF1744; font-weight: bold; font-size: 12px; font-family: 'Consolas';")
        else:
            self.lbl_status.setText(f"● {status_text.upper()}")
            self.lbl_status.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 12px; font-family: 'Consolas';")

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        self.val_loss.setText(f"{loss_ml:.2f} mL")
        self.bar_loss.setValue(min(self.bar_loss.maximum(), int(abs(loss_ml))))