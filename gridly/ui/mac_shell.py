"""
ui/mac_shell.py
Системная macOS-оболочка поверх Windows.

Компоненты:
  * MacMenuBar — верхнее меню с яблоком, часами, батареей и пунктом
    управления;
  * Launchpad — полноэкранная сетка ярлыков из «Пуска» и с рабочего стола;
  * WindowSwitcher — переключатель открытых окон;
  * ControlCenter — компактная панель быстрых действий;
  * MacShell — контроллер, который прячет панель задач Windows, убирает
    окна Gridly с панели задач и регистрирует глобальные горячие клавиши.

Панель задач возвращается при выключении режима, выходе из Gridly и даже
при аварийном завершении процесса — за это отвечает отдельный watchdog.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
from datetime import datetime

from PyQt6.QtCore import (QAbstractNativeEventFilter, QFileInfo, QObject, QPoint,
                          QRectF, QSize, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication,
                         QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap)
from PyQt6.QtWidgets import (QApplication, QFileIconProvider, QFrame, QGridLayout,
                             QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                             QPushButton, QScrollArea, QSlider, QStyle,
                             QToolButton, QVBoxLayout, QWidget)

from core import win_shell
from core.storage import hex_to_bgr
from core.tweaks import MacTweaks
from ui.blur_effect import disable_blur, enable_fence_blur
from ui.mac_dock import make_dock_icon

HOTKEY_LAUNCHPAD = 0xB001
HOTKEY_SWITCHER = 0xB002
HOTKEY_RESTORE = 0xB003
HOTKEY_GRIDLY = 0xB004

_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек")


def _is_dark(tweaks: MacTweaks, fallback: bool = True) -> bool:
    if tweaks.appearance == "dark":
        return True
    if tweaks.appearance == "light":
        return False
    return bool(fallback)


def _clock_text() -> str:
    now = datetime.now()
    return (f"{_WEEKDAYS[now.weekday()]}, {now.day} "
            f"{_MONTHS[now.month - 1]}  {now:%H:%M}")


def _apple_path(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    body = QPainterPath()
    body.addEllipse(QRectF(x + w * 0.18, y + h * 0.30,
                           w * 0.64, h * 0.62))
    notch = QPainterPath()
    notch.addEllipse(QRectF(x + w * 0.39, y + h * 0.16,
                            w * 0.22, h * 0.26))
    body = body.subtracted(notch)
    leaf = QPainterPath()
    leaf.addEllipse(QRectF(x + w * 0.53, y + h * 0.09,
                           w * 0.18, h * 0.13))
    body.addPath(leaf)
    return body


def _apple_icon(color: QColor, size: int = 16) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(_apple_path(QRectF(0, 0, size, size)))
    painter.end()
    return QIcon(pixmap)


class IconCache:
    """Кэш иконок ярлыков и exe-файлов."""

    def __init__(self) -> None:
        self._provider: QFileIconProvider | None = None
        self._cache: dict[str, QIcon] = {}

    def get(self, path: str) -> QIcon:
        if not path:
            return QIcon()
        key = path.casefold()
        if key not in self._cache:
            if self._provider is None:
                self._provider = QFileIconProvider()
            icon = self._provider.icon(QFileInfo(path))
            if icon.isNull():
                icon = QApplication.style().standardIcon(
                    QStyle.StandardPixmap.SP_ComputerIcon)
            self._cache[key] = icon
        return self._cache[key]


_ICONS = IconCache()


class StatusButton(QWidget):
    """Маленькая иконка в правой части верхнего меню."""

    clicked = pyqtSignal()

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.kind = kind
        self._dark = True
        self._hover = False
        self._battery = -1
        self.setFixedSize(28, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setToolTip({
            "search": "Launchpad",
            "wifi": "Пункт управления",
            "battery": "Пункт управления",
            "control": "Пункт управления",
        }.get(kind, ""))

    def set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)
        self.update()

    def set_battery(self, percent: int) -> None:
        self._battery = int(percent)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 30) if self._dark
                       else QColor(0, 0, 0, 22))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1),
                              5, 5)
        color = QColor(245, 245, 247, 235) if self._dark \
            else QColor(29, 29, 31, 235)
        pen = QPen(color, 1.6, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = self.width() / 2.0, self.height() / 2.0

        if self.kind == "search":
            p.drawEllipse(QRectF(cx - 6.5, cy - 6.5, 9.5, 9.5))
            p.drawLine(QPoint(int(cx + 2), int(cy + 2)),
                       QPoint(int(cx + 7), int(cy + 7)))
        elif self.kind == "wifi":
            for radius in (3.0, 6.5, 10.0):
                p.drawArc(QRectF(cx - radius, cy + 3 - radius,
                                 radius * 2, radius * 2),
                          45 * 16, 90 * 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QRectF(cx - 1.2, cy + 3.5, 2.4, 2.4))
        elif self.kind == "battery":
            p.drawRoundedRect(QRectF(cx - 9, cy - 5, 18, 10), 3, 3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(cx + 9.5, cy - 2, 2, 4), 1, 1)
            if self._battery >= 0:
                fill = max(0, min(100, self._battery))
                width = 14.0 * fill / 100.0
                p.setBrush(QColor(48, 209, 88) if fill > 20 else QColor(255, 69, 58))
                p.drawRoundedRect(QRectF(cx - 7, cy - 3, width, 6), 1.5, 1.5)
        elif self.kind == "control":
            p.drawRoundedRect(QRectF(cx - 8, cy - 7, 16, 7), 3.5, 3.5)
            p.drawRoundedRect(QRectF(cx - 8, cy + 1, 16, 7), 3.5, 3.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QRectF(cx + 2, cy - 5.4, 4.4, 4.4))
            p.drawEllipse(QRectF(cx - 6.4, cy + 2.6, 4.4, 4.4))
        p.end()


class MacMenuBar(QWidget):
    """Верхняя строка macOS: меню, часы и быстрые значки."""

    action_requested = pyqtSignal(str)
    control_center_requested = pyqtSignal(object)

    def __init__(self, tweaks: MacTweaks, parent: QWidget | None = None):
        super().__init__(parent)
        self.tweaks = tweaks
        self._dark = True
        self._blur_enabled = False
        self._battery_percent = -1
        self._menus: dict[str, QMenu] = {}

        self.setWindowTitle("Gridly — меню macOS")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedHeight(30)
        self.setMouseTracking(True)

        self._build()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._battery_timer = QTimer(self)
        self._battery_timer.setInterval(30000)
        self._battery_timer.timeout.connect(self._update_battery)
        self._battery_timer.start()
        self._update_clock()
        self._update_battery()
        self.apply_tweaks(tweaks, True)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(1)

        self.apple_btn = QToolButton(self)
        self.apple_btn.setObjectName("appleButton")
        self.apple_btn.setFixedSize(30, 26)
        self.apple_btn.setIconSize(QSize(16, 16))
        self.apple_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apple_btn.setToolTip("Меню Gridly")
        layout.addWidget(self.apple_btn)

        self._menus["apple"] = self._make_menu("apple", [
            ("О Gridly", "about"),
            ("Твики macOS…", "tweaks"),
            (None, None),
            ("Скрыть Gridly", "hide_panel"),
            ("Вернуть панель задач Windows", "restore_taskbar"),
            ("Выйти из macOS-режима", "exit_mac"),
            (None, None),
            ("Завершить Gridly", "quit"),
        ])
        self.apple_btn.clicked.connect(
            lambda _c=False: self._popup_menu(self._menus["apple"],
                                              self.apple_btn)
        )

        self._menu_buttons: dict[str, QPushButton] = {}
        for title, key, items in (
            ("Gridly", "app", [
                ("Launchpad…", "launchpad"),
                ("Переключить окно…", "switcher"),
                ("Скрыть все окна", "minimize_all"),
                (None, None),
                ("Вернуть панель задач Windows", "restore_taskbar"),
                ("Выход", "quit"),
            ]),
            ("Файл", "file", [
                ("Launchpad…", "launchpad"),
                ("Переключить окно…", "switcher"),
                ("Скрыть все окна", "minimize_all"),
                (None, None),
                ("Вернуть панель задач Windows", "restore_taskbar"),
                ("Выход", "quit"),
            ]),
            ("Вид", "view", [
                ("Фенсы", "fences"),
                ("Виджеты", "widgets"),
                ("Кастомизация", "customization"),
                ("Твики", "tweaks"),
                (None, None),
                ("Свернуть все окна", "minimize_all"),
            ]),
            ("Окно", "window", [
                ("Переключатель окон…", "switcher"),
                ("Показать Gridly", "show_panel"),
                ("Скрыть Gridly", "hide_panel"),
                ("Свернуть все окна", "minimize_all"),
            ]),
            ("Помощь", "help", [
                ("Горячие клавиши", "shortcuts"),
                ("О программе", "about"),
            ]),
        ):
            button = QPushButton(title, self)
            button.setObjectName("menuBarItem")
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(24)
            if key == "app":
                font = button.font()
                font.setWeight(QFont.Weight.DemiBold)
                button.setFont(font)
            menu = self._make_menu(key, items)
            button.clicked.connect(
                lambda _c=False, m=menu, b=button: self._popup_menu(m, b)
            )
            layout.addWidget(button)
            self._menu_buttons[key] = button

        layout.addStretch(1)

        self.search_btn = StatusButton("search", self)
        self.wifi_btn = StatusButton("wifi", self)
        self.battery_btn = StatusButton("battery", self)
        self.control_btn = StatusButton("control", self)
        layout.addWidget(self.search_btn)
        layout.addWidget(self.wifi_btn)
        layout.addWidget(self.battery_btn)
        layout.addWidget(self.control_btn)

        self.clock = QLabel(self)
        self.clock.setObjectName("menuClock")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        self.clock.setMinimumWidth(128)
        layout.addWidget(self.clock)

        self.search_btn.clicked.connect(
            lambda: self.action_requested.emit("launchpad"))
        for button in (self.wifi_btn, self.battery_btn, self.control_btn):
            button.clicked.connect(self._emit_control_center)

    def _make_menu(self, key: str, items: list[tuple[str | None, str | None]]
                   ) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("macMenu")
        for title, action in items:
            if title is None:
                menu.addSeparator()
                continue
            item = menu.addAction(title)
            item.setData(action)
        menu.triggered.connect(
            lambda act: self.action_requested.emit(str(act.data()))
        )
        return menu

    def _popup_menu(self, menu: QMenu, button: QWidget) -> None:
        menu.popup(button.mapToGlobal(QPoint(0, button.height() + 2)))

    def _emit_control_center(self) -> None:
        self.control_center_requested.emit(
            self.control_btn.mapToGlobal(QPoint(0, self.control_btn.height() + 2))
        )

    # ------------------------------------------------------------- config
    def apply_tweaks(self, tweaks: MacTweaks, fallback_dark: bool = True) -> None:
        self.tweaks = tweaks
        self._dark = _is_dark(tweaks, fallback_dark)
        text = "#f5f5f7" if self._dark else "#1d1d1f"
        hover = "rgba(255, 255, 255, 30)" if self._dark \
            else "rgba(0, 0, 0, 20)"
        menu_bg = "#242428" if self._dark else "#f7f7f9"
        menu_border = "rgba(255, 255, 255, 38)" if self._dark \
            else "rgba(0, 0, 0, 30)"
        accent = tweaks.accent
        self.setStyleSheet(f"""
            QToolButton#appleButton {{
                background: transparent; border: none; border-radius: 5px;
            }}
            QToolButton#appleButton:hover {{ background: {hover}; }}
            QPushButton#menuBarItem {{
                background: transparent; border: none; color: {text};
                padding: 3px 9px; border-radius: 5px; font-size: 13px;
            }}
            QPushButton#menuBarItem:hover {{ background: {hover}; }}
            QLabel#menuClock {{
                color: {text}; font-size: 12px; padding: 0 6px;
            }}
            QMenu#macMenu {{
                background: {menu_bg}; color: {text};
                border: 1px solid {menu_border}; border-radius: 10px;
                padding: 5px;
            }}
            QMenu#macMenu::item {{
                padding: 6px 26px 6px 12px; border-radius: 6px;
            }}
            QMenu#macMenu::item:selected {{
                background: {accent}; color: #ffffff;
            }}
            QMenu#macMenu::separator {{
                height: 1px; background: {menu_border};
                margin: 5px 8px;
            }}
        """)
        self.apple_btn.setIcon(
            _apple_icon(QColor(text), 16)
        )
        self.search_btn.set_dark(self._dark)
        self.wifi_btn.set_dark(self._dark)
        self.battery_btn.set_dark(self._dark)
        self.control_btn.set_dark(self._dark)
        self._update_battery()
        self._reposition()
        if self.isVisible():
            QTimer.singleShot(0, self._apply_blur)

    def _reposition(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        self.setGeometry(geo.x(), geo.y(), geo.width(), 30)

    def show_at_top(self) -> None:
        self._reposition()
        self.show()
        self.raise_()
        QTimer.singleShot(0, self._apply_blur)

    # --------------------------------------------------------------- clock
    def _update_clock(self) -> None:
        self.clock.setText(_clock_text())

    def _update_battery(self) -> None:
        percent = -1
        try:
            import psutil
            battery = psutil.sensors_battery()
            if battery is not None:
                percent = int(round(battery.percent))
        except (ImportError, AttributeError, OSError):
            percent = -1
        self._battery_percent = percent
        self.battery_btn.setVisible(percent >= 0)
        self.battery_btn.set_battery(percent)

    # --------------------------------------------------------------- blur
    def _apply_blur(self) -> None:
        if not self.isVisible() or not self.tweaks.glass:
            self._disable_blur()
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        tint = hex_to_bgr("#1c1c1e" if self._dark else "#f2f2f7")
        alpha = max(80, min(220, 90 + int(self.tweaks.blur_strength)))
        try:
            enable_fence_blur(hwnd, tint, alpha)
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
    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_blur)

    def hideEvent(self, event) -> None:
        self._disable_blur()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._disable_blur()
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        if self._dark:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0.0, QColor(38, 39, 44, 225))
            gradient.setColorAt(1.0, QColor(24, 25, 29, 218))
            p.setBrush(gradient)
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0.0, QColor(255, 255, 255, 230))
            gradient.setColorAt(1.0, QColor(240, 241, 245, 224))
            p.setBrush(gradient)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(rect)
        p.setPen(QPen(QColor(255, 255, 255, 34) if self._dark
                      else QColor(0, 0, 0, 24), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class ControlCenter(QWidget):
    """Компактная панель быстрых действий под верхним меню."""

    action_requested = pyqtSignal(str)
    tweak_requested = pyqtSignal(str, int)

    def __init__(self, tweaks: MacTweaks, parent: QWidget | None = None):
        super().__init__(parent)
        self.tweaks = tweaks
        self._dark = True
        self._loading = False
        self._blur_enabled = False
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(338)
        self._build()
        self.apply_tweaks(tweaks, True)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(10)

        title = QLabel("Пункт управления")
        title.setObjectName("ccTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(8)
        for index, (text, action) in enumerate((
            ("Твики", "tweaks"),
            ("Launchpad", "launchpad"),
            ("Окна", "switcher"),
            ("Скрыть всё", "hide_all"),
        )):
            button = QPushButton(text)
            button.setObjectName("ccTile")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(42)
            button.clicked.connect(
                lambda _c=False, a=action: self.action_requested.emit(a)
            )
            grid.addWidget(button, index // 2, index % 2)
        layout.addLayout(grid)

        self._translucency = self._slider(
            layout, "Прозрачность", "translucency", 0, 100)
        self._blur = self._slider(
            layout, "Сила размытия", "blur_strength", 0, 100)

        restore = QPushButton("Вернуть панель задач Windows")
        restore.setObjectName("ccDanger")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.setFixedHeight(38)
        restore.clicked.connect(
            lambda _c=False: self.action_requested.emit("restore_taskbar"))
        layout.addWidget(restore)

    def _slider(self, layout: QVBoxLayout, title: str, attr: str,
                minimum: int, maximum: int) -> QSlider:
        row = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("ccLabel")
        value = QLabel("0")
        value.setObjectName("ccValue")
        value.setMinimumWidth(38)
        value.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.valueChanged.connect(
            lambda number, key=attr, lbl=value:
            self._on_slider(key, number, lbl)
        )
        row.addWidget(label)
        row.addWidget(slider, 1)
        row.addWidget(value)
        layout.addLayout(row)
        setattr(self, f"_{attr}_label", value)
        return slider

    def _on_slider(self, attr: str, value: int, label: QLabel) -> None:
        label.setText(str(value))
        if not self._loading:
            self.tweak_requested.emit(attr, int(value))

    def apply_tweaks(self, tweaks: MacTweaks, fallback_dark: bool = True) -> None:
        self.tweaks = tweaks
        self._dark = _is_dark(tweaks, fallback_dark)
        text = "#f5f5f7" if self._dark else "#1d1d1f"
        muted = "rgba(235, 235, 240, 150)" if self._dark \
            else "rgba(40, 40, 45, 150)"
        tile = "rgba(255, 255, 255, 26)" if self._dark \
            else "rgba(0, 0, 0, 14)"
        tile_hover = "rgba(255, 255, 255, 44)" if self._dark \
            else "rgba(0, 0, 0, 26)"
        border = "rgba(255, 255, 255, 40)" if self._dark \
            else "rgba(0, 0, 0, 30)"
        accent = tweaks.accent
        self.setStyleSheet(f"""
            QLabel#ccTitle {{ color: {text}; font-size: 14px;
                              font-weight: 700; }}
            QLabel#ccLabel {{ color: {text}; font-size: 12px; }}
            QLabel#ccValue {{ color: {muted}; font-size: 11px; }}
            QPushButton#ccTile {{
                background: {tile}; border: 1px solid {border};
                border-radius: 10px; color: {text}; font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#ccTile:hover {{ background: {tile_hover}; }}
            QPushButton#ccDanger {{
                background: rgba(255, 69, 58, 30);
                border: 1px solid rgba(255, 69, 58, 110);
                border-radius: 10px; color: #ff6b63; font-size: 12px;
                font-weight: 600;
            }}
            QPushButton#ccDanger:hover {{ background: rgba(255, 69, 58, 55); }}
            QSlider::groove:horizontal {{
                height: 4px; border-radius: 2px; background: {tile};
            }}
            QSlider::sub-page:horizontal {{
                height: 4px; border-radius: 2px; background: {accent};
            }}
            QSlider::handle:horizontal {{
                width: 14px; margin: -5px 0; border-radius: 7px;
                background: {accent}; border: 2px solid transparent;
            }}
        """)
        self._loading = True
        self._translucency.setValue(int(tweaks.translucency))
        self._blur.setValue(int(tweaks.blur_strength))
        self._translucency_label.setText(str(int(tweaks.translucency)))
        self._blur_strength_label.setText(str(int(tweaks.blur_strength)))
        self._loading = False
        self.adjustSize()
        if self.isVisible():
            QTimer.singleShot(0, self._apply_blur)

    def show_at(self, point: QPoint) -> None:
        self.adjustSize()
        screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            x = max(geo.left() + 8,
                    min(point.x() - self.width() + 24,
                        geo.right() - self.width() - 8))
            y = min(point.y() + 8, geo.bottom() - self.height() - 8)
        else:
            x, y = point.x(), point.y()
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(0, self._apply_blur)

    def _apply_blur(self) -> None:
        if not self.isVisible() or not self.tweaks.glass:
            self._disable_blur()
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        tint = hex_to_bgr("#1c1c1e" if self._dark else "#f2f2f7")
        alpha = max(90, min(220, 100 + int(self.tweaks.blur_strength)))
        try:
            enable_fence_blur(hwnd, tint, alpha)
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

    def hideEvent(self, event) -> None:
        self._disable_blur()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(7, 7, -7, -7)
        for index in range(6, 0, -1):
            spread = index * 2.0
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, max(4, 30 - index * 4)))
            p.drawRoundedRect(rect.adjusted(-spread, -spread + 5,
                                            spread, spread + 5),
                              18 + spread, 18 + spread)
        p.setBrush(QColor(32, 33, 38, 242) if self._dark
                   else QColor(250, 250, 252, 246))
        p.setPen(QPen(QColor(255, 255, 255, 46) if self._dark
                      else QColor(0, 0, 0, 28), 1))
        p.drawRoundedRect(rect, 18, 18)
        p.end()


class AppTile(QToolButton):
    """Иконка приложения в Launchpad."""

    def __init__(self, title: str, icon: QIcon, action: str, payload: str,
                 dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.action_key = action
        self.payload = payload
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIcon(icon)
        self.setIconSize(QSize(50, 50))
        self.setFixedSize(118, 96)
        font = QFont(self.font())
        font.setPixelSize(11)
        self.setFont(font)
        metrics = QFontMetrics(font)
        self.setText(metrics.elidedText(
            title, Qt.TextElideMode.ElideRight, 104))
        self.setToolTip(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        text = "#f5f5f7" if dark else "#1d1d1f"
        hover = "rgba(255, 255, 255, 30)" if dark else "rgba(0, 0, 0, 16)"
        self.setStyleSheet(f"""
            QToolButton {{
                border: none; border-radius: 13px; color: {text};
                padding: 7px 4px 5px 4px; background: transparent;
            }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: rgba(120, 120, 128, 70); }}
        """)


class WindowTile(QToolButton):
    """Одна строка в переключателе окон."""

    def __init__(self, title: str, subtitle: str, icon: QIcon,
                 hwnd: int, dark: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.hwnd = int(hwnd)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(icon)
        self.setIconSize(QSize(32, 32))
        self.setFixedSize(378, 60)
        font = QFont(self.font())
        font.setPixelSize(12)
        self.setFont(font)
        metrics = QFontMetrics(font)
        label = metrics.elidedText(title, Qt.TextElideMode.ElideRight, 300)
        self.setText(f"{label}\n{subtitle}")
        self.setToolTip(f"{title}\n{subtitle}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        text = "#f5f5f7" if dark else "#1d1d1f"
        muted = "rgba(235, 235, 240, 150)" if dark \
            else "rgba(40, 40, 45, 150)"
        hover = "rgba(255, 255, 255, 30)" if dark else "rgba(0, 0, 0, 16)"
        self.setStyleSheet(f"""
            QToolButton {{
                border: none; border-radius: 12px; color: {text};
                padding: 8px 12px; text-align: left; background: transparent;
                font-size: 12px;
            }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed {{ background: rgba(120, 120, 128, 70); }}
            QToolButton:disabled {{ color: {muted}; }}
        """)


class Launchpad(QWidget):
    """Полноэкранная сетка ярлыков программ."""

    action_requested = pyqtSignal(str)
    app_launched = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._dark = True
        self._apps: list[dict] = []
        self._builtins = [
            ("Фенсы", "fences", make_dock_icon("fences", 64)),
            ("Виджеты", "widgets", make_dock_icon("widgets", 64)),
            ("Твики", "tweaks", make_dock_icon("tweaks", 64)),
            ("Стиль", "customization", make_dock_icon("customization", 64)),
        ]
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build()
        self.apply_theme(True)

    def _build(self) -> None:
        self._panel = QFrame(self)
        self._panel.setObjectName("launchpadPanel")
        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Launchpad")
        title.setObjectName("launchpadTitle")
        hint = QLabel("Esc — закрыть")
        hint.setObjectName("launchpadHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)

        self._search = QLineEdit()
        self._search.setObjectName("launchpadSearch")
        self._search.setPlaceholderText("Поиск программ…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._populate)
        layout.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._host.setObjectName("launchpadHost")
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(4, 6, 4, 6)
        self._grid.setSpacing(6)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)

    def apply_theme(self, dark: bool) -> None:
        if self._dark == dark and self._panel.styleSheet():
            return
        self._dark = bool(dark)
        text = "#f5f5f7" if dark else "#1d1d1f"
        muted = "rgba(235, 235, 240, 150)" if dark \
            else "rgba(40, 40, 45, 150)"
        panel_bg = "rgba(30, 31, 36, 242)" if dark \
            else "rgba(250, 250, 252, 246)"
        border = "rgba(255, 255, 255, 42)" if dark \
            else "rgba(0, 0, 0, 26)"
        field_bg = "rgba(255, 255, 255, 24)" if dark \
            else "rgba(0, 0, 0, 12)"
        self._panel.setStyleSheet(f"""
            QFrame#launchpadPanel {{
                background: {panel_bg};
                border: 1px solid {border};
                border-radius: 24px;
            }}
            QLabel#launchpadTitle {{
                color: {text}; font-size: 22px; font-weight: 700;
            }}
            QLabel#launchpadHint {{ color: {muted}; font-size: 11px; }}
            QLineEdit#launchpadSearch {{
                background: {field_bg}; border: 1px solid {border};
                border-radius: 10px; padding: 8px 12px; color: {text};
                font-size: 13px;
            }}
            QWidget#launchpadHost {{ background: transparent; }}
            QScrollArea {{ background: transparent; border: none; }}
        """)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._host.setStyleSheet("background: transparent;")
        if self.isVisible():
            self._populate()

    def refresh_apps(self) -> None:
        self._apps = win_shell.list_apps()

    def show_launchpad(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.refresh_apps()
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._populate()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    def _populate(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        query = self._search.text().strip().casefold()
        entries: list[tuple[str, str, str, QIcon]] = []
        for title, action, icon in self._builtins:
            if not query or query in title.casefold():
                entries.append((title, "gridly", action, icon))
        for app in self._apps:
            name = str(app.get("name", ""))
            if query and query not in name.casefold():
                continue
            entries.append((
                name, "app", str(app.get("path", "")),
                _ICONS.get(str(app.get("path", ""))),
            ))
        columns = 6
        for index, (title, action, payload, icon) in enumerate(entries):
            tile = AppTile(title, icon, action, payload, self._dark, self._host)
            tile.clicked.connect(
                lambda _c=False, t=tile: self._activate_tile(t))
            self._grid.addWidget(tile, index // columns, index % columns)
        rows = (len(entries) + columns - 1) // columns
        if not entries:
            empty = QLabel("Ничего не найдено")
            empty.setObjectName("launchpadHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(empty, 0, 0, 1, columns)
            rows = 1
        self._grid.setRowStretch(rows, 1)

    def _activate_tile(self, tile: AppTile) -> None:
        if tile.action_key == "gridly":
            self.hide()
            self.action_requested.emit(tile.payload)
            return
        if win_shell.launch_path(tile.payload):
            self.app_launched.emit(tile.payload)
            self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = min(980, max(620, self.width() - 160))
        height = min(660, max(430, self.height() - 150))
        self._panel.setGeometry(
            (self.width() - width) // 2,
            (self.height() - height) // 2,
            width, height,
        )

    def mousePressEvent(self, event) -> None:
        if not self._panel.geometry().contains(event.position().toPoint()):
            self.hide()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110 if self._dark else 70))
        p.end()


class WindowSwitcher(QWidget):
    """Переключатель открытых окон других приложений."""

    window_activated = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._dark = True
        self._windows: list[win_shell.WindowInfo] = []
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._build()
        self.apply_theme(True)

    def _build(self) -> None:
        self._panel = QFrame(self)
        self._panel.setObjectName("switcherPanel")
        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Переключение окон")
        title.setObjectName("switcherTitle")
        hint = QLabel("Esc — закрыть")
        hint.setObjectName("switcherHint")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(hint)
        layout.addLayout(header)

        self._search = QLineEdit()
        self._search.setObjectName("switcherSearch")
        self._search.setPlaceholderText("Поиск окна…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._populate)
        layout.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._host = QWidget()
        self._host.setObjectName("switcherHost")
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(4, 6, 4, 6)
        self._grid.setSpacing(4)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)

    def apply_theme(self, dark: bool) -> None:
        if self._dark == dark and self._panel.styleSheet():
            return
        self._dark = bool(dark)
        text = "#f5f5f7" if dark else "#1d1d1f"
        muted = "rgba(235, 235, 240, 150)" if dark \
            else "rgba(40, 40, 45, 150)"
        panel_bg = "rgba(30, 31, 36, 242)" if dark \
            else "rgba(250, 250, 252, 246)"
        border = "rgba(255, 255, 255, 42)" if dark \
            else "rgba(0, 0, 0, 26)"
        field_bg = "rgba(255, 255, 255, 24)" if dark \
            else "rgba(0, 0, 0, 12)"
        self._panel.setStyleSheet(f"""
            QFrame#switcherPanel {{
                background: {panel_bg}; border: 1px solid {border};
                border-radius: 22px;
            }}
            QLabel#switcherTitle {{
                color: {text}; font-size: 20px; font-weight: 700;
            }}
            QLabel#switcherHint {{ color: {muted}; font-size: 11px; }}
            QLineEdit#switcherSearch {{
                background: {field_bg}; border: 1px solid {border};
                border-radius: 10px; padding: 8px 12px; color: {text};
                font-size: 13px;
            }}
            QWidget#switcherHost {{ background: transparent; }}
            QScrollArea {{ background: transparent; border: none; }}
        """)
        self._scroll.setStyleSheet("background: transparent; border: none;")
        self._host.setStyleSheet("background: transparent;")
        if self.isVisible():
            self._populate()

    def show_switcher(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self._windows = win_shell.list_windows({os.getpid()})
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._populate()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search.setFocus()

    def _populate(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        query = self._search.text().strip().casefold()
        entries = [
            info for info in self._windows
            if not query
            or query in info.title.casefold()
            or query in os.path.basename(info.exe).casefold()
        ]
        for index, info in enumerate(entries):
            subtitle = os.path.basename(info.exe) or "Приложение"
            tile = WindowTile(
                info.title, subtitle, _ICONS.get(info.exe),
                info.hwnd, self._dark, self._host,
            )
            tile.clicked.connect(
                lambda _c=False, t=tile: self._activate(t))
            self._grid.addWidget(tile, index // 2, index % 2)
        rows = (len(entries) + 1) // 2
        if not entries:
            empty = QLabel("Открытых окон нет")
            empty.setObjectName("switcherHint")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(empty, 0, 0, 1, 2)
            rows = 1
        self._grid.setRowStretch(rows, 1)

    def _activate(self, tile: WindowTile) -> None:
        win_shell.activate_window(tile.hwnd)
        self.window_activated.emit(tile.hwnd)
        self.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        width = min(840, max(620, self.width() - 200))
        height = min(560, max(400, self.height() - 190))
        self._panel.setGeometry(
            (self.width() - width) // 2,
            (self.height() - height) // 2,
            width, height,
        )

    def mousePressEvent(self, event) -> None:
        if not self._panel.geometry().contains(event.position().toPoint()):
            self.hide()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110 if self._dark else 70))
        p.end()


class HotkeyFilter(QAbstractNativeEventFilter):
    """Ловит WM_HOTKEY от RegisterHotKey."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type in ("windows_generic_MSG", "windows_dispatcher_MSG",
                          b"windows_generic_MSG",
                          b"windows_dispatcher_MSG"):
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                return False, 0
            if msg.message == 0x0312:
                self._callback(int(msg.wParam))
        return False, 0


class MacShell(QObject):
    """Управляет системной оболочкой и связывает её с Gridly."""

    def __init__(self, panel, tweaks: MacTweaks):
        super().__init__(panel)
        self.panel = panel
        self.tweaks = tweaks
        self._active = False
        self._hotkeys_registered = False
        self._hotkey_filter: HotkeyFilter | None = None

        self.menu_bar = MacMenuBar(tweaks)
        self.launchpad = Launchpad()
        self.switcher = WindowSwitcher()
        self.control_center = ControlCenter(tweaks)

        self.menu_bar.action_requested.connect(self._on_action)
        self.menu_bar.control_center_requested.connect(self.show_control_center)
        self.control_center.action_requested.connect(self._on_action)
        self.control_center.tweak_requested.connect(self._on_tweak)
        self.launchpad.action_requested.connect(self._on_action)
        self.switcher.window_activated.connect(lambda _hwnd: None)

        self._taskbar_timer = QTimer(self)
        self._taskbar_timer.setInterval(1200)
        self._taskbar_timer.timeout.connect(self._keep_taskbar_hidden)

    # ------------------------------------------------------------- config
    def apply(self, tweaks: MacTweaks) -> None:
        self.tweaks = tweaks
        dark = _is_dark(tweaks, getattr(self.panel, "_dark", True))
        self.menu_bar.apply_tweaks(tweaks, dark)
        self.control_center.apply_tweaks(tweaks, dark)
        self.launchpad.apply_theme(dark)
        self.switcher.apply_theme(dark)

        if not tweaks.enabled:
            self.shutdown()
            return

        if tweaks.shell_enabled:
            win_shell.hide_taskbar()
            self._taskbar_timer.start()
        else:
            self._taskbar_timer.stop()
            win_shell.show_taskbar()

        if tweaks.menu_bar:
            self.menu_bar.show_at_top()
        else:
            self.menu_bar.hide()
            self.control_center.hide()

        self._set_taskbar_buttons(not tweaks.hide_from_taskbar)

        if tweaks.hotkeys:
            self._register_hotkeys()
        else:
            self._unregister_hotkeys()

        self._active = True
        if tweaks.shell_enabled:
            QTimer.singleShot(250, self._refresh_dock_position)

    def shutdown(self) -> None:
        """Возвращает панель задач и убирает все окна оболочки."""
        was_active = self._active
        self._taskbar_timer.stop()
        self._unregister_hotkeys()
        self.launchpad.hide()
        self.switcher.hide()
        self.control_center.hide()
        self.menu_bar.hide()
        win_shell.show_taskbar()
        if was_active:
            self._set_taskbar_buttons(True)
        self._active = False

    def _keep_taskbar_hidden(self) -> None:
        if self.tweaks.enabled and self.tweaks.shell_enabled:
            win_shell.ensure_taskbar_hidden()

    def _refresh_dock_position(self) -> None:
        dock = getattr(self.panel, "dock", None)
        if dock is not None and dock.isVisible():
            dock._reposition()

    def _set_taskbar_buttons(self, show: bool) -> None:
        windows = [self.panel]
        manager = getattr(self.panel, "manager", None)
        if manager is not None:
            windows.extend(list(manager.widgets.values()))
        widget_manager = getattr(self.panel, "widget_manager", None)
        if widget_manager is not None:
            windows.extend(list(widget_manager.widgets.values()))
        for window in windows:
            try:
                hwnd = int(window.winId())
            except (RuntimeError, TypeError, ValueError):
                continue
            try:
                if show:
                    win_shell.show_in_taskbar(hwnd)
                else:
                    win_shell.hide_from_taskbar(hwnd)
            except OSError:
                pass

    # ------------------------------------------------------------ hotkeys
    def _register_hotkeys(self) -> None:
        if self._hotkeys_registered:
            return
        app = QApplication.instance()
        if app is None:
            return
        if self._hotkey_filter is None:
            self._hotkey_filter = HotkeyFilter(self._on_hotkey)
            app.installNativeEventFilter(self._hotkey_filter)
        modifiers = win_shell.MOD_CONTROL | win_shell.MOD_ALT \
            | win_shell.MOD_NOREPEAT
        win_shell.register_hotkey(
            HOTKEY_LAUNCHPAD, modifiers, win_shell.VK_L)
        win_shell.register_hotkey(
            HOTKEY_SWITCHER, modifiers, win_shell.VK_W)
        win_shell.register_hotkey(
            HOTKEY_RESTORE, modifiers, win_shell.VK_ESCAPE)
        # Открыть Gridly, даже если трей скрыт вместе с панелью задач.
        win_shell.register_hotkey(
            HOTKEY_GRIDLY, modifiers, win_shell.VK_G)
        self._hotkeys_registered = True

    def _unregister_hotkeys(self) -> None:
        if not self._hotkeys_registered:
            return
        win_shell.unregister_hotkey(HOTKEY_LAUNCHPAD)
        win_shell.unregister_hotkey(HOTKEY_SWITCHER)
        win_shell.unregister_hotkey(HOTKEY_RESTORE)
        win_shell.unregister_hotkey(HOTKEY_GRIDLY)
        app = QApplication.instance()
        if app is not None and self._hotkey_filter is not None:
            app.removeNativeEventFilter(self._hotkey_filter)
        self._hotkey_filter = None
        self._hotkeys_registered = False

    def _on_hotkey(self, hotkey_id: int) -> None:
        if not self._active:
            return
        if hotkey_id == HOTKEY_LAUNCHPAD:
            self.show_launchpad()
        elif hotkey_id == HOTKEY_SWITCHER:
            self.show_switcher()
        elif hotkey_id == HOTKEY_GRIDLY:
            self.panel._show_section(0)
        elif hotkey_id == HOTKEY_RESTORE:
            # Аварийный выход: панель задач вернётся, даже если верхнее
            # меню скрыто или не отвечает.
            self.panel.disable_shell()

    # ------------------------------------------------------------ actions
    def show_launchpad(self) -> None:
        if not self.tweaks.launchpad_enabled:
            return
        self.switcher.hide()
        self.control_center.hide()
        self.launchpad.show_launchpad()

    def show_switcher(self) -> None:
        if not self.tweaks.switcher_enabled:
            return
        self.launchpad.hide()
        self.control_center.hide()
        self.switcher.show_switcher()

    def show_control_center(self, point) -> None:
        if not isinstance(point, QPoint):
            point = QCursor.pos()
        self.launchpad.hide()
        self.switcher.hide()
        self.control_center.show_at(point)

    def _on_tweak(self, attr: str, value: int) -> None:
        setter = getattr(self.panel, "set_tweak", None)
        if setter is not None:
            setter(attr, value)

    def _on_action(self, action: str) -> None:
        if action == "launchpad":
            self.show_launchpad()
        elif action == "switcher":
            self.show_switcher()
        elif action in ("fences", "widgets", "customization", "tweaks"):
            index = {"fences": 0, "widgets": 1,
                     "customization": 2, "tweaks": 3}[action]
            self.panel._show_section(index)
        elif action == "hide_all":
            self.panel.manager.toggle_all_visibility()
            if self.panel.widget_manager is not None:
                self.panel.widget_manager.toggle_all_visibility()
        elif action == "minimize_all":
            win_shell.minimize_all_windows({os.getpid()})
        elif action == "restore_taskbar":
            self.panel.disable_shell()
        elif action == "exit_mac":
            self.panel.disable_mac_style()
        elif action == "show_panel":
            self.panel._show_section(0)
        elif action == "hide_panel":
            self.panel.hide()
        elif action == "quit":
            self.panel._on_quit()
        elif action == "about":
            QMessageBox.about(
                self.panel, "О Gridly",
                "Gridly — фенсы, виджеты и macOS-оболочка для Windows.\n\n"
                "Верхнее меню, Dock, Launchpad и переключатель окон "
                "заменяют панель задач, пока включён macOS-режим.",
            )
        elif action == "shortcuts":
            QMessageBox.information(
                self.panel, "Горячие клавиши",
                "Ctrl+Alt+L — Launchpad\n"
                "Ctrl+Alt+W — переключатель окон\n"
                "Ctrl+Alt+Esc — вернуть панель задач Windows\n"
                "Esc — закрыть Launchpad или переключатель\n\n"
                "Панель задач также возвращается через меню Gridly → "
                "«Вернуть панель задач Windows», через Пункт управления "
                "или при выходе из Gridly.",
            )
