"""Shared small controls for explicit, safe configuration changes."""
from PySide6.QtWidgets import QComboBox


class PopupOnlyWheelComboBox(QComboBox):
    """Ignore wheel selection while closed, even when the combo has focus."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            # Let the enclosing scroll area handle scrolling.
            event.ignore()
