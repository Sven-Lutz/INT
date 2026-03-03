from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QPushButton, QWidget, QSizePolicy, QGridLayout
)
from src.gui.data.worker import RunParams
from src.gui.widgets.hold_button import HoldButton


class NudgeSpinBox(QWidget):
    valueChanged = Signal(float)

    def __init__(self, minimum: float, maximum: float, decimals: int, step: float, suffix: str, value: float):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.spin = QDoubleSpinBox()
        self.spin.setRange(minimum, maximum)
        self.spin.setDecimals(decimals)
        self.spin.setSingleStep(step)
        self.spin.setSuffix(suffix)
        self.spin.setValue(value)
        self.spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.spin.setFocusPolicy(Qt.ClickFocus)

        self.spin.setStyleSheet("""
            QDoubleSpinBox { 
                background: #050914; 
                border: 1px solid #1F2937; 
                color: #F8FAFC;
                border-radius: 4px;
                padding: 6px 10px;
                font-family: 'Consolas', monospace;
                font-weight: bold;
                font-size: 13px;
            } 
            QDoubleSpinBox:focus { border: 1px solid #8B5CF6; }
        """)

        btn_style = """
            QPushButton { 
                background-color: #111827; 
                color: #A0AEC0; 
                border: 1px solid #2D3748; 
                border-radius: 4px; 
                font-family: Arial, sans-serif; 
                font-size: 18px; 
                font-weight: bold;
                padding: 0px;
                margin: 0px;
            } 
            QPushButton:hover { background-color: #2D3748; color: #FFFFFF; border-color: #8B5CF6; }
            QPushButton:pressed { background-color: #8B5CF6; color: #FFFFFF; border-color: #8B5CF6; }
            QPushButton:disabled { color: #4A5568; background-color: #050914; border-color: #111827; }
        """

        self.btn_m = QPushButton("-")
        self.btn_m.setFixedSize(30, 30)
        self.btn_m.setFocusPolicy(Qt.NoFocus)
        self.btn_m.setStyleSheet(btn_style)

        self.btn_p = QPushButton("+")
        self.btn_p.setFixedSize(30, 30)
        self.btn_p.setFocusPolicy(Qt.NoFocus)
        self.btn_p.setStyleSheet(btn_style)

        lay.addWidget(self.spin)
        lay.addWidget(self.btn_m)
        lay.addWidget(self.btn_p)

        self.btn_m.clicked.connect(lambda: self.spin.setValue(self.spin.value() - self.spin.singleStep()))
        self.btn_p.clicked.connect(lambda: self.spin.setValue(self.spin.value() + self.spin.singleStep()))
        self.spin.valueChanged.connect(self.valueChanged.emit)

    def value(self) -> float: return self.spin.value()

    def setValue(self, val: float): self.spin.setValue(val)

    def setEnabled(self, val: bool):
        super().setEnabled(val)
        self.spin.setEnabled(val)
        self.btn_m.setEnabled(val)
        self.btn_p.setEnabled(val)


@dataclass
class LeftFrameDefaults:
    bw1_dur: float = 20.0;
    bw1_p: float = 600.0
    fill_t: float = 600.0;
    fill_r: float = 10.0;
    fill_h: float = 30.0
    filt_dur: float = 60.0;
    filt_p: float = 1200.0
    vent_dur: float = 20.0
    bw2_base: float = 0.0;
    bw2_p: float = 600.0;
    bw2_max: float = 180.0
    hold_p: float = 600.0;
    hold_max: float = 1.0


class LeftFrame(QFrame):
    params_changed = Signal(RunParams)

    def __init__(self, config=None, parent=None, defaults=None):
        super().__init__(parent)
        self.setProperty("surface", "panel")
        self.defaults = defaults or LeftFrameDefaults()

        self._hold_active = False
        self._hold_allowed = True

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(15)

        hold_card = self._card("MANUAL HOLD", accent="#EC4899")
        hold_lay = hold_card.layout()

        self.sp_hold_pressure = NudgeSpinBox(0, 8000, 0, 25, " mbar", self.defaults.hold_p)
        self.sp_hold_max = NudgeSpinBox(1.0, 36000, 1, 1, " s", self.defaults.hold_max)

        grid_hold = QGridLayout();
        grid_hold.setSpacing(10)
        l1 = QLabel("Setpoint");
        l1.setStyleSheet("color: #A0AEC0; font-size: 11px; font-family: 'Consolas', monospace;")
        l2 = QLabel("Max Time");
        l2.setStyleSheet("color: #A0AEC0; font-size: 11px; font-family: 'Consolas', monospace;")
        grid_hold.addWidget(l1, 0, 0);
        grid_hold.addWidget(self.sp_hold_pressure, 0, 1)
        grid_hold.addWidget(l2, 1, 0);
        grid_hold.addWidget(self.sp_hold_max, 1, 1)
        hold_lay.addLayout(grid_hold)

        self.btn_hold = HoldButton("SYSTEM IDLE")
        self.btn_hold.setFocusPolicy(Qt.NoFocus)
        self.set_hold_active(False)
        hold_lay.addWidget(self.btn_hold)
        root.addWidget(hold_card)

        t2 = QLabel("SEQUENCE PARAMETERS")
        t2.setStyleSheet("font-weight: bold; color: #4A5568; font-size: 10px; letter-spacing: 2px; padding-top: 5px;")
        root.addWidget(t2)

        self.sp_bw1_dur = NudgeSpinBox(1.0, 3600, 1, 1, " s", self.defaults.bw1_dur)
        self.sp_bw1_p = NudgeSpinBox(0, 8000, 0, 50, " mbar", self.defaults.bw1_p)
        root.addWidget(self._param_card("BACKWASH 1", [("Duration", self.sp_bw1_dur), ("Pressure", self.sp_bw1_p)]))

        self.sp_fill_t = NudgeSpinBox(0, 8000, 0, 50, " mbar", self.defaults.fill_t)
        self.sp_fill_r = NudgeSpinBox(1.0, 600, 1, 1, " s", self.defaults.fill_r)
        self.sp_fill_h = NudgeSpinBox(1.0, 3600, 1, 1, " s", self.defaults.fill_h)
        fill_card = self._param_card("FILLING",
                                     [("Target", self.sp_fill_t), ("Ramp", self.sp_fill_r), ("Hold", self.sp_fill_h)])

        self.lbl_fill_out = QLabel("Auto-Calc: —")
        self.lbl_fill_out.setStyleSheet(
            "color: #00E5FF; font-family: 'Consolas', monospace; font-size: 10px; border: none; padding-top: 4px;")
        fill_card.layout().addWidget(self.lbl_fill_out)
        root.addWidget(fill_card)

        self.sp_filt_dur = NudgeSpinBox(1.0, 86400, 1, 5, " s", self.defaults.filt_dur)
        self.sp_filt_p = NudgeSpinBox(0, 8000, 0, 50, " mbar", self.defaults.filt_p)
        root.addWidget(self._param_card("FILTRATION", [("Duration", self.sp_filt_dur), ("Pressure", self.sp_filt_p)]))

        self.sp_vent_dur = NudgeSpinBox(1.0, 3600, 1, 1, " s", self.defaults.vent_dur)
        root.addWidget(self._param_card("VENTING", [("Duration", self.sp_vent_dur)]))

        self.sp_bw2_base = NudgeSpinBox(0.0, 1000, 3, 0.1, " mL", self.defaults.bw2_base)
        self.sp_bw2_p = NudgeSpinBox(0, 8000, 0, 50, " mbar", self.defaults.bw2_p)
        self.sp_bw2_max = NudgeSpinBox(1.0, 3600, 1, 5, " s", self.defaults.bw2_max)
        root.addWidget(self._param_card("BACKWASH 2", [("Base Remove", self.sp_bw2_base), ("Pressure", self.sp_bw2_p),
                                                       ("Max duration", self.sp_bw2_max)]))

        root.addStretch()
        self._wire()

    def _card(self, title: str, accent: str = "#E2E8F0") -> QFrame:
        c = QFrame()
        c.setStyleSheet(
            f"background: #111827; border-radius: 6px; border: 1px solid #1F2937; border-top: 3px solid {accent};")
        l = QVBoxLayout(c);
        l.setContentsMargins(15, 12, 15, 15);
        l.setSpacing(12)
        t = QLabel(title);
        t.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {accent}; letter-spacing: 1.5px; border: none; font-family: 'Consolas', monospace;")
        l.addWidget(t)
        return c

    def _param_card(self, title: str, items: list) -> QFrame:
        c = self._card(title, accent="#4A5568")
        l = c.layout()
        g = QGridLayout();
        g.setSpacing(10)
        for i, (label, widget) in enumerate(items):
            lbl = QLabel(label);
            lbl.setStyleSheet("color: #A0AEC0; font-size: 11px; font-family: 'Consolas', monospace; border: none;")
            g.addWidget(lbl, i, 0);
            g.addWidget(widget, i, 1)
        l.addLayout(g)
        return c

    def _wire(self):
        widgets = [
            self.sp_hold_pressure, self.sp_hold_max, self.sp_bw1_dur, self.sp_bw1_p,
            self.sp_fill_t, self.sp_fill_r, self.sp_fill_h, self.sp_filt_dur,
            self.sp_filt_p, self.sp_vent_dur, self.sp_bw2_base, self.sp_bw2_p,
            self.sp_bw2_max
        ]
        for w in widgets:
            w.valueChanged.connect(self._on_any_change)

    @Slot()
    def _on_any_change(self):
        self.params_changed.emit(self.get_run_params())

    def get_run_params(self) -> RunParams:
        return RunParams(
            backwash1_duration_s=self.sp_bw1_dur.value(),
            backwash1_pressure_mbar=self.sp_bw1_p.value(),
            filling_target_mbar=self.sp_fill_t.value(),
            filling_ramp_s=self.sp_fill_r.value(),
            filling_hold_s=self.sp_fill_h.value(),
            filtration_duration_s=self.sp_filt_dur.value(),
            filtration_pressure_mbar=self.sp_filt_p.value(),
            venting_duration_s=self.sp_vent_dur.value(),
            backwash2_base_remove_ml=self.sp_bw2_base.value(),
            backwash2_pressure_mbar=self.sp_bw2_p.value(),
            backwash2_max_duration_s=self.sp_bw2_max.value()
        )

    def get_backwash_hold_pressure_mbar(self) -> float:
        return self.sp_hold_pressure.value()

    def set_filling_outputs(self, *, target_pct: Optional[float] = None, slope_mbar_s: Optional[float] = None,
                            suggested_ramp_s: Optional[float] = None):
        t = f"{target_pct:.1f}%" if target_pct is not None else "—"
        s = f"{slope_mbar_s:.1f} mbar/s" if slope_mbar_s is not None else "—"
        self.lbl_fill_out.setText(f"Target: {t} | Slope: {s}")

    @Slot(bool)
    def set_hold_active(self, active: bool):
        self._hold_active = active
        self._update_hold_style()

    def set_hold_affordance(self, allowed: bool, hint: str):
        self._hold_allowed = allowed
        if not self._hold_active:
            self._update_hold_style()

    def _update_hold_style(self):
        base_style = "font-family: 'Consolas', monospace; font-size: 11px; font-weight: bold; letter-spacing: 2px; padding: 12px; border-radius: 4px; "
        if self._hold_active:
            self.btn_hold.setText(">>> BACKWASH ACTIVE <<<")
            # 🚀 CHROMA GRADIENT: Pink -> Purple 🚀
            self.btn_hold.setStyleSheet(
                base_style + "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EC4899, stop:1 #8B5CF6); border: none; color: #FFFFFF;")
        elif not self._hold_allowed:
            self.btn_hold.setText("MANUAL CONTROL UNAVAILABLE")
            self.btn_hold.setStyleSheet(base_style + "background: #000000; border: 1px solid #1F2937; color: #4A5568;")
        else:
            self.btn_hold.setText("HOLD (SPACE / CLICK) TO BACKWASH")
            self.btn_hold.setStyleSheet(
                base_style + "background-color: #111827; border: 1px solid #2D3748; color: #EC4899;")

    def set_running(self, running: bool):
        widgets = [
            self.sp_hold_pressure, self.sp_hold_max, self.sp_bw1_dur, self.sp_bw1_p,
            self.sp_fill_t, self.sp_fill_r, self.sp_fill_h, self.sp_filt_dur,
            self.sp_filt_p, self.sp_vent_dur, self.sp_bw2_base, self.sp_bw2_p,
            self.sp_bw2_max
        ]
        for w in widgets:
            w.setEnabled(not running)