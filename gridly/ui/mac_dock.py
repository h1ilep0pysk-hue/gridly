"""
ui/mac_dock.py
Плавающий Dock в стиле macOS для Gridly.

Dock — отдельное frameless-окно: он не перекрывает панель управления,
умеет прятаться к краю экрана, увеличивает иконки при наведении и
показывает, какой раздел Gridly открыт сейчас.
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRectF,
                          QSize, Qt, QTimer, pyqtProperty, pyqtSignal)
from PyQt6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QIcon,
                         QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
                         QPixmap, QRegion)
from PyQt6.QtWidgets import QBoxLayout, QWidget

from core.tweaks import MacTweaks
from ui.blur_effect import disable_blur, enable_fence_blur
from core.storage import hex_to_bgr

DOCK_ITEMS = [
    ("fences", "Фенсы", "Открыть фенсы"),
    ("widgets", "Виджеты", "Открыть виджеты"),
    ("customization", "Стиль", "Открыть кастомизацию"),
    ("tweaks", "Твики", "Открыть твики macOS"),
    ("launchpad", "Запуск", "Открыть Launchpad"),
    ("switcher", "Окна", "Переключить окно"),
    ("hide", "Скрыть", "Показать или скрыть всё на рабочем столе"),
    ("quit", "Выход", "Закрыть Gridly"),
]

SECTION_KEYS = ("fences", "widgets", "customization", "tweaks")

_ICON_COLORS = {
    "fences": ("#4facfe", "#1f6feb"),
    "widgets": ("#a78bfa", "#6d4aff"),
    "customization": ("#ffd166", "#f59e0b"),
    "tweaks": ("#ff8fab", "#e0447c"),
    "launchpad": ("#7dd3fc", "#0e7490"),
    "switcher": ("#c4b5fd", "#6d28d9"),
    "hide": ("#8e8e93", "#4b4b52"),
    "quit": ("#ff6b6b", "#c0392b"),
    "trash": ("#b9bec7", "#767b84"),
}


def _draw_dock_glyph(p: QPainter, rect: QRectF, key: str) -> None:
    """Рисует белую пиктограмму внутри цветной иконки Dock."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    pen = QPen(QColor(255, 255, 255, 238), max(1.4, w * 0.075),
               Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    if key == "fences":
        gap = w * 0.10
        cell = (w - gap * 3) / 2
        for row in range(2):
            for col in range(2):
                p.drawRoundedRect(
                    QRectF(x + gap + col * (cell + gap),
                           y + gap + row * (cell + gap), cell, cell),
                    cell * 0.24, cell * 0.24,
                )
    elif key == "widgets":
        p.drawRoundedRect(QRectF(x + w * 0.14, y + h * 0.16,
                                 w * 0.72, h * 0.30),
                          w * 0.10, w * 0.10)
        p.drawRoundedRect(QRectF(x + w * 0.14, y + h * 0.55,
                                 w * 0.36, h * 0.28),
                          w * 0.10, w * 0.10)
        p.drawRoundedRect(QRectF(x + w * 0.57, y + h * 0.55,
                                 w * 0.29, h * 0.28),
                          w * 0.10, w * 0.10)
    elif key == "customization":
        for i, knob in enumerate((0.34, 0.68, 0.46)):
            yy = y + h * (0.25 + i * 0.25)
            p.drawLine(QPoint(int(x + w * 0.18), int(yy)),
                       QPoint(int(x + w * 0.82), int(yy)))
            p.setBrush(QColor(255, 255, 255, 238))
            p.drawEllipse(QRectF(x + w * knob - w * 0.07,
                                 yy - w * 0.07, w * 0.14, w * 0.14))
            p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "tweaks":
        # Четырёхлучевая «искра» + маленькая звезда.
        cx, cy = x + w * 0.48, y + h * 0.50
        path = QPainterPath()
        path.moveTo(cx, cy - h * 0.29)
        path.quadTo(cx + w * 0.055, cy - h * 0.06,
                    cx + w * 0.28, cy)
        path.quadTo(cx + w * 0.055, cy + h * 0.06,
                    cx, cy + h * 0.29)
        path.quadTo(cx - w * 0.055, cy + h * 0.06,
                    cx - w * 0.28, cy)
        path.quadTo(cx - w * 0.055, cy - h * 0.06,
                    cx, cy - h * 0.29)
        p.setBrush(QColor(255, 255, 255, 238))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        p.drawEllipse(QRectF(x + w * 0.70, y + h * 0.18,
                             w * 0.10, w * 0.10))
    elif key == "launchpad":
        # Сетка 3×3, как в Launchpad.
        gap = w * 0.08
        cell = (w - gap * 4) / 3
        for row in range(3):
            for col in range(3):
                p.drawRoundedRect(
                    QRectF(x + gap + col * (cell + gap),
                           y + gap + row * (cell + gap), cell, cell),
                    cell * 0.28, cell * 0.28,
                )
    elif key == "switcher":
        # Два перекрывающихся окна.
        p.drawRoundedRect(QRectF(x + w * 0.10, y + h * 0.16,
                                 w * 0.56, h * 0.46),
                          w * 0.10, w * 0.10)
        p.setBrush(QColor(255, 255, 255, 238))
        p.drawRoundedRect(QRectF(x + w * 0.34, y + h * 0.38,
                                 w * 0.56, h * 0.46),
                          w * 0.10, w * 0.10)
        p.setBrush(Qt.BrushStyle.NoBrush)
    elif key == "hide":
        path = QPainterPath()
        path.moveTo(x + w * 0.14, y + h * 0.50)
        path.quadTo(x + w * 0.50, y + h * 0.20,
                    x + w * 0.86, y + h * 0.50)
        path.quadTo(x + w * 0.50, y + h * 0.80,
                    x + w * 0.14, y + h * 0.50)
        p.drawPath(path)
        p.setBrush(QColor(255, 255, 255, 238))
        p.drawEllipse(QRectF(x + w * 0.43, y + h * 0.43,
                             w * 0.14, w * 0.14))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPoint(int(x + w * 0.18), int(y + h * 0.82)),
                   QPoint(int(x + w * 0.82), int(y + h * 0.18)))
    elif key == "quit":
        p.drawArc(QRectF(x + w * 0.20, y + h * 0.20,
                         w * 0.60, h * 0.60), 45 * 16, 270 * 16)
        p.drawLine(QPoint(int(x + w * 0.50), int(y + h * 0.12)),
                   QPoint(int(x + w * 0.50), int(y + h * 0.46)))
    elif key == "trash":
        # Корзина: крышка + ведро + вертикальные рёбра.
        lid = QRectF(x + w * 0.22, y + h * 0.16, w * 0.56, h * 0.10)
        p.drawRoundedRect(lid, lid.height() / 2.0, lid.height() / 2.0)
        p.drawLine(QPoint(int(x + w * 0.50), int(y + h * 0.06)),
                   QPoint(int(x + w * 0.50), int(y + h * 0.14)))
        body = QRectF(x + w * 0.26, y + h * 0.28, w * 0.48, h * 0.58)
        p.drawRoundedRect(body, w * 0.08, w * 0.08)
        for offset in (0.10, 0.50, 0.90):
            rx = x + w * (0.26 + 0.48 * offset)
            p.drawLine(QPoint(int(rx + 0.5), int(y + h * 0.36)),
                       QPoint(int(rx + 0.5), int(y + h * 0.80)))
    p.restore()


def make_dock_icon(key: str, size: int = 64) -> QIcon:
    """Создаёт цветную иконку Dock для меню, Launchpad и списков."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(1, 1, size - 2, size - 2)
    radius = size * 0.235
    c1, c2 = _ICON_COLORS.get(key, ("#9aa4b2", "#5b6470"))
    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    grad.setColorAt(0.0, QColor(c1))
    grad.setColorAt(1.0, QColor(c2))
    p.setBrush(grad)
    p.setPen(QPen(QColor(255, 255, 255, 60), max(1.0, size * 0.015)))
    p.drawRoundedRect(rect, radius, radius)
    sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sheen.setColorAt(0.0, QColor(255, 255, 255, 80))
    sheen.setColorAt(0.55, QColor(255, 255, 255, 8))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(sheen)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(rect, radius, radius)
    inset = size * 0.23
    _draw_dock_glyph(p, rect.adjusted(inset, inset, -inset, -inset), key)
    p.end()
    return QIcon(pixmap)


class DockButton(QWidget):
    """Одна иконка Dock с увеличением и подписью."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, label: str, tooltip: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.label = label
        self.tooltip = tooltip
        self._base = 54
        self._labels = False
        self._dots = True
        self._magnify = True
        self._animations = True
        self._soft = False
        self._dark = True
        self._active = False
        self._running = False
        self._hovered = False
        self._zoom = 0.0
        self._accent = QColor("#0a84ff")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip(tooltip)
        self._anim = QPropertyAnimation(self, b"zoom", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._update_size()

    # ------------------------------------------------------------- config
    def configure(self, base: int, labels: bool, dots: bool,
                  magnify: bool, animations: bool, soft: bool) -> None:
        self._base = max(34, min(82, int(base)))
        self._labels = bool(labels)
        self._dots = bool(dots)
        self._magnify = bool(magnify)
        self._animations = bool(animations)
        self._soft = bool(soft)
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        pad = max(14, int(self._base * 0.28))
        width = self._base + pad
        height = self._base + pad
        if self._labels:
            height += 15
        if self._dots:
            height += 7
        self.setFixedSize(QSize(width, height))

    def set_active(self, value: bool) -> None:
        if self._active != value:
            self._active = bool(value)
            self.update()

    def set_running(self, value: bool) -> None:
        if self._running != value:
            self._running = bool(value)
            self.update()

    # --------------------------------------------------------------- zoom
    def get_zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float) -> None:
        self._zoom = max(0.0, min(1.0, float(value)))
        self.update()

    zoom = pyqtProperty(float, fget=get_zoom, fset=set_zoom)

    def _set_hovered(self, value: bool) -> None:
        if self._hovered == value:
            return
        self._hovered = value
        target = 1.0 if value and self._magnify else 0.0
        self._anim.stop()
        if self._animations:
            self._anim.setStartValue(self._zoom)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.set_zoom(target)

    def set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)
        self.update()

    # -------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        icon = self._base * (1.0 + 0.20 * self._zoom)
        top_area = self._base + max(14, int(self._base * 0.28))
        left = (self.width() - icon) / 2.0
        top = (top_area - icon) / 2.0 + 1.0
        rect = QRectF(left, top, icon, icon)
        radius = icon * 0.235

        # Мягкая тень под иконкой
        shadow = QColor(0, 0, 0, 95)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow)
        p.drawRoundedRect(rect.translated(0, 3.0), radius, radius)

        c1, c2 = _ICON_COLORS.get(self.key, ("#9aa4b2", "#5b6470"))
        if self._soft:
            c1 = QColor(c1).lighter(118).name()
            c2 = QColor(c2).lighter(112).name()
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, QColor(c1))
        grad.setColorAt(1.0, QColor(c2))
        p.setBrush(grad)
        p.setPen(QPen(QColor(255, 255, 255, 38), 1.0))
        p.drawRoundedRect(rect, radius, radius)

        # Блик сверху — «стеклянная» иконка
        sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 70))
        sheen.setColorAt(0.55, QColor(255, 255, 255, 8))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(sheen)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius, radius)

        inset = icon * 0.24
        _draw_dock_glyph(p, rect.adjusted(inset, inset, -inset, -inset),
                         self.key)

        if self._active:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self._accent, 2.0))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1),
                              radius - 1, radius - 1)

        text_top = top_area + 1
        if self._labels:
            font = QFont(p.font())
            font.setPixelSize(10)
            font.setWeight(QFont.Weight.Medium)
            p.setFont(font)
            p.setPen(QColor(255, 255, 255, 215) if self._dark
                     else QColor(29, 29, 31, 220))
            p.drawText(QRectF(0, text_top, self.width(), 14),
                       Qt.AlignmentFlag.AlignHCenter
                       | Qt.AlignmentFlag.AlignVCenter, self.label)
            text_top += 15

        if self._dots and self._running:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 220) if self._dark
                       else QColor(29, 29, 31, 190))
            dot = 4.0
            p.drawEllipse(QRectF((self.width() - dot) / 2.0,
                                 text_top + 1, dot, dot))
        p.end()

    # ------------------------------------------------------------- events
    def enterEvent(self, event) -> None:
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hovered(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and \
                self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self.key)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MacDock(QWidget):
    """Плавающая панель запуска разделов Gridly."""

    action_requested = pyqtSignal(str)
    position_changed = pyqtSignal(str)

    def __init__(self, tweaks: MacTweaks | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.tweaks = tweaks or MacTweaks()
        self._buttons: dict[str, DockButton] = {}
        self._active_key = "fences"
        self._hidden_by_autohide = False
        self._blur_enabled = False
        self._locked = False
        self._drag_offset: QPoint | None = None
        self._drag_moved = False

        self.setWindowTitle("Gridly Dock")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(9, 8, 9, 8)
        self._layout.setSpacing(7)
        for key, label, tip in DOCK_ITEMS:
            button = DockButton(key, label, tip, self)
            button.clicked.connect(self._on_click)
            self._layout.addWidget(button)
            self._buttons[key] = button

        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(120)
        self._edge_timer.timeout.connect(self._poll_edge)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(650)
        self._hide_timer.timeout.connect(self._autohide)

        self.apply_tweaks(self.tweaks)
        self.set_active(0)

    # ------------------------------------------------------------- config
    def _is_dark(self) -> bool:
        if self.tweaks.appearance == "dark":
            return True
        if self.tweaks.appearance == "light":
            return False
        palette = QGuiApplication.palette()
        return palette.color(QPalette.ColorRole.Window).lightness() < 128

    def apply_tweaks(self, tweaks: MacTweaks) -> None:
        self.tweaks = tweaks
        if self._locked:
            self._park()
            return
        enabled = bool(tweaks.enabled and tweaks.dock_enabled)
        dark = self._is_dark()
        for button in self._buttons.values():
            button._accent = QColor(tweaks.accent)
            button.set_dark(dark)
            button.configure(tweaks.dock_size, tweaks.dock_labels,
                             tweaks.dock_dots, tweaks.dock_magnify,
                             tweaks.animations, tweaks.soft_icons)
        if "launchpad" in self._buttons:
            self._buttons["launchpad"].setVisible(
                bool(tweaks.launchpad_enabled))
        if "switcher" in self._buttons:
            self._buttons["switcher"].setVisible(
                bool(tweaks.switcher_enabled))
        if tweaks.dock_position == "left":
            self._layout.setDirection(QBoxLayout.Direction.TopToBottom)
        elif tweaks.dock_position == "right":
            self._layout.setDirection(QBoxLayout.Direction.TopToBottom)
        else:
            self._layout.setDirection(QBoxLayout.Direction.LeftToRight)

        self.adjustSize()
        self._reposition()
        self.update()

        if not enabled:
            self._edge_timer.stop()
            self._hide_timer.stop()
            self._hidden_by_autohide = False
            self.hide()
            self._disable_blur()
            return

        if tweaks.dock_autohide:
            self._edge_timer.start()
            if not self._cursor_near_edge():
                self._hidden_by_autohide = True
                self.hide()
                return
        else:
            self._edge_timer.stop()
            self._hidden_by_autohide = False
        self._reveal()

    def set_active(self, index: int) -> None:
        keys = {0: "fences", 1: "widgets", 2: "customization", 3: "tweaks"}
        self._active_key = keys.get(index, "fences")
        for key, button in self._buttons.items():
            button.set_active(key == self._active_key)
            button.set_running(key in SECTION_KEYS)

    def set_locked(self, locked: bool) -> None:
        """Пока работает MyDock, обычный Dock Gridly уступает ему место."""
        locked = bool(locked)
        if self._locked == locked:
            return
        self._locked = locked
        if locked:
            self._park()
        else:
            self.apply_tweaks(self.tweaks)

    def _park(self) -> None:
        """Прячет панель и останавливает всё, что может её показать."""
        self._edge_timer.stop()
        self._hide_timer.stop()
        self._hidden_by_autohide = False
        self.hide()
        self._disable_blur()

    # -------------------------------------------------------------- layout
    def _reposition(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        full_screen = bool(self.tweaks.enabled and self.tweaks.shell_enabled)
        geo = screen.geometry() if full_screen else screen.availableGeometry()
        hint = self.sizeHint()
        width, height = hint.width(), hint.height()
        position = self.tweaks.dock_position
        if position == "left":
            x = geo.left() + 10
            y = geo.top() + (geo.height() - height) // 2
        elif position == "right":
            x = geo.right() - width - 10
            y = geo.top() + (geo.height() - height) // 2
        else:
            x = geo.left() + (geo.width() - width) // 2
            y = geo.bottom() - height - (12 if full_screen else 9)
        self.move(x, y)

    # ------------------------------------------------------------ autohide
    def _cursor_near_edge(self) -> bool:
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.availableGeometry()
        pos = QCursor.pos()
        if self.tweaks.dock_position == "left":
            return pos.x() <= geo.left() + 7
        if self.tweaks.dock_position == "right":
            return pos.x() >= geo.right() - 7
        return pos.y() >= geo.bottom() - 7

    def _poll_edge(self) -> None:
        if self._locked:
            self._park()
            return
        if not (self.tweaks.enabled and self.tweaks.dock_enabled
                and self.tweaks.dock_autohide):
            return
        if self._hidden_by_autohide:
            if self._cursor_near_edge():
                self._reveal()
        elif not self.geometry().adjusted(-10, -10, 10, 10).contains(
                QCursor.pos()) and not self._hide_timer.isActive():
            self._hide_timer.start()

    def _autohide(self) -> None:
        if self._locked:
            return
        if not (self.tweaks.enabled and self.tweaks.dock_enabled
                and self.tweaks.dock_autohide):
            return
        if self.geometry().adjusted(-4, -4, 4, 4).contains(QCursor.pos()):
            return
        self._hidden_by_autohide = True
        self.hide()

    def _reveal(self) -> None:
        if self._locked:
            self._park()
            return
        self._hidden_by_autohide = False
        self._hide_timer.stop()
        self.show()
        self.raise_()
        QTimer.singleShot(0, self._apply_blur)

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if (not self._locked and self.tweaks.enabled
                and self.tweaks.dock_enabled and self.tweaks.dock_autohide):
            self._hide_timer.start()
        super().leaveEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = QRectF(self.rect())
        radius = min(rect.height() / 2.0, 26.0)
        if self.tweaks.dock_position in ("left", "right"):
            radius = min(rect.width() / 2.0, 26.0)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._locked:
            QTimer.singleShot(0, self._park)
            return
        self._reposition()
        QTimer.singleShot(0, self._apply_blur)

    # --------------------------------------------------------------- blur
    def _apply_blur(self) -> None:
        if self._locked or not self.isVisible() or not self.tweaks.dock_glass:
            self._disable_blur()
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        alpha = max(40, min(210, 170 - int(self.tweaks.translucency)))
        tint = "#1c1c1e" if self._is_dark() else "#f2f3f7"
        try:
            enable_fence_blur(hwnd, hex_to_bgr(tint), alpha)
            self._blur_enabled = True
        except Exception:
            self._blur_enabled = False

    def _disable_blur(self) -> None:
        if not self._blur_enabled:
            return
        try:
            disable_blur(int(self.winId()))
        except Exception:
            pass
        self._blur_enabled = False

    # -------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        radius = min(rect.height() / 2.0, 26.0)
        if self.tweaks.dock_position in ("left", "right"):
            radius = min(rect.width() / 2.0, 26.0)

        if self.tweaks.shadows:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 95))
            p.drawRoundedRect(rect.translated(0, 4), radius, radius)

        dark = self._is_dark()
        if self.tweaks.dock_glass:
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if dark:
                grad.setColorAt(0.0, QColor(52, 54, 62, 226))
                grad.setColorAt(0.55, QColor(30, 31, 37, 218))
                grad.setColorAt(1.0, QColor(18, 19, 23, 210))
            else:
                grad.setColorAt(0.0, QColor(255, 255, 255, 232))
                grad.setColorAt(0.55, QColor(244, 245, 249, 224))
                grad.setColorAt(1.0, QColor(232, 234, 240, 216))
            p.setBrush(grad)
        else:
            p.setBrush(QColor(28, 29, 34, 245) if dark
                       else QColor(246, 247, 250, 250))
        p.setPen(QPen(QColor(255, 255, 255, 42) if dark
                      else QColor(0, 0, 0, 30), 1.0))
        p.drawRoundedRect(rect, radius, radius)

        if self.tweaks.dock_glass:
            sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if dark:
                sheen.setColorAt(0.0, QColor(255, 255, 255, 38))
                sheen.setColorAt(0.45, QColor(255, 255, 255, 4))
                sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            else:
                sheen.setColorAt(0.0, QColor(255, 255, 255, 210))
                sheen.setColorAt(0.45, QColor(255, 255, 255, 40))
                sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(sheen)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1),
                              radius - 1, radius - 1)
        p.end()

    # ------------------------------------------------------------- events
    def _on_click(self, key: str) -> None:
        self.action_requested.emit(key)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            self._drag_moved = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and \
                event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self._drag_moved = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            if self._drag_moved:
                self._snap_after_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _snap_after_drag(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        center = self.frameGeometry().center()
        distances = {
            "bottom": abs(geo.bottom() - center.y()),
            "left": abs(center.x() - geo.left()),
            "right": abs(geo.right() - center.x()),
        }
        position = min(distances, key=distances.get)
        self.tweaks.dock_position = position
        self.position_changed.emit(position)
        self.apply_tweaks(self.tweaks)

    def closeEvent(self, event) -> None:
        self._edge_timer.stop()
        self._hide_timer.stop()
        self._disable_blur()
        super().closeEvent(event)


def dock_available() -> bool:
    """Dock имеет смысл только на Windows, где работает acrylic."""
    return sys.platform.startswith("win")
