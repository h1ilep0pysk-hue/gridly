"""
ui/color_wheel.py
Круглая палитра (цветовое колесо) на PyQt6.

Позволяет выбрать цвет кликом или перетаскиванием курсора.
Используется в редакторе fence для настройки цвета фона.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class ColorWheel(QWidget):
    """Круглая палитра: угол — оттенок (hue), радиус — насыщенность (saturation)."""

    color_changed = pyqtSignal(QColor)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(43, 43, 43)
        self._hue = 0.0
        self._sat = 0.0
        self._image: QImage | None = None
        self._image_size = 0

        self.setFixedSize(180, 180)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------- API
    def set_color(self, color: QColor, emit: bool = False) -> None:
        """Устанавливает текущий цвет без испускания сигнала по умолчанию."""
        if not color.isValid():
            return
        self._color = QColor(color)
        hue, sat, _val, _alpha = color.getHsvF()
        self._hue = (hue * 360.0) if hue >= 0 else 0.0
        self._sat = max(0.0, min(1.0, sat))
        self.update()
        if emit:
            self.color_changed.emit(self._color)

    def color(self) -> QColor:
        return QColor(self._color)

    def sizeHint(self) -> QSize:
        return QSize(180, 180)

    # ---------------------------------------------------------- painting
    def paintEvent(self, event) -> None:
        size = min(self.width(), self.height())
        if self._image is None or self._image_size != size:
            self._build_image(size)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        x = (self.width() - size) // 2
        y = (self.height() - size) // 2
        p.drawImage(x, y, self._image)

        # Маркер выбранного цвета
        radius = size / 2.0 - 2.0
        cx = x + size / 2.0
        cy = y + size / 2.0
        angle = math.radians(self._hue)
        mx = cx + math.cos(angle) * radius * self._sat
        my = cy + math.sin(angle) * radius * self._sat

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 170), 3.0))
        p.drawEllipse(QPointF(mx, my), 7.0, 7.0)
        p.setPen(QPen(QColor(255, 255, 255, 235), 2.0))
        p.drawEllipse(QPointF(mx, my), 7.0, 7.0)
        p.end()

    def _build_image(self, size: int) -> None:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)

        cx = size / 2.0
        cy = size / 2.0
        radius = size / 2.0 - 2.0

        for y in range(size):
            dy = y + 0.5 - cy
            for x in range(size):
                dx = x + 0.5 - cx
                dist = math.hypot(dx, dy)
                if dist > radius:
                    continue

                hue = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
                sat = min(1.0, dist / radius)
                color = QColor.fromHsvF(hue / 360.0, sat, 1.0)

                # Мягкий край, чтобы круг не был «лесенкой»
                if dist > radius - 1.5:
                    color.setAlphaF(max(0.0, (radius - dist) / 1.5))

                image.setPixelColor(x, y, color)

        self._image = image
        self._image_size = size

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick(event.position())

    def _pick(self, pos: QPointF) -> None:
        size = min(self.width(), self.height())
        ox = (self.width() - size) / 2.0
        oy = (self.height() - size) / 2.0
        cx = ox + size / 2.0
        cy = oy + size / 2.0
        radius = size / 2.0 - 2.0

        dx = pos.x() - cx
        dy = pos.y() - cy
        dist = math.hypot(dx, dy)
        if dist > radius:
            if dist == 0:
                return
            dx *= radius / dist
            dy *= radius / dist
            dist = radius

        hue = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
        sat = max(0.0, min(1.0, dist / radius)) if radius else 0.0

        self._hue = hue
        self._sat = sat
        self._color = QColor.fromHsvF(hue / 360.0, sat, 1.0)
        self.update()
        self.color_changed.emit(self._color)
