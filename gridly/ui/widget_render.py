"""
ui/widget_render.py
Отрисовка desktop-виджетов и живого предпросмотра.

Одна и та же функция paint_widget() рисует и настоящее окно на рабочем столе,
и карточку предпросмотра в конструкторе — поэтому они выглядят одинаково.
"""

from __future__ import annotations

import math
from datetime import datetime

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QColor, QFont, QFontMetricsF, QLinearGradient,
                         QPainter, QPainterPath, QPen, QRadialGradient)

from core.module_data import (MONTHS_GENITIVE, WEEKDAYS, apply_placeholders,
                              build_placeholders, calculate, format_bytes,
                              format_duration, format_speed, format_uptime,
                              is_audio_url, music_source, music_source_label,
                              normalize_music_url, parse_datetime,
                              parse_duration, parse_plan_done, parse_plans,
                              parse_todo, parse_worldclock, quote_of_day,
                              time_in_zone)
from core.widget_storage import (MODULES, MODULE_ICONS, WidgetBlock,
                                 WidgetState)
from ui.widget_icons import draw_kind_icon


def _color(value: str, fallback: str) -> QColor:
    color = QColor(value)
    if not color.isValid():
        color = QColor(fallback)
    return color


def _text(value: str, fallback: str = "—") -> str:
    value = str(value).strip() if value is not None else ""
    return value or fallback


def _font(pixel_size: float, weight: QFont.Weight = QFont.Weight.Normal,
          letter_spacing: float = 0.0) -> QFont:
    font = QFont("Segoe UI")
    font.setPixelSize(max(8, int(round(pixel_size))))
    font.setWeight(weight)
    if letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                              letter_spacing)
    return font


def _fit_font(text: str, max_px: float, min_px: float, width: float,
              weight: QFont.Weight) -> QFont:
    size = max_px
    while size > min_px:
        font = _font(size, weight)
        if QFontMetricsF(font).horizontalAdvance(text) <= width:
            return font
        size -= 1.0
    return _font(min_px, weight)


def _draw_text(p: QPainter, rect: QRectF, text: str, font: QFont,
               color: QColor, align: Qt.AlignmentFlag =
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               elide: bool = True) -> None:
    p.setFont(font)
    p.setPen(color)
    if elide:
        metrics = QFontMetricsF(font)
        if metrics.horizontalAdvance(text) > rect.width():
            text = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                      rect.width())
    p.drawText(rect, int(align), text)


def _greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


def format_clock(now: datetime, clock_24h: bool, show_seconds: bool) -> str:
    if clock_24h:
        fmt = "%H:%M:%S" if show_seconds else "%H:%M"
    else:
        fmt = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
    value = now.strftime(fmt)
    if not clock_24h:
        value = value.replace("AM", "am").replace("PM", "pm")
        if value.startswith("0"):
            value = value[1:]
    return value


def sample_custom_data(state: WidgetState | None = None) -> dict:
    """Демонстрационные данные для составного виджета."""
    units = state.units if state else "c"
    temp, feels = (70, 68) if units == "f" else (21, 20)
    weather = {
        "temp": temp,
        "feels": feels,
        "humidity": 54,
        "wind": 7.0 if units == "f" else 3.2,
        "description": "Ясно",
        "icon": "weather_sun",
        "city": (state.city if state else "Москва") or "Москва",
        "units": units,
    }
    metrics = {
        "cpu": {"percent": 37, "cores": 8, "interval": 2},
        "memory": {"percent": 62, "used": 10.2, "total": 16.0},
        "battery": {"percent": 84, "plugged": True, "secsleft": None},
        "disk": {"percent": 48, "free": 256.0, "total": 512.0,
                 "letter": "C:"},
        "network": {"down": 1.8 * 1024 ** 2, "up": 240 * 1024,
                    "total_down": 42.0 * 1024 ** 3,
                    "total_up": 3.2 * 1024 ** 3},
        "uptime": {"seconds": 3 * 86400 + 4 * 3600 + 12 * 60,
                   "boot": None},
        "processes": {"count": 248},
    }
    return {"weather": weather, "metrics": metrics, "modules": {}}


def sample_data(kind: str, state: WidgetState | None = None) -> dict:
    """Демонстрационные данные для предпросмотра, пока нет живых."""
    if kind == "custom":
        return sample_custom_data(state)
    now = datetime.now()
    units = state.units if state else "c"
    if kind == "weather":
        temp, feels = (70, 68) if units == "f" else (21, 20)
        return {
            "temp": temp,
            "feels": feels,
            "humidity": 54,
            "wind": 7.0 if units == "f" else 3.2,
            "description": "Ясно",
            "icon": "weather_sun",
            "city": (state.city if state else "Москва") or "Москва",
            "units": units,
        }
    if kind == "clock":
        return {
            "time": format_clock(now, state.clock_24h if state else True,
                                 state.show_seconds if state else False),
            "date": f"{WEEKDAYS[now.weekday()]}, {now.day} " \
                    f"{MONTHS_GENITIVE[now.month - 1]}",
            "greeting": _greeting(now.hour),
            "seconds": now.second,
        }
    if kind == "date":
        return {
            "day": str(now.day),
            "month": MONTHS_GENITIVE[now.month - 1],
            "weekday": WEEKDAYS[now.weekday()],
            "year": str(now.year),
        }
    if kind == "cpu":
        return {"percent": 37, "cores": 8, "interval": state.interval if state else 2}
    if kind == "memory":
        return {"percent": 62, "used": 10.2, "total": 16.0}
    if kind == "battery":
        return {"percent": 84, "plugged": True, "secsleft": None}
    if kind == "disk":
        return {"percent": 48, "free": 256.0, "total": 512.0,
                "letter": "C:"}
    return {"percent": 50}


def _draw_shadow(p: QPainter, card: QRectF, radius: float,
                 light: bool) -> None:
    base_alpha = 46 if light else 70
    for spread, alpha in ((5, base_alpha // 3), (2, base_alpha // 2),
                          (0, base_alpha)):
        rect = card.adjusted(-spread, -spread + 2, spread, spread + 2)
        p.setBrush(QColor(0, 0, 0, alpha))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, radius + spread, radius + spread)


def _draw_card(p: QPainter, card: QRectF, radius: float,
               bg: QColor, accent: QColor, text: QColor,
               template: str, alpha: int) -> None:
    light = bg.lightness() > 165
    border = QColor(0, 0, 0, 34) if light else QColor(255, 255, 255, 42)

    if template == "neon":
        for width, a in ((7, 18), (4, 28), (2, 44)):
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(accent.red(), accent.green(),
                                 accent.blue(), a), width))
            p.drawRoundedRect(card.adjusted(-2, -2, 2, 2),
                              radius + 2, radius + 2)
        fill = QColor(bg)
        fill.setAlpha(alpha)
        p.setBrush(fill)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 150),
                      1.2))
        p.drawRoundedRect(card, radius, radius)
        # Внутреннее свечение сверху
        p.save()
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        p.setClipPath(path)
        glow = QRadialGradient(QPointF(card.left() + card.width() * 0.25,
                                       card.top()),
                               card.width() * 0.8)
        glow.setColorAt(0.0, QColor(accent.red(), accent.green(),
                                    accent.blue(), 45))
        glow.setColorAt(1.0, QColor(accent.red(), accent.green(),
                                    accent.blue(), 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(card)
        p.restore()
        return

    if template == "minimal":
        fill = QColor(bg)
        fill.setAlpha(alpha)
        p.setBrush(fill)
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(card, radius, radius)
        p.save()
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        p.setClipPath(path)
        sheen = QLinearGradient(card.topLeft(), card.bottomLeft())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 20 if not light else 80))
        sheen.setColorAt(0.35, QColor(255, 255, 255, 0))
        p.setBrush(sheen)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(card)
        p.restore()
        return

    # glass / light / warm — мягкий градиент и стеклянный блик
    grad = QLinearGradient(card.topLeft(), card.bottomLeft())
    top = bg.lighter(128)
    bottom = bg.darker(112)
    top.setAlpha(alpha)
    bottom.setAlpha(alpha)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bottom)
    p.setBrush(grad)
    p.setPen(QPen(border, 1.0))
    p.drawRoundedRect(card, radius, radius)

    p.save()
    path = QPainterPath()
    path.addRoundedRect(card, radius, radius)
    p.setClipPath(path)

    sheen = QLinearGradient(card.topLeft(), QPointF(card.left(),
                                                   card.top() + card.height() * 0.55))
    sheen.setColorAt(0.0, QColor(255, 255, 255, 34 if not light else 95))
    sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(sheen)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(card)

    glow = QRadialGradient(
        QPointF(card.left() + card.width() * 0.18, card.top() + 4),
        card.width() * 0.75,
    )
    glow.setColorAt(0.0, QColor(accent.red(), accent.green(),
                                accent.blue(), 30))
    glow.setColorAt(1.0, QColor(accent.red(), accent.green(),
                                accent.blue(), 0))
    p.setBrush(glow)
    p.drawRect(card)
    p.restore()

    if not light:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 26), 1.0))
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5),
                          radius, radius)


def _metric_ring(p: QPainter, rect: QRectF, fraction: float,
                 accent: QColor, track: QColor, width: float) -> None:
    fraction = max(0.0, min(1.0, fraction))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(track, width, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawEllipse(rect)
    if fraction <= 0.001:
        return
    p.setPen(QPen(accent, width, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawArc(rect, 90 * 16, int(-360 * 16 * fraction))


def _weather_icon_color(name: str, accent: QColor, text: QColor) -> QColor:
    if name in ("weather_sun", "weather_thunder"):
        return QColor("#ffd166")
    if name == "weather_moon":
        return QColor("#ffe29a")
    if name == "weather_rain":
        return QColor("#7cc4ff")
    if name == "weather_snow":
        return QColor("#e6f5ff")
    if name == "weather_partly":
        return QColor("#ffd166")
    return QColor(text.red(), text.green(), text.blue(), 230)


def _widget_texts(state: WidgetState, data: dict) -> dict:
    kind = state.kind
    units = "°F" if state.units == "f" else "°C"
    if kind == "weather":
        temp = data.get("temp")
        big = f"{temp}°" if temp is not None else "—"
        wind_unit = "миль/ч" if state.units == "f" else "м/с"
        description = _text(data.get("description"), "Загрузка погоды…")
        if "feels" in data:
            secondary = f"{description} · ощущается {data['feels']}°"
            detail = (f"Влажность {data['humidity']}% · "
                      f"Ветер {data['wind']:.1f} {wind_unit}")
        else:
            secondary = description
            detail = ("Проверьте название города"
                      if data.get("error") else "—")
        return {
            "eyebrow": _text(data.get("city") or state.city, "Погода").upper(),
            "big": big,
            "secondary": secondary,
            "detail": detail,
            "progress": None,
            "icon": data.get("icon", "weather_sun"),
            "tone": units,
        }
    if kind == "clock":
        return {
            "eyebrow": _text(state.title, "Время").upper(),
            "big": _text(data.get("time"), "--:--"),
            "secondary": _text(data.get("date"), ""),
            "detail": _text(data.get("greeting"), ""),
            "progress": (data.get("seconds", 0) or 0) / 60.0,
            "icon": "clock",
        }
    if kind == "date":
        return {
            "eyebrow": "Сегодня",
            "big": _text(data.get("day"), "—"),
            "secondary": _text(data.get("month"), "").capitalize(),
            "detail": f"{_text(data.get('weekday'), '')} · {data.get('year', '')}",
            "progress": None,
            "icon": "date",
        }
    if kind == "cpu":
        return {
            "eyebrow": _text(state.title, "Загрузка ЦП").upper(),
            "big": f"{int(data.get('percent', 0))}%",
            "secondary": "Загрузка процессора",
            "detail": f"{data.get('cores', '—')} ядер · обновление "
                      f"{state.interval} с",
            "progress": data.get("percent", 0) / 100.0,
            "icon": "cpu",
        }
    if kind == "memory":
        return {
            "eyebrow": _text(state.title, "Память").upper(),
            "big": f"{int(data.get('percent', 0))}%",
            "secondary": "Оперативная память",
            "detail": f"{data.get('used', 0):.1f} / {data.get('total', 0):.1f} ГБ",
            "progress": data.get("percent", 0) / 100.0,
            "icon": "memory",
        }
    if kind == "battery":
        if data.get("plugged"):
            detail = "Питание от сети"
            secs = data.get("secsleft")
            if isinstance(secs, (int, float)) and 0 < secs < 24 * 3600:
                detail = f"Заряжается · {int(secs // 3600)} ч " \
                         f"{int(secs % 3600 // 60):02d} мин"
        elif data.get("percent") is not None:
            detail = "Разряжается"
        else:
            detail = "Батарея не найдена"
        return {
            "eyebrow": _text(state.title, "Батарея").upper(),
            "big": f"{int(data.get('percent', 0))}%" if data.get("percent") is not None else "—",
            "secondary": "Батарея",
            "detail": detail,
            "progress": (data.get("percent") or 0) / 100.0,
            "icon": "battery",
        }
    if kind == "disk":
        letter = data.get("letter", "C:")
        return {
            "eyebrow": _text(state.title, f"Диск {letter}").upper(),
            "big": f"{int(data.get('percent', 0))}%",
            "secondary": f"Диск {letter}",
            "detail": f"Свободно {data.get('free', 0):.0f} ГБ "
                      f"из {data.get('total', 0):.0f} ГБ",
            "progress": data.get("percent", 0) / 100.0,
            "icon": "disk",
        }
    return {"eyebrow": "Виджет", "big": "—", "secondary": "",
            "detail": "", "progress": None, "icon": kind}


def _with_alpha(color: QColor, alpha: int) -> QColor:
    result = QColor(color)
    result.setAlpha(max(0, min(255, int(alpha))))
    return result


CARD_MARGIN = 5.0


def widget_card_rect(outer: QRectF) -> QRectF:
    """Основа виджета без поля под тень (совпадает с paint_widget)."""
    return outer.adjusted(CARD_MARGIN, CARD_MARGIN,
                          -CARD_MARGIN, -CARD_MARGIN)


def widget_content_rect(card: QRectF, state: WidgetState) -> QRectF:
    """Область, в которой лежат корневые блоки составного виджета."""
    pad = max(0, min(80, int(state.style.block_padding)))
    return card.adjusted(pad, pad, -pad, -pad)


def block_content_rect(block: WidgetBlock, rect: QRectF) -> QRectF:
    """Внутренняя область блока, в которой лежат вложенные элементы."""
    pad = max(0.0, min(float(block.style.padding),
                       rect.width() / 3, rect.height() / 3))
    area = rect.adjusted(pad, pad, -pad, -pad)
    if block.module == "container" and block.style.show_label:
        label = (block.style.label or "").strip()
        if label:
            header = max(14.0, min(28.0, rect.height() * 0.20))
            area.setTop(min(area.bottom() - 18.0, area.top() + header))
    return area


def iter_widget_blocks(state: WidgetState,
                       card: QRectF) -> list[tuple[WidgetBlock, QRectF]]:
    """Блоки в порядке отрисовки: родитель раньше вложенных детей."""
    result: list[tuple[WidgetBlock, QRectF]] = []
    by_parent: dict[str | None, list[WidgetBlock]] = {}
    for block in state.blocks:
        by_parent.setdefault(block.parent_id, []).append(block)

    def walk(parent_id: str | None, area: QRectF) -> None:
        for block in by_parent.get(parent_id, []):
            rect = QRectF(area.left() + block.x,
                          area.top() + block.y,
                          max(20.0, float(block.width)),
                          max(20.0, float(block.height)))
            result.append((block, rect))
            walk(block.id, block_content_rect(block, rect))

    walk(None, widget_content_rect(card, state))
    return result


def block_rect_at(state: WidgetState, card: QRectF,
                  point: QPointF) -> WidgetBlock | None:
    """Самый верхний блок под точкой."""
    for block, rect in reversed(iter_widget_blocks(state, card)):
        if rect.contains(point):
            return block
    return None


def _block_icon_width(block: WidgetBlock, inner: QRectF) -> float:
    """Ширина колонки иконки — та же формула, что в _paint_block."""
    if not block.style.show_icon or inner.width() <= 66 \
            or inner.height() <= 34:
        return 0.0
    icon_size = max(16.0, min(inner.height() * 0.62,
                              inner.width() * 0.30, 42.0))
    return icon_size + max(6.0, inner.width() * 0.045)


def plan_text_rect(block: WidgetBlock, rect: QRectF) -> QRectF:
    """Область планов без иконки и полосы прогресса."""
    style = block.style
    pad = max(0.0, min(float(style.padding), rect.width() / 3,
                       rect.height() / 3))
    inner = rect.adjusted(pad, pad, -pad, -pad)
    icon_w = _block_icon_width(block, inner)
    text_rect = QRectF(inner.left() + icon_w, inner.top(),
                       max(10.0, inner.width() - icon_w), inner.height())
    if parse_plans(block.text) and text_rect.height() > 30:
        bar_h = max(2.5, min(5.0, text_rect.height() * 0.07))
        text_rect.setBottom(text_rect.bottom() - bar_h - max(2.0, bar_h))
    return text_rect


def plan_header_height(block: WidgetBlock, text_rect: QRectF) -> float:
    if block.style.show_label and text_rect.height() >= 38:
        return max(9.0, min(15.0, text_rect.height() * 0.19))
    return 0.0


def plan_rows_layout(text_rect: QRectF, count: int,
                     header_h: float) -> list[tuple[int, QRectF]]:
    if count <= 0:
        return []
    top = text_rect.top() + header_h + (1.0 if header_h else 0.0)
    area = QRectF(text_rect.left(), top, text_rect.width(),
                  max(0.0, text_rect.bottom() - top))
    if area.height() <= 0:
        return []
    gap = 3.0 if area.height() >= count * 18 else 1.0
    row_h = (area.height() - gap * (count - 1)) / count
    visible = count
    if row_h < 10.0:
        visible = max(1, int((area.height() + gap) // (10.0 + gap)))
        row_h = (area.height() - gap * (visible - 1)) / visible
    rows: list[tuple[int, QRectF]] = []
    y = area.top()
    for index in range(visible):
        rows.append((index, QRectF(area.left(), y, area.width(), row_h)))
        y += row_h + gap
    return rows


def plan_row_index_at(block: WidgetBlock, rect: QRectF,
                      point: QPointF) -> int | None:
    """Индекс плана под точкой (для двойного клика)."""
    if block.module != "plans":
        return None
    text_rect = plan_text_rect(block, rect)
    rows = plan_rows_layout(text_rect, len(parse_plans(block.text)),
                            plan_header_height(block, text_rect))
    for index, row_rect in rows:
        if row_rect.contains(point):
            return index
    return None


def _paint_plan_rows(p: QPainter, text_rect: QRectF, block: WidgetBlock,
                     texts: dict, scale: float) -> None:
    """Красные крестики и зелёные галочки для модуля «Планы на день»."""
    style = block.style
    base_text = _color(style.text_color, "#ffffff")
    light_background = base_text.lightness() < 128
    red = QColor("#d64545") if light_background else QColor("#ff7b72")
    green = QColor("#2f9e5f") if light_background else QColor("#57e389")

    eyebrow = str(texts.get("eyebrow") or "")
    header_h = plan_header_height(block, text_rect)
    if eyebrow and header_h:
        _draw_text(p, QRectF(text_rect.left(), text_rect.top(),
                             text_rect.width(), header_h),
                   eyebrow, _font(max(7.0, min(10.0 * scale,
                                              header_h * 0.78)),
                                  QFont.Weight.DemiBold),
                   _with_alpha(base_text, 160),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    summary = str(texts.get("summary") or "")
    if summary and header_h:
        _draw_text(p, QRectF(text_rect.right() - 48, text_rect.top(), 48,
                             header_h),
                   summary, _font(max(7.0, min(9.5 * scale,
                                              header_h * 0.75)),
                                  QFont.Weight.Medium),
                   _with_alpha(base_text, 135),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    rows = plan_rows_layout(text_rect, len(texts.get("plans") or []), header_h)
    plans = texts.get("plans") or []
    for index, row_rect in rows:
        if index >= len(plans):
            break
        value, done = plans[index]
        color = green if done else red
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_with_alpha(color, 30 if light_background else 26))
        radius = min(7.0, row_rect.height() / 2)
        p.drawRoundedRect(row_rect, radius, radius)
        symbol_w = max(14.0, min(20.0, row_rect.height() * 0.72))
        symbol_rect = QRectF(row_rect.left() + 4, row_rect.top(),
                             symbol_w, row_rect.height())
        p.setFont(_font(max(8.0, min(15.0, row_rect.height() * 0.62)),
                        QFont.Weight.Bold))
        p.setPen(color)
        p.drawText(symbol_rect,
                   int(Qt.AlignmentFlag.AlignCenter),
                   "✓" if done else "✕")
        body_rect = row_rect.adjusted(symbol_w + 8, 0, -4, 0)
        font = _font(max(8.0, min(12.5, row_rect.height() * 0.52)),
                     QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(_with_alpha(color, 235))
        display = QFontMetricsF(font).elidedText(
            str(value), Qt.TextElideMode.ElideRight, body_rect.width()
        )
        p.drawText(body_rect,
                   int(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter),
                   display)


def _block_texts(block: WidgetBlock, state: WidgetState,
                 data: dict | None) -> dict:
    """Текстовое содержимое мини-модуля."""
    now = datetime.now()
    style = block.style
    module = block.module
    metrics = (data or {}).get("metrics") or {}
    weather = (data or {}).get("weather") or {}
    runtime = (data or {}).get("modules") or {}
    units = "°F" if state.units == "f" else "°C"
    custom_label = (style.label or "").strip()
    label = custom_label or MODULES.get(module, module).upper()

    def metric(name: str, key: str, fallback):
        block_data = metrics.get(name) or {}
        value = block_data.get(key)
        return fallback if value is None else value

    def setting(key: str, default: str = "") -> str:
        value = block.settings.get(key)
        return default if value is None else str(value)

    if module == "container":
        return {
            "eyebrow": custom_label,
            "value": "",
            "secondary": "",
            "detail": "",
            "icon": "custom",
            "progress": None,
        }
    if module == "weekday":
        return {
            "eyebrow": label if custom_label else "ДЕНЬ НЕДЕЛИ",
            "value": WEEKDAYS[now.weekday()],
            "secondary": f"{now.day} {MONTHS_GENITIVE[now.month - 1]}",
            "detail": str(now.year),
            "icon": "date",
            "progress": None,
        }
    if module == "date":
        return {
            "eyebrow": label if custom_label else "СЕГОДНЯ",
            "value": f"{now.day} {MONTHS_GENITIVE[now.month - 1]}",
            "secondary": WEEKDAYS[now.weekday()],
            "detail": str(now.year),
            "icon": "date",
            "progress": None,
        }
    if module == "clock":
        return {
            "eyebrow": label if custom_label else "ВРЕМЯ",
            "value": format_clock(now, state.clock_24h, state.show_seconds),
            "secondary": WEEKDAYS[now.weekday()],
            "detail": f"{now.day} {MONTHS_GENITIVE[now.month - 1]}",
            "icon": "clock",
            "progress": now.second / 60.0,
        }
    if module in ("weather", "temperature"):
        temp = weather.get("temp")
        big = f"{temp}°" if temp is not None else "—"
        description = str(weather.get("description") or "Загрузка погоды…")
        city = str(weather.get("city") or state.city or "Погода")
        if module == "temperature":
            return {
                "eyebrow": label if custom_label else "ТЕМПЕРАТУРА",
                "value": big,
                "secondary": city,
                "detail": description,
                "icon": weather.get("icon") or "weather_sun",
                "progress": None,
            }
        humidity = weather.get("humidity")
        wind = weather.get("wind")
        detail = description
        if humidity is not None and wind is not None:
            detail = f"{description} · {humidity}% · {wind:.1f} м/с"
        return {
            "eyebrow": label if custom_label else city.upper(),
            "value": big,
            "secondary": description,
            "detail": detail,
            "icon": weather.get("icon") or "weather_sun",
            "progress": None,
        }
    if module == "cpu":
        percent = int(metric("cpu", "percent", 0))
        return {
            "eyebrow": label if custom_label else "ЗАГРУЗКА ЦП",
            "value": f"{percent}%",
            "secondary": "Процессор",
            "detail": f"{metric('cpu', 'cores', '—')} ядер",
            "icon": "cpu",
            "progress": percent / 100.0,
        }
    if module == "memory":
        percent = int(metric("memory", "percent", 0))
        used = float(metric("memory", "used", 0.0))
        total = float(metric("memory", "total", 0.0))
        return {
            "eyebrow": label if custom_label else "ПАМЯТЬ",
            "value": f"{percent}%",
            "secondary": "Оперативная память",
            "detail": f"{used:.1f} / {total:.1f} ГБ",
            "icon": "memory",
            "progress": percent / 100.0,
        }
    if module == "battery":
        percent = metrics.get("battery", {}).get("percent")
        return {
            "eyebrow": label if custom_label else "БАТАРЕЯ",
            "value": f"{int(percent)}%" if percent is not None else "—",
            "secondary": "Батарея",
            "detail": "Питание от сети"
            if metrics.get("battery", {}).get("plugged") else "Разряжается",
            "icon": "battery",
            "progress": (percent or 0) / 100.0,
        }
    if module == "disk":
        percent = int(metric("disk", "percent", 0))
        letter = metric("disk", "letter", "C:")
        free = float(metric("disk", "free", 0.0))
        total = float(metric("disk", "total", 0.0))
        return {
            "eyebrow": label if custom_label else f"ДИСК {letter}",
            "value": f"{percent}%",
            "secondary": f"Диск {letter}",
            "detail": f"Свободно {free:.0f} из {total:.0f} ГБ",
            "icon": "disk",
            "progress": percent / 100.0,
        }
    if module == "notes":
        body = style.notes.strip() or str(block.text).strip() or "Заметка"
        return {
            "eyebrow": label if (custom_label or style.show_label) else "",
            "value": body,
            "secondary": "",
            "detail": "",
            "icon": "text",
            "progress": None,
            "wrap": True,
        }
    if module == "text":
        body = str(block.text).strip() or style.notes.strip() or "Текст"
        return {
            "eyebrow": label if (custom_label and style.show_label) else "",
            "value": body,
            "secondary": "",
            "detail": "",
            "icon": "text",
            "progress": None,
            "wrap": True,
        }
    if module == "metric":
        value = max(0, min(100, int(block.value)))
        return {
            "eyebrow": label if custom_label else "ИНДИКАТОР",
            "value": f"{value}%",
            "secondary": "",
            "detail": "",
            "icon": "cpu",
            "progress": value / 100.0,
        }
    if module == "progress":
        value = max(0, min(100, int(block.value)))
        return {
            "eyebrow": label if custom_label else "ПРОГРЕСС",
            "value": f"{value}%",
            "secondary": "",
            "detail": "",
            "icon": "disk",
            "progress": value / 100.0,
        }
    if module == "notepad":
        body = str(block.text).strip() or "Нажмите, чтобы записать…"
        return {
            "eyebrow": label if custom_label else "БЛОКНОТ",
            "value": body,
            "secondary": "",
            "detail": "",
            "icon": "notepad",
            "progress": None,
            "wrap": True,
        }
    if module == "calculator":
        expression = setting("expression")
        result, error = calculate(expression)
        return {
            "eyebrow": label if custom_label else "КАЛЬКУЛЯТОР",
            "value": result,
            "secondary": expression or "Введите выражение",
            "detail": error or "Клик по блоку — изменить",
            "icon": "calculator",
            "progress": None,
        }
    if module == "todo":
        items = parse_todo(block.text)
        if not items:
            return {
                "eyebrow": label if custom_label else "СПИСОК ДЕЛ",
                "value": "Добавьте пункты в свойствах",
                "secondary": "",
                "detail": "",
                "icon": "todo",
                "progress": None,
                "wrap": True,
            }
        done = sum(1 for _text_value, is_done in items if is_done)
        lines = []
        for item_text, is_done in items[:5]:
            lines.append(("✓ " if is_done else "○ ") + item_text)
        return {
            "eyebrow": label if custom_label else "СПИСОК ДЕЛ",
            "value": "\n".join(lines),
            "secondary": "",
            "detail": f"{done} из {len(items)}",
            "icon": "todo",
            "progress": done / len(items),
            "wrap": True,
        }
    if module == "plans":
        items = parse_plans(block.text)
        if not items:
            return {
                "eyebrow": label if custom_label else "ПЛАНЫ НА ДЕНЬ",
                "value": "Добавьте планы в свойствах",
                "secondary": "",
                "detail": "",
                "icon": "plans",
                "progress": None,
                "wrap": True,
            }
        done = parse_plan_done(setting("done"), len(items))
        return {
            "eyebrow": label if custom_label else "ПЛАНЫ НА ДЕНЬ",
            "value": "",
            "secondary": "",
            "detail": "",
            "icon": "plans",
            "progress": len(done) / len(items),
            "plans": [(value, index in done)
                      for index, value in enumerate(items)],
            "summary": f"{len(done)}/{len(items)}",
        }
    if module == "music":
        title = setting("title").strip() or "Мой трек"
        artist = setting("artist").strip() or "Любимая музыка"
        url = setting("url").strip()
        source = music_source(setting("source", "auto"), url)
        info = runtime.get(block.id) or {}
        playing = bool(info.get("music_playing"))
        error = str(info.get("music_error") or "")
        if not url:
            detail = "Добавьте ссылку или файл в свойствах"
        elif error:
            detail = error
        elif source == "file" or is_audio_url(url):
            detail = "Играет · клик — пауза" if playing \
                else "Пауза · клик — играть"
        else:
            detail = f"{music_source_label(source)} · клик — открыть"
        icon = source if source in ("browser", "spotify", "soundcloud",
                                    "yandex", "file") else "music"
        return {
            "eyebrow": label if custom_label else "МУЗЫКА",
            "value": title,
            "secondary": artist,
            "detail": detail,
            "icon": icon,
            "progress": None,
        }
    if module == "countdown":
        target = parse_datetime(setting("target"))
        if target is None:
            return {
                "eyebrow": label if custom_label else "ДО СОБЫТИЯ",
                "value": "—",
                "secondary": "Укажите дату",
                "detail": "Формат: 31.12.2026 23:00",
                "icon": "countdown",
                "progress": None,
            }
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return {
                "eyebrow": label if custom_label else "ДО СОБЫТИЯ",
                "value": "00:00:00",
                "secondary": "Событие наступило",
                "detail": target.strftime("%d.%m.%Y %H:%M"),
                "icon": "countdown",
                "progress": 1.0,
            }
        return {
            "eyebrow": label if custom_label else "ДО СОБЫТИЯ",
            "value": format_duration(remaining),
            "secondary": target.strftime("%d.%m.%Y %H:%M"),
            "detail": "До события",
            "icon": "countdown",
            "progress": None,
        }
    if module == "stopwatch":
        info = runtime.get(block.id) or {}
        elapsed = float(info.get("stopwatch_elapsed", 0) or 0)
        running = bool(info.get("stopwatch_running"))
        return {
            "eyebrow": label if custom_label else "СЕКУНДОМЕР",
            "value": format_duration(elapsed),
            "secondary": "Идёт" if running else "Пауза",
            "detail": "Клик по блоку — старт/пауза",
            "icon": "stopwatch",
            "progress": (elapsed % 60) / 60.0,
        }
    if module == "timer":
        duration = max(1, parse_duration(setting("duration")))
        info = runtime.get(block.id) or {}
        remaining = float(info.get("timer_remaining", duration) or 0)
        running = bool(info.get("timer_running"))
        if remaining <= 0.5:
            value = "00:00:00"
            secondary = "Готово"
            progress = 0.0
        else:
            value = format_duration(remaining)
            secondary = "Идёт" if running else "Пауза"
            progress = remaining / duration
        return {
            "eyebrow": label if custom_label else "ТАЙМЕР",
            "value": value,
            "secondary": secondary,
            "detail": "Клик по блоку — старт/пауза",
            "icon": "timer",
            "progress": progress,
        }
    if module == "network":
        down = float(metric("network", "down", 0) or 0)
        up = float(metric("network", "up", 0) or 0)
        show_total = setting("show_total", "0").casefold() in (
            "1", "true", "да", "on", "yes"
        )
        if show_total:
            detail = (f"↓ {format_bytes(metric('network', 'total_down', 0))}"
                      f" · ↑ {format_bytes(metric('network', 'total_up', 0))}")
        else:
            detail = "Скорость сети"
        return {
            "eyebrow": label if custom_label else "СЕТЬ",
            "value": f"↓ {format_speed(down)}",
            "secondary": f"↑ {format_speed(up)}",
            "detail": detail,
            "icon": "network",
            "progress": None,
        }
    if module == "uptime":
        seconds = float(metric("uptime", "seconds", 0) or 0)
        boot = metric("uptime", "boot", None)
        detail = "Время работы системы"
        if isinstance(boot, (int, float)) and boot > 0:
            detail = "С " + datetime.fromtimestamp(boot).strftime(
                "%d.%m.%Y %H:%M"
            )
        return {
            "eyebrow": label if custom_label else "ВРЕМЯ РАБОТЫ",
            "value": format_uptime(seconds),
            "secondary": "Система",
            "detail": detail,
            "icon": "uptime",
            "progress": None,
        }
    if module == "processes":
        count = int(metric("processes", "count", 0) or 0)
        return {
            "eyebrow": label if custom_label else "ПРОЦЕССЫ",
            "value": str(count),
            "secondary": "процессов",
            "detail": "Запущено в системе",
            "icon": "processes",
            "progress": None,
        }
    if module == "quote":
        author = setting("author").strip()
        if str(block.text).strip():
            body = f"«{str(block.text).strip()}»"
            if author:
                body += f"\n— {author}"
        else:
            quote_text, default_author = quote_of_day(now)
            body = f"«{quote_text}»\n— {author or default_author}"
        return {
            "eyebrow": label if custom_label else "ЦИТАТА ДНЯ",
            "value": body,
            "secondary": "",
            "detail": "",
            "icon": "quote",
            "progress": None,
            "wrap": True,
        }
    if module == "worldclock":
        entries = parse_worldclock(setting("cities"))
        if not entries:
            return {
                "eyebrow": label if custom_label else "МИРОВЫЕ ЧАСЫ",
                "value": now.strftime("%H:%M"),
                "secondary": "Укажите города",
                "detail": "Формат: Москва +3",
                "icon": "worldclock",
                "progress": None,
            }
        first_name, first_zone = entries[0]
        rest = entries[1:]
        detail = " · ".join(
            f"{name} {time_in_zone(zone, now)}" for name, zone in rest
        ) or "Клик по блоку не требуется"
        return {
            "eyebrow": label if custom_label else "МИРОВЫЕ ЧАСЫ",
            "value": time_in_zone(first_zone, now),
            "secondary": first_name,
            "detail": detail,
            "icon": "worldclock",
            "progress": None,
        }
    if module == "user":
        values = build_placeholders(state, data, now)
        caption = apply_placeholders(setting("caption"), values).strip()
        body = apply_placeholders(setting("value"), values).strip() or "—"
        subtitle = apply_placeholders(setting("subtitle"), values).strip()
        details = apply_placeholders(setting("details"), values).strip()
        icon = setting("icon", "custom").strip() or "custom"
        show_progress = setting("show_progress", "0").casefold() in (
            "1", "true", "да", "on", "yes"
        )
        try:
            progress = max(0, min(100, int(float(
                setting("progress", "0").replace(",", ".")
            )))) / 100.0
        except ValueError:
            progress = 0.0
        return {
            "eyebrow": caption or custom_label or "СВОЙ МОДУЛЬ",
            "value": body,
            "secondary": subtitle,
            "detail": details,
            "icon": icon,
            "progress": progress if show_progress else None,
        }
    return {
        "eyebrow": label,
        "value": str(block.text or "—"),
        "secondary": "",
        "detail": "",
        "icon": "text",
        "progress": None,
        "wrap": True,
    }


def _paint_block(p: QPainter, rect: QRectF, block: WidgetBlock,
                 state: WidgetState, data: dict | None) -> None:
    """Рисует один блок со всеми вложенными настройками."""
    style = block.style
    if rect.width() < 8 or rect.height() < 8:
        return

    text = _color(style.text_color, "#ffffff")
    accent = _color(style.accent, "#8ab4ff")
    radius = max(0.0, min(float(style.radius), rect.width() / 2,
                          rect.height() / 2))
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    # Внешняя тень
    if style.shadow_enabled and style.shadow_alpha > 0:
        base = _color(style.shadow_color, "#000000")
        blur = max(1, int(style.shadow_blur))
        steps = max(2, min(7, blur // 3 + 2))
        offset = QPointF(style.shadow_offset_x, style.shadow_offset_y)
        p.setPen(Qt.PenStyle.NoPen)
        for step in range(steps, 0, -1):
            spread = blur * step / steps
            alpha = int(style.shadow_alpha * (0.10 + 0.28 * (1 - step / steps)))
            p.setBrush(_with_alpha(base, alpha))
            r = rect.translated(offset).adjusted(-spread, -spread,
                                                spread, spread)
            p.drawRoundedRect(r, radius + spread, radius + spread)

    # Свечение
    if style.glow_enabled and style.glow_alpha > 0:
        glow = max(1, int(style.glow_radius))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for factor, width in ((0.18, glow), (0.30, glow * 0.55)):
            p.setPen(QPen(_with_alpha(_color(style.glow_color, style.accent),
                                      int(style.glow_alpha * factor)),
                          max(1.0, width / 2)))
            p.drawRoundedRect(rect.adjusted(-width / 4, -width / 4,
                                             width / 4, width / 4),
                              radius + width / 4, radius + width / 4)

    # Фон
    bg = _color(style.bg, "#ffffff")
    bg2 = _color(style.bg2, "#dfe7f5")
    alpha = max(0, min(255, int(style.bg_alpha)))
    if style.gradient:
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, _with_alpha(bg, alpha))
        grad.setColorAt(1.0, _with_alpha(bg2, alpha))
        p.setBrush(grad)
    else:
        p.setBrush(_with_alpha(bg, alpha))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(rect, radius, radius)

    # Рамка
    if style.border_width > 0 and style.border_alpha > 0:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(_color(style.border_color, "#ffffff"),
                                  style.border_alpha),
                      float(style.border_width)))
        inset = style.border_width / 2
        p.drawRoundedRect(rect.adjusted(inset, inset, -inset, -inset),
                          radius, radius)

    p.save()
    p.setClipPath(path)
    pad = max(0.0, min(float(style.padding), rect.width() / 3,
                       rect.height() / 3))
    inner = rect.adjusted(pad, pad, -pad, -pad)
    texts = _block_texts(block, state, data)
    scale = max(0.5, min(2.0, style.font_scale / 100.0))
    align_name = style.align if style.align in ("left", "center", "right") \
        else "left"
    align_h = {
        "left": Qt.AlignmentFlag.AlignLeft,
        "center": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignRight,
    }[align_name]
    align_flag = align_h | Qt.AlignmentFlag.AlignVCenter

    icon_kind = texts.get("icon") or MODULE_ICONS.get(block.module, "cpu")
    icon_w = 0.0
    if style.show_icon and inner.width() > 66 and inner.height() > 34:
        icon_size = max(16.0, min(inner.height() * 0.62,
                                  inner.width() * 0.30, 42.0))
        icon_rect = QRectF(inner.left(),
                           inner.top() + (inner.height() - icon_size) / 2,
                           icon_size, icon_size)
        progress = texts.get("progress")
        if progress is not None and icon_size >= 32:
            ring = max(1.5, icon_size * 0.06)
            rr = icon_rect.adjusted(-ring, -ring, ring, ring)
            _metric_ring(p, rr, progress, accent,
                         _with_alpha(text, 36), max(1.5, icon_size * 0.045))
        p.setBrush(_with_alpha(accent, 38))
        p.setPen(QPen(_with_alpha(accent, 90), 1.0))
        p.drawEllipse(icon_rect)
        if str(icon_kind).startswith("weather_"):
            icon_color = _weather_icon_color(str(icon_kind), accent, text)
        elif text.lightness() < 128:
            # Светлая тема: акцент нужно затемнить, иначе иконка теряется.
            icon_color = accent.darker(135)
        else:
            icon_color = accent.lighter(118)
        draw_kind_icon(p, icon_rect.adjusted(icon_size * 0.24,
                                             icon_size * 0.24,
                                             -icon_size * 0.24,
                                             -icon_size * 0.24),
                       str(icon_kind), icon_color,
                       texts.get("progress") or 0.7)
        icon_w = icon_size + max(6.0, inner.width() * 0.045)

    text_rect = QRectF(inner.left() + icon_w, inner.top(),
                       max(10.0, inner.width() - icon_w), inner.height())
    progress = texts.get("progress")
    bar_h = 0.0
    if progress is not None and text_rect.height() > 30:
        bar_h = max(2.5, min(5.0, text_rect.height() * 0.07))
        bar_rect = QRectF(text_rect.left(), text_rect.bottom() - bar_h,
                          text_rect.width(), bar_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_with_alpha(text, 34))
        p.drawRoundedRect(bar_rect, bar_h / 2, bar_h / 2)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(bar_rect.left(), bar_rect.top(),
                                 bar_rect.width() * max(0.0, min(1.0, progress)),
                                 bar_h),
                          bar_h / 2, bar_h / 2)
        text_rect.setBottom(bar_rect.top() - max(2.0, bar_h))

    eyebrow = str(texts.get("eyebrow") or "")
    value = str(texts.get("value") or "")
    secondary = str(texts.get("secondary") or "")
    detail = str(texts.get("detail") or "")
    wrap = bool(texts.get("wrap"))

    if texts.get("plans") is not None:
        _paint_plan_rows(p, text_rect, block, texts, scale)
        p.restore()
        return

    if wrap:
        body_rect = QRectF(text_rect)
        if eyebrow and style.show_label and text_rect.height() >= 38:
            eyebrow_h = max(10.0, min(15.0, text_rect.height() * 0.20))
            _draw_text(p, QRectF(text_rect.left(), text_rect.top(),
                                 text_rect.width(), eyebrow_h),
                       eyebrow, _font(max(7.0, min(10.0 * scale,
                                                  eyebrow_h * 0.78)),
                                      QFont.Weight.DemiBold),
                       _with_alpha(text, 160), align_flag)
            body_rect.setTop(text_rect.top() + eyebrow_h + 1)
        p.setFont(_font(max(8.0, min(15.0, body_rect.height() * 0.30 * scale)),
                        QFont.Weight.Normal))
        p.setPen(_with_alpha(text, 225))
        p.drawText(body_rect, int(align_h | Qt.AlignmentFlag.AlignTop
                                 | Qt.TextFlag.TextWordWrap), value)
        p.restore()
        return

    show_label = style.show_label and bool(eyebrow)
    eyebrow_h = 0.0
    if show_label and text_rect.height() >= 38:
        eyebrow_h = max(9.0, min(15.0, text_rect.height() * 0.19))
        _draw_text(p, QRectF(text_rect.left(), text_rect.top(),
                             text_rect.width(), eyebrow_h),
                   eyebrow, _font(max(7.0, min(9.5 * scale,
                                              eyebrow_h * 0.78)),
                                  QFont.Weight.DemiBold),
                   _with_alpha(text, 155), align_flag)

    body_top = text_rect.top() + eyebrow_h
    body_bottom = text_rect.bottom()
    body_h = max(10.0, body_bottom - body_top)

    detail_h = 0.0
    secondary_h = 0.0
    if detail and body_h >= 52:
        detail_h = max(10.0, min(13.0, body_h * 0.20))
    if secondary and body_h - detail_h >= 32:
        secondary_h = max(11.0, min(15.0, body_h * 0.30))
    value_h = max(12.0, body_h - detail_h - secondary_h)

    value_rect = QRectF(text_rect.left(), body_top,
                        text_rect.width(), value_h)
    big_font = _fit_font(
        value,
        max_px=max(10.0, min(value_h * 0.90,
                             (text_rect.width() / max(1.0, len(value))) * 1.75,
                             64.0) * scale),
        min_px=max(8.0, min(16.0, value_h * 0.52 * scale)),
        width=max(20.0, value_rect.width()),
        weight=QFont.Weight.DemiBold,
    )
    _draw_text(p, value_rect, value, big_font, text, align_flag)

    y = body_top + value_h
    if secondary_h > 0:
        _draw_text(p, QRectF(text_rect.left(), y, text_rect.width(),
                             secondary_h),
                   secondary, _font(max(7.0, min(11.5 * scale,
                                                  secondary_h * 0.78)),
                                    QFont.Weight.Medium),
                   _with_alpha(text, 205),
                   align_h | Qt.AlignmentFlag.AlignTop)
        y += secondary_h
    if detail_h > 0:
        _draw_text(p, QRectF(text_rect.left(), y, text_rect.width(),
                             detail_h),
                   detail, _font(max(6.5, min(9.5 * scale,
                                              detail_h * 0.78)),
                                 QFont.Weight.Normal),
                   _with_alpha(text, 150),
                   align_h | Qt.AlignmentFlag.AlignTop)
    p.restore()


def _paint_custom(p: QPainter, card: QRectF, state: WidgetState,
                  data: dict | None) -> None:
    """Рисует все блоки составного виджета."""
    blocks = iter_widget_blocks(state, card)
    if not blocks:
        text = _color(state.style.text, "#ffffff")
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(text, 48), 1.4, Qt.PenStyle.DashLine))
        inner = card.adjusted(12, 12, -12, -12)
        p.drawRoundedRect(inner, 14, 14)
        p.setFont(_font(max(9.0, min(14.0, inner.height() * 0.12)),
                        QFont.Weight.Medium))
        p.setPen(_with_alpha(text, 120))
        p.drawText(inner, int(Qt.AlignmentFlag.AlignCenter
                              | Qt.TextFlag.TextWordWrap),
                   "Перетащите модули из палитры\nна эту основу")
        p.restore()
        return

    p.save()
    clip = QPainterPath()
    radius = max(0.0, min(float(state.style.corner_radius),
                          card.width() / 2, card.height() / 2))
    clip.addRoundedRect(card, radius, radius)
    p.setClipPath(clip)
    by_id = {block.id: (block, rect) for block, rect in blocks}
    for block, rect in blocks:
        p.save()
        # Вложенный блок не должен вылезать за внутреннюю область родителя.
        parent_id = block.parent_id
        while parent_id:
            parent, parent_rect = by_id.get(parent_id, (None, None))
            if parent is None or parent_rect is None:
                break
            inner = block_content_rect(parent, parent_rect)
            parent_radius = max(0.0, min(float(parent.style.radius),
                                         inner.width() / 2,
                                         inner.height() / 2))
            parent_clip = QPainterPath()
            parent_clip.addRoundedRect(inner, parent_radius, parent_radius)
            p.setClipPath(parent_clip)
            parent_id = parent.parent_id
        _paint_block(p, rect, block, state, data)
        p.restore()
    p.restore()


def paint_widget(p: QPainter, rect, state: WidgetState, data: dict | None = None,
                 hovered: bool = False) -> None:
    """Рисует готовый виджет в заданном прямоугольнике."""
    data = data or sample_data(state.kind, state)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    outer = QRectF(rect)
    card = widget_card_rect(outer)
    if card.width() <= 10 or card.height() <= 10:
        p.restore()
        return

    bg = _color(state.style.bg, "#10161f")
    accent = _color(state.style.accent, "#5cc8ff")
    text = _color(state.style.text, "#ffffff")
    alpha = max(0, min(255, int(state.style.bg_alpha)))
    radius = max(0, min(float(state.style.corner_radius),
                        card.height() / 2.0, card.width() / 2.0))
    light = bg.lightness() > 165

    _draw_shadow(p, card, radius, light)
    _draw_card(p, card, radius, bg, accent, text,
               state.style.template, alpha)

    if state.style.opacity < 255:
        # Прозрачность окна уже применяется к top-level окну; для предпросмотра
        # дополнительно не затемняем содержимое.
        pass

    if hovered:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 150),
                      1.4))
        p.drawRoundedRect(card.adjusted(1, 1, -1, -1), radius, radius)

    if state.kind == "custom":
        _paint_custom(p, card, state, data)
        p.restore()
        return

    # ------------------------------------------------------------------ layout
    pad = max(12.0, min(card.width(), card.height()) * 0.09)
    detail_h = max(11.0, card.height() * 0.085)
    detail_y = card.bottom() - pad - detail_h
    gap = max(2.0, card.height() * 0.018)
    upper_top = card.top() + pad
    upper_bottom = detail_y - gap
    upper_h = max(20.0, upper_bottom - upper_top)

    show_icon = bool(state.style.show_icon)
    badge = 0.0
    badge_rect = QRectF()
    text_x = card.left() + pad
    if show_icon:
        badge = min(upper_h * 0.92, card.width() * 0.28,
                    card.height() * 0.43)
        badge = max(32.0, badge)
        badge_rect = QRectF(card.left() + pad,
                            upper_top + (upper_h - badge) / 2.0,
                            badge, badge)
        text_x = badge_rect.right() + max(10.0, pad * 0.7)
    text_w = max(20.0, card.right() - pad - text_x)
    text_rect = QRectF(text_x, upper_top, text_w, upper_h)

    texts = _widget_texts(state, data)
    show_label = bool(state.style.show_label)
    use_text_shadow = state.style.template == "minimal"

    def draw_text(rect: QRectF, value: str, font: QFont, color: QColor,
                  align: Qt.AlignmentFlag) -> None:
        if use_text_shadow:
            _draw_text(p, rect.translated(1.0, 1.5), value, font,
                       QColor(0, 0, 0, 130), align)
        _draw_text(p, rect, value, font, color, align)

    # Иконка + прогресс-кольцо
    if show_icon:
        ring_space = max(3.0, badge * 0.075)
        ring_rect = badge_rect.adjusted(-ring_space, -ring_space,
                                        ring_space, ring_space)
        fraction = texts.get("progress")
        if fraction is not None:
            _metric_ring(p, ring_rect, fraction, accent,
                         QColor(text.red(), text.green(), text.blue(), 40),
                         max(2.5, badge * 0.045))

        p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 42))
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 92),
                      1.1))
        p.drawEllipse(badge_rect)

        icon = texts.get("icon", state.kind)
        if icon.startswith("weather_"):
            icon_color = _weather_icon_color(icon, accent, text)
        else:
            icon_color = accent.lighter(120) if not light else accent.darker(108)
        inset = badge * 0.28
        draw_kind_icon(p, badge_rect.adjusted(inset, inset, -inset, -inset),
                       icon, icon_color,
                       (texts.get("progress") or 0.7))

    # Текстовая колонка
    scale = max(0.7, min(1.4, state.style.font_scale / 100.0))
    if show_label:
        eyebrow_h = upper_h * 0.20
        value_h = upper_h * 0.52
        secondary_h = upper_h * 0.28
        eyebrow_rect = QRectF(text_x, upper_top, text_w, eyebrow_h)
        value_rect = QRectF(text_x, upper_top + eyebrow_h, text_w, value_h)
        secondary_rect = QRectF(text_x, upper_top + eyebrow_h + value_h,
                                text_w, secondary_h)
    else:
        value_rect = QRectF(text_x, upper_top, text_w, upper_h)
        eyebrow_rect = QRectF()
        secondary_rect = QRectF()

    if show_label:
        eyebrow_font = _font(max(8.0, upper_h * 0.105 * scale),
                             QFont.Weight.DemiBold,
                             max(0.6, upper_h * 0.006))
        draw_text(eyebrow_rect, texts["eyebrow"], eyebrow_font,
                  QColor(text.red(), text.green(), text.blue(), 165),
                  Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    big_text = texts["big"]
    big_font = _fit_font(
        big_text,
        max_px=min(value_rect.height() * 0.92,
                   card.height() * 0.34 * scale),
        min_px=max(12.0, card.height() * 0.12),
        width=value_rect.width(),
        weight=QFont.Weight.DemiBold,
    )
    draw_text(value_rect, big_text, big_font, text,
              Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    if show_label:
        secondary_font = _font(max(8.0, upper_h * 0.125 * scale),
                               QFont.Weight.Medium)
        draw_text(secondary_rect, texts["secondary"], secondary_font,
                  QColor(text.red(), text.green(), text.blue(), 205),
                  Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    detail_font = _font(max(8.0, card.height() * 0.077 * scale),
                        QFont.Weight.Normal)
    detail_color = QColor(text.red(), text.green(), text.blue(), 170)
    draw_text(QRectF(card.left() + pad, detail_y,
                     card.width() - pad * 2, detail_h),
              texts["detail"], detail_font, detail_color,
              Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    # Маленькая акцентная черта сверху — фирменная деталь Gridly
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 190))
    line_w = max(18.0, card.width() * 0.075)
    p.drawRoundedRect(QRectF(card.left() + pad, card.top() + 8,
                             line_w, 2.2), 1.1, 1.1)
    p.restore()


class WidgetPreview:
    """Общие функции предпросмотра вынесены сюда для читаемости."""

    @staticmethod
    def paint(p: QPainter, rect, state: WidgetState, data: dict | None,
              dark: bool) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(rect)

        base = QColor("#1b2230") if dark else QColor("#e9eef5")
        base2 = QColor("#0d131d") if dark else QColor("#f8fafc")
        grad = QLinearGradient(outer.topLeft(), outer.bottomRight())
        grad.setColorAt(0.0, base)
        grad.setColorAt(1.0, base2)
        p.setBrush(grad)
        p.setPen(QPen(QColor(255, 255, 255, 20) if dark
                      else QColor(0, 0, 0, 20), 1.0))
        p.drawRoundedRect(outer, 14, 14)

        # Лёгкая «сетка рабочего стола»
        p.save()
        path = QPainterPath()
        path.addRoundedRect(outer, 14, 14)
        p.setClipPath(path)
        dot = QColor(255, 255, 255, 16) if dark else QColor(0, 0, 0, 14)
        p.setPen(QPen(dot, 1.0))
        step = 18
        y = outer.top() + 12
        while y < outer.bottom():
            x = outer.left() + 12
            while x < outer.right():
                p.drawPoint(QPointF(x, y))
                x += step
            y += step
        p.restore()

        # Вписываем виджет с сохранением пропорций
        ratio = max(0.5, state.width / max(1, state.height))
        avail = outer.adjusted(18, 18, -18, -18)
        target_w = avail.width()
        target_h = target_w / ratio
        if target_h > avail.height():
            target_h = avail.height()
            target_w = target_h * ratio
        target = QRectF(0, 0, target_w, target_h)
        target.moveCenter(outer.center())
        paint_widget(p, target, state, data, hovered=False)
        p.restore()
