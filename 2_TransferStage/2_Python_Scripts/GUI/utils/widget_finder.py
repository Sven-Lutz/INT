from PySide6.QtWidgets import QWidget
def list_widgets_of_type(self, ui, widget_type):
    widgets = ui.findChildren(widget_type)
    for w in widgets:
        print(f"{w.objectName()}: {type(w).__name__}")


def list_all_widgets(self, ui):
    widgets = ui.findChildren(QWidget)
    for w in widgets:
        name = w.objectName()
        cls = type(w).__name__
        print(f"{name}: {cls}")
