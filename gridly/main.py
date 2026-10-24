"""
main.py
Gridly — Fences-подобные контейнеры для рабочего стола Windows.
Target: Windows 10/11 x64. Toolchain: Python 3.11, PyQt6 6.6+, pywin32 306+.

Запуск: python main.py
Управление: окно Gridly, иконка в трее, двойной клик по пустому месту рабочего стола.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Callable

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from core.desktop_watcher import DesktopDoubleClickWatcher
from core.fence_manager import FenceManager
from core.widget_manager import WidgetManager
from core.widget_storage import KIND_ORDER, WIDGET_KINDS
from ui.control_panel import ControlPanel
from ui.fence_widget import LAYOUT_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gridly.main")


def build_tray_icon(app: QApplication, manager: FenceManager,
                    show_panel: Callable[[], None],
                    widget_manager: WidgetManager | None = None,
                    show_customization: Callable[[str | None], None] | None = None,
                    show_tweaks: Callable[[], None] | None = None,
                    restore_taskbar: Callable[[], None] | None = None
                    ) -> QSystemTrayIcon:
    icon_path = Path(__file__).parent / "assets" / "icons" / "tray.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
    else:
        icon = app.style().standardIcon(QStyle.StandardPixmap.SP_DesktopIcon)

    tray = QSystemTrayIcon(icon, app)
    menu = QMenu()

    open_action = QAction("Открыть окно Gridly", menu)
    open_action.triggered.connect(lambda _c=False: show_panel())
    menu.addAction(open_action)

    if show_customization is not None:
        custom_action = QAction("Кастомизация…", menu)
        custom_action.triggered.connect(
            lambda _c=False: show_customization(None)
        )
        menu.addAction(custom_action)

    if show_tweaks is not None:
        tweaks_action = QAction("Твики macOS…", menu)
        tweaks_action.triggered.connect(lambda _c=False: show_tweaks())
        menu.addAction(tweaks_action)

    if restore_taskbar is not None:
        taskbar_action = QAction("Вернуть панель задач Windows", menu)
        taskbar_action.triggered.connect(
            lambda _c=False: restore_taskbar()
        )
        menu.addAction(taskbar_action)

    toggle_action = QAction("Показать/скрыть все fences", menu)
    toggle_action.triggered.connect(lambda _c=False: manager.toggle_all_visibility())
    menu.addAction(toggle_action)

    add_menu = menu.addMenu("Добавить fence")
    for key, label in LAYOUT_NAMES.items():
        act = QAction(label, add_menu)
        act.triggered.connect(lambda _c=False, k=key: manager.create_fence(k))
        add_menu.addAction(act)

    if widget_manager is not None:
        widgets_menu = menu.addMenu("Добавить виджет")
        for kind in KIND_ORDER:
            act = QAction(WIDGET_KINDS[kind], widgets_menu)
            act.triggered.connect(
                lambda _c=False, k=kind: widget_manager.create_widget(k)
            )
            widgets_menu.addAction(act)
        widgets_menu.addSeparator()

        def open_custom_widget() -> None:
            widget = widget_manager.create_widget("custom")
            if show_customization is not None:
                show_customization(widget.state.id)

        custom_act = QAction("Составной виджет…", widgets_menu)
        custom_act.triggered.connect(
            lambda _c=False: open_custom_widget()
        )
        widgets_menu.addAction(custom_act)

    menu.addSeparator()

    quit_action = QAction("Выход", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: manager.toggle_all_visibility()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.setToolTip("Gridly")
    tray.show()
    return tray


def main() -> int:
    if not sys.platform.startswith("win"):
        logger.error("Gridly работает только на Windows (нужен Win32 shell API).")
        return 1

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    manager = FenceManager()
    manager.load_or_create_default()

    widget_manager = WidgetManager()
    widget_manager.load_or_create_default()

    watcher = DesktopDoubleClickWatcher()
    watcher.desktop_double_clicked.connect(manager.toggle_all_visibility)
    watcher.start()

    panel = ControlPanel(manager, on_quit=app.quit,
                         widget_manager=widget_manager)
    panel.move(40, 40)
    panel.show()

    def show_panel() -> None:
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def show_customization(widget_id: str | None = None) -> None:
        if widget_id:
            panel._open_widget_customization(widget_id)
            return
        show_panel()
        panel._set_mode(2)

    def show_tweaks() -> None:
        show_panel()
        panel._set_mode(3)

    tray = build_tray_icon(app, manager, show_panel, widget_manager,
                           show_customization, show_tweaks,
                           panel.disable_shell)

    app.aboutToQuit.connect(panel.shutdown_shell)
    exit_code = app.exec()

    panel.shutdown_shell()
    watcher.stop()
    manager.save()
    widget_manager.save()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())