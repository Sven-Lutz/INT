from PySide6.QtCore import QObject, Signal, QTimer

from operations.dummy_operations.dummy_run import DummyOperation


class BaseOperation(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

class AddOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        print("AddOperation started")
        self.dummy.start()

    def stop(self):
        print("AddOperation stopped")
        self.dummy.stop()
        self.finished.emit()  # Emit manually if interrupted

    def _done(self):
        print("AddOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class RemoveOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        print("RemoveOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        print("RemoveOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        print("RemoveOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class FillOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        print("FillOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        print("FillOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        print("FillOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class EmptyOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        print("EmptyOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        print("EmptyOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        print("EmptyOperation finished")
        self.finished.emit()  # <-- notify OperationManager

class AutomaticOperation(BaseOperation):
    def __init__(self):
        super().__init__()
        self.dummy = DummyOperation()
        self.dummy.finished.connect(self._done)  # <-- critical line

    def start(self):
        print("AutomaticOperation started")
        self.dummy.start()
        #self.timer.start(3000)  # simulate a 3-second Operation

    def stop(self):
        print("AutomaticOperation stopped")
        self.dummy.stop()
        self.finished.emit()

    def _done(self):
        print("AutomaticOperation finished")
        self.finished.emit()  # <-- notify OperationManager