from PySide6.QtWidgets import QWidget

class WidgetFinder:
    def __init__(self, ui):
        self.ui = ui
        return

    def list_widgets_of_type(self, widget_type):
        widgets = self.ui.findChildren(widget_type)
        for w in widgets:
            print(f"{w.objectName()}: {type(w).__name__}")
        return

    def list_all_widgets(self):
        widgets = self.ui.findChildren(QWidget)
        for w in widgets:
            name = w.objectName()
            cls = type(w).__name__
            print(f"{name}: {cls}")
        return