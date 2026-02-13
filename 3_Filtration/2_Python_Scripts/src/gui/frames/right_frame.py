from PySide6.QtWidgets import QFrame, QVBoxLayout, QProgressBar, QLabel


class RightFrame(QFrame):
    def __init__(self, config):
        super().__init__()
        layout = QVBoxLayout(self)

        self.step_label = QLabel("Step: IDLE")
        self.status_label = QLabel("Status: Idle")
        self.loss_label = QLabel("Loss (Filtration+Venting): 0.0 mL")

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)

        layout.addWidget(self.step_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.loss_label)
        layout.addWidget(self.progress)

    def set_step(self, step: str) -> None:
        self.step_label.setText(f"Step: {step}")

    def set_status(self, status: str) -> None:
        self.status_label.setText(f"Status: {status}")

    def set_loss(self, loss_ml: float) -> None:
        self.loss_label.setText(f"Loss (Filtration+Venting): {loss_ml:.3f} mL")

    def set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
