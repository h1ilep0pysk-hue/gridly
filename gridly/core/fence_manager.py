"""
core/fence_manager.py
Toolchain: Python 3.11, PyQt6.

Создаёт, удаляет и хранит fences. Fence — обычные окна поверх рабочего стола.
"""

from __future__ import annotations

import copy
import logging
import os

import win32con
import win32gui
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication

from core.storage import FenceItem, FenceState, load_all, save_all
from ui.fence_widget import FenceWidget, FOLDER_COLLAPSED

logger = logging.getLogger("gridly.manager")

AUTOSAVE_INTERVAL_MS = 5_000
DEFAULT_W = 320
DEFAULT_H = 240


class FenceManager(QObject):
    changed = pyqtSignal()   # список fences изменился (для панели управления)
    customize_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.widgets: dict[str, FenceWidget] = {}
        self._all_hidden = False

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self.save)

    # -------------------------------------------------------------- init
    def load_or_create_default(self) -> None:
        states = load_all()
        for state in states:
            self._spawn(state)
        if not states:
            self.create_fence("grid", title="Shortcuts")
        self._autosave_timer.start()
        self.changed.emit()

    def _spawn(self, state: FenceState) -> FenceWidget:
        widget = FenceWidget(state)
        widget.geometry_changed.connect(lambda _id: self.save())
        widget.items_changed.connect(lambda _id: self.save())
        widget.layout_changed.connect(lambda _id: self._on_layout_changed())
        widget.title_changed.connect(lambda _id: self._on_meta_changed())
        widget.lock_changed.connect(lambda _id, _locked: self._on_meta_changed())
        widget.behavior_changed.connect(lambda _id: self._on_meta_changed())
        widget.customize_requested.connect(
            lambda fid: self.customize_requested.emit(fid)
        )
        widget.delete_requested.connect(self.remove_fence)
        widget.launch_requested.connect(self._launch)
        widget.show()

        hwnd = int(widget.winId())
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )

        self.widgets[state.id] = widget
        return widget

    # ----------------------------------------------------------- actions
    def create_fence(self, layout: str = "grid", title: str | None = None) -> FenceWidget:
        self._all_hidden = False
        offset = (len(self.widgets) % 8) * 28
        x, y = self._center_position(DEFAULT_W, DEFAULT_H)
        state = FenceState(
            title=title or f"Fence {len(self.widgets) + 1}",
            x=x + offset,
            y=y + offset,
            width=DEFAULT_W,
            height=DEFAULT_H,
            layout=layout,
        )
        widget = self._spawn(state)
        for other in self.widgets.values():
            other.setVisible(True)
        self.save()
        self.changed.emit()
        return widget

    def duplicate_fence(self, fence_id: str) -> FenceWidget | None:
        """Создаёт копию fence со сдвигом, тем же стилем и набором ярлыков."""
        src = self.widgets.get(fence_id)
        if src is None:
            return None

        src_state = src.state
        widget = self.create_fence(
            src_state.layout,
            title=f"{src_state.title} (копия)",
        )
        state = widget.state

        state.width = src_state.width
        state.height = src_state.height
        state.x = src_state.x + 28
        state.y = src_state.y + 28
        state.rolled_up = src_state.rolled_up
        state.locked = False
        state.always_on_top = src_state.always_on_top
        state.mode = src_state.mode
        state.portal_path = src_state.portal_path
        state.style = copy.deepcopy(src_state.style)
        state.items = [FenceItem(path=item.path, x=item.x, y=item.y)
                       for item in src_state.items]

        widget.move(state.x, state.y)
        if state.layout != "folder":
            widget.resize(state.width, state.height)
        widget._rebuild_items()
        widget.apply_style()

        self.save()
        self.changed.emit()
        return widget

    def remove_fence(self, fence_id: str) -> None:
        widget = self.widgets.pop(fence_id, None)
        if widget is None:
            return
        widget.hide()
        widget.close()
        widget.deleteLater()
        self.save()
        self.changed.emit()

    def toggle_all_visibility(self) -> None:
        self._all_hidden = not self._all_hidden
        logger.info("Видимость fences: %s", "скрыты" if self._all_hidden else "показаны")
        for widget in self.widgets.values():
            widget.setVisible(not self._all_hidden)

    # ------------------------------------------------------------- state
    def save(self) -> None:
        save_all([w.state for w in self.widgets.values()])

    def _on_layout_changed(self) -> None:
        self.save()
        self.changed.emit()

    def _on_meta_changed(self) -> None:
        self.save()
        self.changed.emit()

    # ------------------------------------------------------------- misc
    @staticmethod
    def _center_position(width: int, height: int) -> tuple[int, int]:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        return screen.center().x() - width // 2, screen.center().y() - height // 2

    @staticmethod
    def _launch(path: str) -> None:
        try:
            os.startfile(path)  # noqa: S606 — штатный способ запуска на Windows
        except OSError as exc:
            logger.error("Не удалось запустить %s: %s", path, exc)