"""
ui/control_panel.py
Окно Gridly: слева — список fences и управление, справа — редактор
выбранного fence (двойной клик по элементу списка открывает редактор).
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QEvent, QPoint, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QGuiApplication, QPainter, QPainterPath,
                         QPalette)
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QFrame, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMenu, QPushButton, QScrollArea,
                             QSizeGrip, QSlider, QSpinBox, QSplitter,
                             QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from core.storage import FenceStyle, hex_to_bgr
from core.tweaks import MacTweaks, load_tweaks
from ui.blur_effect import (DWMWCP_DEFAULT, DWMWCP_ROUND,
                            DWMWCP_ROUNDSMALL, disable_blur,
                            enable_fence_blur, set_window_corner_preference)
from ui.color_wheel import ColorWheel
from ui.customization_page import CustomizationPage
from ui.fence_widget import LAYOUT_NAMES
from ui.mac_dock import MacDock
from ui.mac_shell import MacShell
from ui.mydock import MyDockBar
from ui.tweaks_page import TweaksPage
from ui.widget_page import WidgetPage


def tint_from_qcolor(color: QColor) -> int:
    """QColor → int в формате, который использует FenceStyle.tint_bgr."""
    return (color.blue() << 16) | (color.green() << 8) | color.red()


def qcolor_from_tint(tint: int) -> QColor:
    """int из FenceStyle.tint_bgr → QColor."""
    return QColor(tint & 0xFF, (tint >> 8) & 0xFF, (tint >> 16) & 0xFF)


class ControlPanel(QWidget):
    def __init__(self, manager, on_quit: Callable[[], None],
                 widget_manager=None):
        super().__init__()
        self.manager = manager
        self.widget_manager = widget_manager
        self._on_quit = on_quit
        self._current_fence_id: str | None = None
        self._loading_editor = False
        self._connected_widget_ids: set[str] = set()
        self.widget_page: WidgetPage | None = None
        self.dock: MacDock | None = None
        self.mydock: MyDockBar | None = None
        self.tweaks = load_tweaks()
        self._mac_active = False
        self._panel_blur = False
        self._drag_offset: QPoint | None = None
        self._shell_effect = None

        self.setWindowTitle("Gridly")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumSize(920, 660)

        self._build_ui()
        self.mac_shell = MacShell(self, self.tweaks)

        self.manager.changed.connect(self._on_manager_changed)
        if self.widget_manager is not None:
            self.widget_manager.edit_requested.connect(
                self._open_widget_from_desktop
            )
            self.widget_manager.changed.connect(self._on_widgets_changed)
        self.refresh()
        self._apply_tweaks(self.tweaks, initial=True)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("macShell")
        self.shell.setStyleSheet(
            "QFrame#macShell { background: transparent; border: none; }"
        )
        self.shell_layout = QVBoxLayout(self.shell)
        self.shell_layout.setContentsMargins(16, 16, 16, 16)
        self.shell_layout.setSpacing(10)
        root.addWidget(self.shell, 1)

        # Подстраиваемся под светлую/тёмную тему системы
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Unknown:
            dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        else:
            dark = scheme == Qt.ColorScheme.Dark
        if dark:
            self._theme = {
                "btn_bg": "#3a3f46",
                "btn_hover": "#464c55",
                "btn_pressed": "#2f343a",
                "btn_border": "#555d67",
                "btn_text": "#e6e8eb",
                "btn_disabled_bg": "#2f3338",
                "btn_disabled_text": "#7c838c",
                "input_bg": "#24282d",
                "input_border": "#3f464f",
                "input_focus": "#7f8a97",
                "input_text": "#e6e8eb",
                "list_bg": "#24282d",
                "list_border": "#3f464f",
                "list_text": "#e6e8eb",
                "list_selected": "#3a424b",
                "list_hover": "#2d3339",
                "add_top": "#4a5058",
                "add_bottom": "#343940",
                "add_border": "#5b636d",
                "add_text": "#f3f4f6",
                "add_hover": "rgba(255, 255, 255, 30)",
                "add_pressed": "rgba(0, 0, 0, 60)",
                "add_sep": "#5b636d",
            }
        else:
            self._theme = {
                "btn_bg": "#e8eaee",
                "btn_hover": "#dce0e5",
                "btn_pressed": "#cfd4db",
                "btn_border": "#b8bfc9",
                "btn_text": "#2f3742",
                "btn_disabled_bg": "#eceef1",
                "btn_disabled_text": "#9ca3af",
                "input_bg": "#ffffff",
                "input_border": "#d2d6dc",
                "input_focus": "#9aa4b2",
                "input_text": "#111827",
                "list_bg": "#ffffff",
                "list_border": "#d2d6dc",
                "list_text": "#111827",
                "list_selected": "#e6e9ee",
                "list_hover": "#f2f4f7",
                "add_top": "#eef0f3",
                "add_bottom": "#d0d5dc",
                "add_border": "#b0b8c3",
                "add_text": "#252c35",
                "add_hover": "rgba(255, 255, 255, 140)",
                "add_pressed": "rgba(0, 0, 0, 24)",
                "add_sep": "#b0b8c3",
            }

        self._dark = bool(dark)
        t = self._theme
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {t['btn_bg']};
                border: 1px solid {t['btn_border']};
                border-radius: 7px;
                padding: 5px 10px;
                color: {t['btn_text']};
            }}
            QPushButton:hover {{ background: {t['btn_hover']}; }}
            QPushButton:pressed {{ background: {t['btn_pressed']}; }}
            QPushButton:disabled {{
                background: {t['btn_disabled_bg']};
                color: {t['btn_disabled_text']};
            }}
            """
        )

        self.traffic_box = QWidget()
        traffic_lay = QHBoxLayout(self.traffic_box)
        traffic_lay.setContentsMargins(0, 0, 0, 0)
        traffic_lay.setSpacing(7)
        self.traffic_close = self._traffic_button(
            "#ff5f57", "Закрыть окно", self.hide
        )
        self.traffic_min = self._traffic_button(
            "#febc2e", "Свернуть окно", self.showMinimized
        )
        self.traffic_max = self._traffic_button(
            "#28c840", "Развернуть окно", self._toggle_maximized
        )
        traffic_lay.addWidget(self.traffic_close)
        traffic_lay.addWidget(self.traffic_min)
        traffic_lay.addWidget(self.traffic_max)
        self.traffic_box.hide()

        self.title_label = QLabel("Gridly")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)
        title_row.addWidget(self.traffic_box)
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)

        self.header = QWidget()
        self.header.setObjectName("macHeader")
        self.header.setLayout(title_row)
        self.header.installEventFilter(self)
        self.title_label.installEventFilter(self)
        self.shell_layout.addWidget(self.header)

        self.mode_switch = QFrame()
        self.mode_switch.setObjectName("modeSwitch")
        switch_lay = QHBoxLayout(self.mode_switch)
        switch_lay.setContentsMargins(3, 3, 3, 3)
        switch_lay.setSpacing(2)

        self.mode_fences_btn = QPushButton("Фенсы")
        self.mode_fences_btn.setObjectName("modeBtn")
        self.mode_fences_btn.setCheckable(True)
        self.mode_fences_btn.setAutoExclusive(True)
        self.mode_fences_btn.setChecked(True)
        self.mode_fences_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_fences_btn.clicked.connect(lambda _c=False: self._set_mode(0))
        switch_lay.addWidget(self.mode_fences_btn)

        self.mode_widgets_btn = QPushButton("Виджеты")
        self.mode_widgets_btn.setObjectName("modeBtn")
        self.mode_widgets_btn.setCheckable(True)
        self.mode_widgets_btn.setAutoExclusive(True)
        self.mode_widgets_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_widgets_btn.clicked.connect(lambda _c=False: self._set_mode(1))
        switch_lay.addWidget(self.mode_widgets_btn)
        if self.widget_manager is None:
            self.mode_widgets_btn.hide()

        self.mode_custom_btn = QPushButton("Кастомизация")
        self.mode_custom_btn.setObjectName("modeBtn")
        self.mode_custom_btn.setCheckable(True)
        self.mode_custom_btn.setAutoExclusive(True)
        self.mode_custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_custom_btn.clicked.connect(lambda _c=False: self._set_mode(2))
        switch_lay.addWidget(self.mode_custom_btn)

        self.mode_tweaks_btn = QPushButton("Твики")
        self.mode_tweaks_btn.setObjectName("modeBtn")
        self.mode_tweaks_btn.setCheckable(True)
        self.mode_tweaks_btn.setAutoExclusive(True)
        self.mode_tweaks_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_tweaks_btn.clicked.connect(lambda _c=False: self._set_mode(3))
        switch_lay.addWidget(self.mode_tweaks_btn)

        title_row.addWidget(self.mode_switch)

        self.mode_stack = QStackedWidget()
        self.fences_page = QSplitter(Qt.Orientation.Horizontal)
        self.fences_page.setChildrenCollapsible(False)
        self.fences_page.addWidget(self._build_left())
        self.fences_page.addWidget(self._build_right())
        self.fences_page.setSizes([360, 520])
        self.fences_page.setStretchFactor(0, 1)
        self.fences_page.setStretchFactor(1, 1)
        self.mode_stack.addWidget(self.fences_page)

        if self.widget_manager is not None:
            self.widget_page = WidgetPage(self.widget_manager, self._theme)
            self.widget_page.custom_requested.connect(
                self._open_widget_customization
            )
            self.widget_page.blocks_requested.connect(
                self._open_widget_customization
            )
            self.mode_stack.addWidget(self.widget_page)

        self.customization_page = CustomizationPage(
            self.manager, self.widget_manager, self._theme
        )
        self.mode_stack.addWidget(self.customization_page)
        if hasattr(self.manager, "customize_requested"):
            self.manager.customize_requested.connect(
                self._open_fence_customization
            )

        self.tweaks_page = TweaksPage(self._theme)
        self.tweaks_page.changed.connect(self._on_tweaks_changed)
        self.mode_stack.addWidget(self.tweaks_page)
        self.tweaks = self.tweaks_page.tweaks

        self.shell_layout.addWidget(self.mode_stack, 1)

        self.size_grip = QSizeGrip(self.shell)
        self.size_grip.setFixedSize(18, 18)
        self.size_grip.hide()

        self.setStyleSheet(self.styleSheet() + f"""
            QFrame#modeSwitch {{
                background: {t['input_bg']};
                border: 1px solid {t['input_border']};
                border-radius: 9px;
            }}
            QPushButton#modeBtn {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 5px 12px;
                color: {t['input_text']};
                font-weight: 600;
            }}
            QPushButton#modeBtn:hover {{ background: {t['btn_hover']}; }}
            QPushButton#modeBtn:checked {{
                background: {t['btn_bg']};
                border: 1px solid {t['btn_border']};
            }}
        """)
        self._base_stylesheet = self.styleSheet()

    def _traffic_button(self, color: str, tooltip: str,
                        handler: Callable[[], None]) -> QPushButton:
        button = QPushButton()
        button.setFixedSize(13, 13)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: {color}; border: none;"
            " border-radius: 6px; }"
            f"QPushButton:hover {{ background: {color};"
            " border: 1px solid rgba(0, 0, 0, 70); }"
        )
        button.clicked.connect(lambda _c=False: handler())
        return button

    def _toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _set_mode(self, index: int) -> None:
        if index == 1 and self.widget_page is None:
            return
        pages = {
            0: self.fences_page,
            1: self.widget_page,
            2: self.customization_page,
            3: self.tweaks_page,
        }
        page = pages.get(index)
        if page is None:
            return
        buttons = {
            0: self.mode_fences_btn,
            1: self.mode_widgets_btn,
            2: self.mode_custom_btn,
            3: self.mode_tweaks_btn,
        }
        button = buttons.get(index)
        if button is not None:
            button.setChecked(True)
        self.mode_stack.setCurrentWidget(page)
        if self.dock is not None:
            self.dock.set_active(index)

    def _open_widget_from_desktop(self, fid: str) -> None:
        if self.widget_page is None:
            return
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_mode(1)
        self.widget_page.open_widget(fid)

    def _open_fence_customization(self, fid: str) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_mode(2)
        self.customization_page.open_fence(fid)

    def _open_widget_customization(self, fid: str) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_mode(2)
        self.customization_page.open_widget(fid)

    # --------------------------------------------------------- macOS style
    def _ensure_dock(self) -> MacDock:
        if self.dock is None:
            self.dock = MacDock(self.tweaks)
            self.dock.action_requested.connect(self._on_dock_action)
            self.dock.position_changed.connect(
                self._on_dock_position_changed)
        return self.dock

    def _ensure_mydock(self) -> MyDockBar:
        if self.mydock is None:
            self.mydock = MyDockBar(self.tweaks)
            self.mydock.systemRequested.connect(self._on_mydock_system)
        return self.mydock

    def _apply_mydock(self, tweaks: MacTweaks) -> None:
        """MyDock создаём только когда он нужен; выключенный — скрываем."""
        if tweaks.enabled and tweaks.mydock_enabled:
            self._ensure_mydock().apply_tweaks(tweaks)
        elif self.mydock is not None:
            self.mydock.apply_tweaks(tweaks)

    def _suspend_mydock(self) -> None:
        if self.mydock is not None:
            self.mydock.suspend()

    def _current_section(self) -> int:
        current = self.mode_stack.currentWidget()
        if current is self.widget_page:
            return 1
        if current is self.customization_page:
            return 2
        if current is self.tweaks_page:
            return 3
        return 0

    def _on_tweaks_changed(self, tweaks: MacTweaks) -> None:
        self.tweaks = tweaks
        self._apply_tweaks(tweaks)

    def _apply_tweaks(self, tweaks: MacTweaks, initial: bool = False) -> None:
        """Применяет настройки macOS ко всем окнам Gridly."""
        self.tweaks = tweaks
        mydock_on = bool(tweaks.enabled and tweaks.mydock_enabled)
        if tweaks.enabled:
            self._activate_mac_style(tweaks)
            dock = self._ensure_dock()
            dock.set_locked(mydock_on)
            dock.apply_tweaks(tweaks)
            dock.set_active(self._current_section())
        else:
            self._deactivate_mac_style()
            if self.dock is not None:
                self.dock.set_locked(mydock_on)
                self.dock.apply_tweaks(tweaks)
        self._apply_mydock(tweaks)
        self._apply_to_windows(tweaks)
        self.mac_shell.apply(tweaks)

    def _activate_mac_style(self, tweaks: MacTweaks) -> None:
        was_visible = self.isVisible()
        if not self._mac_active:
            self.setWindowFlags(
                Qt.WindowType.Window
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self._mac_active = True
            if was_visible:
                self.show()

        dark = self._dark if tweaks.appearance == "auto" \
            else tweaks.appearance == "dark"
        bg = (28, 29, 33) if dark else (247, 248, 251)
        text = "#f5f5f7" if dark else "#1d1d1f"
        border = "rgba(255, 255, 255, 42)" if dark \
            else "rgba(0, 0, 0, 28)"
        alpha = max(100, min(248, 255 - int(tweaks.translucency * 1.45)))
        radius = int(tweaks.corner_radius) if tweaks.rounded else 0
        outer = 22 if tweaks.floating_panel else 0
        self.layout().setContentsMargins(outer, outer, outer, outer)
        self.shell_layout.setContentsMargins(16, 16, 16, 16)
        self.shell.setStyleSheet(
            f"QFrame#macShell {{ background: rgba({bg[0]}, {bg[1]}, "
            f"{bg[2]}, {alpha}); border: 1px solid {border};"
            f" border-radius: {radius}px; }}"
        )
        self.title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 600; color: {text};"
        )
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        self.title_label.setCursor(Qt.CursorShape.SizeAllCursor)
        self.traffic_box.setVisible(bool(tweaks.traffic_lights))
        self.size_grip.setVisible(True)
        self._position_size_grip()

        accent = tweaks.accent
        switch_bg = "rgba(255, 255, 255, 26)" if dark \
            else "rgba(0, 0, 0, 16)"
        self.setStyleSheet(self._base_stylesheet + f"""
            QFrame#modeSwitch {{
                background: {switch_bg};
                border: 1px solid {border};
                border-radius: 9px;
            }}
            QPushButton#modeBtn {{ color: {text}; }}
            QPushButton#modeBtn:checked {{
                border: 1px solid {accent};
                background: rgba(255, 255, 255, 35);
            }}
        """)
        self.update()
        QTimer.singleShot(0, self._apply_panel_blur)
        QTimer.singleShot(0, self._apply_system_corners)

    def _deactivate_mac_style(self) -> None:
        was_visible = self.isVisible()
        if self._mac_active:
            self._disable_panel_blur()
            self.setWindowFlags(
                Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(
                Qt.WidgetAttribute.WA_TranslucentBackground, False
            )
            self._mac_active = False
            try:
                set_window_corner_preference(
                    int(self.winId()), DWMWCP_DEFAULT
                )
            except (RuntimeError, TypeError, ValueError):
                pass
            if was_visible:
                self.show()
        self.layout().setContentsMargins(16, 16, 16, 16)
        self.shell.setStyleSheet(
            "QFrame#macShell { background: transparent; border: none; }"
        )
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        self.header.setCursor(Qt.CursorShape.ArrowCursor)
        self.title_label.setCursor(Qt.CursorShape.ArrowCursor)
        self.traffic_box.hide()
        self.size_grip.hide()
        self.setStyleSheet(self._base_stylesheet)
        self.update()

    def _apply_panel_blur(self) -> None:
        if not self._mac_active or not self.tweaks.glass:
            self._disable_panel_blur()
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        dark = self._dark if self.tweaks.appearance == "auto" \
            else self.tweaks.appearance == "dark"
        tint = hex_to_bgr("#1c1c1e" if dark else "#f2f3f7")
        alpha = max(55, min(210, 55 + int(self.tweaks.blur_strength)))
        try:
            enable_fence_blur(hwnd, tint, alpha)
            self._panel_blur = True
        except Exception:
            self._panel_blur = False

    def _disable_panel_blur(self) -> None:
        if not self._panel_blur:
            return
        try:
            disable_blur(int(self.winId()))
        except Exception:
            pass
        self._panel_blur = False

    def _apply_system_corners(self) -> None:
        if not self._mac_active:
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        if self.tweaks.rounded and self.tweaks.corner_radius > 0:
            preference = DWMWCP_ROUND \
                if self.tweaks.corner_radius >= 14 else DWMWCP_ROUNDSMALL
        else:
            preference = DWMWCP_DEFAULT
        try:
            set_window_corner_preference(hwnd, preference)
        except Exception:
            pass

    def _apply_to_windows(self, tweaks: MacTweaks) -> None:
        for fence in list(self.manager.widgets.values()):
            apply = getattr(fence, "apply_mac_tweaks", None)
            if apply is not None:
                apply(tweaks)
        if self.widget_manager is not None:
            for widget in list(self.widget_manager.widgets.values()):
                apply = getattr(widget, "apply_mac_tweaks", None)
                if apply is not None:
                    apply(tweaks)

    def _on_widgets_changed(self) -> None:
        self._apply_to_windows(self.tweaks)

    def _show_section(self, index: int) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self._set_mode(index)

    def _on_dock_action(self, action: str) -> None:
        if action == "fences":
            self._show_section(0)
        elif action == "widgets":
            self._show_section(1)
        elif action == "customization":
            self._show_section(2)
        elif action == "tweaks":
            self._show_section(3)
        elif action == "launchpad":
            self.mac_shell.show_launchpad()
        elif action == "switcher":
            self.mac_shell.show_switcher()
        elif action == "hide":
            self.manager.toggle_all_visibility()
            if self.widget_manager is not None:
                self.widget_manager.toggle_all_visibility()
        elif action == "quit":
            self._on_quit()

    def _on_mydock_system(self, action: str) -> None:
        """Системные значки MyDock: Finder открывает панель Gridly."""
        if action in ("fences", "finder"):
            self._show_section(0)
        elif action == "launchpad":
            self.mac_shell.show_launchpad()

    def _on_dock_position_changed(self, position: str) -> None:
        self.tweaks_page.set_value("dock_position", position)

    def set_tweak(self, attr: str, value) -> None:
        """Применяет настройку из верхнего меню или Пункта управления."""
        self.tweaks_page.set_value(attr, value)

    def disable_shell(self) -> None:
        """Возвращает панель задач Windows, не закрывая Gridly."""
        self.tweaks_page.set_value("shell_enabled", False)
        self.mac_shell.shutdown()

    def disable_mac_style(self) -> None:
        """Полностью выключает macOS-режим и возвращает обычный Windows."""
        self.tweaks_page.set_value("enabled", False)
        self.mac_shell.shutdown()
        self._suspend_mydock()

    def shutdown_shell(self) -> None:
        self.mac_shell.shutdown()
        self._suspend_mydock()

    def _position_size_grip(self) -> None:
        if not hasattr(self, "size_grip"):
            return
        self.size_grip.move(self.shell.width() - 22,
                            self.shell.height() - 22)
        self.size_grip.raise_()

    def _refresh_mac_runtime(self) -> None:
        if not self.tweaks.enabled:
            return
        self._apply_panel_blur()
        self._apply_system_corners()
        if self.dock is not None:
            self.dock.apply_tweaks(self.tweaks)
        self._apply_mydock(self.tweaks)
        self._apply_to_windows(self.tweaks)

    # --------------------------------------------------------------- events
    def eventFilter(self, obj, event) -> bool:
        if self._mac_active and obj in (self.header, self.title_label):
            if event.type() == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton:
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
                return True
            if event.type() == QEvent.Type.MouseMove and \
                    self._drag_offset is not None and \
                    event.buttons() & Qt.MouseButton.LeftButton:
                self.move(event.globalPosition().toPoint() - self._drag_offset)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_offset = None
                return True
            if event.type() == QEvent.Type.MouseButtonDblClick and \
                    obj is self.header:
                self._toggle_maximized()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_size_grip()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.tweaks.enabled:
            QTimer.singleShot(0, self._refresh_mac_runtime)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._mac_active or not self.tweaks.shadows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        geo = QRectF(self.shell.geometry())
        radius = float(self.tweaks.corner_radius) \
            if self.tweaks.rounded else 0.0
        inner = QPainterPath()
        inner.addRoundedRect(geo, radius, radius)
        for i in range(8, 0, -1):
            spread = i * 3.0
            alpha = int(38 * (1.0 - i / 9.0))
            shadow = QPainterPath()
            shadow.addRoundedRect(
                geo.adjusted(-spread, -spread + 8, spread, spread + 8),
                radius + spread, radius + spread,
            )
            # Тень рисуется только снаружи панели: иначе она просвечивает
            # через полупрозрачный фон и делает светлую тему серой.
            p.setClipPath(shadow.subtracted(inner))
            p.setBrush(QColor(0, 0, 0, max(3, alpha)))
            p.drawPath(shadow)
        p.end()

    def _build_left(self) -> QWidget:
        w = QWidget()
        t = self._theme
        w.setStyleSheet(
            f"""
            QLineEdit#fenceSearch {{
                border: 1px solid {t['input_border']};
                border-radius: 8px;
                padding: 7px 10px;
                background: {t['input_bg']};
                color: {t['input_text']};
            }}
            QLineEdit#fenceSearch:focus {{ border: 1px solid {t['input_focus']}; }}
            QListWidget#fenceList {{
                border: 1px solid {t['list_border']};
                border-radius: 8px;
                background: {t['list_bg']};
                color: {t['list_text']};
                padding: 4px;
            }}
            QListWidget#fenceList::item {{
                padding: 7px 8px;
                border-radius: 5px;
            }}
            QListWidget#fenceList::item:selected {{
                background: {t['list_selected']};
                color: {t['list_text']};
            }}
            QListWidget#fenceList::item:hover {{ background: {t['list_hover']}; }}
            """
        )
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        # --- Составная кнопка: «Добавить fence» + выбор раскладки ---
        add_box = QFrame()
        add_box.setObjectName("addFenceBox")
        add_box.setFixedHeight(40)
        add_box.setStyleSheet(
            f"""
            QFrame#addFenceBox {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 {t['add_top']}, stop:1 {t['add_bottom']});
                border: 1px solid {t['add_border']};
                border-radius: 10px;
            }}
            QPushButton#addFenceMain {{
                color: {t['add_text']};
                background: transparent;
                border: none;
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
                padding: 0 14px;
                font-weight: 600;
                text-align: left;
            }}
            QPushButton#addFenceMain:hover {{ background: {t['add_hover']}; }}
            QPushButton#addFenceMain:pressed {{ background: {t['add_pressed']}; }}
            QToolButton#addFenceArrow {{
                color: {t['add_text']};
                background: transparent;
                border: none;
                border-left: 1px solid {t['add_sep']};
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
                font-size: 12px;
            }}
            QToolButton#addFenceArrow:hover {{ background: {t['add_hover']}; }}
            QToolButton#addFenceArrow:pressed {{ background: {t['add_pressed']}; }}
            QToolButton#addFenceArrow::menu-indicator {{ image: none; width: 0; }}
            """
        )
        add_lay = QHBoxLayout(add_box)
        add_lay.setContentsMargins(0, 0, 0, 0)
        add_lay.setSpacing(0)

        add_btn = QPushButton("+  Добавить fence")
        add_btn.setObjectName("addFenceMain")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.clicked.connect(lambda _c=False: self.manager.create_fence("grid"))
        add_lay.addWidget(add_btn, 1)

        arrow = QToolButton()
        arrow.setObjectName("addFenceArrow")
        arrow.setText("▾")
        arrow.setToolTip("Выбрать тип fence")
        arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        arrow.setFixedWidth(38)
        arrow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        arrow.setMenu(self._type_menu())
        add_lay.addWidget(arrow)
        lay.addWidget(add_box)

        # --- Поиск по заборам ---
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("fenceSearch")
        self.search_edit.setPlaceholderText("Поиск по названию...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh)
        lay.addWidget(self.search_edit)

        self.list_label = QLabel("Существующие fences:")
        lay.addWidget(self.list_label)

        self.list = QListWidget()
        self.list.setObjectName("fenceList")
        self.list.setMinimumHeight(200)
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)
        lay.addWidget(self.list, 1)

        # --- Действия с выбранным забором ---
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        dup_btn = QPushButton("Дублировать")
        dup_btn.setObjectName("dupBtn")
        dup_btn.setMinimumHeight(32)
        dup_btn.setToolTip("Создать копию выбранного fence")
        dup_btn.clicked.connect(lambda _c=False: self._duplicate_selected())
        action_row.addWidget(dup_btn, 1)

        del_btn = QPushButton("Удалить")
        del_btn.setObjectName("delBtn")
        del_btn.setMinimumHeight(32)
        del_btn.clicked.connect(lambda _c=False: self._delete_selected())
        action_row.addWidget(del_btn, 1)
        lay.addLayout(action_row)

        vis_btn = QPushButton("Показать / скрыть все")
        vis_btn.setObjectName("visBtn")
        vis_btn.setMinimumHeight(32)
        vis_btn.clicked.connect(lambda _c=False: self.manager.toggle_all_visibility())
        lay.addWidget(vis_btn)

        quit_btn = QPushButton("Выход")
        quit_btn.setObjectName("quitBtn")
        quit_btn.setMinimumHeight(32)
        quit_btn.clicked.connect(lambda _c=False: self._on_quit())
        lay.addWidget(quit_btn)
        return w

    def _build_right(self) -> QWidget:
        self.editor_stack = QStackedWidget()

        placeholder = QLabel(
            "Выберите забор двойным кликом\nв списке слева, чтобы открыть редактор."
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #888; font-size: 13px;")
        self.editor_stack.addWidget(placeholder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._build_editor())
        self.editor_scroll = scroll
        self.editor_stack.addWidget(scroll)
        return self.editor_stack

    def _build_editor(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(16, 0, 0, 0)
        lay.setSpacing(12)

        self.editor_title = QLabel("Редактор fence")
        self.editor_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        lay.addWidget(self.editor_title)

        # ------------------------------------------------------- основное
        main_group = QGroupBox("Основное")
        form = QFormLayout(main_group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Название fence")
        self.title_edit.editingFinished.connect(self._apply_title)
        form.addRow("Название:", self.title_edit)

        self.layout_combo = QComboBox()
        for key, label in LAYOUT_NAMES.items():
            self.layout_combo.addItem(label, key)
        self.layout_combo.currentIndexChanged.connect(self._apply_layout)
        form.addRow("Раскладка:", self.layout_combo)

        size_row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(140, 4000)
        self.width_spin.setSuffix(" px")
        self.width_spin.valueChanged.connect(self._apply_geometry)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(80, 4000)
        self.height_spin.setSuffix(" px")
        self.height_spin.valueChanged.connect(self._apply_geometry)

        size_row.addWidget(self.width_spin, 1)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_spin, 1)
        form.addRow("Размер:", size_row)

        pos_row = QHBoxLayout()
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-10000, 10000)
        self.x_spin.setPrefix("X ")
        self.x_spin.valueChanged.connect(self._apply_geometry)

        self.y_spin = QSpinBox()
        self.y_spin.setRange(-10000, 10000)
        self.y_spin.setPrefix("Y ")
        self.y_spin.valueChanged.connect(self._apply_geometry)

        pos_row.addWidget(self.x_spin, 1)
        pos_row.addWidget(self.y_spin, 1)
        form.addRow("Позиция:", pos_row)
        lay.addWidget(main_group)

        # ---------------------------------------------------- цвет и стиль
        style_group = QGroupBox("Цвет и прозрачность")
        style_lay = QVBoxLayout(style_group)
        style_lay.setSpacing(8)

        self.color_wheel = ColorWheel()
        self.color_wheel.color_changed.connect(self._apply_color)
        style_lay.addWidget(self.color_wheel, 0, Qt.AlignmentFlag.AlignHCenter)

        swatch_row = QHBoxLayout()
        swatch_row.addWidget(QLabel("Цвет фона:"))
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(56, 24)
        self.color_preview.setStyleSheet(
            "border: 1px solid #555; border-radius: 5px; background: #2b2b2b;"
        )
        swatch_row.addWidget(self.color_preview)
        swatch_row.addStretch(1)
        style_lay.addLayout(swatch_row)

        self.alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.valueChanged.connect(self._apply_alpha)
        self.alpha_value = QLabel("160")
        style_lay.addLayout(self._slider_row("Прозрачность фона", self.alpha_slider, self.alpha_value))

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(40, 255)
        self.opacity_slider.valueChanged.connect(self._apply_opacity)
        self.opacity_value = QLabel("235")
        style_lay.addLayout(self._slider_row("Прозрачность окна", self.opacity_slider, self.opacity_value))

        self.radius_slider = QSlider(Qt.Orientation.Horizontal)
        self.radius_slider.setRange(0, 40)
        self.radius_slider.valueChanged.connect(self._apply_radius)
        self.radius_value = QLabel("10")
        style_lay.addLayout(self._slider_row("Скругление углов", self.radius_slider, self.radius_value))

        lay.addWidget(style_group)

        # -------------------------------------------------------- кнопки
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Сбросить стиль")
        reset_btn.setMinimumHeight(30)
        reset_btn.clicked.connect(lambda _c=False: self._reset_style())
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)

        close_btn = QPushButton("Свернуть редактор")
        close_btn.setMinimumHeight(30)
        close_btn.clicked.connect(lambda _c=False: self._close_editor())
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        lay.addStretch(1)
        return w

    @staticmethod
    def _slider_row(title: str, slider: QSlider, value_label: QLabel) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch(1)
        top.addWidget(value_label)
        box.addLayout(top)
        box.addWidget(slider)
        return box

    def _type_menu(self) -> QMenu:
        menu = QMenu(self)
        for key, label in LAYOUT_NAMES.items():
            act = menu.addAction(label)
            act.triggered.connect(lambda _c=False, k=key: self.manager.create_fence(k))
        return menu

    # --------------------------------------------------------------- list
    @staticmethod
    def _item_text(state) -> str:
        return f"{state.title}  —  {LAYOUT_NAMES.get(state.layout, state.layout)}"

    def refresh(self) -> None:
        query = ""
        if hasattr(self, "search_edit"):
            query = self.search_edit.text().strip().lower()

        self.list.clear()
        shown = 0
        for fid, widget in self.manager.widgets.items():
            st = widget.state
            if query and query not in st.title.lower():
                continue
            item = QListWidgetItem(self._item_text(st))
            item.setData(Qt.ItemDataRole.UserRole, fid)
            self.list.addItem(item)
            shown += 1

        if hasattr(self, "list_label"):
            if query:
                self.list_label.setText(f"Существующие fences ({shown}):")
            else:
                self.list_label.setText(f"Существующие fences ({len(self.manager.widgets)}):")

        if self._current_fence_id and self._current_fence_id in self.manager.widgets:
            self._select_item(self._current_fence_id)

    def _select_item(self, fid: str) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == fid:
                self.list.setCurrentItem(item)
                return

    def _update_list_item(self, widget) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == widget.state.id:
                item.setText(self._item_text(widget.state))
                return

    def _on_manager_changed(self) -> None:
        current = self._current_fence_id
        self.refresh()
        self._apply_to_windows(self.tweaks)

        if not current:
            return
        widget = self.manager.widgets.get(current)
        if widget is None:
            self._close_editor()
            return
        if self.editor_stack.currentIndex() == 1:
            self._load_editor(widget)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        fid = item.data(Qt.ItemDataRole.UserRole)
        widget = self.manager.widgets.get(fid)
        if widget is None:
            return
        self._current_fence_id = fid
        self._load_editor(widget)
        self.editor_stack.setCurrentIndex(1)
        self.editor_scroll.verticalScrollBar().setValue(0)

    def _delete_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.manager.remove_fence(item.data(Qt.ItemDataRole.UserRole))

    def _duplicate_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return

        widget = self.manager.duplicate_fence(item.data(Qt.ItemDataRole.UserRole))
        if widget is None:
            return

        self._current_fence_id = widget.state.id
        self._load_editor(widget)
        self.editor_stack.setCurrentIndex(1)
        self.editor_scroll.verticalScrollBar().setValue(0)
        self._select_item(widget.state.id)

    # ------------------------------------------------------------- editor
    def _current_widget(self):
        if not self._current_fence_id:
            return None
        return self.manager.widgets.get(self._current_fence_id)

    def _load_editor(self, widget) -> None:
        st = widget.state
        if st.id not in self._connected_widget_ids:
            widget.geometry_changed.connect(self._on_widget_geometry_changed)
            self._connected_widget_ids.add(st.id)

        self._loading_editor = True
        try:
            self.title_edit.setText(st.title)

            idx = self.layout_combo.findData(st.layout)
            if idx >= 0:
                self.layout_combo.setCurrentIndex(idx)

            self.width_spin.setValue(st.width)
            self.height_spin.setValue(st.height)
            self.x_spin.setValue(st.x)
            self.y_spin.setValue(st.y)

            self.alpha_slider.setValue(st.style.bg_alpha)
            self.opacity_slider.setValue(st.style.opacity)
            self.radius_slider.setValue(st.style.corner_radius)
            self.alpha_value.setText(str(st.style.bg_alpha))
            self.opacity_value.setText(str(st.style.opacity))
            self.radius_value.setText(str(st.style.corner_radius))

            color = QColor(st.style.bg_color)
            if not color.isValid():
                color = qcolor_from_tint(st.style.tint_bgr)
            self.color_wheel.set_color(color)
            self._update_color_preview(color)

            self.editor_title.setText(f"Редактор — {st.title}")
            self._update_size_enabled()
        finally:
            self._loading_editor = False

    def _on_widget_geometry_changed(self, fid: str) -> None:
        if fid != self._current_fence_id:
            return
        if self.editor_stack.currentIndex() != 1:
            return
        widget = self.manager.widgets.get(fid)
        if widget is None:
            return

        st = widget.state
        self._loading_editor = True
        try:
            self.width_spin.setValue(st.width)
            self.height_spin.setValue(st.height)
            self.x_spin.setValue(st.x)
            self.y_spin.setValue(st.y)
        finally:
            self._loading_editor = False

    def _update_size_enabled(self) -> None:
        is_folder = self.layout_combo.currentData() == "folder"
        self.width_spin.setEnabled(not is_folder)
        self.height_spin.setEnabled(not is_folder)
        tip = "Для раскладки «Папка» размер фиксирован"
        self.width_spin.setToolTip(tip if is_folder else "")
        self.height_spin.setToolTip(tip if is_folder else "")

    def _update_color_preview(self, color: QColor) -> None:
        self.color_preview.setStyleSheet(
            f"border: 1px solid #555; border-radius: 5px;"
            f" background: {color.name()};"
        )

    def _close_editor(self) -> None:
        self._current_fence_id = None
        self.editor_stack.setCurrentIndex(0)
        self.list.clearSelection()

    # ------------------------------------------------------------- apply
    def _apply_title(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setText(widget.state.title)
            return
        if title == widget.state.title:
            return

        widget.state.title = title
        widget.title_label.setText(title)
        widget.title_changed.emit(widget.state.id)
        self.manager.save()
        self.editor_title.setText(f"Редактор — {title}")
        self._update_list_item(widget)

    def _apply_layout(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        key = self.layout_combo.currentData()
        if key and key != widget.state.layout:
            widget.set_layout(key)
            self.manager.save()

        self._update_size_enabled()

    def _apply_geometry(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        st = widget.state
        st.width = self.width_spin.value()
        st.height = self.height_spin.value()
        st.x = self.x_spin.value()
        st.y = self.y_spin.value()

        widget.move(st.x, st.y)
        if st.layout != "folder":
            widget.resize(st.width, st.height)
        self.manager.save()

    def _apply_color(self, color: QColor) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        widget.state.style.tint_bgr = tint_from_qcolor(color)
        widget.state.style.bg_color = color.name()
        self._update_color_preview(color)
        widget.apply_style()
        self.manager.save()

    def _apply_alpha(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        widget.state.style.tint_alpha = value
        widget.state.style.bg_alpha = value
        self.alpha_value.setText(str(value))
        widget.apply_style()
        self.manager.save()

    def _apply_opacity(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        widget.state.style.opacity = value
        self.opacity_value.setText(str(value))
        widget.setWindowOpacity(value / 255.0)
        self.manager.save()

    def _apply_radius(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return

        widget.state.style.corner_radius = value
        self.radius_value.setText(str(value))
        widget.apply_style()
        self.manager.save()

    def _reset_style(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return

        widget.state.style = FenceStyle()
        widget.apply_style()
        self._load_editor(widget)
        self.manager.save()
