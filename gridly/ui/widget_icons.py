"""
ui/widget_icons.py
Векторные иконки для конструктора и desktop-виджетов.

Иконки рисуются QPainter'ом, без эмодзи и внешних файлов, поэтому одинаково
чётко выглядят на любом DPI и в любой теме.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QIcon, QLinearGradient, QPainter,
                         QPainterPath, QPen, QPixmap)

from core.widget_storage import KIND_ACCENTS


def _cloud_path(x: float = 0.0, y: float = 0.0,
                scale: float = 1.0) -> QPainterPath:
    def box(cx: float, cy: float, w: float, h: float) -> QRectF:
        return QRectF(x + cx * scale, y + cy * scale, w * scale, h * scale)

    path = QPainterPath()
    path.addEllipse(box(0.16, 0.38, 0.30, 0.28))
    path.addEllipse(box(0.34, 0.24, 0.36, 0.36))
    path.addEllipse(box(0.56, 0.38, 0.28, 0.28))
    path.addRoundedRect(box(0.19, 0.47, 0.62, 0.22), 0.11 * scale,
                        0.11 * scale)
    return path.simplified()


def _sun(p: QPainter, color: QColor, cx: float, cy: float,
         radius: float) -> None:
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(cx, cy), radius, radius)
    p.setPen(QPen(color, 0.065, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    for i in range(8):
        angle = math.radians(i * 45.0)
        inner = radius * 1.55
        outer = radius * 2.15
        p.drawLine(
            QPointF(cx + math.cos(angle) * inner, cy + math.sin(angle) * inner),
            QPointF(cx + math.cos(angle) * outer, cy + math.sin(angle) * outer),
        )


def _draw_weather(p: QPainter, name: str, color: QColor) -> None:
    if name == "weather_sun":
        _sun(p, color, 0.5, 0.5, 0.17)
        return

    if name == "weather_moon":
        outer = QPainterPath()
        outer.addEllipse(QRectF(0.20, 0.18, 0.60, 0.60))
        inner = QPainterPath()
        inner.addEllipse(QRectF(0.34, 0.08, 0.56, 0.56))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(outer.subtracted(inner))
        return

    if name == "weather_partly":
        _sun(p, color, 0.36, 0.34, 0.115)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(_cloud_path(0.06, 0.18, 0.84))
        return

    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    if name == "weather_cloud":
        p.drawPath(_cloud_path(0.02, 0.04, 0.96))
    elif name == "weather_fog":
        p.drawPath(_cloud_path(0.02, -0.06, 0.96))
        p.setPen(QPen(color, 0.055, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for i, y in enumerate((0.72, 0.82, 0.92)):
            p.drawLine(QPointF(0.22 + i * 0.03, y), QPointF(0.78, y))
    elif name == "weather_rain":
        p.drawPath(_cloud_path(0.02, -0.04, 0.96))
        p.setPen(QPen(color, 0.055, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for i, x in enumerate((0.34, 0.50, 0.66)):
            p.drawLine(QPointF(x + 0.03, 0.70), QPointF(x - 0.03, 0.86))
    elif name == "weather_snow":
        p.drawPath(_cloud_path(0.02, -0.04, 0.96))
        p.setPen(QPen(color, 0.04, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for x in (0.34, 0.50, 0.66):
            for angle in (0.0, 60.0, 120.0):
                a = math.radians(angle)
                dx, dy = math.cos(a) * 0.055, math.sin(a) * 0.055
                p.drawLine(QPointF(x - dx, 0.79 - dy),
                           QPointF(x + dx, 0.79 + dy))
    elif name == "weather_thunder":
        p.drawPath(_cloud_path(0.02, -0.04, 0.96))
        p.setBrush(color)
        bolt = QPainterPath()
        bolt.moveTo(0.52, 0.60)
        bolt.lineTo(0.42, 0.78)
        bolt.lineTo(0.51, 0.78)
        bolt.lineTo(0.44, 0.96)
        bolt.lineTo(0.62, 0.72)
        bolt.lineTo(0.53, 0.72)
        bolt.lineTo(0.60, 0.60)
        bolt.closeSubpath()
        p.drawPath(bolt)
    else:
        p.drawPath(_cloud_path(0.02, 0.04, 0.96))


def _draw_kind(p: QPainter, kind: str, color: QColor,
               percent: float = 0.7) -> None:
    p.setPen(QPen(color, 0.065, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)

    if kind in ("weather", "weather_sun", "weather_moon", "weather_cloud",
                "weather_partly", "weather_rain", "weather_snow",
                "weather_thunder", "weather_fog"):
        _draw_weather(p, kind if kind.startswith("weather_") else "weather_sun",
                      color)
        return

    if kind == "clock":
        p.drawEllipse(QRectF(0.20, 0.20, 0.60, 0.60))
        p.drawLine(QPointF(0.50, 0.33), QPointF(0.50, 0.52))
        p.drawLine(QPointF(0.50, 0.52), QPointF(0.65, 0.60))
        return

    if kind == "date":
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0.20, 0.26, 0.60, 0.56), 0.10, 0.10)
        p.setBrush(QColor(0, 0, 0, 0))
        p.setPen(QPen(color, 0.05))
        p.drawRoundedRect(QRectF(0.20, 0.26, 0.60, 0.56), 0.10, 0.10)
        p.setPen(QPen(QColor(0, 0, 0, 90), 0.035))
        p.drawLine(QPointF(0.20, 0.40), QPointF(0.80, 0.40))
        p.setPen(QPen(QColor(0, 0, 0, 110), 0.035,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x in (0.32, 0.50, 0.68):
            for y in (0.52, 0.63, 0.74):
                p.drawPoint(QPointF(x, y))
        p.setPen(QPen(color, 0.05, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0.36, 0.18), QPointF(0.36, 0.30))
        p.drawLine(QPointF(0.64, 0.18), QPointF(0.64, 0.30))
        return

    if kind == "cpu":
        p.drawRoundedRect(QRectF(0.26, 0.26, 0.48, 0.48), 0.07, 0.07)
        p.drawRoundedRect(QRectF(0.40, 0.40, 0.20, 0.20), 0.03, 0.03)
        for t in (0.35, 0.50, 0.65):
            p.drawLine(QPointF(t, 0.16), QPointF(t, 0.26))
            p.drawLine(QPointF(t, 0.74), QPointF(t, 0.84))
            p.drawLine(QPointF(0.16, t), QPointF(0.26, t))
            p.drawLine(QPointF(0.74, t), QPointF(0.84, t))
        return

    if kind == "memory":
        p.drawRoundedRect(QRectF(0.14, 0.34, 0.72, 0.32), 0.05, 0.05)
        p.setBrush(color)
        for x in (0.25, 0.38, 0.51, 0.64):
            p.drawRoundedRect(QRectF(x, 0.42, 0.09, 0.13), 0.02, 0.02)
        p.setPen(QPen(color, 0.045, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for x in (0.24, 0.34, 0.44, 0.56, 0.66, 0.76):
            p.drawLine(QPointF(x, 0.66), QPointF(x, 0.76))
        return

    if kind == "battery":
        p.drawRoundedRect(QRectF(0.14, 0.30, 0.64, 0.40), 0.06, 0.06)
        p.drawRoundedRect(QRectF(0.79, 0.42, 0.07, 0.16), 0.02, 0.02)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        fill = max(0.02, min(0.92, percent))
        p.drawRoundedRect(QRectF(0.20, 0.36, 0.52 * fill, 0.28), 0.03, 0.03)
        return

    if kind == "disk":
        p.drawRoundedRect(QRectF(0.14, 0.32, 0.72, 0.38), 0.07, 0.07)
        p.drawEllipse(QRectF(0.66, 0.42, 0.12, 0.12))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0.22, 0.55, 0.32, 0.05), 0.02, 0.02)
        return

    if kind in ("text", "notes"):
        p.setPen(QPen(color, 0.055, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for y, x2 in ((0.30, 0.78), (0.46, 0.70), (0.62, 0.78),
                      (0.78, 0.58)):
            p.drawLine(QPointF(0.22, y), QPointF(x2, y))
        return

    if kind == "notepad":
        p.drawRoundedRect(QRectF(0.23, 0.13, 0.54, 0.74), 0.06, 0.06)
        p.setPen(QPen(color, 0.045, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for y, x2 in ((0.32, 0.67), (0.47, 0.61), (0.62, 0.67)):
            p.drawLine(QPointF(0.33, y), QPointF(x2, y))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        for y in (0.24, 0.40, 0.56, 0.72):
            p.drawEllipse(QPointF(0.18, y), 0.025, 0.025)
        return

    if kind == "calculator":
        p.drawRoundedRect(QRectF(0.22, 0.12, 0.56, 0.76), 0.08, 0.08)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0.30, 0.20, 0.40, 0.15), 0.03, 0.03)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(color, 0.05, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for y in (0.50, 0.64, 0.78):
            for x in (0.32, 0.50, 0.68):
                p.drawPoint(QPointF(x, y))
        return

    if kind == "todo":
        p.drawRoundedRect(QRectF(0.20, 0.12, 0.60, 0.76), 0.07, 0.07)
        p.setPen(QPen(color, 0.04, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for y, checked in ((0.32, True), (0.50, False), (0.68, False)):
            p.drawRect(QRectF(0.28, y - 0.055, 0.11, 0.11))
            if checked:
                p.drawLine(QPointF(0.30, y), QPointF(0.34, y + 0.04))
                p.drawLine(QPointF(0.34, y + 0.04), QPointF(0.40, y - 0.05))
            p.drawLine(QPointF(0.46, y), QPointF(0.72, y))
        return

    if kind == "plans":
        p.drawRoundedRect(QRectF(0.20, 0.12, 0.60, 0.76), 0.07, 0.07)
        p.setPen(QPen(color, 0.04, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for y, checked in ((0.30, True), (0.48, False), (0.66, False),
                           (0.82, False)):
            p.drawRect(QRectF(0.28, y - 0.045, 0.09, 0.09))
            if checked:
                p.drawLine(QPointF(0.29, y), QPointF(0.32, y + 0.035))
                p.drawLine(QPointF(0.32, y + 0.035), QPointF(0.37, y - 0.04))
            p.drawLine(QPointF(0.43, y), QPointF(0.71, y))
        return

    if kind == "music":
        p.setPen(QPen(color, 0.055, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0.38, 0.26), QPointF(0.38, 0.70))
        p.drawLine(QPointF(0.70, 0.18), QPointF(0.70, 0.62))
        p.drawLine(QPointF(0.38, 0.26), QPointF(0.70, 0.18))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0.31, 0.73), 0.085, 0.065)
        p.drawEllipse(QPointF(0.63, 0.65), 0.085, 0.065)
        return

    if kind == "browser":
        p.drawEllipse(QRectF(0.16, 0.16, 0.68, 0.68))
        p.drawEllipse(QRectF(0.36, 0.16, 0.28, 0.68))
        p.drawLine(QPointF(0.16, 0.50), QPointF(0.84, 0.50))
        return

    if kind == "spotify":
        p.drawEllipse(QRectF(0.14, 0.14, 0.72, 0.72))
        for y, span in ((0.36, 150), (0.50, 130), (0.64, 105)):
            p.drawArc(QRectF(0.28, y - 0.10, 0.44, 0.22), 25 * 16,
                      span * 16)
        return

    if kind == "soundcloud":
        p.drawPath(_cloud_path(0.02, 0.18, 0.80))
        p.setPen(QPen(color, 0.045, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for x, top in ((0.56, 0.44), (0.64, 0.36), (0.72, 0.42),
                       (0.80, 0.50)):
            p.drawLine(QPointF(x, top), QPointF(x, 0.78))
        return

    if kind == "yandex":
        p.drawEllipse(QRectF(0.14, 0.14, 0.72, 0.72))
        play = QPainterPath()
        play.moveTo(0.42, 0.32)
        play.lineTo(0.42, 0.68)
        play.lineTo(0.72, 0.50)
        play.closeSubpath()
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(play)
        return

    if kind == "file":
        p.drawRoundedRect(QRectF(0.22, 0.12, 0.56, 0.76), 0.06, 0.06)
        p.setPen(QPen(color, 0.045, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0.32, 0.28), QPointF(0.68, 0.28))
        p.drawLine(QPointF(0.32, 0.42), QPointF(0.58, 0.42))
        p.drawLine(QPointF(0.32, 0.56), QPointF(0.50, 0.56))
        return

    if kind == "countdown":
        p.drawLine(QPointF(0.26, 0.16), QPointF(0.74, 0.16))
        p.drawLine(QPointF(0.26, 0.84), QPointF(0.74, 0.84))
        top = QPainterPath()
        top.moveTo(0.30, 0.18)
        top.lineTo(0.70, 0.18)
        top.lineTo(0.50, 0.50)
        top.closeSubpath()
        bottom = QPainterPath()
        bottom.moveTo(0.30, 0.82)
        bottom.lineTo(0.70, 0.82)
        bottom.lineTo(0.50, 0.50)
        bottom.closeSubpath()
        p.drawPath(top)
        p.drawPath(bottom)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0.50, 0.66), 0.035, 0.035)
        return

    if kind == "stopwatch":
        p.drawEllipse(QRectF(0.20, 0.26, 0.60, 0.60))
        p.drawLine(QPointF(0.42, 0.14), QPointF(0.58, 0.14))
        p.drawLine(QPointF(0.50, 0.14), QPointF(0.50, 0.26))
        p.drawLine(QPointF(0.50, 0.56), QPointF(0.50, 0.42))
        p.drawLine(QPointF(0.50, 0.56), QPointF(0.62, 0.63))
        return

    if kind == "timer":
        p.drawArc(QRectF(0.20, 0.24, 0.60, 0.60), 60 * 16, 300 * 16)
        p.drawLine(QPointF(0.42, 0.12), QPointF(0.58, 0.12))
        p.drawLine(QPointF(0.50, 0.12), QPointF(0.50, 0.24))
        p.drawLine(QPointF(0.50, 0.54), QPointF(0.50, 0.40))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(0.50, 0.54), 0.035, 0.035)
        return

    if kind == "network":
        p.drawLine(QPointF(0.36, 0.20), QPointF(0.36, 0.78))
        p.drawLine(QPointF(0.36, 0.78), QPointF(0.26, 0.66))
        p.drawLine(QPointF(0.36, 0.78), QPointF(0.46, 0.66))
        p.drawLine(QPointF(0.64, 0.80), QPointF(0.64, 0.22))
        p.drawLine(QPointF(0.64, 0.22), QPointF(0.54, 0.34))
        p.drawLine(QPointF(0.64, 0.22), QPointF(0.74, 0.34))
        return

    if kind == "uptime":
        p.drawArc(QRectF(0.22, 0.24, 0.56, 0.56), 60 * 16, 300 * 16)
        p.drawLine(QPointF(0.50, 0.14), QPointF(0.50, 0.46))
        return

    if kind == "processes":
        for y in (0.28, 0.46, 0.64):
            p.drawRoundedRect(QRectF(0.18, y - 0.055, 0.12, 0.11),
                              0.025, 0.025)
            p.drawLine(QPointF(0.38, y), QPointF(0.78, y))
        return

    if kind == "quote":
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        for x in (0.20, 0.52):
            p.drawEllipse(QPointF(x + 0.07, 0.42), 0.07, 0.07)
            p.drawRoundedRect(QRectF(x + 0.01, 0.42, 0.12, 0.22),
                              0.04, 0.04)
        return

    if kind == "worldclock":
        p.drawEllipse(QRectF(0.16, 0.16, 0.68, 0.68))
        p.drawEllipse(QRectF(0.36, 0.16, 0.28, 0.68))
        p.drawLine(QPointF(0.16, 0.50), QPointF(0.84, 0.50))
        p.drawArc(QRectF(0.18, 0.28, 0.64, 0.44), 0, 180 * 16)
        p.drawArc(QRectF(0.18, 0.28, 0.64, 0.44), 180 * 16, 180 * 16)
        return

    if kind == "user":
        for y, knob in ((0.30, 0.38), (0.50, 0.64), (0.70, 0.46)):
            p.setPen(QPen(color, 0.05, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(0.18, y), QPointF(0.82, y))
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(knob, y), 0.075, 0.075)
        return

    if kind == "custom":
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.16, 0.16, 0.30, 0.30), 0.06, 0.06)
        p.drawRoundedRect(QRectF(0.54, 0.16, 0.30, 0.30), 0.06, 0.06)
        p.drawRoundedRect(QRectF(0.16, 0.54, 0.30, 0.30), 0.06, 0.06)
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0.54, 0.54, 0.30, 0.30), 0.06, 0.06)
        return

    # fallback
    p.drawEllipse(QRectF(0.25, 0.25, 0.50, 0.50))


def draw_kind_icon(p: QPainter, rect: QRectF, kind: str, color: QColor,
                   percent: float = 0.7) -> None:
    """Рисует иконку типа виджета в произвольный квадратный прямоугольник."""
    if rect.width() <= 0 or rect.height() <= 0:
        return
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(rect.topLeft())
    size = min(rect.width(), rect.height())
    p.scale(size, size)
    p.setPen(QPen(color, 0.065, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    _draw_kind(p, kind, color, percent)
    p.restore()


def draw_weather_icon(p: QPainter, rect: QRectF, name: str,
                      color: QColor) -> None:
    draw_kind_icon(p, rect, name, color)


def make_kind_icon(kind: str, size: int = 24,
                   color: QColor | None = None) -> QIcon:
    """Иконка для кнопок и списков."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if color is None:
        color = QColor(KIND_ACCENTS.get(kind, "#5cc8ff"))
    draw_kind_icon(p, QRectF(1, 1, size * 2 - 2, size * 2 - 2), kind, color)
    p.end()
    return QIcon(pm)


def make_preset_icon(kind: str, size: int = 34) -> QIcon:
    """Цветная плитка для галереи готовых шаблонов."""
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    accent = QColor(KIND_ACCENTS.get(kind, "#5cc8ff"))
    rect = QRectF(1, 1, size * 2 - 2, size * 2 - 2)
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, accent.lighter(125))
    grad.setColorAt(1.0, accent.darker(140))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(rect, size * 0.46, size * 0.46)

    inner = rect.adjusted(size * 0.52, size * 0.52,
                          -size * 0.52, -size * 0.52)
    draw_kind_icon(p, inner, kind, QColor(255, 255, 255, 235))
    p.end()
    return QIcon(pm)
