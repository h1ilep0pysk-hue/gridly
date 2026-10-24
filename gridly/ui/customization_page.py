"""
ui/customization_page.py
Вкладка «Кастомизация»: глубокая панель свойств Fences и конструктор
составных виджетов из вложенных мини-модулей.

Слева — объекты (fences и составные виджеты) и палитра модулей, справа —
панель свойств. Изменения сразу применяются к окнам и сохраняются.
"""

from __future__ import annotations

import copy
from typing import Callable

from PyQt6.QtCore import (QMimeData, QPoint, QPointF, QRectF, Qt, QTimer,
                          pyqtSignal)
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog,
                             QComboBox, QFileDialog, QFormLayout, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QPlainTextEdit,
                             QPushButton, QScrollArea, QSlider, QSizePolicy,
                             QSpinBox, QSplitter, QStackedWidget, QTabWidget,
                             QVBoxLayout, QWidget)

from core.module_data import (MUSIC_SOURCES, USER_PLACEHOLDERS,
                              format_plan_done, parse_plan_done, parse_plans,
                              toggle_plan_done)
from core.storage import (BACKGROUND_MODES, BORDER_STYLES, TEXTURES,
                          TITLE_ALIGNS)
from core.widget_storage import (MODULE_ACCENTS, MODULE_DEFAULT_SIZE,
                                 MODULE_DEFAULT_TEXT, MODULE_ICONS,
                                 MODULE_ORDER, MODULES, WIDGET_KINDS,
                                 WidgetBlock, WidgetState, block_descendants,
                                 default_module_settings, make_block,
                                 state_needs_clock, state_needs_metrics,
                                 state_needs_weather)
from ui.fence_widget import LAYOUT_NAMES
from ui.widget_icons import make_kind_icon
from ui.widget_render import (block_content_rect, block_rect_at,
                              iter_widget_blocks, plan_row_index_at,
                              sample_custom_data, widget_card_rect,
                              widget_content_rect)

MODULE_MIME = "application/x-gridly-module"
USER_ICON_OPTIONS = {
    "custom": "Сетка",
    "text": "Текст",
    "notepad": "Блокнот",
    "calculator": "Калькулятор",
    "todo": "Список дел",
    "clock": "Часы",
    "date": "Дата",
    "countdown": "Отсчёт",
    "stopwatch": "Секундомер",
    "timer": "Таймер",
    "network": "Сеть",
    "uptime": "Время работы",
    "processes": "Процессы",
    "quote": "Цитата",
    "worldclock": "Глобус",
    "cpu": "Процессор",
    "memory": "Память",
    "battery": "Батарея",
    "disk": "Диск",
    "weather_sun": "Солнце",
    "weather_moon": "Луна",
    "weather_cloud": "Облако",
    "weather_rain": "Дождь",
    "weather_snow": "Снег",
    "user": "Слайдеры",
}
FENCE_COLORS = {
    "background": "#2b2b2b",
    "border": "#ffffff",
    "text": "#ffffff",
    "shadow": "#000000",
}


# --------------------------------------------------------------------------
#  Небольшие переиспользуемые элементы управления
# --------------------------------------------------------------------------
class ColorButton(QPushButton):
    """Кнопка-образец цвета. По клику открывает системную палитру."""

    color_edited = pyqtSignal(QColor)

    def __init__(self, color: str = "#ffffff", parent: QWidget | None = None):
        super().__init__(parent)
        self._color = QColor(color)
        if not self._color.isValid():
            self._color = QColor("#ffffff")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(27)
        self.setMinimumWidth(110)
        self.setFixedWidth(138)
        self.setSizePolicy(QSizePolicy.Policy.Fixed,
                           QSizePolicy.Policy.Fixed)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: QColor | str) -> None:
        value = QColor(color)
        if not value.isValid():
            return
        self._color = value
        self._refresh()

    def _refresh(self) -> None:
        name = self._color.name()
        self.setText(name.upper())
        self.setStyleSheet(
            "QPushButton {"
            f" background: {name};"
            f" color: {'#111111' if self._color.lightness() > 150 else '#ffffff'};"
            " border: 1px solid rgba(128, 128, 128, 160);"
            " border-radius: 6px; padding: 2px 8px; font-size: 11px;"
            " text-align: left; }"
            "QPushButton:hover { border-color: #7f8a97; }"
        )

    def _pick(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Выберите цвет")
        if chosen.isValid():
            self.set_color(chosen)
            self.color_edited.emit(chosen)


class SliderField(QWidget):
    """Подписанный слайдер со значением."""

    value_changed = pyqtSignal(int)

    def __init__(self, minimum: int, maximum: int, value: int,
                 suffix: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._suffix = suffix
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        top = QHBoxLayout()
        top.addStretch(1)
        self.value_label = QLabel()
        self.value_label.setObjectName("mutedLabel")
        top.addWidget(self.value_label)
        lay.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.slider.valueChanged.connect(self._on_value)
        lay.addWidget(self.slider)
        self._update_label(value)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(int(value))
        self.slider.blockSignals(False)
        self._update_label(self.slider.value())

    def _update_label(self, value: int) -> None:
        self.value_label.setText(f"{value}{self._suffix}")

    def _on_value(self, value: int) -> None:
        self._update_label(value)
        self.value_changed.emit(value)


class ModulePalette(QListWidget):
    """Палитра модулей с drag-and-drop на основу виджета."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setObjectName("modulePalette")
        self.setMinimumHeight(170)

    def mimeData(self, items):  # noqa: N802 — API Qt
        data = QMimeData()
        if items:
            module = items[0].data(Qt.ItemDataRole.UserRole)
            if module:
                data.setData(MODULE_MIME, str(module).encode("utf-8"))
                data.setText(str(module))
        return data


# --------------------------------------------------------------------------
#  Интерактивная основа составного виджета
# --------------------------------------------------------------------------
class CustomWidgetCanvas(QWidget):
    block_selected = pyqtSignal(str)
    blocks_changed = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._state: WidgetState | None = None
        self._data: dict | None = None
        self._selected_id = ""
        self._mode: str | None = None
        self._start_block: WidgetBlock | None = None
        self._start_pt = QPointF()
        self._start_x = 0
        self._start_y = 0
        self._start_w = 0
        self._start_h = 0
        self._changed = False
        self.setMinimumHeight(310)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------- state
    def set_state(self, state: WidgetState | None) -> None:
        self._state = state
        self._data = sample_custom_data(state) if state else None
        if state and self._selected_id and not any(
                b.id == self._selected_id for b in state.blocks):
            self._selected_id = ""
        self.update()

    def set_selected(self, block_id: str) -> None:
        self._selected_id = block_id or ""
        self.update()

    def selected_id(self) -> str:
        return self._selected_id

    # ------------------------------------------------------------ layout
    def _target(self) -> tuple[QRectF, float]:
        if self._state is None:
            return QRectF(), 1.0
        margin = 14.0
        avail_w = max(1.0, self.width() - margin * 2)
        avail_h = max(1.0, self.height() - margin * 2)
        scale = min(avail_w / max(1, self._state.width),
                    avail_h / max(1, self._state.height), 1.0)
        w = self._state.width * scale
        h = self._state.height * scale
        return QRectF((self.width() - w) / 2,
                      (self.height() - h) / 2, w, h), scale

    def _to_widget(self, pos: QPoint) -> QPointF:
        """Переводит точку холста в координаты окна виджета (1:1)."""
        target, scale = self._target()
        if scale <= 0:
            return QPointF()
        return QPointF((pos.x() - target.left()) / scale,
                       (pos.y() - target.top()) / scale)

    def _widget_rect(self) -> QRectF:
        """Прямоугольник окна виджета в натуральных координатах."""
        assert self._state is not None
        return QRectF(0, 0, max(1, self._state.width),
                      max(1, self._state.height))

    def _card_rect(self) -> QRectF:
        """Основа виджета без поля под тень — система координат блоков."""
        return widget_card_rect(self._widget_rect())

    def _block_rects(self) -> list[tuple[WidgetBlock, QRectF]]:
        if self._state is None:
            return []
        return iter_widget_blocks(self._state, self._card_rect())

    def _map_rect(self, rect: QRectF) -> QRectF:
        """Натуральные координаты блока → координаты холста."""
        target, scale = self._target()
        return QRectF(target.left() + rect.left() * scale,
                      target.top() + rect.top() * scale,
                      rect.width() * scale,
                      rect.height() * scale)

    def _parent_size(self, block: WidgetBlock) -> tuple[float, float]:
        """Размер области родителя в координатах блоков."""
        assert self._state is not None
        if not block.parent_id:
            area = widget_content_rect(self._card_rect(), self._state)
            return (max(1.0, area.width()), max(1.0, area.height()))
        for other in self._state.blocks:
            if other.id == block.parent_id:
                area = block_content_rect(
                    other, QRectF(0, 0, other.width, other.height)
                )
                return (max(1.0, area.width()), max(1.0, area.height()))
        area = widget_content_rect(self._card_rect(), self._state)
        return (max(1.0, area.width()), max(1.0, area.height()))

    def _parent_area(self, block: WidgetBlock) -> QRectF:
        assert self._state is not None
        if not block.parent_id:
            return widget_content_rect(self._card_rect(), self._state)
        for other, rect in self._block_rects():
            if other.id == block.parent_id:
                return block_content_rect(other, rect)
        return widget_content_rect(self._card_rect(), self._state)

    # ------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor("#00000000"))

        # Лёгкая «сцена» вокруг основы
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(128, 128, 128, 18))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)

        if self._state is None:
            p.setPen(QColor(150, 150, 150, 170))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       "Выберите составной виджет")
            p.end()
            return

        target, scale = self._target()
        try:
            from ui.widget_render import paint_widget
            p.save()
            p.translate(target.topLeft())
            p.scale(scale, scale)
            paint_widget(p, self._widget_rect(), self._state, self._data,
                         hovered=False)
            p.restore()
        except Exception as exc:  # предпросмотр не должен ронять приложение
            p.setPen(QColor("#ff6b6b"))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       f"Ошибка предпросмотра:\n{exc}")

        if self._selected_id:
            for block, rect in self._block_rects():
                if block.id != self._selected_id:
                    continue
                canvas_rect = self._map_rect(rect)
                accent = QColor("#5cc8ff")
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(accent, 1.5, Qt.PenStyle.DashLine))
                p.drawRoundedRect(canvas_rect.adjusted(-1, -1, 1, 1), 6, 6)
                handle = QRectF(canvas_rect.right() - 4,
                                canvas_rect.bottom() - 4, 9, 9)
                p.setPen(QPen(QColor("#ffffff"), 1))
                p.setBrush(accent)
                p.drawRect(handle)
                break
        p.end()

    # -------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        if self._state is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        _target, scale = self._target()
        point = self._to_widget(event.position().toPoint())

        if self._selected_id:
            for block, rect in self._block_rects():
                if block.id != self._selected_id:
                    continue
                handle = 10.0 / max(0.2, scale)
                if (abs(point.x() - rect.right()) <= handle
                        and abs(point.y() - rect.bottom()) <= handle):
                    self._mode = "resize"
                    self._start_block = block
                    self._start_pt = point
                    self._start_w = block.width
                    self._start_h = block.height
                    self._changed = False
                    return

        block = block_rect_at(self._state, self._card_rect(), point)
        if block is None:
            if self._selected_id:
                self._selected_id = ""
                self.block_selected.emit("")
            self.update()
            return

        if block.id != self._selected_id:
            self._selected_id = block.id
            self.block_selected.emit(block.id)
        self._mode = "move"
        self._start_block = block
        self._start_pt = point
        self._start_x = block.x
        self._start_y = block.y
        self._changed = False
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if (self._state is None or self._start_block is None
                or self._mode is None):
            return
        point = self._to_widget(event.position().toPoint())
        delta = point - self._start_pt
        block = self._start_block
        area_w, area_h = self._parent_size(block)
        if self._mode == "move":
            max_x = max(0, int(area_w - block.width))
            max_y = max(0, int(area_h - block.height))
            new_x = max(0, min(max_x, int(round(self._start_x + delta.x()))))
            new_y = max(0, min(max_y, int(round(self._start_y + delta.y()))))
            if (new_x, new_y) != (block.x, block.y):
                block.x = new_x
                block.y = new_y
                self._changed = True
                self.update()
        elif self._mode == "resize":
            max_w = max(36, int(area_w - block.x))
            max_h = max(28, int(area_h - block.y))
            new_w = max(36, min(max_w, int(round(self._start_w + delta.x()))))
            new_h = max(28, min(max_h, int(round(self._start_h + delta.y()))))
            if (new_w, new_h) != (block.width, block.height):
                block.width = new_w
                block.height = new_h
                self._changed = True
                self.update()

    def mouseReleaseEvent(self, event) -> None:
        was_changed = self._changed
        self._mode = None
        self._start_block = None
        self._changed = False
        if was_changed:
            self.blocks_changed.emit()

    def mouseDoubleClickEvent(self, event) -> None:
        if self._state is None:
            return
        point = self._to_widget(event.position().toPoint())
        block = block_rect_at(self._state, self._card_rect(), point)
        if block is not None:
            self._selected_id = block.id
            self.block_selected.emit(block.id)
            if block.module == "plans":
                rect = next((rect for item, rect in self._block_rects()
                             if item.id == block.id), QRectF())
                index = plan_row_index_at(block, rect, point)
                if index is not None:
                    items = parse_plans(block.text)
                    block.settings["done"] = toggle_plan_done(
                        block.settings.get("done", ""), index, len(items)
                    )
                    self.blocks_changed.emit()
            self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) \
                and self._state is not None and self._selected_id:
            self._remove_selected()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------- drag/drop
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MODULE_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MODULE_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if self._state is None or not event.mimeData().hasFormat(MODULE_MIME):
            return
        module = bytes(event.mimeData().data(MODULE_MIME)).decode("utf-8")
        if module not in MODULES:
            return
        point = self._to_widget(event.position().toPoint())
        parent = block_rect_at(self._state, self._card_rect(), point)
        parent_id = parent.id if parent else None
        area = self._parent_area(parent) if parent else widget_content_rect(
            self._card_rect(), self._state)
        default_w, default_h = MODULE_DEFAULT_SIZE.get(module, (180, 70))
        x = int(round(point.x() - area.left() - default_w / 2))
        y = int(round(point.y() - area.top() - default_h / 2))
        max_x = max(0, int(area.width() - default_w))
        max_y = max(0, int(area.height() - default_h))
        block = make_block(module, max(0, min(max_x, x)),
                           max(0, min(max_y, y)), parent_id=parent_id)
        self._state.blocks.append(block)
        self._selected_id = block.id
        self.block_selected.emit(block.id)
        self.blocks_changed.emit()
        self.status_message.emit(
            f"Добавлен модуль «{MODULES.get(module, module)}»"
            + (f" внутрь «{MODULES.get(parent.module, '')}»" if parent else "")
        )
        self.update()
        event.acceptProposedAction()

    # ------------------------------------------------------------- helpers
    def _remove_selected(self) -> None:
        if self._state is None or not self._selected_id:
            return
        doomed = block_descendants(self._state.blocks, self._selected_id)
        doomed.add(self._selected_id)
        self._state.blocks = [b for b in self._state.blocks
                              if b.id not in doomed]
        self._selected_id = ""
        self.block_selected.emit("")
        self.blocks_changed.emit()
        self.update()


# --------------------------------------------------------------------------
#  Вкладка кастомизации
# --------------------------------------------------------------------------
class CustomizationPage(QWidget):
    """Глубокая настройка fences и сборка составных виджетов."""

    open_widget_requested = pyqtSignal(str)

    def __init__(self, fence_manager, widget_manager, theme: dict,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.fence_manager = fence_manager
        self.widget_manager = widget_manager
        self._theme = theme
        self._current_kind: str | None = None
        self._current_id: str | None = None
        self._loading = False
        self._refreshing_objects = False
        self._geometry_connected: set[str] = set()
        self._fence_controls: list[tuple[QWidget, str, str]] = []
        self._custom_widget_controls: list[tuple[QWidget, str, str]] = []
        self._custom_block_controls: list[tuple[QWidget, str, str]] = []

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._flush_save)

        self._build_ui()
        if hasattr(self.fence_manager, "changed"):
            self.fence_manager.changed.connect(self._on_objects_changed)
        if self.widget_manager is not None and \
                hasattr(self.widget_manager, "changed"):
            self.widget_manager.changed.connect(self._on_objects_changed)
        self.refresh_objects()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        t = self._theme
        self.setStyleSheet(
            f"""
            QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
                background: {t['input_bg']};
                color: {t['input_text']};
                border: 1px solid {t['input_border']};
                border-radius: 7px;
                padding: 5px 8px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
            QPlainTextEdit:focus {{
                border: 1px solid {t['input_focus']};
            }}
            QComboBox QAbstractItemView {{
                background: {t['input_bg']};
                color: {t['input_text']};
                selection-background-color: {t['list_selected']};
                border: 1px solid {t['input_border']};
            }}
            QListWidget#objectList, QListWidget#modulePalette {{
                border: 1px solid {t['list_border']};
                border-radius: 8px;
                background: {t['list_bg']};
                color: {t['list_text']};
                padding: 4px;
            }}
            QListWidget#objectList::item, QListWidget#modulePalette::item {{
                padding: 6px 8px;
                border-radius: 5px;
            }}
            QListWidget#objectList::item:selected,
            QListWidget#modulePalette::item:selected {{
                background: {t['list_selected']};
                color: {t['list_text']};
            }}
            QListWidget#objectList::item:hover,
            QListWidget#modulePalette::item:hover {{
                background: {t['list_hover']};
            }}
            QGroupBox {{
                border: 1px solid {t['list_border']};
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 10px;
                font-weight: 600;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 4px;
            }}
            QFrame#customCanvasFrame {{
                border: 1px solid {t['list_border']};
                border-radius: 12px;
                background: transparent;
            }}
            QLabel#mutedLabel {{ color: #8a94a3; }}
            QTabWidget::pane {{
                border: 1px solid {t['list_border']};
                border-radius: 8px;
                top: -1px;
            }}
            QTabBar::tab {{
                padding: 7px 13px;
                border: 1px solid transparent;
                background: transparent;
                color: {t['input_text']};
            }}
            QTabBar::tab:selected {{
                background: {t['btn_bg']};
                border: 1px solid {t['btn_border']};
                border-radius: 6px;
            }}
            QTabBar::tab:hover {{ background: {t['btn_hover']}; }}
            QSlider::groove:horizontal {{
                height: 4px;
                background: {t['input_border']};
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: #7f8a97;
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px;
                margin: -6px 0;
                border-radius: 7px;
                background: {t['btn_text']};
                border: 1px solid {t['btn_border']};
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setSizes([310, 700])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 10, 0)
        lay.setSpacing(9)

        title = QLabel("Объекты")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        lay.addWidget(title)

        self.object_list = QListWidget()
        self.object_list.setObjectName("objectList")
        self.object_list.setMinimumHeight(170)
        self.object_list.currentItemChanged.connect(self._on_object_selected)
        lay.addWidget(self.object_list, 1)

        obj_btns = QHBoxLayout()
        obj_btns.setSpacing(6)
        add_fence_btn = QPushButton("+ Fence")
        add_fence_btn.setToolTip("Создать новый fence и открыть его свойства")
        add_fence_btn.clicked.connect(lambda _c=False: self._create_fence())
        obj_btns.addWidget(add_fence_btn, 1)
        if self.widget_manager is not None:
            add_custom_btn = QPushButton("+ Составной")
            add_custom_btn.setToolTip(
                "Создать пустую основу составного виджета"
            )
            add_custom_btn.clicked.connect(
                lambda _c=False: self._create_custom_widget()
            )
            obj_btns.addWidget(add_custom_btn, 1)
        lay.addLayout(obj_btns)

        if self.widget_manager is not None:
            modules_group = QGroupBox("Мини-модули")
            modules_lay = QVBoxLayout(modules_group)
            modules_lay.setContentsMargins(8, 12, 8, 8)
            modules_lay.setSpacing(6)
            palette_hint = QLabel(
                "Перетащите модуль на основу.\n"
                "Бросок на блок вкладывает модуль внутрь.\n"
                "«Свой модуль» собирается без кода."
            )
            palette_hint.setObjectName("mutedLabel")
            palette_hint.setWordWrap(True)
            palette_hint.setStyleSheet("font-size: 11px;")
            modules_lay.addWidget(palette_hint)
            self.module_palette = ModulePalette()
            for module in MODULE_ORDER:
                item = QListWidgetItem(
                    make_kind_icon(MODULE_ICONS.get(module, "custom"), 12,
                                   QColor(MODULE_ACCENTS.get(module,
                                                             "#8ab4ff"))),
                    MODULES[module],
                )
                item.setData(Qt.ItemDataRole.UserRole, module)
                item.setToolTip(
                    f"{MODULES[module]} — перетащите на основу виджета"
                )
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled)
                self.module_palette.addItem(item)
            self.module_palette.itemDoubleClicked.connect(
                lambda item: self._add_module_to_root(
                    item.data(Qt.ItemDataRole.UserRole)
                )
            )
            modules_lay.addWidget(self.module_palette, 1)
            add_module_btn = QPushButton("Добавить выбранный модуль")
            add_module_btn.setMinimumHeight(30)
            add_module_btn.clicked.connect(
                lambda _c=False: self._add_module_from_palette()
            )
            modules_lay.addWidget(add_module_btn)
            own_module_btn = QPushButton("+ Свой модуль без кода")
            own_module_btn.setMinimumHeight(30)
            own_module_btn.setToolTip(
                "Добавить универсальный модуль с подписями, иконкой, "
                "прогрессом и подстановками"
            )
            own_module_btn.clicked.connect(
                lambda _c=False: self._add_module_to_root("user")
            )
            modules_lay.addWidget(own_module_btn)
            lay.addWidget(modules_group, 1)
        else:
            self.module_palette = None

        self.left_hint = QLabel(
            "Выберите объект слева.\n"
            "Fences настраиваются по десяткам параметров, а составные\n"
            "виджеты собираются перетаскиванием мини-модулей."
        )
        self.left_hint.setObjectName("mutedLabel")
        self.left_hint.setWordWrap(True)
        self.left_hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.left_hint)
        return w

    def _build_right(self) -> QWidget:
        self.stack = QStackedWidget()

        placeholder = QWidget()
        p_lay = QVBoxLayout(placeholder)
        p_lay.addStretch(1)
        icon = QLabel()
        icon.setPixmap(make_kind_icon("custom", 34, QColor("#5cc8ff"))
                       .pixmap(68, 68))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_lay.addWidget(icon)
        title = QLabel("Кастомизация рабочего стола")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 19px; font-weight: 600;")
        p_lay.addWidget(title)
        desc = QLabel(
            "Слева выберите fence или составной виджет.\n"
            "Fences настраиваются по десяткам параметров, а составные\n"
            "виджеты собираются перетаскиванием мини-модулей."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setObjectName("mutedLabel")
        desc.setWordWrap(True)
        p_lay.addWidget(desc)
        p_lay.addStretch(1)
        self.stack.addWidget(placeholder)

        self.fence_tabs = self._build_fence_panel()
        self.stack.addWidget(self.fence_tabs)

        if self.widget_manager is not None:
            self.custom_panel = self._build_custom_panel()
            self.stack.addWidget(self.custom_panel)
        else:
            self.custom_panel = None
        return self.stack

    # ---------------------------------------------------------- fence panel
    def _build_fence_panel(self) -> QWidget:
        tabs = QTabWidget()
        self._fence_tab_widgets = tabs

        tab, form = self._make_tab(tabs, "Геометрия")
        self._build_fence_geometry(form)
        tab, form = self._make_tab(tabs, "Фон")
        self._build_fence_background(form)
        tab, form = self._make_tab(tabs, "Рамка и эффекты")
        self._build_fence_effects(form)
        tab, form = self._make_tab(tabs, "Заголовок")
        self._build_fence_header(form)
        tab, form = self._make_tab(tabs, "Поведение")
        self._build_fence_behavior(form)
        tab, form = self._make_tab(tabs, "Элементы")
        self._build_fence_items(form)
        return tabs

    def _make_tab(self, tabs: QTabWidget,
                  name: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(10, 10, 10, 10)
        page_lay.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        content = QWidget()
        form = QVBoxLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        scroll.setWidget(content)
        page_lay.addWidget(scroll, 1)
        tabs.addTab(page, name)
        return page, form

    def _group(self, parent_layout: QVBoxLayout,
               title: str) -> QFormLayout:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(7)
        parent_layout.addWidget(group)
        return form

    def _add_spin(self, form: QFormLayout, label: str, attr: str,
                  minimum: int, maximum: int, value: int,
                  source: str = "style", suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        if suffix:
            spin.setSuffix(suffix)
        spin.setValue(int(value))
        spin.valueChanged.connect(
            lambda v, a=attr, s=source: self._set_fence_value(a, v, s)
        )
        form.addRow(label, spin)
        self._fence_controls.append((spin, source, attr))
        return spin

    def _add_slider(self, form: QFormLayout, label: str, attr: str,
                    minimum: int, maximum: int, value: int,
                    source: str = "style", suffix: str = "") -> SliderField:
        field = SliderField(minimum, maximum, int(value), suffix)
        field.value_changed.connect(
            lambda v, a=attr, s=source: self._set_fence_value(a, v, s)
        )
        form.addRow(label, field)
        self._fence_controls.append((field, source, attr))
        return field

    def _add_check(self, form: QFormLayout, label: str, attr: str,
                   checked: bool, source: str = "style") -> QCheckBox:
        check = QCheckBox(label)
        check.setChecked(bool(checked))
        check.toggled.connect(
            lambda v, a=attr, s=source: self._set_fence_value(a, v, s)
        )
        form.addRow(check)
        self._fence_controls.append((check, source, attr))
        return check

    def _add_combo(self, form: QFormLayout, label: str, attr: str,
                   options: dict, value, source: str = "style") -> QComboBox:
        combo = QComboBox()
        for key, text in options.items():
            combo.addItem(text, key)
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda _i, a=attr, s=source, c=combo:
            self._set_fence_value(a, c.currentData(), s)
        )
        form.addRow(label, combo)
        self._fence_controls.append((combo, source, attr))
        return combo

    def _add_color(self, form: QFormLayout, label: str, attr: str,
                   value: str, source: str = "style") -> ColorButton:
        btn = ColorButton(value)
        btn.color_edited.connect(
            lambda color, a=attr, s=source:
            self._set_fence_value(a, color.name(), s)
        )
        form.addRow(label, btn)
        self._fence_controls.append((btn, source, attr))
        return btn

    def _build_fence_geometry(self, form: QVBoxLayout) -> None:
        st = self._current_style()
        state = self._current_fence_state()
        box = self._group(form, "Размер и позиция")
        size_row = QHBoxLayout()
        self._fence_width = QSpinBox()
        self._fence_width.setRange(140, 4000)
        self._fence_width.setSuffix(" px")
        self._fence_height = QSpinBox()
        self._fence_height.setRange(80, 4000)
        self._fence_height.setSuffix(" px")
        self._fence_width.valueChanged.connect(
            lambda v: self._set_fence_state_value("width", v)
        )
        self._fence_height.valueChanged.connect(
            lambda v: self._set_fence_state_value("height", v)
        )
        size_row.addWidget(self._fence_width, 1)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self._fence_height, 1)
        box.addRow("Размер:", size_row)
        self._fence_controls.extend([
            (self._fence_width, "state", "width"),
            (self._fence_height, "state", "height"),
        ])

        pos_row = QHBoxLayout()
        self._fence_x = QSpinBox()
        self._fence_x.setRange(-10000, 10000)
        self._fence_x.setPrefix("X ")
        self._fence_y = QSpinBox()
        self._fence_y.setRange(-10000, 10000)
        self._fence_y.setPrefix("Y ")
        self._fence_x.valueChanged.connect(
            lambda v: self._set_fence_state_value("x", v)
        )
        self._fence_y.valueChanged.connect(
            lambda v: self._set_fence_state_value("y", v)
        )
        pos_row.addWidget(self._fence_x, 1)
        pos_row.addWidget(self._fence_y, 1)
        box.addRow("Позиция:", pos_row)
        self._fence_controls.extend([
            (self._fence_x, "state", "x"),
            (self._fence_y, "state", "y"),
        ])

        container = self._group(form, "Контейнер")
        self._add_slider(container, "Скругление углов:", "corner_radius",
                         0, 120, st.corner_radius, suffix=" px")
        self._add_slider(container, "Внутренний паддинг:", "padding",
                         0, 80, st.padding, suffix=" px")
        self._add_slider(container, "Расстояние между элементами:", "spacing",
                         0, 80, st.spacing, suffix=" px")
        self._add_slider(container, "Прозрачность окна:", "opacity",
                         30, 255, st.opacity)
        self._add_spin(container, "Высота заголовка:", "header_height",
                       0, 200, st.header_height, suffix=" px")

        note = QLabel(
            "Размер и позиция применяются к окну fence сразу. "
            "Для раскладки «Папка» ширина и высота фиксированы."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px;")
        form.addWidget(note)
        form.addStretch(1)
        del state

    def _build_fence_background(self, form: QVBoxLayout) -> None:
        st = self._current_style()
        box = self._group(form, "Фон")
        self._add_combo(box, "Режим:", "bg_mode", BACKGROUND_MODES,
                        st.bg_mode)
        self._add_color(box, "Основной цвет:", "bg_color", st.bg_color)
        self._add_color(box, "Второй цвет:", "bg_color2", st.bg_color2)
        self._add_slider(box, "Прозрачность фона:", "bg_alpha",
                         0, 255, st.bg_alpha)
        self._add_slider(box, "Угол градиента:", "gradient_angle",
                         0, 360, st.gradient_angle, suffix="°")
        self._add_slider(box, "Прозрачность градиента:", "gradient_alpha",
                         0, 255, st.gradient_alpha)

        texture = self._group(form, "Текстура")
        self._add_combo(texture, "Узор:", "texture", TEXTURES, st.texture)
        self._add_color(texture, "Цвет узора:", "texture_color",
                        st.texture_color)
        self._add_slider(texture, "Яркость узора:", "texture_alpha",
                         0, 160, st.texture_alpha)
        self._add_slider(texture, "Масштаб узора:", "texture_scale",
                         6, 80, st.texture_scale, suffix=" px")

        blur = self._group(form, "Акриловое размытие")
        self._add_check(blur, "Включить glassmorphism", "blur_enabled",
                        st.blur_enabled)
        self._add_slider(blur, "Интенсивность тонирования:", "blur_alpha",
                         0, 255, st.blur_alpha)
        hint = QLabel(
            "Размытие применяется к рабочему столу за окном fence. "
            "Работает на Windows 10/11; при недоступности API включается "
            "обычный blur-behind."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11px;")
        blur.addRow(hint)
        form.addStretch(1)

    def _build_fence_effects(self, form: QVBoxLayout) -> None:
        st = self._current_style()
        border = self._group(form, "Рамка")
        self._add_spin(border, "Толщина:", "border_width",
                       0, 24, st.border_width, suffix=" px")
        self._add_color(border, "Цвет:", "border_color", st.border_color)
        self._add_slider(border, "Непрозрачность рамки:", "border_alpha",
                         0, 255, st.border_alpha)
        self._add_combo(border, "Стиль:", "border_style", BORDER_STYLES,
                        st.border_style)

        shadow = self._group(form, "Внешняя тень")
        self._add_check(shadow, "Включить внешнюю тень", "shadow_enabled",
                        st.shadow_enabled)
        self._add_color(shadow, "Цвет тени:", "shadow_color", st.shadow_color)
        self._add_slider(shadow, "Сила тени:", "shadow_alpha",
                         0, 255, st.shadow_alpha)
        self._add_slider(shadow, "Размытие:", "shadow_blur",
                         0, 80, st.shadow_blur, suffix=" px")
        shadow.addRow("Смещение:", self._pair_spins(
            "shadow_offset_x", "shadow_offset_y", -40, 40,
            st.shadow_offset_x, st.shadow_offset_y))

        inner = self._group(form, "Внутренняя тень")
        self._add_check(inner, "Включить внутреннюю тень",
                        "inner_shadow_enabled", st.inner_shadow_enabled)
        self._add_color(inner, "Цвет:", "inner_shadow_color",
                        st.inner_shadow_color)
        self._add_slider(inner, "Сила:", "inner_shadow_alpha",
                         0, 255, st.inner_shadow_alpha)
        self._add_slider(inner, "Размытие:", "inner_shadow_blur",
                         0, 60, st.inner_shadow_blur, suffix=" px")
        inner.addRow("Смещение:", self._pair_spins(
            "inner_shadow_offset_x", "inner_shadow_offset_y", -40, 40,
            st.inner_shadow_offset_x, st.inner_shadow_offset_y))

        glow = self._group(form, "Свечение")
        self._add_check(glow, "Включить свечение", "glow_enabled",
                        st.glow_enabled)
        self._add_color(glow, "Цвет свечения:", "glow_color", st.glow_color)
        self._add_slider(glow, "Сила свечения:", "glow_alpha",
                         0, 255, st.glow_alpha)
        self._add_slider(glow, "Радиус:", "glow_radius",
                         0, 60, st.glow_radius, suffix=" px")
        form.addStretch(1)

    def _pair_spins(self, attr_a: str, attr_b: str, minimum: int, maximum: int,
                    value_a: int, value_b: int) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        spin_a = QSpinBox()
        spin_a.setRange(minimum, maximum)
        spin_a.setPrefix("X ")
        spin_a.setValue(int(value_a))
        spin_a.valueChanged.connect(
            lambda v, a=attr_a: self._set_fence_value(a, v)
        )
        spin_b = QSpinBox()
        spin_b.setRange(minimum, maximum)
        spin_b.setPrefix("Y ")
        spin_b.setValue(int(value_b))
        spin_b.valueChanged.connect(
            lambda v, a=attr_b: self._set_fence_value(a, v)
        )
        lay.addWidget(spin_a, 1)
        lay.addWidget(spin_b, 1)
        self._fence_controls.append((spin_a, "style", attr_a))
        self._fence_controls.append((spin_b, "style", attr_b))
        return row

    def _build_fence_header(self, form: QVBoxLayout) -> None:
        st = self._current_style()
        header = self._group(form, "Панель заголовка")
        self._add_check(header, "Показывать заголовок", "header_visible",
                        st.header_visible)
        self._add_spin(header, "Высота:", "header_height",
                       20, 200, st.header_height, suffix=" px")
        self._add_color(header, "Цвет заголовка:", "header_bg", st.header_bg)
        self._add_color(header, "Второй цвет:", "header_bg2", st.header_bg2)
        self._add_slider(header, "Прозрачность заголовка:", "header_alpha",
                         0, 255, st.header_alpha)
        self._add_check(header, "Градиент заголовка", "header_gradient",
                        st.header_gradient)

        title = self._group(form, "Текст заголовка")
        self._add_color(title, "Цвет текста:", "title_color", st.title_color)
        font_combo = QComboBox()
        font_combo.setEditable(True)
        fonts = [
            "Segoe UI", "Segoe UI Variable", "Arial", "Calibri", "Cambria",
            "Candara", "Consolas", "Corbel", "Georgia", "Tahoma",
            "Times New Roman", "Trebuchet MS", "Verdana",
        ]
        for family in fonts:
            font_combo.addItem(family, family)
        if st.title_font not in fonts:
            font_combo.addItem(st.title_font, st.title_font)
        index = font_combo.findData(st.title_font)
        if index >= 0:
            font_combo.setCurrentIndex(index)
        font_combo.currentTextChanged.connect(
            lambda family: self._set_fence_value(
                "title_font", family, "style"
            )
        )
        title.addRow("Шрифт:", font_combo)
        self._fence_controls.append((font_combo, "style", "title_font"))
        self._add_spin(title, "Размер:", "title_size",
                       8, 72, st.title_size, suffix=" px")
        weights = {
            100: "Thin", 200: "ExtraLight", 300: "Light", 400: "Normal",
            500: "Medium", 600: "DemiBold", 700: "Bold", 800: "ExtraBold",
            900: "Black",
        }
        self._add_combo(title, "Насыщенность:", "title_weight",
                        weights, _nearest_weight(st.title_weight))
        self._add_check(title, "Курсив", "title_italic", st.title_italic)
        self._add_spin(title, "Межбуквенное расстояние:",
                       "title_letter_spacing", -5, 30,
                       st.title_letter_spacing, suffix=" px")
        self._add_combo(title, "Выравнивание:", "title_align", TITLE_ALIGNS,
                        st.title_align)
        self._add_check(title, "Кнопка закрытия", "show_close_button",
                        st.show_close_button)
        self._add_check(title, "Кнопка закрепления", "show_lock_button",
                        st.show_lock_button)

        shadow = self._group(form, "Тень текста")
        self._add_check(shadow, "Включить тень текста", "title_shadow",
                        st.title_shadow)
        self._add_color(shadow, "Цвет тени:", "title_shadow_color",
                        st.title_shadow_color)
        self._add_slider(shadow, "Сила тени:", "title_shadow_alpha",
                         0, 255, st.title_shadow_alpha)
        self._add_slider(shadow, "Размытие:", "title_shadow_blur",
                         0, 24, st.title_shadow_blur, suffix=" px")
        shadow.addRow("Смещение:", self._pair_spins(
            "title_shadow_offset_x", "title_shadow_offset_y", -20, 20,
            st.title_shadow_offset_x, st.title_shadow_offset_y))

        glow = self._group(form, "Свечение текста")
        self._add_check(glow, "Включить свечение текста", "title_glow",
                        st.title_glow)
        self._add_color(glow, "Цвет свечения:", "title_glow_color",
                        st.title_glow_color)
        self._add_slider(glow, "Сила свечения:", "title_glow_alpha",
                         0, 255, st.title_glow_alpha)
        self._add_slider(glow, "Радиус:", "title_glow_radius",
                         0, 40, st.title_glow_radius, suffix=" px")
        form.addStretch(1)

    def _build_fence_behavior(self, form: QVBoxLayout) -> None:
        st = self._current_style()
        behavior = self._group(form, "Поведение")
        self.fence_title_edit = QLineEdit()
        self.fence_title_edit.setPlaceholderText("Название fence")
        self.fence_title_edit.editingFinished.connect(self._apply_fence_title)
        behavior.addRow("Название:", self.fence_title_edit)

        self.fence_layout_combo = QComboBox()
        for key, label in LAYOUT_NAMES.items():
            self.fence_layout_combo.addItem(label, key)
        self.fence_layout_combo.currentIndexChanged.connect(
            self._apply_fence_layout
        )
        behavior.addRow("Раскладка:", self.fence_layout_combo)

        self.fence_lock_check = QCheckBox(
            "Закрепить (запретить перемещение)"
        )
        self.fence_lock_check.toggled.connect(self._apply_fence_lock)
        behavior.addRow(self.fence_lock_check)

        self.fence_top_check = QCheckBox("Поверх всех окон")
        self.fence_top_check.toggled.connect(self._apply_fence_top)
        behavior.addRow(self.fence_top_check)

        buttons = QHBoxLayout()
        rename_btn = QPushButton("Переименовать…")
        rename_btn.clicked.connect(lambda _c=False: self._rename_fence())
        buttons.addWidget(rename_btn)
        duplicate_btn = QPushButton("Дублировать")
        duplicate_btn.clicked.connect(lambda _c=False: self._duplicate_fence())
        buttons.addWidget(duplicate_btn)
        behavior.addRow(buttons)

        reset_btn = QPushButton("Сбросить всё оформление")
        reset_btn.setMinimumHeight(30)
        reset_btn.clicked.connect(lambda _c=False: self._reset_fence_style())
        behavior.addRow(reset_btn)

        note = QLabel(
            "Закреплённый fence нельзя сдвинуть мышью, но его элементы "
            "продолжают работать. «Поверх всех окон» поднимает контейнер "
            "над остальными окнами."
        )
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        note.setStyleSheet("font-size: 11px;")
        behavior.addRow(note)
        form.addStretch(1)
        del st

    def _build_fence_items(self, form: QVBoxLayout) -> None:
        st = self._current_style()
        grid = self._group(form, "Размер элементов")
        self._add_spin(grid, "Ширина элемента:", "item_width",
                       40, 300, st.item_width, suffix=" px")
        self._add_spin(grid, "Высота элемента:", "item_height",
                       44, 300, st.item_height, suffix=" px")
        self._add_spin(grid, "Размер иконки:", "item_icon_size",
                       16, 160, st.item_icon_size, suffix=" px")

        text = self._group(form, "Подписи")
        self._add_check(text, "Показывать подписи", "show_item_labels",
                        st.show_item_labels)
        self._add_color(text, "Цвет текста:", "item_text_color",
                        st.item_text_color)
        self._add_spin(text, "Размер текста:", "item_text_size",
                       7, 32, st.item_text_size, suffix=" px")

        background = self._group(form, "Фон элементов")
        self._add_color(background, "Цвет фона:", "item_bg", st.item_bg)
        self._add_slider(background, "Непрозрачность фона:", "item_bg_alpha",
                         0, 255, st.item_bg_alpha)
        self._add_slider(background, "Подсветка при наведении:",
                         "item_hover_alpha", 0, 255, st.item_hover_alpha)
        self._add_slider(background, "Скругление элементов:", "item_radius",
                         0, 80, st.item_radius, suffix=" px")
        form.addStretch(1)

    # --------------------------------------------------------- custom panel
    def _build_custom_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(4, 0, 4, 4)
        lay.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("Конструктор составного виджета")
        title.setStyleSheet("font-size: 15px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        self.custom_subtitle = QLabel("")
        self.custom_subtitle.setObjectName("mutedLabel")
        head.addWidget(self.custom_subtitle)
        lay.addLayout(head)

        vertical = QSplitter(Qt.Orientation.Vertical)
        vertical.setChildrenCollapsible(False)

        canvas_box = QFrame()
        canvas_box.setObjectName("customCanvasFrame")
        canvas_lay = QVBoxLayout(canvas_box)
        canvas_lay.setContentsMargins(8, 8, 8, 8)
        canvas_lay.setSpacing(5)
        canvas_head = QHBoxLayout()
        canvas_title = QLabel("Основа · перетаскивайте блоки и их уголки")
        canvas_title.setObjectName("mutedLabel")
        canvas_title.setStyleSheet("font-size: 11px;")
        canvas_head.addWidget(canvas_title)
        canvas_head.addStretch(1)
        self.canvas_status = QLabel("")
        self.canvas_status.setObjectName("mutedLabel")
        self.canvas_status.setStyleSheet("font-size: 11px;")
        canvas_head.addWidget(self.canvas_status)
        canvas_lay.addLayout(canvas_head)

        self.canvas = CustomWidgetCanvas()
        self.canvas.block_selected.connect(self._on_block_selected)
        self.canvas.blocks_changed.connect(self._on_canvas_changed)
        self.canvas.status_message.connect(self._set_canvas_status)
        canvas_lay.addWidget(self.canvas, 1)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        parent_label = QLabel("Родитель:")
        tools.addWidget(parent_label)
        self.parent_combo = QComboBox()
        self.parent_combo.setMinimumWidth(170)
        self.parent_combo.currentIndexChanged.connect(
            self._apply_block_parent
        )
        tools.addWidget(self.parent_combo, 1)
        dup_btn = QPushButton("Дублировать")
        dup_btn.clicked.connect(lambda _c=False: self._duplicate_block())
        tools.addWidget(dup_btn)
        up_btn = QPushButton("Выше")
        up_btn.clicked.connect(lambda _c=False: self._move_block(-1))
        tools.addWidget(up_btn)
        down_btn = QPushButton("Ниже")
        down_btn.clicked.connect(lambda _c=False: self._move_block(1))
        tools.addWidget(down_btn)
        del_btn = QPushButton("Удалить блок")
        del_btn.clicked.connect(lambda _c=False: self._delete_block())
        tools.addWidget(del_btn)
        canvas_lay.addLayout(tools)
        vertical.addWidget(canvas_box)

        self.block_tabs = QTabWidget()
        self._build_block_tabs(self.block_tabs)
        vertical.addWidget(self.block_tabs)
        vertical.setSizes([360, 330])
        lay.addWidget(vertical, 1)
        return panel

    def _build_block_tabs(self, tabs: QTabWidget) -> None:
        tab, form = self._make_tab(tabs, "Блок")
        self._build_block_module(form)
        tab, form = self._make_tab(tabs, "Геометрия")
        self._build_block_geometry(form)
        tab, form = self._make_tab(tabs, "Оформление")
        self._build_block_style(form)
        tab, form = self._make_tab(tabs, "Эффекты")
        self._build_block_effects(form)
        tab, form = self._make_tab(tabs, "Виджет")
        self._build_custom_widget_tab(form)
        self._widget_tab_index = tabs.count() - 1

    def _add_block_spin(self, form: QFormLayout, label: str, attr: str,
                        minimum: int, maximum: int, value: int,
                        source: str = "style",
                        suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        if suffix:
            spin.setSuffix(suffix)
        spin.setValue(int(value))
        spin.valueChanged.connect(
            lambda v, a=attr, s=source: self._set_block_value(a, v, s)
        )
        form.addRow(label, spin)
        self._custom_block_controls.append((spin, source, attr))
        return spin

    def _add_block_slider(self, form: QFormLayout, label: str, attr: str,
                          minimum: int, maximum: int, value: int,
                          source: str = "style",
                          suffix: str = "") -> SliderField:
        field = SliderField(minimum, maximum, int(value), suffix)
        field.value_changed.connect(
            lambda v, a=attr, s=source: self._set_block_value(a, v, s)
        )
        form.addRow(label, field)
        self._custom_block_controls.append((field, source, attr))
        return field

    def _add_block_check(self, form: QFormLayout, label: str, attr: str,
                         checked: bool) -> QCheckBox:
        check = QCheckBox(label)
        check.setChecked(bool(checked))
        check.toggled.connect(
            lambda v, a=attr: self._set_block_value(a, v, "style")
        )
        form.addRow(check)
        self._custom_block_controls.append((check, "style", attr))
        return check

    def _add_block_color(self, form: QFormLayout, label: str, attr: str,
                         value: str) -> ColorButton:
        btn = ColorButton(value)
        btn.color_edited.connect(
            lambda color, a=attr:
            self._set_block_value(a, color.name(), "style")
        )
        form.addRow(label, btn)
        self._custom_block_controls.append((btn, "style", attr))
        return btn

    def _add_block_combo(self, form: QFormLayout, label: str, attr: str,
                         options: dict, value: str,
                         source: str = "style") -> QComboBox:
        combo = QComboBox()
        for key, text in options.items():
            combo.addItem(text, key)
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.currentIndexChanged.connect(
            lambda _i, a=attr, s=source, c=combo:
            self._set_block_value(a, c.currentData(), s)
        )
        form.addRow(label, combo)
        self._custom_block_controls.append((combo, source, attr))
        return combo

    def _build_block_module(self, form: QVBoxLayout) -> None:
        group = self._group(form, "Мини-модуль")
        self.block_main_form = group
        self.block_module_combo = QComboBox()
        for module in MODULE_ORDER:
            self.block_module_combo.addItem(MODULES[module], module)
        self.block_module_combo.currentIndexChanged.connect(
            self._apply_block_module
        )
        group.addRow("Тип модуля:", self.block_module_combo)
        self._custom_block_controls.append(
            (self.block_module_combo, "block", "module")
        )

        self.block_label_edit = QLineEdit()
        self.block_label_edit.setPlaceholderText(
            "Своя подпись (пусто — название модуля)"
        )
        self.block_label_edit.editingFinished.connect(
            lambda: self._set_block_value(
                "label", self.block_label_edit.text(), "style"
            )
        )
        group.addRow("Подпись:", self.block_label_edit)
        self._custom_block_controls.append(
            (self.block_label_edit, "style", "label")
        )

        self.block_value_spin = QSpinBox()
        self.block_value_spin.setRange(0, 100)
        self.block_value_spin.setSuffix(" %")
        self.block_value_spin.valueChanged.connect(
            lambda v: self._set_block_value("value", v, "block")
        )
        group.addRow("Значение индикатора:", self.block_value_spin)
        self._custom_block_controls.append(
            (self.block_value_spin, "block", "value")
        )

        self.block_text_edit = QPlainTextEdit()
        self.block_text_edit.setPlaceholderText(
            "Текст или заметка. Используется модулями «Текст», «Заметки», "
            "«Блокнот», «Список дел», «Планы на день» и «Цитата дня»."
        )
        self.block_text_edit.setFixedHeight(76)
        self.block_text_edit.textChanged.connect(
            lambda: self._set_block_value(
                "text", self.block_text_edit.toPlainText(), "block"
            )
        )
        group.addRow("Содержимое:", self.block_text_edit)
        self._custom_block_controls.append(
            (self.block_text_edit, "block", "text")
        )

        self.block_settings_group = QGroupBox("Настройки модуля")
        settings_lay = QVBoxLayout(self.block_settings_group)
        settings_lay.setContentsMargins(8, 12, 8, 8)
        settings_lay.setSpacing(6)
        self.block_settings_layout = QVBoxLayout()
        self.block_settings_layout.setContentsMargins(0, 0, 0, 0)
        self.block_settings_layout.setSpacing(6)
        settings_lay.addLayout(self.block_settings_layout)
        form.addWidget(self.block_settings_group)
        form.addStretch(1)

    # --------------------------------------------------- module settings
    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Сразу убираем из дерева, иначе старые поля ещё видны
                # в findChildren() до обработки DeferredDelete.
                widget.setParent(None)
                widget.deleteLater()
            child = item.layout()
            if child is not None:
                self._clear_layout(child)

    def _rebuild_block_settings(self, block: WidgetBlock | None) -> None:
        """Строит поля настроек, относящиеся только к выбранному модулю."""
        if not hasattr(self, "block_settings_layout"):
            return
        self._clear_layout(self.block_settings_layout)
        if block is None:
            self.block_settings_group.setVisible(False)
            return
        self.block_settings_group.setVisible(True)
        container = QWidget()
        form = QFormLayout(container)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(7)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.block_settings_layout.addWidget(container)

        module = block.module
        if module == "notepad":
            self._settings_hint(
                form,
                "Клик по блоку на основе открывает редактор прямо на месте. "
                "Текст также можно изменить в поле «Содержимое»."
            )
        elif module == "calculator":
            self._settings_line(form, "expression", "Выражение:", block,
                                "Например: (12 + 8) × 3")
            self._settings_hint(
                form,
                "Поддерживаются + − × ÷, скобки, степени, sqrt, sin, cos, "
                "pi. Клик по блоку — быстрое редактирование."
            )
        elif module == "todo":
            self._settings_hint(
                form,
                "По одному пункту на строку. [x] или ✓ — выполнено, "
                "[ ] или ○ — не выполнено. Пункты редактируются в поле "
                "«Содержимое»."
            )
        elif module == "plans":
            reset = QPushButton("Сбросить отметки")
            reset.clicked.connect(
                lambda _c=False, b=block: self._reset_plan_marks(b)
            )
            form.addRow(reset)
            self._settings_hint(
                form,
                "Напишите планы в поле «Содержимое» — по одному на строку. "
                "Сначала каждый план красный с крестиком. Двойной клик по "
                "строке на основе делает его зелёным с галочкой, повторный "
                "двойной клик возвращает крестик."
            )
        elif module == "music":
            self._settings_line(form, "title", "Название:", block,
                                "Мой трек")
            self._settings_line(form, "artist", "Исполнитель:", block,
                                "Любимая музыка")
            url_edit = self._settings_line(
                form, "url", "Ссылка или файл:", block,
                "https://soundcloud.com/… или C:\\Music\\track.mp3"
            )
            choose = QPushButton("Выбрать файл…")
            choose.clicked.connect(
                lambda _c=False, b=block, e=url_edit:
                self._choose_music_file(b, e)
            )
            form.addRow(choose)
            self._settings_combo(form, "source", "Источник:", block,
                                 MUSIC_SOURCES)
            self._settings_spin(form, "volume", "Громкость:", 0, 100,
                                block, suffix=" %")
            buttons = QHBoxLayout()
            play = QPushButton("Проверить / играть")
            play.clicked.connect(
                lambda _c=False, b=block: self._play_music_block(b)
            )
            stop = QPushButton("Остановить")
            stop.clicked.connect(lambda _c=False: self._stop_music_block())
            buttons.addWidget(play, 1)
            buttons.addWidget(stop, 1)
            form.addRow(buttons)
            self._settings_hint(
                form,
                "Spotify, SoundCloud и Яндекс Музыка открываются в браузере. "
                "Прямые аудиофайлы и локальные MP3/WAV/OGG/FLAC играет "
                "встроенный плеер. Клик по блоку — играть или пауза."
            )
        elif module == "countdown":
            self._settings_line(form, "target", "Дата события:", block,
                                "31.12.2026 23:00")
            self._settings_hint(
                form,
                "Форматы: 31.12.2026 23:00, 2026-12-31 23:00, "
                "23:00 (сегодня или завтра)."
            )
        elif module == "stopwatch":
            reset = QPushButton("Сбросить секундомер")
            reset.clicked.connect(
                lambda _c=False, b=block: self._reset_runtime_module(b)
            )
            form.addRow(reset)
            self._settings_hint(
                form,
                "Клик по блоку на основе — старт или пауза. "
                "Время не сохраняется между запусками Gridly."
            )
        elif module == "timer":
            self._settings_line(form, "duration", "Длительность:", block,
                                "300 или 5 мин")
            reset = QPushButton("Сбросить таймер")
            reset.clicked.connect(
                lambda _c=False, b=block: self._reset_runtime_module(b)
            )
            form.addRow(reset)
            self._settings_hint(
                form,
                "Клик по блоку — старт или пауза. Форматы: 300, 5 мин, "
                "1 ч 30 мин, 01:30."
            )
        elif module == "network":
            self._settings_check(form, "show_total",
                                 "Показывать принято/отправлено", block)
            self._settings_hint(
                form,
                "Скорость считается по изменению сетевых счётчиков "
                "между обновлениями данных."
            )
        elif module == "uptime":
            self._settings_hint(
                form, "Показывает время с момента загрузки системы."
            )
        elif module == "processes":
            self._settings_hint(
                form, "Количество запущенных процессов в системе."
            )
        elif module == "quote":
            self._settings_line(form, "author", "Автор:", block,
                                "Пусто — автор из сборника")
            self._settings_hint(
                form,
                "Своя цитата задаётся в поле «Содержимое». Если оно пустое, "
                "показывается цитата дня."
            )
        elif module == "worldclock":
            self._settings_text(form, "cities", "Города:", block,
                                "Москва +3\nЛондон 0\nНью-Йорк -5", 66)
            self._settings_hint(
                form,
                "По одному городу на строку: «Москва +3» или просто "
                "«Лондон» — тогда используется часовой пояс с летним "
                "временем."
            )
        elif module == "user":
            self._settings_line(form, "caption", "Заголовок:", block,
                                "МОЙ МОДУЛЬ")
            self._settings_line(form, "value", "Значение:", block,
                                "42 или {cpu}")
            self._settings_line(form, "subtitle", "Вторая строка:", block,
                                "Например, {city}")
            self._settings_line(form, "details", "Подробности:", block,
                                "{date} · {time}")
            self._settings_combo(form, "icon", "Иконка:", block,
                                 USER_ICON_OPTIONS)
            self._settings_check(form, "show_progress",
                                 "Показывать прогресс", block)
            self._settings_spin(form, "progress", "Прогресс:", 0, 100,
                                block, suffix=" %")
            hint = "Подстановки: " + ", ".join(
                f"{token} — {description}"
                for token, description in USER_PLACEHOLDERS
            )
            self._settings_hint(form, hint)

    def _settings_line(self, form: QFormLayout, key: str, label: str,
                       block: WidgetBlock, placeholder: str = "") -> QLineEdit:
        edit = QLineEdit(str(block.settings.get(key, "")))
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(
            lambda k=key, e=edit: self._set_block_setting(k, e.text())
        )
        form.addRow(label, edit)
        return edit

    def _settings_text(self, form: QFormLayout, key: str, label: str,
                       block: WidgetBlock, placeholder: str = "",
                       height: int = 62) -> QPlainTextEdit:
        edit = QPlainTextEdit(str(block.settings.get(key, "")))
        edit.setPlaceholderText(placeholder)
        edit.setFixedHeight(height)
        edit.textChanged.connect(
            lambda k=key, e=edit: self._set_block_setting(k, e.toPlainText())
        )
        form.addRow(label, edit)
        return edit

    def _settings_check(self, form: QFormLayout, key: str, label: str,
                        block: WidgetBlock) -> QCheckBox:
        check = QCheckBox(label)
        check.setChecked(str(block.settings.get(key, "0")).casefold() in (
            "1", "true", "да", "on", "yes"
        ))
        check.toggled.connect(
            lambda value, k=key: self._set_block_setting(
                k, "1" if value else "0"
            )
        )
        form.addRow(check)
        return check

    def _settings_spin(self, form: QFormLayout, key: str, label: str,
                       minimum: int, maximum: int, block: WidgetBlock,
                       suffix: str = "") -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        if suffix:
            spin.setSuffix(suffix)
        try:
            value = int(float(str(block.settings.get(key, "0"))
                              .replace(",", ".")))
        except ValueError:
            value = 0
        spin.setValue(max(minimum, min(maximum, value)))
        spin.valueChanged.connect(
            lambda value, k=key: self._set_block_setting(k, str(value))
        )
        form.addRow(label, spin)
        return spin

    def _settings_combo(self, form: QFormLayout, key: str, label: str,
                        block: WidgetBlock, options: dict) -> QComboBox:
        combo = QComboBox()
        for value, text in options.items():
            combo.addItem(text, value)
        index = combo.findData(str(block.settings.get(key, "")))
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _index, k=key, c=combo:
            self._set_block_setting(k, str(c.currentData()))
        )
        form.addRow(label, combo)
        return combo

    def _settings_hint(self, form: QFormLayout, text: str) -> QLabel:
        hint = QLabel(text)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11px;")
        form.addRow(hint)
        return hint

    def _reset_runtime_module(self, block: WidgetBlock) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        widget.reset_module(block.id)
        self.canvas.update()
        self._set_canvas_status("Модуль сброшен")

    def _reset_plan_marks(self, block: WidgetBlock) -> None:
        block.settings["done"] = ""
        widget = self._current_widget()
        if widget is not None:
            widget.update()
        self.canvas.update()
        self._schedule_save()
        self._set_canvas_status("Отметки планов сброшены")

    def _choose_music_file(self, block: WidgetBlock,
                           edit: QLineEdit) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Выбрать музыку", "",
            "Аудио (*.mp3 *.wav *.ogg *.oga *.flac *.m4a *.aac *.opus "
            "*.wma *.aiff);;Все файлы (*.*)"
        )
        if not path:
            return
        edit.setText(path)
        block.settings["url"] = path
        block.settings["source"] = "auto"
        widget = self._current_widget()
        if widget is not None:
            widget.apply_state()
            widget.update()
        self.canvas.update()
        self._rebuild_block_settings(block)
        self._schedule_save()
        self._set_canvas_status("Файл выбран")

    def _play_music_block(self, block: WidgetBlock) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        widget.toggle_music(block.id)
        self.canvas.update()

    def _stop_music_block(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        widget.stop_music()
        self.canvas.update()
        self._set_canvas_status("Музыка остановлена")

    def _set_block_setting(self, key: str, value) -> None:
        if self._loading:
            return
        block = self._current_block()
        widget = self._current_widget()
        if block is None or widget is None:
            return
        block.settings[str(key)] = str(value)
        self.canvas.update()
        widget.update()
        self._schedule_save()
        if block.module == "timer" and key == "duration":
            widget.reset_module(block.id)
        elif block.module == "user":
            widget.apply_state()

    def _build_block_geometry(self, form: QVBoxLayout) -> None:
        box = self._group(form, "Положение и размер")
        pos = QHBoxLayout()
        self.block_x_spin = QSpinBox()
        self.block_x_spin.setRange(0, 4000)
        self.block_x_spin.setPrefix("X ")
        self.block_x_spin.valueChanged.connect(
            lambda v: self._set_block_value("x", v, "block")
        )
        self.block_y_spin = QSpinBox()
        self.block_y_spin.setRange(0, 4000)
        self.block_y_spin.setPrefix("Y ")
        self.block_y_spin.valueChanged.connect(
            lambda v: self._set_block_value("y", v, "block")
        )
        pos.addWidget(self.block_x_spin, 1)
        pos.addWidget(self.block_y_spin, 1)
        box.addRow("Позиция:", pos)
        self._custom_block_controls.extend([
            (self.block_x_spin, "block", "x"),
            (self.block_y_spin, "block", "y"),
        ])

        size = QHBoxLayout()
        self.block_w_spin = QSpinBox()
        self.block_w_spin.setRange(36, 4000)
        self.block_w_spin.setSuffix(" px")
        self.block_w_spin.valueChanged.connect(
            lambda v: self._set_block_value("width", v, "block")
        )
        self.block_h_spin = QSpinBox()
        self.block_h_spin.setRange(28, 4000)
        self.block_h_spin.setSuffix(" px")
        self.block_h_spin.valueChanged.connect(
            lambda v: self._set_block_value("height", v, "block")
        )
        size.addWidget(self.block_w_spin, 1)
        size.addWidget(QLabel("×"))
        size.addWidget(self.block_h_spin, 1)
        box.addRow("Размер:", size)
        self._custom_block_controls.extend([
            (self.block_w_spin, "block", "width"),
            (self.block_h_spin, "block", "height"),
        ])

        padding = self._group(form, "Внутренние отступы")
        self._add_block_slider(padding, "Паддинг блока:", "padding",
                               0, 80, 10, source="style", suffix=" px")
        hint = QLabel(
            "Вложенные блоки позиционируются внутри паддинга родителя. "
            "Выберите родителя в списке над предпросмотром."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11px;")
        padding.addRow(hint)
        form.addStretch(1)

    def _build_block_style(self, form: QVBoxLayout) -> None:
        box = self._group(form, "Фон и рамка")
        self._add_block_color(box, "Основной цвет:", "bg", "#ffffff")
        self._add_block_color(box, "Второй цвет:", "bg2", "#dfe7f5")
        self._add_block_slider(box, "Непрозрачность фона:", "bg_alpha",
                               0, 255, 24)
        self._add_block_check(box, "Градиент", "gradient", False)
        self._add_block_slider(box, "Скругление:", "radius",
                               0, 100, 12, suffix=" px")
        self._add_block_spin(box, "Толщина рамки:", "border_width",
                             0, 20, 1, suffix=" px")
        self._add_block_color(box, "Цвет рамки:", "border_color", "#ffffff")
        self._add_block_slider(box, "Прозрачность рамки:", "border_alpha",
                               0, 255, 46)

        text = self._group(form, "Текст")
        self._add_block_color(text, "Цвет текста:", "text_color", "#ffffff")
        self._add_block_color(text, "Акцент:", "accent", "#8ab4ff")
        self._add_block_slider(text, "Масштаб текста:", "font_scale",
                               50, 220, 100, suffix=" %")
        self._add_block_combo(text, "Выравнивание:", "align", {
            "left": "Слева",
            "center": "По центру",
            "right": "Справа",
        }, "left")
        self._add_block_check(text, "Показывать подпись", "show_label", True)
        self._add_block_check(text, "Показывать иконку", "show_icon", True)
        form.addStretch(1)

    def _build_block_effects(self, form: QVBoxLayout) -> None:
        shadow = self._group(form, "Внешняя тень")
        self._add_block_check(shadow, "Включить тень", "shadow_enabled", False)
        self._add_block_color(shadow, "Цвет тени:", "shadow_color", "#000000")
        self._add_block_slider(shadow, "Сила тени:", "shadow_alpha",
                               0, 255, 90)
        self._add_block_slider(shadow, "Размытие:", "shadow_blur",
                               0, 60, 12, suffix=" px")
        self._add_block_spin(shadow, "Сдвиг по X:", "shadow_offset_x",
                             -40, 40, 0, suffix=" px")
        self._add_block_spin(shadow, "Сдвиг по Y:", "shadow_offset_y",
                             -40, 40, 4, suffix=" px")

        glow = self._group(form, "Свечение")
        self._add_block_check(glow, "Включить свечение", "glow_enabled", False)
        self._add_block_color(glow, "Цвет свечения:", "glow_color", "#8ab4ff")
        self._add_block_slider(glow, "Сила свечения:", "glow_alpha",
                               0, 255, 80)
        self._add_block_slider(glow, "Радиус:", "glow_radius",
                               0, 60, 10, suffix=" px")
        form.addStretch(1)

    def _add_widget_control(self, form: QFormLayout, label: str, attr: str,
                            source: str, control: QWidget) -> QWidget:
        form.addRow(label, control)
        self._custom_widget_controls.append((control, source, attr))
        return control

    def _build_custom_widget_tab(self, form: QVBoxLayout) -> None:
        main = self._group(form, "Виджет")
        title_edit = QLineEdit()
        title_edit.setPlaceholderText("Название виджета")
        main.addRow("Название:", title_edit)
        self.custom_title_edit = title_edit
        title_edit.editingFinished.connect(self._apply_custom_title)

        size = QHBoxLayout()
        self.custom_w_spin = QSpinBox()
        self.custom_w_spin.setRange(180, 1200)
        self.custom_w_spin.setSuffix(" px")
        self.custom_w_spin.valueChanged.connect(
            lambda v: self._set_custom_widget_value("width", v, "state")
        )
        self.custom_h_spin = QSpinBox()
        self.custom_h_spin.setRange(110, 900)
        self.custom_h_spin.setSuffix(" px")
        self.custom_h_spin.valueChanged.connect(
            lambda v: self._set_custom_widget_value("height", v, "state")
        )
        size.addWidget(self.custom_w_spin, 1)
        size.addWidget(QLabel("×"))
        size.addWidget(self.custom_h_spin, 1)
        main.addRow("Размер:", size)
        self._custom_widget_controls.extend([
            (self.custom_w_spin, "state", "width"),
            (self.custom_h_spin, "state", "height"),
        ])

        style = self._group(form, "Оформление основы")
        bg = ColorButton("#10161f")
        bg.color_edited.connect(
            lambda c: self._set_custom_widget_value("bg", c.name(), "style")
        )
        self._add_widget_control(style, "Фон:", "bg", "style", bg)
        accent = ColorButton("#8ab4ff")
        accent.color_edited.connect(
            lambda c: self._set_custom_widget_value("accent", c.name(),
                                                     "style")
        )
        self._add_widget_control(style, "Акцент:", "accent", "style", accent)
        text = ColorButton("#ffffff")
        text.color_edited.connect(
            lambda c: self._set_custom_widget_value("text", c.name(), "style")
        )
        self._add_widget_control(style, "Текст:", "text", "style", text)

        alpha = SliderField(0, 255, 210)
        alpha.value_changed.connect(
            lambda v: self._set_custom_widget_value("bg_alpha", v, "style")
        )
        self._add_widget_control(style, "Прозрачность фона:", "bg_alpha",
                                 "style", alpha)
        radius = SliderField(0, 80, 26, " px")
        radius.value_changed.connect(
            lambda v: self._set_custom_widget_value("corner_radius", v,
                                                     "style")
        )
        self._add_widget_control(style, "Скругление:", "corner_radius",
                                 "style", radius)
        opacity = SliderField(30, 255, 255)
        opacity.value_changed.connect(
            lambda v: self._set_custom_widget_value("opacity", v, "style")
        )
        self._add_widget_control(style, "Прозрачность окна:", "opacity",
                                 "style", opacity)
        font = SliderField(60, 180, 100, " %")
        font.value_changed.connect(
            lambda v: self._set_custom_widget_value("font_scale", v, "style")
        )
        self._add_widget_control(style, "Масштаб текста:", "font_scale",
                                 "style", font)
        block_pad = SliderField(0, 80, 12, " px")
        block_pad.value_changed.connect(
            lambda v: self._set_custom_widget_value("block_padding", v,
                                                     "style")
        )
        self._add_widget_control(style, "Отступ блоков:", "block_padding",
                                 "style", block_pad)

        data = self._group(form, "Данные")
        city_edit = QLineEdit()
        city_edit.setPlaceholderText("Город для погоды")
        city_edit.editingFinished.connect(self._apply_custom_city)
        data.addRow("Город:", city_edit)
        self.custom_city_edit = city_edit
        units = QComboBox()
        units.addItem("°C", "c")
        units.addItem("°F", "f")
        units.currentIndexChanged.connect(self._apply_custom_units)
        data.addRow("Температура:", units)
        self.custom_units_combo = units
        clock_24h = QCheckBox("24-часовой формат")
        clock_24h.toggled.connect(self._apply_custom_clock)
        data.addRow(clock_24h)
        self.custom_clock24_check = clock_24h
        seconds = QCheckBox("Показывать секунды")
        seconds.toggled.connect(self._apply_custom_clock)
        data.addRow(seconds)
        self.custom_seconds_check = seconds
        interval = QSpinBox()
        interval.setRange(1, 180)
        interval.setSuffix(" сек")
        interval.valueChanged.connect(self._apply_custom_interval)
        data.addRow("Обновление данных:", interval)
        self.custom_interval_spin = interval
        form.addStretch(1)

    # ----------------------------------------------------- object helpers
    def _current_fence_state(self):
        if self._current_kind != "fence" or not self._current_id:
            return None
        widget = self.fence_manager.widgets.get(self._current_id)
        return widget.state if widget else None

    def _current_style(self):
        state = self._current_fence_state()
        if state is None:
            from core.storage import FenceStyle
            return FenceStyle()
        return state.style

    def _current_fence(self):
        if self._current_kind != "fence" or not self._current_id:
            return None
        return self.fence_manager.widgets.get(self._current_id)

    def _current_widget(self):
        if self.widget_manager is None or self._current_kind != "widget" \
                or not self._current_id:
            return None
        return self.widget_manager.widgets.get(self._current_id)

    def _current_block(self) -> WidgetBlock | None:
        widget = self._current_widget()
        if widget is None:
            return None
        for block in widget.state.blocks:
            if block.id == self.canvas.selected_id():
                return block
        return None

    # --------------------------------------------------------- object list
    def refresh_objects(self) -> None:
        if self._current_kind and not self._object_exists():
            self._current_kind = None
            self._current_id = None
            self.stack.setCurrentIndex(0)
        self._refreshing_objects = True
        try:
            self.object_list.clear()
            for widget in self.fence_manager.widgets.values():
                item = QListWidgetItem(
                    make_kind_icon("custom", 11, QColor("#8ab4ff")),
                    f"Fence · {widget.state.title}",
                )
                item.setData(Qt.ItemDataRole.UserRole,
                             ("fence", widget.state.id))
                item.setToolTip("Fence: глубокие настройки контейнера")
                self.object_list.addItem(item)
            if self.widget_manager is not None:
                for widget in self.widget_manager.widgets.values():
                    if widget.state.kind != "custom":
                        continue
                    item = QListWidgetItem(
                        make_kind_icon("custom", 11, QColor("#5cc8ff")),
                        f"Виджет · {widget.state.title}",
                    )
                    item.setData(Qt.ItemDataRole.UserRole,
                                 ("widget", widget.state.id))
                    item.setToolTip(
                        "Составной виджет: блоки и вложенные модули"
                    )
                    self.object_list.addItem(item)

            if self._current_kind and self._current_id:
                for i in range(self.object_list.count()):
                    item = self.object_list.item(i)
                    data = item.data(Qt.ItemDataRole.UserRole)
                    if data == (self._current_kind, self._current_id):
                        self.object_list.setCurrentItem(item)
                        break
        finally:
            self._refreshing_objects = False

    def _object_exists(self) -> bool:
        if self._current_kind == "fence":
            return self._current_id in self.fence_manager.widgets
        if self._current_kind == "widget" and self.widget_manager is not None:
            return self._current_id in self.widget_manager.widgets
        return False

    def _on_objects_changed(self) -> None:
        self.refresh_objects()
        if self._current_kind == "fence" and self._object_exists():
            self._sync_fence_controls()
        elif self._current_kind == "widget" and self._object_exists():
            self._sync_custom_controls()

    def _on_object_selected(self, current, previous) -> None:
        if self._refreshing_objects or current is None:
            return
        data = current.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, object_id = data
        if kind == "fence":
            self.open_fence(object_id)
        else:
            self.open_widget(object_id)

    # --------------------------------------------------------------- open
    def open_fence(self, fence_id: str) -> None:
        widget = self.fence_manager.widgets.get(fence_id)
        if widget is None:
            return
        self._current_kind = "fence"
        self._current_id = fence_id
        self.stack.setCurrentIndex(1)
        self.left_hint.setText(
            "Fence: геометрия, фон, рамки, тени, свечение,\n"
            "акриловое размытие и типографика заголовка.\n"
            "Изменения применяются сразу и сохраняются автоматически."
        )
        if fence_id not in self._geometry_connected:
            widget.geometry_changed.connect(self._on_fence_geometry)
            self._geometry_connected.add(fence_id)
        self._sync_fence_controls()
        self._select_object_in_list("fence", fence_id)

    def open_widget(self, widget_id: str) -> None:
        if self.widget_manager is None:
            return
        widget = self.widget_manager.widgets.get(widget_id)
        if widget is None or widget.state.kind != "custom":
            return
        self._current_kind = "widget"
        self._current_id = widget_id
        self.stack.setCurrentIndex(2)
        self.left_hint.setText(
            "Составной виджет: перетащите модуль на основу.\n"
            "Бросок на блок вкладывает модуль внутрь.\n"
            "Выберите блок, чтобы настроить его отдельно."
        )
        self.canvas.set_state(widget.state)
        self.canvas.set_selected("")
        self._sync_custom_controls()
        self._select_object_in_list("widget", widget_id)

    def _select_object_in_list(self, kind: str, object_id: str) -> None:
        self._refreshing_objects = True
        try:
            for i in range(self.object_list.count()):
                item = self.object_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == (kind, object_id):
                    self.object_list.setCurrentItem(item)
                    break
        finally:
            self._refreshing_objects = False

    # ----------------------------------------------------- fence syncing
    def _sync_fence_controls(self) -> None:
        widget = self._current_fence()
        if widget is None:
            return
        state = widget.state
        style = state.style
        self._loading = True
        try:
            for control, source, attr in self._fence_controls:
                value = getattr(style if source == "style" else state, attr)
                self._set_control_value(control, value)
            self.fence_title_edit.setText(state.title)
            index = self.fence_layout_combo.findData(state.layout)
            if index >= 0:
                self.fence_layout_combo.setCurrentIndex(index)
            self.fence_lock_check.setChecked(bool(state.locked))
            self.fence_top_check.setChecked(bool(state.always_on_top))
            folder = state.layout == "folder"
            self._fence_width.setEnabled(not folder)
            self._fence_height.setEnabled(not folder)
        finally:
            self._loading = False

    def _on_fence_geometry(self, fence_id: str) -> None:
        if self._current_kind == "fence" and fence_id == self._current_id:
            self._loading = True
            try:
                state = self._current_fence_state()
                if state is not None:
                    self._fence_x.setValue(state.x)
                    self._fence_y.setValue(state.y)
                    self._fence_width.setValue(state.width)
                    self._fence_height.setValue(state.height)
            finally:
                self._loading = False

    def _set_fence_value(self, attr: str, value, source: str = "style") -> None:
        if self._loading:
            return
        widget = self._current_fence()
        if widget is None:
            return
        target = widget.state.style if source == "style" else widget.state
        setattr(target, attr, value)
        if source == "style" and attr in ("bg_color", "bg_alpha"):
            widget.state.style.sync_legacy()
        widget.apply_style()
        self._schedule_save()

    def _set_fence_state_value(self, attr: str, value) -> None:
        if self._loading:
            return
        widget = self._current_fence()
        if widget is None:
            return
        state = widget.state
        setattr(state, attr, int(value))
        widget.move(state.x, state.y)
        if state.layout != "folder":
            widget.resize(state.width, state.height)
        self._schedule_save()

    def _apply_fence_title(self) -> None:
        if self._loading:
            return
        widget = self._current_fence()
        if widget is None:
            return
        title = self.fence_title_edit.text().strip()
        if not title:
            self.fence_title_edit.setText(widget.state.title)
            return
        if title == widget.state.title:
            return
        widget.set_title(title)
        self._schedule_save()

    def _apply_fence_layout(self) -> None:
        if self._loading:
            return
        widget = self._current_fence()
        if widget is None:
            return
        layout = self.fence_layout_combo.currentData()
        if layout:
            widget.set_layout(layout)
            folder = layout == "folder"
            self._fence_width.setEnabled(not folder)
            self._fence_height.setEnabled(not folder)
            self._schedule_save()

    def _apply_fence_lock(self) -> None:
        if self._loading:
            return
        widget = self._current_fence()
        if widget is None:
            return
        widget.set_locked(self.fence_lock_check.isChecked())
        self._schedule_save()

    def _apply_fence_top(self) -> None:
        if self._loading:
            return
        widget = self._current_fence()
        if widget is None:
            return
        widget.set_always_on_top(self.fence_top_check.isChecked())
        self._schedule_save()

    def _rename_fence(self) -> None:
        widget = self._current_fence()
        if widget is not None:
            widget.rename()

    def _duplicate_fence(self) -> None:
        widget = self._current_fence()
        if widget is None:
            return
        duplicate = self.fence_manager.duplicate_fence(widget.state.id)
        if duplicate is not None:
            self.refresh_objects()
            self.open_fence(duplicate.state.id)

    def _reset_fence_style(self) -> None:
        widget = self._current_fence()
        if widget is None:
            return
        from core.storage import FenceStyle
        widget.state.style = FenceStyle()
        widget.apply_style()
        self._sync_fence_controls()
        self._schedule_save()

    # ----------------------------------------------------- custom syncing
    def _sync_custom_controls(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        state = widget.state
        self._loading = True
        try:
            self.custom_title_edit.setText(state.title)
            self.custom_subtitle.setText(
                f"{len(state.blocks)} блок(ов) · "
                f"{state.width}×{state.height}"
            )
            self.custom_w_spin.setValue(state.width)
            self.custom_h_spin.setValue(state.height)
            for control, source, attr in self._custom_widget_controls:
                target = state.style if source == "style" else state
                self._set_control_value(control, getattr(target, attr))
            self.custom_city_edit.setText(state.city)
            units_index = self.custom_units_combo.findData(state.units)
            if units_index >= 0:
                self.custom_units_combo.setCurrentIndex(units_index)
            self.custom_clock24_check.setChecked(state.clock_24h)
            self.custom_seconds_check.setChecked(state.show_seconds)
            self.custom_interval_spin.setValue(state.interval)
            self.canvas.set_state(state)
            self._sync_block_controls()
        finally:
            self._loading = False

    def _sync_block_controls(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        block = self._current_block()
        self._loading = True
        try:
            self._refresh_parent_combo(block)
            if block is None:
                for index in range(self._widget_tab_index):
                    self.block_tabs.setTabEnabled(index, False)
                self.block_tabs.setCurrentIndex(self._widget_tab_index)
                self._rebuild_block_settings(None)
                self.canvas_status.setText(
                    "Выберите блок на основе или перетащите модуль"
                )
                return
            for index in range(self._widget_tab_index):
                self.block_tabs.setTabEnabled(index, True)
            if self.block_tabs.currentIndex() == self._widget_tab_index:
                self.block_tabs.setCurrentIndex(0)
            for control, source, attr in self._custom_block_controls:
                target = block.style if source == "style" else block
                self._set_control_value(control, getattr(target, attr))
            self._update_block_fields(block)
            self._rebuild_block_settings(block)
            self.canvas_status.setText(
                f"Выбран: {MODULES.get(block.module, block.module)}"
            )
        finally:
            self._loading = False

    def _set_form_row_visible(self, field: QWidget, visible: bool) -> None:
        """Скрывает поле вместе с его подписью в QFormLayout."""
        label = self.block_main_form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)
        field.setEnabled(visible)

    def _update_block_fields(self, block: WidgetBlock) -> None:
        """Показывает только те поля, которые использует модуль."""
        module = block.module
        text_modules = ("text", "notes", "notepad", "todo", "plans", "quote")
        self._set_form_row_visible(
            self.block_value_spin, module in ("metric", "progress")
        )
        self._set_form_row_visible(
            self.block_text_edit, module in text_modules
        )
        self.block_value_spin.setToolTip(
            "Используется модулями «Индикатор» и «Прогресс-бар»"
        )
        self.block_text_edit.setToolTip(
            "Используется модулями «Текст», «Заметки», «Блокнот», "
            "«Список дел», «Планы на день» и «Цитата дня»"
        )
        placeholders = {
            "notepad": "Текст заметки. Клик по блоку — редактирование "
                       "прямо на основе.",
            "todo": "По одному пункту на строку. [x] — выполнено, "
                    "[ ] — не выполнено.",
            "plans": "По одному плану на строку. Двойной клик по строке "
                     "на основе отмечает выполнение.",
            "quote": "Своя цитата. Если пусто — показывается цитата дня.",
        }
        self.block_text_edit.setPlaceholderText(
            placeholders.get(
                module,
                "Текст или заметка. Используется модулями «Текст», "
                "«Заметки», «Блокнот», «Список дел» и «Цитата дня»."
            )
        )

    def _refresh_parent_combo(self, block: WidgetBlock | None) -> None:
        self.parent_combo.blockSignals(True)
        try:
            self.parent_combo.clear()
            self.parent_combo.addItem("— Основа виджета —", "")
            if block is not None:
                forbidden = {block.id} | block_descendants(
                    self._current_widget().state.blocks, block.id
                )
                for other in self._current_widget().state.blocks:
                    if other.id in forbidden:
                        continue
                    label = other.style.label or MODULES.get(
                        other.module, other.module
                    )
                    self.parent_combo.addItem(
                        f"{label}  ·  {other.id[:6]}", other.id
                    )
                index = self.parent_combo.findData(block.parent_id or "")
                self.parent_combo.setCurrentIndex(index if index >= 0 else 0)
            self.parent_combo.setEnabled(block is not None)
        finally:
            self.parent_combo.blockSignals(False)

    def _set_control_value(self, control: QWidget, value) -> None:
        if isinstance(control, ColorButton):
            control.set_color(str(value))
        elif isinstance(control, SliderField):
            control.set_value(int(value))
        elif isinstance(control, QSpinBox):
            control.setValue(int(value))
        elif isinstance(control, QCheckBox):
            control.setChecked(bool(value))
        elif isinstance(control, QComboBox):
            index = control.findData(value)
            if index < 0:
                index = control.findText(str(value))
            if index >= 0:
                control.setCurrentIndex(index)
            elif control.isEditable():
                control.setCurrentText(str(value))
        elif isinstance(control, QPlainTextEdit):
            control.setPlainText(str(value))
        elif isinstance(control, QLineEdit):
            control.setText(str(value))

    def _set_custom_widget_value(self, attr: str, value, source: str) -> None:
        if self._loading:
            return
        widget = self._current_widget()
        if widget is None:
            return
        target = widget.state.style if source == "style" else widget.state
        setattr(target, attr, value)
        self.canvas.set_state(widget.state)
        self.canvas.update()
        widget.apply_state()
        self._schedule_save()
        self.custom_subtitle.setText(
            f"{len(widget.state.blocks)} блок(ов) · "
            f"{widget.state.width}×{widget.state.height}"
        )

    def _set_block_value(self, attr: str, value, source: str) -> None:
        if self._loading:
            return
        block = self._current_block()
        widget = self._current_widget()
        if block is None or widget is None:
            return
        target = block.style if source == "style" else block
        setattr(target, attr, value)
        if attr == "text" and block.module == "plans":
            items = parse_plans(block.text)
            block.settings["done"] = format_plan_done(
                parse_plan_done(block.settings.get("done", ""), len(items))
            )
        self.canvas.update()
        widget.update()
        self._schedule_save()
        if attr in ("width", "height", "module", "label"):
            self._sync_block_controls()

    def _apply_block_module(self) -> None:
        if self._loading:
            return
        block = self._current_block()
        if block is None:
            return
        module = self.block_module_combo.currentData()
        if not module or module == block.module:
            return
        block.module = module
        block.style.accent = MODULE_ACCENTS.get(module, block.style.accent)
        block.settings = default_module_settings(module)
        if module in ("text", "notes", "notepad", "todo", "plans", "quote"):
            if not str(block.text).strip():
                block.text = MODULE_DEFAULT_TEXT.get(module, "")
        else:
            block.text = ""
        self.canvas.set_state(self._current_widget().state)
        self.canvas.update()
        self._current_widget().update()
        self._sync_block_controls()
        self._schedule_save()

    def _apply_block_parent(self) -> None:
        if self._loading:
            return
        block = self._current_block()
        widget = self._current_widget()
        if block is None or widget is None:
            return
        parent = self.parent_combo.currentData() or None
        if parent == block.parent_id:
            return
        block.parent_id = parent
        area_w, area_h = self.canvas._parent_size(block)
        block.width = max(36, min(int(block.width), max(36, int(area_w))))
        block.height = max(28, min(int(block.height), max(28, int(area_h))))
        block.x = max(0, min(int(block.x), max(0, int(area_w - block.width))))
        block.y = max(0, min(int(block.y), max(0, int(area_h - block.height))))
        self.canvas.set_state(widget.state)
        self.canvas.update()
        widget.update()
        self._sync_block_controls()
        self._schedule_save()

    def _on_block_selected(self, block_id: str) -> None:
        self.canvas.set_selected(block_id)
        self._sync_block_controls()

    def _on_canvas_changed(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        widget.apply_state()
        self._sync_block_controls()
        self._schedule_save()
        self._set_canvas_status("Изменения применены")

    def _set_canvas_status(self, text: str) -> None:
        self.canvas_status.setText(text)
        QTimer.singleShot(2500, lambda: self.canvas_status.setText(""))

    def _apply_custom_title(self) -> None:
        if self._loading:
            return
        widget = self._current_widget()
        if widget is None:
            return
        title = self.custom_title_edit.text().strip()
        if not title:
            self.custom_title_edit.setText(widget.state.title)
            return
        if title == widget.state.title:
            return
        widget.rename(title)
        self._schedule_save()
        self.refresh_objects()

    def _apply_custom_city(self) -> None:
        if self._loading:
            return
        widget = self._current_widget()
        if widget is None:
            return
        city = self.custom_city_edit.text().strip()
        if not city or city == widget.state.city:
            return
        widget.state.city = city
        widget.state.resolved_city = ""
        if state_needs_weather(widget.state):
            widget.data.pop("weather", None)
            widget.request_weather()
        widget.apply_state()
        self._schedule_save()

    def _apply_custom_units(self) -> None:
        if self._loading:
            return
        widget = self._current_widget()
        if widget is None:
            return
        units = self.custom_units_combo.currentData()
        if units not in ("c", "f") or units == widget.state.units:
            return
        widget.state.units = units
        if state_needs_weather(widget.state):
            widget.request_weather()
        widget.apply_state()
        self._schedule_save()

    def _apply_custom_clock(self) -> None:
        if self._loading:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.clock_24h = self.custom_clock24_check.isChecked()
        widget.state.show_seconds = self.custom_seconds_check.isChecked()
        widget.apply_state()
        self._schedule_save()

    def _apply_custom_interval(self) -> None:
        if self._loading:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.interval = self.custom_interval_spin.value()
        widget.apply_state()
        self._schedule_save()

    # ---------------------------------------------------------- block ops
    def _add_module_from_palette(self) -> None:
        if self.module_palette is None:
            return
        item = self.module_palette.currentItem()
        if item is not None:
            self._add_module_to_root(item.data(Qt.ItemDataRole.UserRole))

    def _add_module_to_root(self, module: str | None) -> None:
        widget = self._current_widget()
        if widget is None or not module:
            return
        state = widget.state
        count = len([b for b in state.blocks if not b.parent_id])
        x = 12 + (count % 4) * 14
        y = 12 + (count % 6) * 14
        block = make_block(module, x, y)
        state.blocks.append(block)
        self.canvas.set_state(state)
        self.canvas.set_selected(block.id)
        self.canvas.update()
        widget.apply_state()
        self._sync_block_controls()
        self._schedule_save()
        self._set_canvas_status(f"Добавлен модуль «{MODULES.get(module)}»")

    def _duplicate_block(self) -> None:
        block = self._current_block()
        widget = self._current_widget()
        if block is None or widget is None:
            return
        clone = copy.deepcopy(block)
        clone.id = __import__("uuid").uuid4().hex
        clone.parent_id = block.parent_id
        clone.x += 14
        clone.y += 14
        widget.state.blocks.append(clone)
        self.canvas.set_state(widget.state)
        self.canvas.set_selected(clone.id)
        self.canvas.update()
        widget.apply_state()
        self._sync_block_controls()
        self._schedule_save()

    def _delete_block(self) -> None:
        block = self._current_block()
        widget = self._current_widget()
        if block is None or widget is None:
            return
        doomed = block_descendants(widget.state.blocks, block.id)
        doomed.add(block.id)
        widget.state.blocks = [b for b in widget.state.blocks
                               if b.id not in doomed]
        self.canvas.set_state(widget.state)
        self.canvas.set_selected("")
        self.canvas.update()
        widget.apply_state()
        self._sync_block_controls()
        self._schedule_save()

    def _move_block(self, direction: int) -> None:
        block = self._current_block()
        widget = self._current_widget()
        if block is None or widget is None:
            return
        blocks = widget.state.blocks
        index = blocks.index(block)
        new_index = max(0, min(len(blocks) - 1, index + direction))
        if new_index == index:
            return
        blocks[index], blocks[new_index] = blocks[new_index], blocks[index]
        self.canvas.set_state(widget.state)
        self.canvas.update()
        widget.update()
        self._schedule_save()

    # ---------------------------------------------------------- creation
    def _create_fence(self) -> None:
        widget = self.fence_manager.create_fence("grid")
        self.refresh_objects()
        if widget is not None:
            self.open_fence(widget.state.id)

    def _create_custom_widget(self) -> None:
        if self.widget_manager is None:
            return
        widget = self.widget_manager.create_widget("custom")
        self.refresh_objects()
        if widget is not None:
            self.open_widget(widget.state.id)

    # ------------------------------------------------------------- saving
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _flush_save(self) -> None:
        if hasattr(self.fence_manager, "save"):
            self.fence_manager.save()
        if self.widget_manager is not None:
            self.widget_manager.save()


def _nearest_weight(value: int) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 600
    weights = [100, 200, 300, 400, 500, 600, 700, 800, 900]
    return min(weights, key=lambda item: abs(item - value))
