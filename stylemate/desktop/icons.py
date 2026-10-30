"""Small original vector icons, rendered at device-independent resolution."""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def navigation_icon(name):
    canvas = QPixmap(48, 48)
    canvas.fill(Qt.GlobalColor.transparent)
    canvas.setDevicePixelRatio(2)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#626870"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin))
    if name == "wardrobe":
        painter.drawRoundedRect(QRectF(4, 3, 16, 17), 2, 2)
        painter.drawLine(12, 3, 12, 20)
        painter.drawPoint(9, 12)
        painter.drawPoint(15, 12)
        painter.drawLine(6, 20, 6, 22)
        painter.drawLine(18, 20, 18, 22)
    elif name == "outfits":
        path = QPainterPath(QPointF(10, 6))
        path.cubicTo(10, 1, 17, 3, 14, 7)
        path.lineTo(12, 9)
        path.lineTo(3, 17)
        path.lineTo(21, 17)
        path.lineTo(12, 9)
        painter.drawPath(path)
    elif name == "chat":
        path = QPainterPath(QPointF(5, 4))
        path.lineTo(20, 4)
        path.lineTo(20, 17)
        path.lineTo(9, 17)
        path.lineTo(4, 21)
        path.lineTo(4, 5)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawLine(8, 9, 16, 9)
        painter.drawLine(8, 13, 13, 13)
    elif name == "favorites":
        path = QPainterPath(QPointF(12, 20))
        path.cubicTo(-4, 10, 6, -3, 12, 7)
        path.cubicTo(18, -3, 28, 10, 12, 20)
        painter.drawPath(path)
    else:
        painter.drawEllipse(QRectF(7, 7, 10, 10))
        painter.drawEllipse(QRectF(10, 10, 4, 4))
        painter.translate(12, 12)
        for _ in range(8):
            painter.drawLine(0, 7, 0, 10)
            painter.rotate(45)
    painter.end()
    return QIcon(canvas)
