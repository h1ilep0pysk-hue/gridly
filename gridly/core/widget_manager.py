"""
core/widget_manager.py
Создание, хранение и удаление desktop-виджетов Gridly.
"""

from __future__ import annotations

import copy
import logging
import uuid

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication

from core import widget_storage
from core.weather_service import WeatherService
from core.widget_storage import WidgetState, make_widget_state
from ui.widget_window import WidgetWindow

logger = logging.getLogger("gridly.widget_manager")

AUTOSAVE_INTERVAL_MS = 5_000


class WidgetManager(QObject):
    changed = pyqtSignal()
    edit_requested = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.widgets: dict[str, WidgetWindow] = {}
        self._all_hidden = False
        self.weather = WeatherService(self)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self.save)
        self._autosave_timer.start()

    # ------------------------------------------------------------------ load
    def load_or_create_default(self) -> None:
        existed = widget_storage.DATA_FILE.exists()
        states = widget_storage.load_all()
        if not states and not existed:
            states = [make_widget_state("weather", x=160, y=150)]
        for state in states:
            self._spawn(state)
        self.save()

    # --------------------------------------------------------------- create
    def _auto_position(self, state: WidgetState) -> tuple[int, int]:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 160, 150
        area = screen.availableGeometry()
        index = len(self.widgets) % 6
        x = area.left() + 90 + index * 38
        y = area.top() + 90 + index * 34
        x = min(x, area.right() - state.width - 24)
        y = min(y, area.bottom() - state.height - 24)
        return max(area.left() + 12, x), max(area.top() + 12, y)

    def create_widget(self, kind: str, x: int | None = None,
                      y: int | None = None) -> WidgetWindow:
        state = make_widget_state(kind)
        if x is None or y is None:
            state.x, state.y = self._auto_position(state)
        else:
            state.x, state.y = x, y

        widget = self._spawn(state)
        widget.show()
        self.save()
        self.changed.emit()
        return widget

    def _spawn(self, state: WidgetState) -> WidgetWindow:
        widget = WidgetWindow(state, self.weather)
        widget.geometry_changed.connect(self._on_geometry_changed)
        widget.state_changed.connect(lambda _id: self.save())
        widget.edit_requested.connect(self.edit_requested)
        widget.delete_requested.connect(self.remove_widget)
        widget.duplicate_requested.connect(self._on_duplicate_requested)
        self.widgets[state.id] = widget
        widget.show()
        return widget

    # --------------------------------------------------------------- modify
    def duplicate_widget(self, fence_id: str) -> WidgetWindow | None:
        src = self.widgets.get(fence_id)
        if src is None:
            return None

        state = copy.deepcopy(src.state)
        state.id = str(uuid.uuid4())
        state.title = f"{state.title} (копия)"
        state.x += 32
        state.y += 32
        state.locked = False

        widget = self._spawn(state)
        widget.show()
        self.save()
        self.changed.emit()
        return widget

    def _on_duplicate_requested(self, fence_id: str) -> None:
        widget = self.duplicate_widget(fence_id)
        if widget is not None:
            self.edit_requested.emit(widget.state.id)

    def remove_widget(self, fence_id: str) -> None:
        widget = self.widgets.pop(fence_id, None)
        if widget is not None:
            widget.close()
            widget.deleteLater()
        self.save()
        self.changed.emit()

    def toggle_all_visibility(self) -> None:
        if not self.widgets:
            return
        any_visible = any(w.isVisible() for w in self.widgets.values())
        self._all_hidden = any_visible
        for widget in self.widgets.values():
            if any_visible:
                widget.hide()
            else:
                widget.show()
                if widget.state.always_on_top:
                    widget.raise_()

    def save(self) -> None:
        widget_storage.save_all([w.state for w in self.widgets.values()])

    def _on_geometry_changed(self, _fence_id: str) -> None:
        self.save()
