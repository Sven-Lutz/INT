from typing import Optional
from PySide6.QtCore import Slot, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QProgressBar


# =========================================================================
# STYLE CONSTANTS
# =========================================================================
_CARD_STYLE = """
    QFrame#MetricCard {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #111827, stop:1 #050914);
        border-top: 3px solid {color};
        border-right: 1px solid #1E293B;
        border-bottom: 1px solid #1E293B;
        border-left: 1px solid #1E293B;
        border-radius: 6px;
    }}
"""
_TITLE_STYLE = "color: #94A3B8; font-weight: bold; font-size: 10px; letter-spacing: 1.5px; border: none; background: transparent;"
_VAL_STYLE = "color: {color}; font-weight: bold; font-size: 18px; font-family: 'Consolas'; border: none; background: transparent;"
_SUB_STYLE = "color: #64748B; font-weight: bold; font-size: 10px; font-family: 'Consolas'; border: none; background: transparent;"
_BAR_STYLE = """
    QProgressBar {{ background: #0F172A; border: none; border-radius: 2px; }}
    QProgressBar::chunk {{ background-color: {color}; border-radius: 2px; }}
"""
_STATUS_BASE = "font-weight: bold; font-size: 12px; font-family: 'Consolas';"


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        v = float(val)
        if v == v and v not in (float("inf"), float("-inf")):
            return v
    except Exception:
        pass
    return None


class TopFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")

        self._current_phase = "IDLE"
        self._progress_target_ml = 0.0
        self._progress_current_ml = 0.0
        self._last_valve_state: str = ""
        self._valve_pending: str = ""
        self._valve_debounce = QTimer(self)
        self._valve_debounce.setSingleShot(True)
        self._valve_debounce.setInterval(400)
        self._valve_debounce.timeout.connect(self._flush_valve_state)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(15, 10, 15, 10)
        lay.setSpacing(16)

        # 1. Branding / Status / Phase
        self.lbl_title = QLabel("PELLIKAN OS")
        self.lbl_title.setStyleSheet("color: #F8FAFC; font-weight: 900; font-size: 14px; letter-spacing: 2px;")

        self.lbl_status = QLabel("● IDLE")
        self.lbl_status.setStyleSheet(f"color: #00E5FF; {_STATUS_BASE}")

        self.lbl_phase = QLabel("")
        self.lbl_phase.setStyleSheet("color: #64748B; font-weight: bold; font-size: 10px; font-family: 'Consolas';")

        box_brand = QVBoxLayout()
        box_brand.setSpacing(1)
        box_brand.addWidget(self.lbl_title)
        box_brand.addWidget(self.lbl_status)
        box_brand.addWidget(self.lbl_phase)
        lay.addLayout(box_brand)
        lay.addStretch()

        # 2. Pressure cards: Soll/Ist nebeneinander
        self.val_p1, self.sub_p1, self.bar_p1 = self._add_pressure_card(lay, "P1 MAIN", "#00E5FF", 2000)
        self.val_p2, self.sub_p2, self.bar_p2 = self._add_pressure_card(lay, "P2 BACKWASH", "#8B5CF6", 400)

        # 3. Flow
        self.val_flow, self.bar_flow = self._add_simple_card(lay, "FLOW RATE", "0.000 ml/min", "#00FF66", 500)

        # 4. Valve State
        self.val_valves = self._add_text_card(lay, "VALVES", "—", "#94A3B8")

        # 5. Progress (Loss / Target)
        self.val_progress, self.bar_progress = self._add_simple_card(lay, "PROGRESS", "—", "#F59E0B", 100)

    # -----------------------------------------------------------------
    # CARD BUILDERS
    # -----------------------------------------------------------------
    def _add_pressure_card(self, parent_layout, title: str, color: str, max_val: int):
        """Pressure card: großer Ist-Wert + kleiner Soll-Wert darunter + Gauge-Bar."""
        card, card_lay = self._make_card_frame(color)

        lbl_t = QLabel(title)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t.setStyleSheet(_TITLE_STYLE)
        card_lay.addWidget(lbl_t)

        lbl_v = QLabel("0 mbar")
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v.setMinimumWidth(130)
        lbl_v.setStyleSheet(_VAL_STYLE.format(color=color))
        card_lay.addWidget(lbl_v)

        lbl_sub = QLabel("SET: 0 mbar")
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setStyleSheet(_SUB_STYLE)
        card_lay.addWidget(lbl_sub)

        bar = self._make_bar(color, max_val)
        card_lay.addWidget(bar)

        parent_layout.addWidget(card)
        return lbl_v, lbl_sub, bar

    def _add_simple_card(self, parent_layout, title: str, initial: str, color: str, max_val: int):
        """Simple card: Wert + Gauge-Bar."""
        card, card_lay = self._make_card_frame(color)

        lbl_t = QLabel(title)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t.setStyleSheet(_TITLE_STYLE)
        card_lay.addWidget(lbl_t)

        lbl_v = QLabel(initial)
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v.setMinimumWidth(110)
        lbl_v.setStyleSheet(_VAL_STYLE.format(color=color))
        card_lay.addWidget(lbl_v)

        bar = self._make_bar(color, max_val)
        card_lay.addWidget(bar)

        parent_layout.addWidget(card)
        return lbl_v, bar

    def _add_text_card(self, parent_layout, title: str, initial: str, color: str):
        """Text-only card: kein Gauge-Bar."""
        card, card_lay = self._make_card_frame(color)

        lbl_t = QLabel(title)
        lbl_t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_t.setStyleSheet(_TITLE_STYLE)
        card_lay.addWidget(lbl_t)

        lbl_v = QLabel(initial)
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_v.setMinimumWidth(90)
        lbl_v.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 13px; font-family: 'Consolas'; border: none; background: transparent;")
        card_lay.addWidget(lbl_v)

        parent_layout.addWidget(card)
        return lbl_v

    def _make_card_frame(self, color: str):
        card = QFrame()
        card.setObjectName("MetricCard")
        card.setStyleSheet(_CARD_STYLE.format(color=color))
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 8, 12, 10)
        card_lay.setSpacing(4)
        return card, card_lay

    def _make_bar(self, color: str, max_val: int) -> QProgressBar:
        bar = QProgressBar()
        bar.setRange(0, max_val)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(_BAR_STYLE.format(color=color))
        return bar

    # -----------------------------------------------------------------
    # TELEMETRY UPDATE
    # -----------------------------------------------------------------
    @Slot(dict)
    def update_telemetry(self, sample: dict):
        if not isinstance(sample, dict):
            return

        pressures = sample.get("pressure")
        if not isinstance(pressures, dict):
            pressures = {}

        # --- P1 Main: Ist + Soll ---
        p1_data = pressures.get(1, pressures.get("1", {}))
        if not isinstance(p1_data, dict):
            p1_data = {}

        p1_meas = _safe_float(sample.get("p1_meas") if sample.get("p1_meas") is not None else p1_data.get("meas"))
        p1_set = _safe_float(sample.get("p1_set") if sample.get("p1_set") is not None else p1_data.get("set"))

        if p1_meas is not None:
            self.val_p1.setText(f"{p1_meas:.0f} mbar")
            self.bar_p1.setValue(min(self.bar_p1.maximum(), int(abs(p1_meas))))
        else:
            self.val_p1.setText("---")
            self.bar_p1.setValue(0)

        if p1_set is not None:
            self.sub_p1.setText(f"SET: {p1_set:.0f} mbar")
            # Druck-Drift Indikator: wenn Ist > 10% vom Soll abweicht → rot
            if p1_meas is not None and p1_set > 10:
                drift_pct = abs(p1_meas - p1_set) / p1_set * 100
                if drift_pct > 10:
                    self.sub_p1.setStyleSheet("color: #FF1744; font-weight: bold; font-size: 10px; font-family: 'Consolas'; border: none; background: transparent;")
                else:
                    self.sub_p1.setStyleSheet(_SUB_STYLE)
            else:
                self.sub_p1.setStyleSheet(_SUB_STYLE)
        else:
            self.sub_p1.setText("SET: —")

        # --- P2 Backwash: Ist + Soll ---
        p2_data = pressures.get(2, pressures.get("2", {}))
        if not isinstance(p2_data, dict):
            p2_data = {}

        p2_meas = _safe_float(sample.get("p2_meas") if sample.get("p2_meas") is not None else p2_data.get("meas"))
        p2_set = _safe_float(sample.get("p2_set") if sample.get("p2_set") is not None else p2_data.get("set"))

        if p2_meas is not None:
            self.val_p2.setText(f"{p2_meas:.0f} mbar")
            self.bar_p2.setValue(min(self.bar_p2.maximum(), int(abs(p2_meas))))
        else:
            self.val_p2.setText("---")
            self.bar_p2.setValue(0)

        self.sub_p2.setText(f"SET: {p2_set:.0f} mbar" if p2_set is not None else "SET: —")

        # --- Flow ---
        flow = _safe_float(sample.get("flow"))
        if flow is not None:
            self.val_flow.setText(f"{flow:.1f} ml/min")
            self.bar_flow.setValue(min(self.bar_flow.maximum(), int(abs(flow))))
        else:
            self.val_flow.setText("--- ml/min")
            self.bar_flow.setValue(0)

        # --- Valve State (debounced 400 ms → verhindert Flackern bei Umschaltvorgängen) ---
        v_state = str(sample.get("valves", "—"))
        if v_state != self._valve_pending:
            self._valve_pending = v_state
            self._valve_debounce.start()

        # --- Progress ---
        if "loss_ml" in sample:
            self._update_progress(sample["loss_ml"])

    def _flush_valve_state(self):
        if self._valve_pending != self._last_valve_state:
            self._last_valve_state = self._valve_pending
            self.val_valves.setText(self._valve_pending[:12])

    # -----------------------------------------------------------------
    # PROGRESS & LOSS
    # -----------------------------------------------------------------
    def set_progress_target(self, target_ml: float):
        """Wird vom MainWindow aufgerufen wenn der Run startet."""
        self._progress_target_ml = max(0.01, float(target_ml))

    @Slot(float)
    def set_loss_ml(self, loss_ml: float):
        self._update_progress(loss_ml)

    def _update_progress(self, loss_ml_raw):
        loss = _safe_float(loss_ml_raw) or 0.0
        self._progress_current_ml = loss

        if self._progress_target_ml > 0.01:
            pct = min(100.0, abs(loss) / self._progress_target_ml * 100.0)
            self.val_progress.setText(f"{abs(loss):.1f} / {self._progress_target_ml:.1f} mL")
            self.bar_progress.setValue(int(pct))
        else:
            self.val_progress.setText(f"{abs(loss):.2f} mL")
            self.bar_progress.setValue(0)

    # -----------------------------------------------------------------
    # STATUS & PHASE
    # -----------------------------------------------------------------
    @Slot(str)
    def update_status(self, status_text: str):
        safe = str(status_text).upper() if status_text else "UNKNOWN"

        if "RUNNING" in safe or "RAMPING" in safe or "HOLD" in safe:
            color = "#00FF66"
        elif "ABORT" in safe or "FAIL" in safe or "ERROR" in safe or "SAFETY" in safe:
            color = "#FF1744"
        elif "WAIT" in safe or "CONFIRM" in safe:
            color = "#F59E0B"
        else:
            color = "#00E5FF"

        self.lbl_status.setText(f"● {safe}")
        self.lbl_status.setStyleSheet(f"color: {color}; {_STATUS_BASE}")

    @Slot(str)
    def update_phase(self, phase_str: str):
        """Zeigt die aktuelle Phase als kleines Label unter dem Status."""
        self._current_phase = str(phase_str)
        if phase_str and phase_str not in ("IDLE", "FINISHED", "ABORTED"):
            self.lbl_phase.setText(f"PHASE: {phase_str}")
            self.lbl_phase.setStyleSheet("color: #8B5CF6; font-weight: bold; font-size: 10px; font-family: 'Consolas';")
        else:
            self.lbl_phase.setText("")