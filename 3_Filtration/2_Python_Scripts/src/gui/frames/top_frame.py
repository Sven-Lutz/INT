from typing import Optional
from PySide6.QtCore import Slot, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QProgressBar

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
        
        box_brand = QVBoxLayout()
        box_brand.setSpacing(2)
        box_brand.addWidget(self.lbl_title)
        box_brand.addWidget(self.lbl_status)
        lay.addLayout(box_brand)
        lay.addStretch()

        # 2. Metriken mit dynamischen Balken (Gauges)
        self.val_p_main, self.bar_p_main = self._add_metric(lay, "MAIN PRESSURE", "0 mbar", "#00E5FF", max_val=3000)
        self.val_p_back, self.bar_p_back = self._add_metric(lay, "BACKWASH", "0 mbar", "#8B5CF6", max_val=1000)
        self.val_flow, self.bar_flow = self._add_metric(lay, "FLOW RATE", "0.000 mL/min", "#00FF66", max_val=10)
        self.val_loss, self.bar_loss = self._add_metric(lay, "VOLUME LOSS", "0.00 mL", "#EC4899", max_val=50)

    def _add_metric(self, parent_layout, title: str, initial_val: str, color: str, max_val: int):
        card = QFrame()
        card.setObjectName("MetricCard")
        card.setStyleSheet(f"""
            QFrame#MetricCard {{
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #111827, stop:1 #050914);
                border-top: 3px solid {color};
                border-right: 1px solid #1E293B;
                border-bottom: 1px solid #1E293B;
                border-left: 1px solid #1E293B;
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(15, 10, 15, 12)
        lay.setSpacing(6)

        lbl_t = QLabel(title)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t.setStyleSheet("color: #94A3B8; font-weight: bold; font-size: 10px; letter-spacing: 1.5px; border: none; background: transparent;")
        lay.addWidget(lbl_t)

        lbl_v = QLabel(initial_val)
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v.setMinimumWidth(120)
        lbl_v.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 18px; font-family: 'Consolas'; border: none; background: transparent;")
        lay.addWidget(lbl_v)

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

    def _to_safe_float(self, val) -> Optional[float]:
        if val is None: 
            return None
        try:
            v = float(val)
            if v == v and v not in (float("inf"), float("-inf")):
                return v
            return None
        except Exception:
            return None

    @Slot(dict)
    def update_telemetry(self, sample: dict):
        pressures = sample.get("pressure", {})
        
        p1_data = pressures.get(1, pressures.get("1", {}))
        p1_raw = sample.get("p1_meas") if sample.get("p1_meas") is not None else p1_data.get("meas")
        self._set_metric_value(self.val_p_main, self.bar_p_main, self._to_safe_float(p1_raw), "{:.0f} mbar")
        
        p2_data = pressures.get(2, pressures.get("2", {}))
        p2_raw = sample.get("p2_meas") if sample.get("p2_meas") is not None else p2_data.get("meas")
        self._set_metric_value(self.val_p_back, self.bar_p_back, self._to_safe_float(p2_raw), "{:.0f} mbar")
        
        f = self._to_safe_float(sample.get("flow"))
        self._set_metric_value(self.val_flow, self.bar_flow, f, "{:.3f} mL/min", is_flow=True)

        # 🚀 FIX: Den Live-Loss abfangen und verarbeiten!
        if "loss_ml" in sample:
            self.set_loss_ml(sample["loss_ml"])

    def _set_metric_value(self, label: QLabel, bar: QProgressBar, value: Optional[float], format_str: str, is_flow: bool = False):
        if value is None:
            label.setText("---")
            bar.setValue(0)
            label.setStyleSheet(label.styleSheet().replace("color: #00FF66;", "color: #F8FAFC;").replace("color: #FF1744;", "color: #F8FAFC;"))
            return

        prefix = "+" if value > 0 else ""
        text = f"{prefix}{format_str.format(value)}"
        label.setText(text)
        
        try:
            bar.setValue(min(bar.maximum(), int(abs(value))))
        except Exception:
            bar.setValue(0)
        
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
        safe_status = str(status_text).upper() if status_text else "UNKNOWN"
        
        if "RUNNING" in safe_status:
            self.lbl_status.setText(f"● {safe_status}")
            self.lbl_status.setStyleSheet("color: #00FF66; font-weight: bold; font-size: 12px; font-family: 'Consolas';")
        elif "ABORTED" in safe_status or "FAILED" in safe_status or "ERROR" in safe_status:
            self.lbl_status.setText(f"● {safe_status}")
            self.lbl_status.setStyleSheet("color: #FF1744; font-weight: bold; font-size: 12px; font-family: 'Consolas';")
        else:
            self.lbl_status.setText(f"● {safe_status}")
            self.lbl_status.setStyleSheet("color: #00E5FF; font-weight: bold; font-size: 12px; font-family: 'Consolas';")

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        safe_loss = self._to_safe_float(loss_ml) or 0.0
        self.val_loss.setText(f"{safe_loss:.2f} mL")
        try:
            self.bar_loss.setValue(min(self.bar_loss.maximum(), int(abs(safe_loss))))
        except Exception:
            pass