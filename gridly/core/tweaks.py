"""
core/tweaks.py
Настройки macOS-подобного оформления Gridly.

Файл хранится рядом с остальными данными приложения. Значения читаются
терпимо к старым/повреждённым файлам: неизвестные поля игнорируются,
числа приводятся к безопасным диапазонам.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields

from core import storage

logger = logging.getLogger("gridly.tweaks")

APPEARANCES = {
    "auto": "Как в системе",
    "light": "Светлая",
    "dark": "Тёмная",
}

ACCENTS = {
    "#0a84ff": "Синий",
    "#bf5af2": "Фиолетовый",
    "#ff375f": "Розовый",
    "#30d158": "Зелёный",
    "#ff9f0a": "Оранжевый",
    "#8e8e93": "Графит",
}

DOCK_POSITIONS = {
    "bottom": "Снизу",
    "left": "Слева",
    "right": "Справа",
}

OVERLAY_LEVELS = {
    "main_menu": "Уровень главного меню",
    "floating": "Плавающий уровень",
}

# Версия формата tweaks.json. Файлы без поля schema_version записаны до
# того, как системная оболочка стала включаться по умолчанию (версия 1).
SCHEMA_VERSION = 3


@dataclass
class MacTweaks:
    """Все переключатели вкладки «Твики»."""

    schema_version: int = SCHEMA_VERSION
    enabled: bool = False
    appearance: str = "auto"
    accent: str = "#0a84ff"

    # Панели и окна
    glass: bool = True
    translucency: int = 70
    blur_strength: int = 55
    rounded: bool = True
    corner_radius: int = 18
    floating_panel: bool = True
    traffic_lights: bool = True
    shadows: bool = True
    animations: bool = True

    # Dock
    dock_enabled: bool = True
    dock_position: str = "bottom"
    dock_size: int = 54
    dock_magnify: bool = True
    dock_autohide: bool = False
    dock_labels: bool = False
    dock_dots: bool = True
    dock_glass: bool = True

    # MyDock — копия MyDockFinder; при включении заменяет Dock Gridly.
    # Размер, масштаб, автоскрытие, стекло и точки берутся из Dock-панели.
    mydock_enabled: bool = True

    # Системная оболочка Windows
    shell_enabled: bool = True
    menu_bar: bool = True
    hide_from_taskbar: bool = True
    launchpad_enabled: bool = True
    switcher_enabled: bool = True
    hotkeys: bool = True

    # macOS overlay (глобальная панель вместо Dock, работает только на macOS)
    overlay_enabled: bool = True
    overlay_level: str = "main_menu"
    overlay_max_apps: int = 14
    overlay_clock: bool = True
    # Заголовки окон macOS: собственная плашка вместо нативного заголовка.
    # bundles — bundle id через запятую; нужен доступ «Универсальный доступ».
    titlebar_wrap_enabled: bool = False
    titlebar_wrap_bundles: str = "com.apple.TextEdit, com.apple.Notes"

    # Рабочий стол
    fence_blur: bool = True
    widget_blur: bool = True
    soft_icons: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict | None) -> "MacTweaks":
        result = MacTweaks()
        if not isinstance(raw, dict):
            return result
        allowed = {f.name for f in fields(MacTweaks)}
        for key, value in raw.items():
            if key not in allowed:
                continue
            current = getattr(result, key)
            if isinstance(current, bool):
                setattr(result, key, bool(value))
            elif isinstance(current, int):
                try:
                    setattr(result, key, int(value))
                except (TypeError, ValueError):
                    continue
            else:
                setattr(result, key, str(value))
        result.normalize()
        return result

    def normalize(self) -> None:
        if self.appearance not in APPEARANCES:
            self.appearance = "auto"
        if self.accent not in ACCENTS:
            self.accent = "#0a84ff"
        if self.dock_position not in DOCK_POSITIONS:
            self.dock_position = "bottom"
        if self.overlay_level not in OVERLAY_LEVELS:
            self.overlay_level = "main_menu"
        self.translucency = max(0, min(100, int(self.translucency)))
        self.blur_strength = max(0, min(100, int(self.blur_strength)))
        self.corner_radius = max(0, min(40, int(self.corner_radius)))
        self.dock_size = max(34, min(82, int(self.dock_size)))
        self.overlay_max_apps = max(4, min(30, int(self.overlay_max_apps)))


def tweaks_path():
    return storage.DATA_DIR / "tweaks.json"


def _migrate(raw: dict) -> bool:
    """Приводит словарь старого формата к текущему. True — если менялся."""
    try:
        version = int(raw.get("schema_version", 1))
    except (TypeError, ValueError):
        version = 1
    if version >= SCHEMA_VERSION:
        return False
    if version < 2:
        # v1 → v2: оболочка Windows теперь включена по умолчанию. Старые файлы
        # могли содержать shell_enabled=false только по умолчанию, поэтому
        # переводим их в новое умолчание один раз.
        raw["shell_enabled"] = True
    if version < 3:
        # v2 → v3: MyDock (док с запущенными приложениями) по умолчанию.
        raw["mydock_enabled"] = True
    raw["schema_version"] = SCHEMA_VERSION
    logger.info("tweaks.json мигрирован с версии %s на %s",
                version, SCHEMA_VERSION)
    return True


def load_tweaks() -> MacTweaks:
    path = tweaks_path()
    if not path.exists():
        return MacTweaks()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Не удалось прочитать %s: %s", path, exc)
        return MacTweaks()
    if not isinstance(raw, dict):
        return MacTweaks()
    migrated = _migrate(raw)
    result = MacTweaks.from_dict(raw)
    if migrated:
        save_tweaks(result)
    return result


def save_tweaks(tweaks: MacTweaks) -> None:
    path = tweaks_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(tweaks.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        logger.error("Не удалось сохранить твики %s: %s", path, exc)
