"""Shared native controls for the desktop workspace."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox


class ArrowComboBox(QComboBox):
    """Keep the dropdown affordance visible with the custom Qt stylesheet."""

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#747a80"), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        x, y = self.width() - 17, self.height() / 2 - 1
        painter.drawLine(QPointF(x - 4, y - 1), QPointF(x, y + 3))
        painter.drawLine(QPointF(x, y + 3), QPointF(x + 4, y - 1))
        painter.end()
