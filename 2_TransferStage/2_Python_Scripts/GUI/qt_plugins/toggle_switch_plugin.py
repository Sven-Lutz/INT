# toggle_switch_plugin.py
from PySide6.QtDesigner import QPyDesignerCustomWidgetPlugin
from PySide6.QtCore import Qt, QMetaObject, QMetaProperty
from toggle_switch import ToggleSwitch

class ToggleSwitchPlugin(QPyDesignerCustomWidgetPlugin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.initialized = False

    def initialize(self, core):
        if self.initialized:
            return
        self.initialized = True

    def isInitialized(self):
        return self.initialized

    def createWidget(self, parent):
        return ToggleSwitch(parent)

    def name(self):
        return "ToggleSwitch"

    def group(self):
        return "Custom Widgets"

    def icon(self):
        from PySide6.QtGui import QIcon
        return QIcon()  # You can use a real icon if you want

    def toolTip(self):
        return "Android-style toggle switch"

    def whatsThis(self):
        return "A smooth toggle switch"

    def isContainer(self):
        return False

    def includeFile(self):
        return "toggle_switch"  # The module name, no `.py`
