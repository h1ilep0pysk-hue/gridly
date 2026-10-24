"""
core/storage.py
JSON-хранилище состояния Fences. Toolchain: Python 3.11.

Схема data/fences.json:
{
  "fences": [
    {
      "id": "uuid4-str",
      "title": "Shortcuts",
      "x": 100, "y": 100, "width": 320, "height": 240,
      "layout": "grid",          # "grid" | "vertical" | "horizontal" | "folder"
      "rolled_up": false,
      "locked": false,
      "always_on_top": false,
      "mode": "manual",
      "portal_path": null,
      "items": [{"path": "C:\\...\\app.lnk", "x": 8, "y": 8}],
      "style": {
        "tint_bgr": 2829099, "tint_alpha": 160, "opacity": 235,
        "corner_radius": 10,
        ... расширенные параметры фона, рамки, теней, типографики ...
      }
    }
  ]
}
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

logger = logging.getLogger("gridly.storage")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "fences.json"

BACKGROUND_MODES = {
    "solid": "Сплошной",
    "gradient": "Градиент",
    "glass": "Стекло",
}

BORDER_STYLES = {
    "solid": "Сплошная",
    "dashed": "Пунктир",
    "dotted": "Точки",
    "none": "Без рамки",
}

TEXTURES = {
    "none": "Нет",
    "dots": "Точки",
    "grid": "Сетка",
    "diagonal": "Диагональ",
    "noise": "Шум",
}

TITLE_ALIGNS = {
    "left": "Слева",
    "center": "По центру",
    "right": "Справа",
}


def bgr_to_hex(value: int) -> str:
    """0xBBGGRR (как в FenceStyle.tint_bgr) → '#rrggbb'."""
    b = value & 0xFF
    g = (value >> 8) & 0xFF
    r = (value >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_bgr(value: str) -> int:
    """'#rrggbb' → 0xBBGGRR."""
    raw = str(value or "").strip().lstrip("#")
    if len(raw) != 6:
        return 0x2B2B2B
    try:
        r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return 0x2B2B2B
    return (b << 16) | (g << 8) | r


@dataclass
class FenceItem:
    path: str
    x: int = 8
    y: int = 8


@dataclass
class FenceStyle:
    # --- обратная совместимость и общая прозрачность -----------------
    tint_bgr: int = 0x2B2B2B
    tint_alpha: int = 160
    opacity: int = 235
    corner_radius: int = 10

    # --- геометрия содержимого ---------------------------------------
    padding: int = 8
    spacing: int = 6
    item_width: int = 76
    item_height: int = 84
    item_icon_size: int = 40
    show_item_labels: bool = True
    item_text_color: str = "#ffffff"
    item_text_size: int = 11
    item_bg: str = "#ffffff"
    item_bg_alpha: int = 0
    item_hover_alpha: int = 22
    item_radius: int = 6

    # --- фон ----------------------------------------------------------
    bg_mode: str = "solid"
    bg_color: str = "#2b2b2b"
    bg_color2: str = "#141414"
    bg_alpha: int = 160
    gradient_angle: int = 160
    gradient_alpha: int = 180
    texture: str = "none"
    texture_color: str = "#ffffff"
    texture_alpha: int = 14
    texture_scale: int = 18
    blur_enabled: bool = False
    blur_alpha: int = 150

    # --- рамка --------------------------------------------------------
    border_width: int = 0
    border_color: str = "#ffffff"
    border_alpha: int = 40
    border_style: str = "solid"

    # --- внешняя тень -------------------------------------------------
    shadow_enabled: bool = False
    shadow_color: str = "#000000"
    shadow_alpha: int = 110
    shadow_blur: int = 18
    shadow_offset_x: int = 0
    shadow_offset_y: int = 6

    # --- внутренняя тень ---------------------------------------------
    inner_shadow_enabled: bool = False
    inner_shadow_color: str = "#000000"
    inner_shadow_alpha: int = 70
    inner_shadow_blur: int = 10
    inner_shadow_offset_x: int = 0
    inner_shadow_offset_y: int = 4

    # --- свечение -----------------------------------------------------
    glow_enabled: bool = False
    glow_color: str = "#5cc8ff"
    glow_alpha: int = 90
    glow_radius: int = 14

    # --- заголовок ----------------------------------------------------
    header_visible: bool = True
    header_height: int = 30
    header_bg: str = "#000000"
    header_bg2: str = "#000000"
    header_alpha: int = 50
    header_gradient: bool = False
    title_color: str = "#ffffff"
    title_font: str = "Segoe UI"
    title_size: int = 12
    title_weight: int = 600
    title_italic: bool = False
    title_letter_spacing: int = 0
    title_align: str = "left"
    title_shadow: bool = False
    title_shadow_color: str = "#000000"
    title_shadow_alpha: int = 160
    title_shadow_offset_x: int = 1
    title_shadow_offset_y: int = 1
    title_shadow_blur: int = 2
    title_glow: bool = False
    title_glow_color: str = "#5cc8ff"
    title_glow_alpha: int = 160
    title_glow_radius: int = 8
    show_close_button: bool = True
    show_lock_button: bool = True

    def sync_legacy(self) -> None:
        """Держит старые поля tint_* в согласии с новым фоном."""
        self.tint_bgr = hex_to_bgr(self.bg_color)
        self.tint_alpha = int(self.bg_alpha)


@dataclass
class FenceState:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New Fence"
    x: int = 100
    y: int = 100
    width: int = 320
    height: int = 240
    layout: str = "grid"
    rolled_up: bool = False
    locked: bool = False
    always_on_top: bool = False
    mode: str = "manual"
    portal_path: str | None = None
    items: list[FenceItem] = field(default_factory=list)
    style: FenceStyle = field(default_factory=FenceStyle)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "FenceState":
        items: list[FenceItem] = []
        for raw in d.get("items", []) or []:
            try:
                items.append(FenceItem(
                    path=str(raw.get("path", "")),
                    x=int(raw.get("x", 8)),
                    y=int(raw.get("y", 8)),
                ))
            except (TypeError, ValueError, AttributeError):
                logger.warning("Пропускаю повреждённый элемент fence: %r", raw)

        style_data = d.get("style")
        if not isinstance(style_data, dict):
            style_data = {}
        allowed = {f.name for f in fields(FenceStyle)}
        clean_style = {k: v for k, v in style_data.items() if k in allowed}
        style = FenceStyle(**clean_style)
        # Миграция старых файлов: tint_* задаёт фон, если новый цвет не сохранён.
        if "bg_color" not in clean_style:
            style.bg_color = bgr_to_hex(style.tint_bgr)
        if "bg_alpha" not in clean_style:
            style.bg_alpha = int(style.tint_alpha)
        if style.bg_mode not in BACKGROUND_MODES:
            style.bg_mode = "solid"
        if style.border_style not in BORDER_STYLES:
            style.border_style = "solid"
        if style.texture not in TEXTURES:
            style.texture = "none"
        if style.title_align not in TITLE_ALIGNS:
            style.title_align = "left"

        return FenceState(
            id=str(d.get("id") or uuid.uuid4()),
            title=str(d.get("title", "Fence")),
            x=int(d.get("x", 100)),
            y=int(d.get("y", 100)),
            width=int(d.get("width", 320)),
            height=int(d.get("height", 240)),
            layout=str(d.get("layout", "grid")),
            rolled_up=bool(d.get("rolled_up", False)),
            locked=bool(d.get("locked", False)),
            always_on_top=bool(d.get("always_on_top", False)),
            mode=str(d.get("mode", "manual")),
            portal_path=d.get("portal_path"),
            items=items,
            style=style,
        )


def load_all() -> list[FenceState]:
    if not DATA_FILE.exists():
        return []
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Не удалось прочитать %s: %s — стартуем с пустого состояния",
                     DATA_FILE, exc)
        return []
    result: list[FenceState] = []
    for raw_fence in raw.get("fences", []) or []:
        try:
            result.append(FenceState.from_dict(raw_fence))
        except (TypeError, ValueError) as exc:
            logger.error("Пропускаю повреждённый fence: %s", exc)
    return result


def save_all(fences: list[FenceState]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"fences": [f.to_dict() for f in fences]}
    tmp = DATA_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(DATA_FILE)
