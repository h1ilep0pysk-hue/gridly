"""
ui/tweaks_page.py
Вкладка «Твики»: macOS-подобное оформление Gridly.

Все параметры собраны в одном месте и применяются сразу. Пользователь
включает только то, что ему нужно: Dock, акриловое размытие, скругления,
светофор в заголовке, прозрачность и т. д.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                             QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QScrollArea, QSlider,
                             QVBoxLayout, QWidget)

from core import mac_overlay
from core.tweaks import (ACCENTS, APPEARANCES, DOCK_POSITIONS, OVERLAY_LEVELS,
                         MacTweaks, load_tweaks, save_tweaks)


class TweaksPage(QWidget):
    """Панель переключателей macOS-стиля."""

    changed = pyqtSignal(object)

    def __init__(self, theme: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._theme = theme
        self._loading = True
        self.tweaks = load_tweaks()
        self._checks: dict[str, QCheckBox] = {}
        self._combos: dict[str, QComboBox] = {}
        self._texts: dict[str, QLineEdit] = {}
        self._sliders: dict[str, tuple[QSlider, QLabel]] = {}
        self._build()
        self._sync()
        self._loading = False

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        t = self._theme
        accent = self.tweaks.accent
        self.setStyleSheet(
            f"""
            QScrollArea {{ border: none; background: transparent; }}
            QWidget#tweaksContent {{ background: transparent; }}
            QGroupBox {{
                border: 1px solid {t['input_border']};
                border-radius: 12px;
                margin-top: 14px;
                padding: 14px 10px 10px 10px;
                font-weight: 600;
                color: {t['input_text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 5px;
                color: {t['input_text']};
            }}
            QCheckBox {{ spacing: 9px; padding: 3px 0; color: {t['input_text']}; }}
            QCheckBox::indicator {{
                width: 17px; height: 17px; border-radius: 5px;
                border: 1px solid {t['input_border']};
                background: {t['input_bg']};
            }}
            QCheckBox::indicator:checked {{
                background: {accent};
                border-color: {accent};
            }}
            QLabel#muted {{ color: {t['btn_disabled_text']}; font-size: 11px; }}
            QLabel#tweaksTitle {{ font-size: 20px; font-weight: 700; }}
            QLabel#tweaksSubtitle {{ color: {t['btn_disabled_text']}; }}
            QComboBox {{
                border: 1px solid {t['input_border']};
                border-radius: 8px;
                padding: 5px 9px;
                background: {t['input_bg']};
                color: {t['input_text']};
                min-width: 150px;
            }}
            QSlider::groove:horizontal {{
                height: 4px; border-radius: 2px;
                background: {t['input_border']};
            }}
            QSlider::sub-page:horizontal {{
                height: 4px; border-radius: 2px; background: {accent};
            }}
            QSlider::handle:horizontal {{
                width: 16px; margin: -6px 0; border-radius: 8px;
                background: {accent}; border: 2px solid {t['input_bg']};
            }}
            QPushButton#resetTweaks {{
                border: 1px solid {t['input_border']};
                border-radius: 9px;
                padding: 7px 14px;
                background: {t['btn_bg']};
                color: {t['btn_text']};
            }}
            QPushButton#resetTweaks:hover {{ background: {t['btn_hover']}; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("tweaksContent")
        lay = QVBoxLayout(content)
        lay.setContentsMargins(22, 18, 22, 22)
        lay.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        title = QLabel("Твики macOS")
        title.setObjectName("tweaksTitle")
        lay.addWidget(title)
        subtitle = QLabel(
            "Включите macOS-стиль и настройте панели, Dock, прозрачность "
            "и скругления. Изменения применяются сразу."
        )
        subtitle.setObjectName("tweaksSubtitle")
        subtitle.setWordWrap(True)
        lay.addWidget(subtitle)

        general, gl = self._group(
            lay, "Общий стиль",
            "Внешний вид панели Gridly: тема рамки, акцент, светофор "
            "и анимации."
        )
        self._check(gl, "enabled", "Включить macOS-стиль",
                    "Главный переключатель. Пока он выключен, Gridly "
                    "выглядит как раньше.")
        self._combo(gl, "appearance", "Тема панели:", APPEARANCES)
        self._combo(gl, "accent", "Акцентный цвет:", ACCENTS)
        self._check(gl, "traffic_lights",
                    "Светофор в заголовке (закрыть / свернуть / развернуть)")
        self._check(gl, "floating_panel",
                    "Плавающая панель со скруглёнными краями")
        self._check(gl, "shadows", "Мягкие тени окон")
        self._check(gl, "animations", "Анимации Dock и наведения")
        self._check(gl, "soft_icons", "Мягкие пастельные иконки")

        glass, glass_l = self._group(
            lay, "Прозрачность и размытие",
            "Эффект стекла для панели, Dock, фенсов и виджетов."
        )
        self._check(glass_l, "glass", "Стеклянные панели (Blur / Acrylic)")
        self._slider(glass_l, "translucency", "Прозрачность панелей:",
                     0, 100, "%")
        self._slider(glass_l, "blur_strength", "Сила размытия:", 0, 100, "%")
        self._check(glass_l, "rounded", "Скруглять углы окон")
        self._slider(glass_l, "corner_radius", "Радиус углов:", 0, 40, " px")

        dock, dock_l = self._group(
            lay, "Dock-панель",
            "Нижняя панель в стиле macOS. Запускает разделы Gridly и "
            "показывает, что сейчас открыто. Dock можно перетащить к "
            "любому краю экрана."
        )
        self._check(dock_l, "dock_enabled", "Показывать Dock")
        self._combo(dock_l, "dock_position", "Положение Dock:",
                    DOCK_POSITIONS)
        self._slider(dock_l, "dock_size", "Размер иконок:", 34, 82, " px")
        self._check(dock_l, "dock_magnify",
                    "Увеличивать иконку при наведении")
        self._check(dock_l, "dock_autohide", "Автоматически скрывать Dock")
        self._check(dock_l, "dock_labels", "Показывать подписи под иконками")
        self._check(dock_l, "dock_dots",
                    "Точки запущенных разделов под иконками")
        self._check(dock_l, "dock_glass", "Стеклянный фон Dock")

        mydock, mydock_l = self._group(
            lay, "MyDock (копия MyDockFinder)",
            "Док с иконками приложений из панели задач Windows. Пока он "
            "включён, обычный Dock Gridly скрыт."
        )
        self._check(mydock_l, "mydock_enabled",
                    "Показывать MyDock вместо Dock Gridly")
        self._hint(
            mydock_l,
            "Размер, масштаб, автоскрытие, стекло и точки наследуются из "
            "«Dock-панель».",
        )

        shell, shell_l = self._group(
            lay, "Системная оболочка Windows",
            "Заменяет панель задач Windows на macOS-оболочку: верхнее меню, "
            "Dock, Launchpad и переключатель окон. Панель задач вернётся "
            "при выключении режима или выходе из Gridly."
        )
        self._check(shell_l, "shell_enabled",
                    "Заменить панель задач Windows (macOS-оболочка)")
        self._check(shell_l, "menu_bar", "Верхнее меню macOS")
        self._check(shell_l, "hide_from_taskbar",
                    "Убирать окна Gridly с панели задач")
        self._check(shell_l, "launchpad_enabled",
                    "Показывать Launchpad в Dock")
        self._check(shell_l, "switcher_enabled",
                    "Показывать переключатель окон в Dock")
        self._check(shell_l, "hotkeys", "Глобальные горячие клавиши")
        self._hint(
            shell_l,
            "Ctrl+Alt+L — Launchpad, Ctrl+Alt+W — переключатель окон, "
            "Ctrl+Alt+G — открыть Gridly (трей скрыт вместе с панелью задач), "
            "Ctrl+Alt+Esc — вернуть панель задач. Панель задач также "
            "возвращается при выходе из Gridly."
        )

        overlay, overlay_l = self._group(
            lay, "macOS overlay",
            "Глобальная системная панель для macOS: висит поверх всех окон "
            "и системного Dock на всех Spaces, не крадёт фокус, показывает "
            "запущенные приложения и часы. Сами настройки применяются на "
            "стороне macOS — скриптом macos_global_overlay.py."
        )
        self._check(overlay_l, "overlay_enabled",
                    "Панель включена (она же работает и без Gridly, "
                    "если запустить скрипт вручную)")
        self._combo(overlay_l, "overlay_level",
                    "Уровень окна поверх системы:", OVERLAY_LEVELS)
        self._slider(overlay_l, "overlay_max_apps",
                     "Иконок приложений до кнопки «…»:", 4, 30, "")
        self._check(overlay_l, "overlay_clock", "Часы в панели")
        self._check(overlay_l, "titlebar_wrap_enabled",
                    "Заменять заголовки окон плашкой Gridly (macOS)")
        self._text(overlay_l, "titlebar_wrap_bundles",
                   "Приложения (bundle id через запятую):")
        self._hint(
            overlay_l,
            "Значения автоматически пишутся в macos_overlay.json рядом со "
            "скриптом: macOS-оверлей подхватывает их при каждом запуске."
        )
        export_row = QHBoxLayout()
        export_row.addStretch(1)
        export_btn = QPushButton("Экспортировать overlay…")
        export_btn.setObjectName("resetTweaks")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.clicked.connect(self._export_overlay)
        export_row.addWidget(export_btn)
        overlay_l.addLayout(export_row)

        desk, desk_l = self._group(
            lay, "Рабочий стол",
            "Дополнительные эффекты для фенсов и desktop-виджетов."
        )
        self._check(desk_l, "fence_blur", "Размытие фона у фенсов")
        self._check(desk_l, "widget_blur", "Размытие фона у виджетов")

        footer = QHBoxLayout()
        note = QLabel(
            "Совет: для максимально «маковского» вида включите стеклянные "
            "панели, скругления и Dock снизу."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        reset = QPushButton("Сбросить настройки")
        reset.setObjectName("resetTweaks")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.clicked.connect(self._reset)
        footer.addWidget(reset)
        lay.addLayout(footer)
        lay.addStretch(1)
        self._base_stylesheet = self.styleSheet()

    def _group(self, parent: QVBoxLayout, title: str,
               description: str) -> tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(title)
        inner = QVBoxLayout(box)
        inner.setContentsMargins(6, 8, 6, 6)
        inner.setSpacing(4)
        hint = QLabel(description)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        inner.addWidget(hint)
        parent.addWidget(box)
        return box, inner

    def _hint(self, layout: QVBoxLayout, text: str) -> None:
        label = QLabel(text)
        label.setObjectName("muted")
        label.setWordWrap(True)
        layout.addWidget(label)

    def _check(self, layout: QVBoxLayout, attr: str, text: str,
               hint: str = "") -> QCheckBox:
        box = QCheckBox(text)
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.toggled.connect(
            lambda value, key=attr: self._set_bool(key, value)
        )
        layout.addWidget(box)
        if hint:
            self._hint(layout, hint)
        self._checks[attr] = box
        return box

    def _combo(self, layout: QVBoxLayout, attr: str, label: str,
               options: dict) -> QComboBox:
        row = QHBoxLayout()
        text = QLabel(label)
        combo = QComboBox()
        for value, title in options.items():
            combo.addItem(title, value)
        combo.currentIndexChanged.connect(
            lambda _index, key=attr, c=combo:
            self._set_str(key, str(c.currentData()))
        )
        row.addWidget(text)
        row.addStretch(1)
        row.addWidget(combo)
        layout.addLayout(row)
        self._combos[attr] = combo
        return combo

    def _text(self, layout: QVBoxLayout, attr: str, label: str) -> QLineEdit:
        row = QHBoxLayout()
        text = QLabel(label)
        edit = QLineEdit()
        edit.editingFinished.connect(
            lambda key=attr, e=edit: self._set_str(key, e.text().strip()))
        row.addWidget(text)
        row.addWidget(edit, 1)
        layout.addLayout(row)
        self._texts[attr] = edit
        return edit

    def _slider(self, layout: QVBoxLayout, attr: str, label: str,
                minimum: int, maximum: int, suffix: str = "") -> QSlider:
        row = QHBoxLayout()
        text = QLabel(label)
        value = QLabel("0")
        value.setMinimumWidth(46)
        value.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.valueChanged.connect(
            lambda number, key=attr, suffix_text=suffix:
            self._set_int(key, number, suffix_text)
        )
        row.addWidget(text)
        row.addWidget(slider, 1)
        row.addWidget(value)
        layout.addLayout(row)
        self._sliders[attr] = (slider, value, suffix)
        return slider

    # ------------------------------------------------------------- changes
    def _export_overlay(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Куда экспортировать macOS overlay",
            str(mac_overlay.PROJECT_ROOT),
        )
        if not directory:
            return
        files = mac_overlay.export_overlay(self.tweaks, directory)
        names = "\n".join(path.name for path in files) or "—"
        QMessageBox.information(
            self,
            "Экспорт macOS overlay",
            "Готово. Перенесите эту папку на Mac и запустите:\n"
            "    python3 -m pip install -r requirements-macos.txt\n"
            "    python3 macos_global_overlay.py\n\n"
            f"Файлы:\n{names}",
        )

    def _set_bool(self, attr: str, value: bool) -> None:
        if self._loading:
            return
        setattr(self.tweaks, attr, bool(value))
        self._changed()

    def _set_str(self, attr: str, value: str) -> None:
        if self._loading:
            return
        setattr(self.tweaks, attr, str(value))
        self._changed()

    def _set_int(self, attr: str, value: int, suffix: str = "") -> None:
        if self._loading:
            return
        setattr(self.tweaks, attr, int(value))
        if attr in self._sliders:
            self._sliders[attr][1].setText(f"{value}{suffix}")
        self._changed()

    def _apply_accent_styles(self) -> None:
        accent = self.tweaks.accent
        self.setStyleSheet(self._base_stylesheet + f"""
            QCheckBox::indicator:checked {{
                background: {accent};
                border-color: {accent};
            }}
            QSlider::sub-page:horizontal {{ background: {accent}; }}
            QSlider::handle:horizontal {{
                background: {accent};
                border: 2px solid {self._theme['input_bg']};
            }}
        """)

    def _changed(self) -> None:
        self.tweaks.normalize()
        save_tweaks(self.tweaks)
        mac_overlay.sync_config(self.tweaks)
        self._apply_accent_styles()
        self.changed.emit(MacTweaks.from_dict(self.tweaks.to_dict()))

    def _reset(self) -> None:
        self.tweaks = MacTweaks()
        save_tweaks(self.tweaks)
        mac_overlay.sync_config(self.tweaks)
        self._sync()
        self._apply_accent_styles()
        self.changed.emit(MacTweaks.from_dict(self.tweaks.to_dict()))

    def set_value(self, attr: str, value) -> None:
        """Меняет настройку из другого окна (меню, Dock, Control Center)."""
        if attr in self._checks:
            self._checks[attr].setChecked(bool(value))
        elif attr in self._sliders:
            self._sliders[attr][0].setValue(int(value))
        elif attr in self._combos:
            combo = self._combos[attr]
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        elif attr in self._texts:
            self._texts[attr].setText(str(value))

    # --------------------------------------------------------------- sync
    def _sync(self) -> None:
        was_loading = self._loading
        self._loading = True
        try:
            for attr, box in self._checks.items():
                box.setChecked(bool(getattr(self.tweaks, attr)))
            for attr, combo in self._combos.items():
                index = combo.findData(getattr(self.tweaks, attr))
                combo.setCurrentIndex(index if index >= 0 else 0)
            for attr, edit in self._texts.items():
                edit.setText(str(getattr(self.tweaks, attr)))
            for attr, (slider, label, suffix) in self._sliders.items():
                value = int(getattr(self.tweaks, attr))
                slider.setValue(value)
                label.setText(f"{value}{suffix}")
        finally:
            self._loading = was_loading
