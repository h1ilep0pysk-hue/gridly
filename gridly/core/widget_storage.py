"""
core/widget_storage.py
Модель desktop-виджетов Gridly и JSON-хранилище.

Виджет — самостоятельное окно поверх рабочего стола: погода, часы, дата,
загрузка процессора, память, батарея или диск. Пользователь собирает его
из готовых шаблонов и настраивает внешний вид без кода.

Отдельный тип — составной виджет («custom»). Это пустая прямоугольная
основа, на которую перетаскиваются мини-модули. Каждый блок имеет
собственные координаты, размер, оформление и может содержать вложенные
блоки через parent_id.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("gridly.widget_storage")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "widgets.json"

WIDGET_KINDS: dict[str, str] = {
    "weather": "Погода",
    "clock": "Часы",
    "date": "Дата",
    "cpu": "Загрузка ЦП",
    "memory": "Оперативная память",
    "battery": "Батарея",
    "disk": "Диск",
    "custom": "Составной",
}

KIND_ORDER = ["weather", "clock", "date", "cpu", "memory", "battery", "disk"]
ALL_KINDS = KIND_ORDER + ["custom"]

# Мини-модули для конструктора составных виджетов.
MODULES: dict[str, str] = {
    "container": "Контейнер",
    "weekday": "День недели",
    "date": "Дата",
    "clock": "Часы",
    "weather": "Погода",
    "temperature": "Температура",
    "cpu": "Загрузка ЦП",
    "memory": "Оперативная память",
    "battery": "Батарея",
    "disk": "Диск",
    "notes": "Заметки",
    "text": "Текст",
    "metric": "Индикатор",
    "progress": "Прогресс-бар",
    "notepad": "Блокнот",
    "calculator": "Калькулятор",
    "todo": "Список дел",
    "plans": "Планы на день",
    "countdown": "Обратный отсчёт",
    "stopwatch": "Секундомер",
    "timer": "Таймер",
    "network": "Сеть",
    "uptime": "Время работы",
    "processes": "Процессы",
    "quote": "Цитата дня",
    "worldclock": "Мировые часы",
    "music": "Музыка",
    "user": "Свой модуль",
}

MODULE_ORDER = [
    "container",
    "weekday", "date", "clock", "weather", "temperature",
    "cpu", "memory", "battery", "disk",
    "notes", "text", "metric", "progress",
    "notepad", "calculator", "todo", "plans", "countdown", "stopwatch",
    "timer", "network", "uptime", "processes", "quote", "worldclock",
    "music", "user",
]

MODULE_ACCENTS: dict[str, str] = {
    "container": "#8ab4ff",
    "weekday": "#ffcf6e",
    "date": "#ffcf6e",
    "clock": "#a78bfa",
    "weather": "#5cc8ff",
    "temperature": "#5cc8ff",
    "cpu": "#57e389",
    "memory": "#c792ea",
    "battery": "#7ee787",
    "disk": "#ffb86b",
    "notes": "#8ab4ff",
    "text": "#e6e8eb",
    "metric": "#ff9e64",
    "progress": "#7ee787",
    "notepad": "#ffcf6e",
    "calculator": "#57e389",
    "todo": "#7ee787",
    "plans": "#ff7a7a",
    "countdown": "#ff9e64",
    "stopwatch": "#a78bfa",
    "timer": "#c792ea",
    "network": "#5cc8ff",
    "uptime": "#57e389",
    "processes": "#ffb86b",
    "quote": "#ffcf6e",
    "worldclock": "#5cc8ff",
    "music": "#c792ea",
    "user": "#8ab4ff",
}

MODULE_DEFAULT_SIZE: dict[str, tuple[int, int]] = {
    "container": (300, 150),
    "weekday": (170, 76),
    "date": (170, 96),
    "clock": (190, 86),
    "weather": (210, 96),
    "temperature": (140, 90),
    "cpu": (170, 86),
    "memory": (170, 86),
    "battery": (170, 78),
    "disk": (180, 82),
    "notes": (200, 120),
    "text": (180, 60),
    "metric": (170, 82),
    "progress": (200, 64),
    "notepad": (210, 130),
    "calculator": (190, 100),
    "todo": (210, 150),
    "plans": (230, 190),
    "countdown": (200, 100),
    "stopwatch": (180, 96),
    "timer": (180, 96),
    "network": (180, 90),
    "uptime": (180, 90),
    "processes": (170, 86),
    "quote": (220, 130),
    "worldclock": (200, 120),
    "music": (230, 112),
    "user": (200, 100),
}

# Псевдонимы иконок для блоков.
MODULE_ICONS: dict[str, str] = {
    "container": "custom",
    "weekday": "date",
    "date": "date",
    "clock": "clock",
    "weather": "weather_sun",
    "temperature": "weather_sun",
    "cpu": "cpu",
    "memory": "memory",
    "battery": "battery",
    "disk": "disk",
    "notes": "text",
    "text": "text",
    "metric": "cpu",
    "progress": "disk",
    "notepad": "notepad",
    "calculator": "calculator",
    "todo": "todo",
    "plans": "plans",
    "countdown": "countdown",
    "stopwatch": "stopwatch",
    "timer": "timer",
    "network": "network",
    "uptime": "uptime",
    "processes": "processes",
    "quote": "quote",
    "worldclock": "worldclock",
    "music": "music",
    "user": "user",
}

# Стартовые значения настроек для мини-модулей. Хранятся строками,
# чтобы формат JSON оставался простым и стабильным.
MODULE_DEFAULT_SETTINGS: dict[str, dict[str, str]] = {
    "calculator": {"expression": "12 × 8"},
    "plans": {"done": ""},
    "music": {
        "title": "Мой трек",
        "artist": "Любимая музыка",
        "url": "",
        "source": "auto",
        "volume": "70",
    },
    "countdown": {"target": ""},
    "timer": {"duration": "300"},
    "network": {"show_total": "0"},
    "quote": {"author": ""},
    "worldclock": {"cities": "Москва +3\nЛондон 0\nНью-Йорк -5"},
    "user": {
        "caption": "МОЙ МОДУЛЬ",
        "value": "42",
        "subtitle": "Собрано без кода",
        "details": "{date} · {time}",
        "icon": "custom",
        "progress": "0",
        "show_progress": "0",
    },
}

MODULE_DEFAULT_TEXT: dict[str, str] = {
    "todo": "[ ] Купить продукты\n[ ] Проверить почту\n[x] Открыть Gridly",
    "plans": ("Сделать зарядку\nПрочитать 20 страниц\nЗакончить отчёт\n"
              "Прогуляться\nЛечь до 23:00"),
}

# Подстановки no-code модуля, которым нужны часы или системные метрики.
USER_CLOCK_TOKENS = ("{time}", "{date}", "{weekday}", "{greeting}")
USER_METRIC_TOKENS = ("{cpu}", "{memory}", "{battery}", "{disk}", "{uptime}",
                      "{processes}", "{net_down}", "{net_up}")


def default_module_settings(module: str) -> dict[str, str]:
    """Стартовые настройки модуля, включая вычисляемые значения."""
    settings = dict(MODULE_DEFAULT_SETTINGS.get(module, {}))
    if module == "countdown" and not settings.get("target"):
        settings["target"] = f"01.01.{datetime.now().year + 1} 00:00"
    return settings

DEFAULT_SIZES: dict[str, tuple[int, int]] = {
    "weather": (330, 190),
    "clock": (330, 170),
    "date": (270, 170),
    "cpu": (300, 180),
    "memory": (330, 180),
    "battery": (300, 170),
    "disk": (330, 180),
    "custom": (440, 280),
}

KIND_ACCENTS: dict[str, str] = {
    "weather": "#5cc8ff",
    "clock": "#a78bfa",
    "date": "#ffcf6e",
    "cpu": "#57e389",
    "memory": "#c792ea",
    "battery": "#7ee787",
    "disk": "#ffb86b",
    "custom": "#8ab4ff",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "weather": "glass",
    "clock": "neon",
    "date": "minimal",
    "cpu": "glass",
    "memory": "neon",
    "battery": "glass",
    "disk": "glass",
    "custom": "glass",
}

DEFAULT_INTERVALS = {
    "weather": 10, "cpu": 2, "memory": 2, "battery": 10,
    "disk": 5, "custom": 2,
}

# Оформление: наборы цветов и геометрии, которые применяются одним кликом.
TEMPLATES: dict[str, dict] = {
    "glass": {
        "label": "Стекло",
        "bg": "#10161f",
        "accent": "#5cc8ff",
        "text": "#ffffff",
        "bg_alpha": 210,
        "corner_radius": 26,
    },
    "neon": {
        "label": "Неон",
        "bg": "#070b10",
        "accent": "#39ffd0",
        "text": "#eafffb",
        "bg_alpha": 235,
        "corner_radius": 22,
    },
    "minimal": {
        "label": "Минимал",
        "bg": "#000000",
        "accent": "#ffcf6e",
        "text": "#ffffff",
        "bg_alpha": 42,
        "corner_radius": 20,
    },
    "light": {
        "label": "Светлый",
        "bg": "#f3f6fb",
        "accent": "#2f6fed",
        "text": "#111827",
        "bg_alpha": 238,
        "corner_radius": 24,
    },
    "warm": {
        "label": "Тёплый",
        "bg": "#2a1a12",
        "accent": "#ff9e64",
        "text": "#fff4ea",
        "bg_alpha": 220,
        "corner_radius": 26,
    },
}


def apply_template(style: "WidgetStyle", template: str,
                   keep_accent: bool = False) -> None:
    """Применяет к стилю готовую цветовую схему."""
    preset = TEMPLATES.get(template)
    if preset is None:
        return
    old_accent = style.accent
    style.template = template
    style.bg = preset["bg"]
    style.text = preset["text"]
    style.bg_alpha = preset["bg_alpha"]
    style.corner_radius = preset["corner_radius"]
    style.accent = old_accent if keep_accent else preset["accent"]


@dataclass
class WidgetStyle:
    template: str = "glass"
    bg: str = "#10161f"
    accent: str = "#5cc8ff"
    text: str = "#ffffff"
    bg_alpha: int = 210
    opacity: int = 255
    corner_radius: int = 26
    font_scale: int = 100
    show_icon: bool = True
    show_label: bool = True
    # Отступ, внутри которого размещаются корневые блоки составного виджета.
    block_padding: int = 12


@dataclass
class BlockStyle:
    """Оформление одного блока составного виджета."""

    bg: str = "#ffffff"
    bg2: str = "#dfe7f5"
    bg_alpha: int = 24
    gradient: bool = False
    radius: int = 12
    border_width: int = 1
    border_color: str = "#ffffff"
    border_alpha: int = 46
    padding: int = 10
    text_color: str = "#ffffff"
    accent: str = "#8ab4ff"
    font_scale: int = 100
    align: str = "left"          # left | center | right
    show_label: bool = True
    show_icon: bool = True
    label: str = ""
    notes: str = ""
    shadow_enabled: bool = False
    shadow_color: str = "#000000"
    shadow_alpha: int = 90
    shadow_blur: int = 12
    shadow_offset_x: int = 0
    shadow_offset_y: int = 4
    glow_enabled: bool = False
    glow_color: str = "#8ab4ff"
    glow_alpha: int = 80
    glow_radius: int = 10


def _sanitize_settings(raw, module: str) -> dict[str, str]:
    """Приводит настройки блока к безопасному словарю строк."""
    if not isinstance(raw, dict):
        return default_module_settings(module)
    result: dict[str, str] = {}
    for key, value in list(raw.items())[:64]:
        if not isinstance(key, str):
            continue
        if isinstance(value, (str, int, float, bool)):
            result[key[:64]] = str(value)[:4000]
    return result


@dataclass
class WidgetBlock:
    """Блок — прямоугольник на основе составного виджета.

    Координаты x/y заданы относительно области содержимого родителя
    (для корневых блоков — относительно внутренней области виджета).
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    module: str = "text"
    parent_id: str | None = None
    x: int = 10
    y: int = 10
    width: int = 180
    height: int = 70
    value: int = 60
    text: str = ""
    settings: dict[str, str] = field(default_factory=dict)
    style: BlockStyle = field(default_factory=BlockStyle)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "WidgetBlock":
        module = str(data.get("module", "text"))
        if module not in MODULES:
            module = "text"
        style_data = data.get("style")
        if not isinstance(style_data, dict):
            style_data = {}
        allowed = {f.name for f in fields(BlockStyle)}
        style = BlockStyle(**{k: v for k, v in style_data.items()
                              if k in allowed})
        if style.align not in ("left", "center", "right"):
            style.align = "left"
        default_w, default_h = MODULE_DEFAULT_SIZE.get(module, (180, 70))
        parent = data.get("parent_id")
        settings = _sanitize_settings(data.get("settings"), module)
        return WidgetBlock(
            id=str(data.get("id") or uuid.uuid4()),
            module=module,
            parent_id=str(parent) if parent else None,
            x=int(data.get("x", 10)),
            y=int(data.get("y", 10)),
            width=max(36, int(data.get("width", default_w))),
            height=max(28, int(data.get("height", default_h))),
            value=max(0, min(100, int(data.get("value", 60)))),
            text=str(data.get("text", "")),
            settings=settings,
            style=style,
        )


def _sanitize_blocks(blocks: list[WidgetBlock]) -> list[WidgetBlock]:
    """Чинит битые ссылки, дубликаты id и циклы вложенности."""
    seen: set[str] = set()
    cleaned: list[WidgetBlock] = []
    for block in blocks:
        if not block.id or block.id in seen:
            block.id = str(uuid.uuid4())
        seen.add(block.id)
        if block.module not in MODULES:
            block.module = "text"
        cleaned.append(block)

    by_id = {block.id: block for block in cleaned}
    for block in cleaned:
        if block.parent_id and block.parent_id not in by_id:
            block.parent_id = None
        if block.parent_id == block.id:
            block.parent_id = None

    # Разрываем циклы, поднимая блок на корень.
    for block in cleaned:
        cursor = block
        visited = {cursor.id}
        while cursor.parent_id:
            parent = by_id.get(cursor.parent_id)
            if parent is None or parent.id in visited:
                cursor.parent_id = None
                break
            visited.add(parent.id)
            cursor = parent
    return cleaned


def block_descendants(blocks: list[WidgetBlock], block_id: str) -> set[str]:
    """Возвращает id всех потомков блока (для удаления/запрета циклов)."""
    result: set[str] = set()
    frontier = [block_id]
    while frontier:
        current = frontier.pop()
        for block in blocks:
            if block.parent_id == current and block.id not in result:
                result.add(block.id)
                frontier.append(block.id)
    return result


def state_modules(state: "WidgetState") -> set[str]:
    """Набор мини-модулей, из которых состоит виджет."""
    if state.kind != "custom":
        return {state.kind}
    return {block.module for block in state.blocks}


def _user_templates(state: "WidgetState") -> str:
    """Тексты no-code модулей, в которых могут быть подстановки."""
    parts: list[str] = []
    for block in state.blocks:
        if block.module != "user":
            continue
        for key in ("caption", "value", "subtitle", "details"):
            parts.append(str(block.settings.get(key, "")))
    return " ".join(parts).casefold()


def state_needs_weather(state: "WidgetState") -> bool:
    if state.kind == "weather":
        return True
    if state.kind != "custom":
        return False
    if {"weather", "temperature"} & state_modules(state):
        return True
    templates = _user_templates(state)
    return any(token in templates for token in
               ("{temp}", "{city}", "{weather}", "{humidity}", "{wind}"))


def state_needs_metrics(state: "WidgetState") -> bool:
    if state.kind in ("cpu", "memory", "battery", "disk"):
        return True
    if state.kind != "custom":
        return False
    modules = state_modules(state)
    if {"cpu", "memory", "battery", "disk", "metric", "progress",
            "network", "uptime", "processes"} & modules:
        return True
    if "user" in modules:
        templates = _user_templates(state)
        return any(token in templates for token in USER_METRIC_TOKENS)
    return False


def state_needs_clock(state: "WidgetState") -> bool:
    if state.kind in ("clock", "date"):
        return True
    if state.kind != "custom":
        return False
    modules = state_modules(state)
    if {"clock", "date", "weekday", "timer", "stopwatch", "countdown",
            "worldclock", "music"} & modules:
        return True
    if "user" in modules:
        templates = _user_templates(state)
        return any(token in templates for token in USER_CLOCK_TOKENS)
    return False


@dataclass
class WidgetState:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "weather"
    title: str = "Погода"
    x: int = 140
    y: int = 140
    width: int = 330
    height: int = 190
    locked: bool = False
    always_on_top: bool = False
    city: str = "Москва"
    latitude: float | None = None
    longitude: float | None = None
    resolved_city: str = ""
    units: str = "c"
    clock_24h: bool = True
    show_seconds: bool = False
    interval: int = 10
    style: WidgetStyle = field(default_factory=WidgetStyle)
    blocks: list[WidgetBlock] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "WidgetState":
        kind = data.get("kind", "weather")
        if kind not in WIDGET_KINDS:
            kind = "weather"

        style_data = data.get("style")
        if not isinstance(style_data, dict):
            style_data = {}
        allowed_style = {f.name for f in fields(WidgetStyle)}
        style = WidgetStyle(**{k: v for k, v in style_data.items()
                               if k in allowed_style})
        if style.template not in TEMPLATES:
            style.template = "glass"

        width, height = DEFAULT_SIZES[kind]
        units = data.get("units", "c")
        if units not in ("c", "f"):
            units = "c"

        blocks: list[WidgetBlock] = []
        raw_blocks = data.get("blocks")
        if isinstance(raw_blocks, list):
            for raw in raw_blocks:
                if not isinstance(raw, dict):
                    continue
                try:
                    blocks.append(WidgetBlock.from_dict(raw))
                except (TypeError, ValueError, AttributeError):
                    logger.warning("Пропускаю повреждённый блок виджета: %r",
                                   raw)
        blocks = _sanitize_blocks(blocks)

        return WidgetState(
            id=data.get("id") or str(uuid.uuid4()),
            kind=kind,
            title=data.get("title") or WIDGET_KINDS[kind],
            x=int(data.get("x", 140)),
            y=int(data.get("y", 140)),
            width=int(data.get("width", width)),
            height=int(data.get("height", height)),
            locked=bool(data.get("locked", False)),
            always_on_top=bool(data.get("always_on_top", False)),
            city=str(data.get("city", "Москва")),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            resolved_city=str(data.get("resolved_city", "")),
            units=units,
            clock_24h=bool(data.get("clock_24h", True)),
            show_seconds=bool(data.get("show_seconds", False)),
            interval=int(data.get("interval", DEFAULT_INTERVALS.get(kind, 5))),
            style=style,
            blocks=blocks,
        )


def make_block(module: str, x: int = 10, y: int = 10,
               width: int | None = None, height: int | None = None,
               parent_id: str | None = None) -> WidgetBlock:
    """Создаёт блок с разумным размером и оформлением под модуль."""
    if module not in MODULES:
        module = "text"
    default_w, default_h = MODULE_DEFAULT_SIZE.get(module, (180, 70))
    accent = MODULE_ACCENTS.get(module, "#8ab4ff")
    style = BlockStyle(accent=accent, label="")
    settings = default_module_settings(module)
    text = MODULE_DEFAULT_TEXT.get(module, "")
    if module == "container":
        style.bg_alpha = 18
        style.border_alpha = 52
        style.padding = 12
        style.show_icon = False
        style.radius = 16
    elif module == "notes":
        style.notes = "Заметка"
        style.bg_alpha = 38
    elif module in ("metric", "progress"):
        style.bg_alpha = 18
    elif module in ("notepad", "todo", "plans", "quote"):
        style.bg_alpha = 30
    elif module in ("calculator", "music"):
        style.bg_alpha = 26
    return WidgetBlock(
        module=module,
        parent_id=parent_id,
        x=int(x),
        y=int(y),
        width=max(36, int(width if width is not None else default_w)),
        height=max(28, int(height if height is not None else default_h)),
        text=text,
        settings=settings,
        style=style,
    )


def make_widget_state(kind: str, x: int = 140, y: int = 140) -> WidgetState:
    """Создаёт виджет с красивым оформлением по умолчанию."""
    if kind not in WIDGET_KINDS:
        kind = "weather"
    template = DEFAULT_TEMPLATES.get(kind, "glass")
    style = WidgetStyle()
    apply_template(style, template)
    style.accent = KIND_ACCENTS.get(kind, style.accent)

    width, height = DEFAULT_SIZES.get(kind, (320, 180))
    title = WIDGET_KINDS[kind]
    if kind == "custom":
        title = "Составной виджет"
    state = WidgetState(
        kind=kind,
        title=title,
        x=x,
        y=y,
        width=width,
        height=height,
        interval=DEFAULT_INTERVALS.get(kind, 5),
        style=style,
    )
    if kind == "weather":
        state.city = "Москва"
    return state


def load_all() -> list[WidgetState]:
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Не удалось прочитать %s: %s — стартуем с пустого списка",
                     DATA_FILE, exc)
        return []

    result: list[WidgetState] = []
    for item in raw.get("widgets", []):
        try:
            result.append(WidgetState.from_dict(item))
        except (TypeError, ValueError) as exc:
            logger.error("Пропускаю повреждённый виджет: %s", exc)
    return result


def save_all(widgets: list[WidgetState]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"widgets": [w.to_dict() for w in widgets]}
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(DATA_FILE)
