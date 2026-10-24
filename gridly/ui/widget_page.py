"""
ui/widget_page.py
Конструктор desktop-виджетов Gridly.

Слева — галерея готовых шаблонов и список созданных виджетов, справа —
живой предпросмотр и настройки. Любое изменение сразу применяется к окну
виджета и сохраняется, код писать не нужно.
"""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QFrame,
                             QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QPushButton, QScrollArea, QSlider, QSpinBox,
                             QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from core.widget_storage import (DEFAULT_SIZES, DEFAULT_TEMPLATES,
                                 KIND_ACCENTS, KIND_ORDER, TEMPLATES,
                                 WIDGET_KINDS, WidgetState, apply_template)
from ui.color_wheel import ColorWheel
from ui.widget_icons import make_kind_icon, make_preset_icon
from ui.widget_render import sample_data
from ui.widget_window import WidgetPreviewWidget

PRESET_SHORT_LABELS = {
    "memory": "Память",
}


class WidgetPage(QWidget):
    custom_requested = pyqtSignal(str)
    blocks_requested = pyqtSignal(str)

    def __init__(self, manager, theme: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.manager = manager
        self._theme = theme
        self._current_id: str | None = None
        self._loading_editor = False
        self._syncing_color = False
        self._connected_ids: set[str] = set()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._flush_save)

        self._build_ui()
        self.manager.changed.connect(self._on_manager_changed)
        self.manager.edit_requested.connect(self.open_widget)
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        t = self._theme
        self.setStyleSheet(
            f"""
            QLineEdit, QComboBox, QSpinBox {{
                background: {t['input_bg']};
                color: {t['input_text']};
                border: 1px solid {t['input_border']};
                border-radius: 7px;
                padding: 5px 8px;
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{
                border: 1px solid {t['input_focus']};
            }}
            QComboBox QAbstractItemView {{
                background: {t['input_bg']};
                color: {t['input_text']};
                selection-background-color: {t['list_selected']};
                border: 1px solid {t['input_border']};
            }}
            QListWidget#widgetList {{
                border: 1px solid {t['list_border']};
                border-radius: 8px;
                background: {t['list_bg']};
                color: {t['list_text']};
                padding: 4px;
            }}
            QListWidget#widgetList::item {{
                padding: 7px 8px;
                border-radius: 5px;
            }}
            QListWidget#widgetList::item:selected {{
                background: {t['list_selected']};
                color: {t['list_text']};
            }}
            QListWidget#widgetList::item:hover {{
                background: {t['list_hover']};
            }}
            QPushButton#presetCard {{
                text-align: left;
                padding: 4px 10px;
                min-height: 42px;
                font-weight: 500;
            }}
            QPushButton#presetCard:hover {{
                background: {t['btn_hover']};
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
            QFrame#previewFrame {{
                border: 1px solid {t['list_border']};
                border-radius: 12px;
                background: transparent;
            }}
            QLabel#mutedLabel {{
                color: #8a94a3;
            }}
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
        splitter.setSizes([330, 560])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(10)

        title = QLabel("Готовые виджеты")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        lay.addWidget(title)

        gallery = QGroupBox("Добавить на рабочий стол")
        grid = QGridLayout(gallery)
        grid.setContentsMargins(10, 14, 10, 10)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        for index, kind in enumerate(KIND_ORDER):
            btn = QPushButton(
                f"  {PRESET_SHORT_LABELS.get(kind, WIDGET_KINDS[kind])}"
            )
            btn.setObjectName("presetCard")
            btn.setIcon(make_preset_icon(kind, 19))
            btn.setIconSize(QSize(26, 26))
            btn.setToolTip(f"Создать виджет «{WIDGET_KINDS[kind]}»")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, k=kind: self._add_widget(k)
            )
            if kind == "disk":
                grid.addWidget(btn, index // 2, 0, 1, 2)
            else:
                grid.addWidget(btn, index // 2, index % 2)

        create_btn = QPushButton("  Создать / Конструктор")
        create_btn.setObjectName("presetCard")
        create_btn.setIcon(make_preset_icon("custom", 19))
        create_btn.setIconSize(QSize(26, 26))
        create_btn.setToolTip(
            "Создать пустую основу и собрать составной виджет из модулей"
        )
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setStyleSheet(
            "text-align: left; font-weight: 600; min-height: 46px;"
        )
        create_btn.clicked.connect(
            lambda _c=False: self._add_custom_widget()
        )
        grid.addWidget(create_btn, (len(KIND_ORDER) + 1) // 2, 0, 1, 2)
        lay.addWidget(gallery)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Поиск по виджетам…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.refresh)
        lay.addWidget(self.search_edit)

        self.list_label = QLabel("Мои виджеты:")
        lay.addWidget(self.list_label)

        self.list = QListWidget()
        self.list.setObjectName("widgetList")
        self.list.setMinimumHeight(150)
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)
        lay.addWidget(self.list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        dup_btn = QPushButton("Дублировать")
        dup_btn.setMinimumHeight(32)
        dup_btn.clicked.connect(lambda _c=False: self._duplicate_selected())
        actions.addWidget(dup_btn, 1)

        del_btn = QPushButton("Удалить")
        del_btn.setMinimumHeight(32)
        del_btn.clicked.connect(lambda _c=False: self._delete_selected())
        actions.addWidget(del_btn, 1)
        lay.addLayout(actions)

        vis_btn = QPushButton("Скрыть / показать все")
        vis_btn.setMinimumHeight(32)
        vis_btn.clicked.connect(
            lambda _c=False: self.manager.toggle_all_visibility()
        )
        lay.addWidget(vis_btn)

        hint = QLabel("Двойной клик по виджету — настройка.\n"
                      "Изменения применяются сразу.")
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11px;")
        lay.addWidget(hint)
        return w

    def _build_right(self) -> QWidget:
        self.stack = QStackedWidget()

        placeholder = QWidget()
        p_lay = QVBoxLayout(placeholder)
        p_lay.addStretch(1)
        icon = QLabel()
        icon.setPixmap(make_preset_icon("weather", 38).pixmap(76, 76))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_lay.addWidget(icon)
        title = QLabel("Соберите виджет без кода")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        p_lay.addWidget(title)
        desc = QLabel(
            "Выберите шаблон слева — погоду, часы, загрузку ПК\n"
            "или другой виджет. Затем настройте цвета, размер\n"
            "и данные в конструкторе. Всё сохраняется автоматически."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setObjectName("mutedLabel")
        desc.setWordWrap(True)
        p_lay.addWidget(desc)
        p_lay.addStretch(1)
        self.stack.addWidget(placeholder)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setWidget(self._build_editor())
        self.editor_scroll = scroll
        self.stack.addWidget(scroll)
        return self.stack

    def _build_editor(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 0, 4, 8)
        lay.setSpacing(10)

        self.editor_title = QLabel("Конструктор виджета")
        self.editor_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        lay.addWidget(self.editor_title)

        self.editor_subtitle = QLabel(
            "Изменения применяются вживую и сохраняются автоматически."
        )
        self.editor_subtitle.setObjectName("mutedLabel")
        self.editor_subtitle.setStyleSheet("font-size: 11px;")
        lay.addWidget(self.editor_subtitle)

        # ------------------------------------------------------- предпросмотр
        preview_frame = QFrame()
        preview_frame.setObjectName("previewFrame")
        pv_lay = QVBoxLayout(preview_frame)
        pv_lay.setContentsMargins(8, 8, 8, 8)
        pv_lay.setSpacing(4)
        pv_title = QLabel("Живой предпросмотр")
        pv_title.setObjectName("mutedLabel")
        pv_title.setStyleSheet("font-size: 11px; padding-left: 4px;")
        pv_lay.addWidget(pv_title)
        self.preview = WidgetPreviewWidget()
        pv_lay.addWidget(self.preview)
        lay.addWidget(preview_frame)

        # ------------------------------------------------------------ основное
        main_group = QGroupBox("Виджет")
        main_form = QFormLayout(main_group)
        main_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        main_form.setSpacing(8)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Название виджета")
        self.title_edit.editingFinished.connect(self._apply_title)
        main_form.addRow("Название:", self.title_edit)

        self.kind_combo = QComboBox()
        for kind in KIND_ORDER:
            self.kind_combo.addItem(WIDGET_KINDS[kind], kind)
        self.kind_combo.addItem(WIDGET_KINDS["custom"], "custom")
        self.kind_combo.currentIndexChanged.connect(self._apply_kind)
        main_form.addRow("Тип:", self.kind_combo)
        lay.addWidget(main_group)

        # --------------------------------------------------- составной виджет
        self.custom_group = QGroupBox("Составной виджет")
        custom_lay = QVBoxLayout(self.custom_group)
        custom_lay.setSpacing(7)
        custom_hint = QLabel(
            "Виджет собирается из мини-модулей на вкладке «Кастомизация»: "
            "перетаскивайте блоки на основу, вкладывайте их друг в друга "
            "и настраивайте каждый отдельно."
        )
        custom_hint.setObjectName("mutedLabel")
        custom_hint.setWordWrap(True)
        custom_lay.addWidget(custom_hint)
        open_blocks_btn = QPushButton("Открыть конструктор блоков →")
        open_blocks_btn.setMinimumHeight(32)
        open_blocks_btn.clicked.connect(
            lambda _c=False: self._open_blocks()
        )
        custom_lay.addWidget(open_blocks_btn)
        lay.addWidget(self.custom_group)

        # --------------------------------------------------------------- погода
        self.weather_group = QGroupBox("Погода")
        weather_form = QFormLayout(self.weather_group)
        weather_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        weather_form.setSpacing(8)

        city_row = QWidget()
        city_lay = QHBoxLayout(city_row)
        city_lay.setContentsMargins(0, 0, 0, 0)
        city_lay.setSpacing(6)
        self.city_edit = QLineEdit()
        self.city_edit.setPlaceholderText("Например, Москва")
        self.city_edit.returnPressed.connect(self._apply_city)
        city_lay.addWidget(self.city_edit, 1)
        find_btn = QPushButton("Найти")
        find_btn.setMinimumHeight(30)
        find_btn.clicked.connect(lambda _c=False: self._apply_city())
        city_lay.addWidget(find_btn)
        weather_form.addRow("Город:", city_row)

        self.units_combo = QComboBox()
        self.units_combo.addItem("°C", "c")
        self.units_combo.addItem("°F", "f")
        self.units_combo.currentIndexChanged.connect(self._apply_weather_units)
        weather_form.addRow("Температура:", self.units_combo)

        self.weather_status = QLabel("Введите город и нажмите «Найти».")
        self.weather_status.setObjectName("mutedLabel")
        self.weather_status.setWordWrap(True)
        weather_form.addRow(self.weather_status)
        lay.addWidget(self.weather_group)

        # ---------------------------------------------------------------- часы
        self.clock_group = QGroupBox("Часы")
        clock_form = QFormLayout(self.clock_group)
        clock_form.setSpacing(8)
        self.clock_24h_check = QCheckBox("24-часовой формат")
        self.clock_24h_check.toggled.connect(self._apply_clock_options)
        clock_form.addRow(self.clock_24h_check)
        self.seconds_check = QCheckBox("Показывать секунды")
        self.seconds_check.toggled.connect(self._apply_clock_options)
        clock_form.addRow(self.seconds_check)
        lay.addWidget(self.clock_group)

        # ------------------------------------------------------------ данные
        self.system_group = QGroupBox("Данные")
        system_form = QFormLayout(self.system_group)
        system_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        system_form.setSpacing(8)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 180)
        self.interval_spin.valueChanged.connect(self._apply_interval)
        system_form.addRow("Обновление:", self.interval_spin)

        self.interval_hint = QLabel("")
        self.interval_hint.setObjectName("mutedLabel")
        self.interval_hint.setWordWrap(True)
        system_form.addRow(self.interval_hint)

        refresh_btn = QPushButton("Обновить сейчас")
        refresh_btn.setMinimumHeight(30)
        refresh_btn.clicked.connect(lambda _c=False: self._refresh_now())
        system_form.addRow(refresh_btn)
        lay.addWidget(self.system_group)

        # ------------------------------------------------------- оформление
        style_group = QGroupBox("Оформление")
        style_lay = QVBoxLayout(style_group)
        style_lay.setSpacing(8)

        template_form = QFormLayout()
        template_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.template_combo = QComboBox()
        for key, preset in TEMPLATES.items():
            self.template_combo.addItem(preset["label"], key)
        self.template_combo.currentIndexChanged.connect(self._apply_template)
        template_form.addRow("Шаблон:", self.template_combo)
        style_lay.addLayout(template_form)

        self.color_target_combo = QComboBox()
        self.color_target_combo.addItem("Фон", "bg")
        self.color_target_combo.addItem("Акцент", "accent")
        self.color_target_combo.addItem("Текст", "text")
        self.color_target_combo.currentIndexChanged.connect(
            self._sync_color_widgets
        )
        style_lay.addWidget(self.color_target_combo)

        color_row = QHBoxLayout()
        color_row.setSpacing(12)
        self.color_wheel = ColorWheel()
        self.color_wheel.setFixedSize(156, 156)
        self.color_wheel.color_changed.connect(self._apply_color)
        color_row.addWidget(self.color_wheel, 0,
                            Qt.AlignmentFlag.AlignHCenter)

        color_side = QVBoxLayout()
        color_side.setSpacing(6)
        color_side.addWidget(QLabel("Выбранный цвет:"))
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(84, 34)
        color_side.addWidget(self.color_swatch)
        self.color_hex = QLabel("#FFFFFF")
        self.color_hex.setObjectName("mutedLabel")
        color_side.addWidget(self.color_hex)
        color_side.addStretch(1)
        color_row.addLayout(color_side, 1)
        style_lay.addLayout(color_row)

        self.alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.valueChanged.connect(self._apply_alpha)
        self.alpha_value = QLabel("210")
        style_lay.addLayout(self._slider_row("Прозрачность фона",
                                             self.alpha_slider,
                                             self.alpha_value))

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(40, 255)
        self.opacity_slider.valueChanged.connect(self._apply_opacity)
        self.opacity_value = QLabel("255")
        style_lay.addLayout(self._slider_row("Прозрачность окна",
                                             self.opacity_slider,
                                             self.opacity_value))

        self.radius_slider = QSlider(Qt.Orientation.Horizontal)
        self.radius_slider.setRange(0, 48)
        self.radius_slider.valueChanged.connect(self._apply_radius)
        self.radius_value = QLabel("26")
        style_lay.addLayout(self._slider_row("Скругление углов",
                                             self.radius_slider,
                                             self.radius_value))

        self.font_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_slider.setRange(70, 140)
        self.font_slider.valueChanged.connect(self._apply_font_scale)
        self.font_value = QLabel("100%")
        style_lay.addLayout(self._slider_row("Масштаб текста",
                                             self.font_slider,
                                             self.font_value))

        checks = QHBoxLayout()
        checks.setSpacing(16)
        self.show_icon_check = QCheckBox("Показывать иконку")
        self.show_icon_check.toggled.connect(self._apply_visibility_options)
        checks.addWidget(self.show_icon_check)
        self.show_label_check = QCheckBox("Показывать подписи")
        self.show_label_check.toggled.connect(self._apply_visibility_options)
        checks.addWidget(self.show_label_check)
        checks.addStretch(1)
        style_lay.addLayout(checks)

        reset_style_btn = QPushButton("Сбросить оформление")
        reset_style_btn.setMinimumHeight(30)
        reset_style_btn.clicked.connect(lambda _c=False: self._reset_style())
        style_lay.addWidget(reset_style_btn)
        lay.addWidget(style_group)

        # ------------------------------------------------------ размер и место
        geo_group = QGroupBox("Размер и позиция")
        geo_form = QFormLayout(geo_group)
        geo_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        geo_form.setSpacing(8)

        size_row = QHBoxLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(180, 900)
        self.width_spin.setSuffix(" px")
        self.width_spin.valueChanged.connect(self._apply_geometry)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(110, 700)
        self.height_spin.setSuffix(" px")
        self.height_spin.valueChanged.connect(self._apply_geometry)
        size_row.addWidget(self.width_spin, 1)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.height_spin, 1)
        geo_form.addRow("Размер:", size_row)

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
        geo_form.addRow("Позиция:", pos_row)

        self.lock_check = QCheckBox("Закрепить (запретить перетаскивание)")
        self.lock_check.toggled.connect(self._apply_lock)
        geo_form.addRow(self.lock_check)
        self.top_check = QCheckBox("Поверх всех окон")
        self.top_check.toggled.connect(self._apply_top)
        geo_form.addRow(self.top_check)
        lay.addWidget(geo_group)

        # -------------------------------------------------------------- кнопки
        btn_row = QHBoxLayout()
        delete_btn = QPushButton("Удалить виджет")
        delete_btn.setMinimumHeight(32)
        delete_btn.clicked.connect(lambda _c=False: self._delete_current())
        btn_row.addWidget(delete_btn)
        btn_row.addStretch(1)
        close_btn = QPushButton("Свернуть конструктор")
        close_btn.setMinimumHeight(32)
        close_btn.clicked.connect(lambda _c=False: self._close_editor())
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)
        lay.addStretch(1)
        return w

    @staticmethod
    def _slider_row(title: str, slider: QSlider,
                    value_label: QLabel) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch(1)
        top.addWidget(value_label)
        box.addLayout(top)
        box.addWidget(slider)
        return box

    # ---------------------------------------------------------------- list
    @staticmethod
    def _item_text(state: WidgetState) -> str:
        kind_label = WIDGET_KINDS.get(state.kind, state.kind)
        if state.title.strip() == kind_label:
            return kind_label
        return f"{state.title}  —  {kind_label}"

    def refresh(self) -> None:
        query = self.search_edit.text().strip().lower() if \
            hasattr(self, "search_edit") else ""
        self.list.clear()
        shown = 0
        for fid, widget in self.manager.widgets.items():
            state = widget.state
            haystack = f"{state.title} {WIDGET_KINDS.get(state.kind, '')}".lower()
            if query and query not in haystack:
                continue
            item = QListWidgetItem(
                make_kind_icon(state.kind, 11, QColor(state.style.accent)),
                self._item_text(state),
            )
            item.setData(Qt.ItemDataRole.UserRole, fid)
            item.setToolTip("Двойной клик — открыть конструктор")
            self.list.addItem(item)
            shown += 1

        total = len(self.manager.widgets)
        if query:
            self.list_label.setText(f"Мои виджеты ({shown} из {total}):")
        else:
            self.list_label.setText(f"Мои виджеты ({total}):")

        if self._current_id and self._current_id in self.manager.widgets:
            self._select_item(self._current_id)

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
                item.setIcon(make_kind_icon(
                    widget.state.kind, 11, QColor(widget.state.style.accent)
                ))
                return

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self.open_widget(item.data(Qt.ItemDataRole.UserRole))

    def _on_manager_changed(self) -> None:
        current = self._current_id
        self.refresh()
        if not current:
            return
        widget = self.manager.widgets.get(current)
        if widget is None:
            self._close_editor()
            return
        if self.stack.currentIndex() == 1:
            self._load_editor(widget)

    # -------------------------------------------------------------- actions
    def _add_widget(self, kind: str) -> None:
        widget = self.manager.create_widget(kind)
        self.open_widget(widget.state.id)

    def _add_custom_widget(self) -> None:
        widget = self.manager.create_widget("custom")
        self.custom_requested.emit(widget.state.id)

    def _open_blocks(self) -> None:
        widget = self._current_widget()
        if widget is not None and widget.state.kind == "custom":
            self.blocks_requested.emit(widget.state.id)

    def open_widget(self, fid: str) -> None:
        widget = self.manager.widgets.get(fid)
        if widget is None:
            return
        self._current_id = fid
        self._load_editor(widget)
        self.stack.setCurrentIndex(1)
        self.editor_scroll.verticalScrollBar().setValue(0)
        self._select_item(fid)

    def _delete_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.manager.remove_widget(item.data(Qt.ItemDataRole.UserRole))

    def _duplicate_selected(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        widget = self.manager.duplicate_widget(
            item.data(Qt.ItemDataRole.UserRole)
        )
        if widget is not None:
            self.open_widget(widget.state.id)

    def _delete_current(self) -> None:
        if self._current_id:
            self.manager.remove_widget(self._current_id)

    def _close_editor(self) -> None:
        self._current_id = None
        self.stack.setCurrentIndex(0)
        self.list.clearSelection()

    # --------------------------------------------------------------- editor
    def _current_widget(self):
        if not self._current_id:
            return None
        return self.manager.widgets.get(self._current_id)

    def _load_editor(self, widget) -> None:
        state = widget.state
        if state.id not in self._connected_ids:
            widget.data_updated.connect(self._on_data_updated)
            widget.status_changed.connect(self._on_status_changed)
            self._connected_ids.add(state.id)

        self._loading_editor = True
        try:
            self.editor_title.setText(f"Конструктор — {state.title}")
            self.title_edit.setText(state.title)
            index = self.kind_combo.findData(state.kind)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)

            self.city_edit.setText(state.city)
            units_index = self.units_combo.findData(state.units)
            if units_index >= 0:
                self.units_combo.setCurrentIndex(units_index)
            self._update_weather_status(widget)

            self.clock_24h_check.setChecked(state.clock_24h)
            self.seconds_check.setChecked(state.show_seconds)

            self.interval_spin.setValue(state.interval)
            self._update_interval_labels()

            template_index = self.template_combo.findData(state.style.template)
            if template_index >= 0:
                self.template_combo.setCurrentIndex(template_index)

            self.alpha_slider.setValue(state.style.bg_alpha)
            self.opacity_slider.setValue(state.style.opacity)
            self.radius_slider.setValue(state.style.corner_radius)
            self.font_slider.setValue(state.style.font_scale)
            self.alpha_value.setText(str(state.style.bg_alpha))
            self.opacity_value.setText(str(state.style.opacity))
            self.radius_value.setText(str(state.style.corner_radius))
            self.font_value.setText(f"{state.style.font_scale}%")
            self.show_icon_check.setChecked(state.style.show_icon)
            self.show_label_check.setChecked(state.style.show_label)

            self.width_spin.setValue(state.width)
            self.height_spin.setValue(state.height)
            self.x_spin.setValue(state.x)
            self.y_spin.setValue(state.y)
            self.lock_check.setChecked(state.locked)
            self.top_check.setChecked(state.always_on_top)

            self._sync_color_widgets()
            self._update_visible_groups()

            self.preview.set_state(state)
            if widget.data and (state.kind != "weather"
                                or widget.data.get("temp") is not None):
                self.preview.set_data(widget.data)
            else:
                self.preview.set_data(sample_data(state.kind, state))
        finally:
            self._loading_editor = False

    def _update_visible_groups(self) -> None:
        kind = self.kind_combo.currentData()
        weather = kind == "weather"
        clock = kind == "clock"
        custom = kind == "custom"
        self.weather_group.setVisible(weather)
        self.clock_group.setVisible(clock)
        self.custom_group.setVisible(custom)
        self.system_group.setVisible(
            kind in ("weather", "cpu", "memory", "battery", "disk")
        )
        self._update_interval_labels()

    def _update_interval_labels(self) -> None:
        kind = self.kind_combo.currentData()
        if kind == "weather":
            self.interval_spin.setSuffix(" мин")
            self.interval_hint.setText(
                "Как часто запрашивать свежую погоду. Минимум 1 минута."
            )
        else:
            self.interval_spin.setSuffix(" сек")
            self.interval_hint.setText(
                "Как часто обновлять показатели. Минимум 1 секунда."
            )

    def _update_weather_status(self, widget) -> None:
        data = widget.data or {}
        if data.get("error"):
            self.weather_status.setText(str(data["error"]))
        elif data.get("temp") is not None:
            city = widget.state.resolved_city or data.get("city", "")
            self.weather_status.setText(f"Найдено: {city}")
        else:
            self.weather_status.setText(
                "Введите город и нажмите «Найти»."
            )

    # ---------------------------------------------------------------- apply
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _flush_save(self) -> None:
        self.manager.save()

    def _refresh_preview(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        self.preview.set_state(widget.state)
        if widget.data and (widget.state.kind != "weather"
                            or widget.data.get("temp") is not None):
            self.preview.set_data(widget.data)
        else:
            self.preview.set_data(sample_data(widget.state.kind, widget.state))
        self.preview.update()

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
        widget.rename(title)
        self.editor_title.setText(f"Конструктор — {title}")
        self._update_list_item(widget)
        self._schedule_save()
        self._refresh_preview()

    def _apply_kind(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        kind = self.kind_combo.currentData()
        if not kind or kind == widget.state.kind:
            self._update_visible_groups()
            return

        state = widget.state
        old_kind = state.kind
        default_title = WIDGET_KINDS.get(old_kind)
        new_title = ("Составной виджет" if kind == "custom"
                     else WIDGET_KINDS[kind])
        if not state.title.strip() or state.title == default_title \
                or state.title == "Составной виджет":
            state.title = new_title
            self.title_edit.setText(state.title)

        old_size = DEFAULT_SIZES.get(old_kind)
        if old_size and (state.width, state.height) == old_size:
            state.width, state.height = DEFAULT_SIZES[kind]
            self.width_spin.setValue(state.width)
            self.height_spin.setValue(state.height)

        if state.style.accent == KIND_ACCENTS.get(old_kind):
            state.style.accent = KIND_ACCENTS.get(kind, state.style.accent)

        old_interval = state.interval
        state.kind = kind
        from core.widget_storage import DEFAULT_INTERVALS
        if old_interval == DEFAULT_INTERVALS.get(old_kind):
            state.interval = DEFAULT_INTERVALS.get(kind, old_interval)
        if kind == "weather" and not state.city.strip():
            state.city = "Москва"
            self.city_edit.setText(state.city)

        widget.data = {}
        widget.rename(state.title)
        widget.apply_state()
        if kind == "weather":
            widget.request_weather()
        else:
            widget.refresh_now()
        self._load_editor(widget)
        self._update_list_item(widget)
        self.manager.changed.emit()
        self._schedule_save()

    def _apply_city(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        city = self.city_edit.text().strip()
        if not city:
            self.weather_status.setText("Введите название города.")
            return
        if city == widget.state.city and widget.data.get("temp") is not None:
            return

        widget.state.city = city
        widget.state.resolved_city = ""
        widget.state.latitude = None
        widget.state.longitude = None
        widget.data = {}
        self.weather_status.setText("Поиск города…")
        widget.apply_state()
        widget.request_weather()
        self._refresh_preview()
        self._schedule_save()

    def _apply_weather_units(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None or widget.state.kind != "weather":
            return
        units = self.units_combo.currentData()
        if units == widget.state.units:
            return
        widget.state.units = units
        widget.data = {}
        widget.request_weather()
        self._refresh_preview()
        self._schedule_save()

    def _apply_clock_options(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None or widget.state.kind != "clock":
            return
        widget.state.clock_24h = self.clock_24h_check.isChecked()
        widget.state.show_seconds = self.seconds_check.isChecked()
        widget.apply_state()
        widget.refresh_now()
        self._refresh_preview()
        self._schedule_save()

    def _apply_interval(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.interval = self.interval_spin.value()
        widget.apply_state()
        self._refresh_preview()
        self._schedule_save()

    def _apply_template(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        template = self.template_combo.currentData()
        if not template:
            return
        apply_template(widget.state.style, template, keep_accent=True)
        widget.state.style.template = template
        widget.update()
        self._sync_style_controls()
        self._refresh_preview()
        self._schedule_save()

    def _sync_style_controls(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        style = widget.state.style
        self.alpha_slider.setValue(style.bg_alpha)
        self.opacity_slider.setValue(style.opacity)
        self.radius_slider.setValue(style.corner_radius)
        self.font_slider.setValue(style.font_scale)
        self.alpha_value.setText(str(style.bg_alpha))
        self.opacity_value.setText(str(style.opacity))
        self.radius_value.setText(str(style.corner_radius))
        self.font_value.setText(f"{style.font_scale}%")
        self._sync_color_widgets()

    def _color_key(self) -> str:
        return self.color_target_combo.currentData() or "bg"

    def _sync_color_widgets(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        color = QColor(getattr(widget.state.style, self._color_key()))
        if not color.isValid():
            color = QColor("#ffffff")
        self._syncing_color = True
        try:
            self.color_wheel.set_color(color)
            self.color_swatch.setStyleSheet(
                "border: 1px solid #666; border-radius: 7px;"
                f" background: {color.name()};"
            )
            self.color_hex.setText(color.name().upper())
        finally:
            self._syncing_color = False

    def _apply_color(self, color: QColor) -> None:
        if self._loading_editor or self._syncing_color:
            return
        widget = self._current_widget()
        if widget is None:
            return
        setattr(widget.state.style, self._color_key(), color.name())
        widget.update()
        self.color_swatch.setStyleSheet(
            "border: 1px solid #666; border-radius: 7px;"
            f" background: {color.name()};"
        )
        self.color_hex.setText(color.name().upper())
        self._update_list_item(widget)
        self._refresh_preview()
        self._schedule_save()

    def _apply_alpha(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.style.bg_alpha = value
        self.alpha_value.setText(str(value))
        widget.update()
        self._refresh_preview()
        self._schedule_save()

    def _apply_opacity(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.style.opacity = value
        self.opacity_value.setText(str(value))
        widget.setWindowOpacity(max(0.15, value / 255.0))
        self._refresh_preview()
        self._schedule_save()

    def _apply_radius(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.style.corner_radius = value
        self.radius_value.setText(str(value))
        widget.update()
        self._refresh_preview()
        self._schedule_save()

    def _apply_font_scale(self, value: int) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.style.font_scale = value
        self.font_value.setText(f"{value}%")
        widget.update()
        self._refresh_preview()
        self._schedule_save()

    def _apply_visibility_options(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.style.show_icon = self.show_icon_check.isChecked()
        widget.state.style.show_label = self.show_label_check.isChecked()
        widget.update()
        self._refresh_preview()
        self._schedule_save()

    def _apply_geometry(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        state = widget.state
        state.width = self.width_spin.value()
        state.height = self.height_spin.value()
        state.x = self.x_spin.value()
        state.y = self.y_spin.value()
        widget.apply_state()
        self._refresh_preview()
        self._schedule_save()

    def _apply_lock(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.locked = self.lock_check.isChecked()
        widget.apply_state()
        self._schedule_save()

    def _apply_top(self) -> None:
        if self._loading_editor:
            return
        widget = self._current_widget()
        if widget is None:
            return
        widget.state.always_on_top = self.top_check.isChecked()
        widget.apply_state()
        self._schedule_save()

    def _refresh_now(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        widget.refresh_now()
        if widget.state.kind == "weather":
            self.weather_status.setText("Обновление…")

    def _reset_style(self) -> None:
        widget = self._current_widget()
        if widget is None:
            return
        style = widget.state.style
        apply_template(style, DEFAULT_TEMPLATES.get(widget.state.kind, "glass"),
                       keep_accent=False)
        style.accent = KIND_ACCENTS.get(widget.state.kind, style.accent)
        style.bg_alpha = TEMPLATES[style.template]["bg_alpha"]
        style.corner_radius = TEMPLATES[style.template]["corner_radius"]
        style.opacity = 255
        style.font_scale = 100
        style.show_icon = True
        style.show_label = True
        widget.apply_state()
        self._sync_style_controls()
        self.show_icon_check.setChecked(True)
        self.show_label_check.setChecked(True)
        self._refresh_preview()
        self._schedule_save()

    # --------------------------------------------------------------- events
    def _on_data_updated(self, fid: str) -> None:
        if fid != self._current_id or self.stack.currentIndex() != 1:
            return
        widget = self.manager.widgets.get(fid)
        if widget is None:
            return
        self._update_weather_status(widget)
        self._refresh_preview()

    def _on_status_changed(self, fid: str, text: str) -> None:
        if fid == self._current_id and self.stack.currentIndex() == 1:
            self.weather_status.setText(text)
