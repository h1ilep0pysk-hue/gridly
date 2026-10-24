"""
core/module_data.py
Логика мини-модулей Gridly: калькулятор, даты, таймеры, цитаты,
мировые часы и подстановки для no-code модуля «Свой модуль».

Модуль не зависит от Qt и от модели виджетов — его можно тестировать
отдельно и использовать в предпросмотре без запуска приложения.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
WEEKDAYS = [
    "Понедельник", "Вторник", "Среда", "Четверг",
    "Пятница", "Суббота", "Воскресенье",
]

QUOTES: list[tuple[str, str]] = [
    ("Простота — высшая степень изящества.", "Леонардо да Винчи"),
    ("Дорогу осилит идущий.", "Латинская пословица"),
    ("Знание — сила.", "Фрэнсис Бэкон"),
    ("Терпение и труд всё перетрут.", "Русская пословица"),
    ("Не откладывай на завтра то, что можно сделать сегодня.",
     "Бенджамин Франклин"),
    ("Кто не идёт вперёд, тот идёт назад.", "Иоганн Вольфганг Гёте"),
    ("Нет ничего постояннее перемен.", "Гераклит"),
    ("Хорошее начало — половина дела.", "Платон"),
    ("Повторение — мать учения.", "Русская пословица"),
    ("Краткость — сестра таланта.", "Антон Чехов"),
    ("Время — лучший учитель.", "Латинская пословица"),
    ("Свет разума — в знаниях.", "Восточная мудрость"),
    ("Счастье — это путь, а не пункт назначения.", "Афоризм"),
    ("Маленькие шаги каждый день ведут к большим переменам.",
     "Афоризм"),
]

# Города для модуля «Мировые часы». Если после города не указано
# смещение, используется настоящая часовая зона с переходом на летнее время.
CITY_ZONES: dict[str, str] = {
    "москва": "Europe/Moscow",
    "санкт-петербург": "Europe/Moscow",
    "питер": "Europe/Moscow",
    "казань": "Europe/Moscow",
    "минск": "Europe/Minsk",
    "киев": "Europe/Kyiv",
    "алматы": "Asia/Almaty",
    "новосибирск": "Asia/Novosibirsk",
    "екатеринбург": "Asia/Yekaterinburg",
    "владивосток": "Asia/Vladivostok",
    "лондон": "Europe/London",
    "берлин": "Europe/Berlin",
    "париж": "Europe/Paris",
    "рим": "Europe/Rome",
    "мадрид": "Europe/Madrid",
    "стамбул": "Europe/Istanbul",
    "дубай": "Asia/Dubai",
    "нью-йорк": "America/New_York",
    "лос-анджелес": "America/Los_Angeles",
    "чикаго": "America/Chicago",
    "торонто": "America/Toronto",
    "сан-паулу": "America/Sao_Paulo",
    "токио": "Asia/Tokyo",
    "пекин": "Asia/Shanghai",
    "сеул": "Asia/Seoul",
    "сингапур": "Asia/Singapore",
    "дели": "Asia/Kolkata",
    "сидней": "Australia/Sydney",
}

USER_PLACEHOLDERS: tuple[tuple[str, str], ...] = (
    ("{time}", "текущее время"),
    ("{date}", "дата"),
    ("{weekday}", "день недели"),
    ("{greeting}", "приветствие"),
    ("{cpu}", "загрузка процессора"),
    ("{memory}", "оперативная память"),
    ("{battery}", "заряд батареи"),
    ("{disk}", "занятость диска"),
    ("{city}", "город погоды"),
    ("{temp}", "температура"),
    ("{uptime}", "время работы системы"),
    ("{processes}", "число процессов"),
    ("{net_down}", "скорость скачивания"),
    ("{net_up}", "скорость отдачи"),
)


class CalculatorError(ValueError):
    """Понятная пользователю ошибка вычисления."""


_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS = {
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTANTS = {
    "pi": math.pi,
    "π": math.pi,
    "e": math.e,
}


def normalize_expression(text: str) -> str:
    """Заменяет привычные знаки калькулятора на понятные Python."""
    value = str(text or "").strip()
    value = (value.replace("×", "*").replace("÷", "/")
             .replace("−", "-").replace("—", "-")
             .replace("^", "**"))
    # Десятичная запятая: 2,5 + 1 → 2.5 + 1
    value = re.sub(r"(?<=\d),(?=\d)", ".", value)
    return value.strip()


def _format_number(value: float) -> str:
    if not math.isfinite(value):
        raise CalculatorError("Слишком большое число")
    if abs(value) < 1e-12:
        return "0"
    if abs(value) >= 1e12:
        text = f"{value:.6g}"
    elif abs(value - round(value)) < 1e-9:
        text = f"{int(round(value)):,}".replace(",", " ")
    else:
        text = f"{value:.8f}".rstrip("0").rstrip(".")
        if "." in text:
            whole, fraction = text.split(".")
            whole = f"{int(whole):,}".replace(",", " ")
            text = f"{whole},{fraction}"
        else:
            text = text.replace(".", ",")
    return text.replace(".", ",")


def _eval_node(node: ast.AST, depth: int = 0) -> float:
    if depth > 40:
        raise CalculatorError("Слишком сложное выражение")
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)):
            raise CalculatorError("Неподдерживаемое значение")
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError("Неподдерживаемая операция")
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 64:
            raise CalculatorError("Слишком большая степень")
        return float(op(left, right))
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise CalculatorError("Неподдерживаемая операция")
        return float(op(_eval_node(node.operand, depth + 1)))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise CalculatorError("Неподдерживаемая функция")
        func = _FUNCTIONS.get(node.func.id.lower())
        if func is None:
            raise CalculatorError(f"Неизвестная функция: {node.func.id}")
        if len(node.args) > 4:
            raise CalculatorError("Слишком много аргументов")
        args = [_eval_node(arg, depth + 1) for arg in node.args]
        return float(func(*args))
    if isinstance(node, ast.Name):
        constant = _CONSTANTS.get(node.id.lower())
        if constant is None:
            raise CalculatorError(f"Неизвестное имя: {node.id}")
        return float(constant)
    raise CalculatorError("Неподдерживаемое выражение")


def calculate(expression: str) -> tuple[str, str | None]:
    """Безопасно вычисляет выражение.

    Возвращает (результат, ошибка). Ошибка равна None при успехе.
    """
    source = normalize_expression(expression)
    if not source:
        return "0", None
    if len(source) > 300:
        return "—", "Слишком длинное выражение"
    try:
        tree = ast.parse(source, mode="eval")
        value = _eval_node(tree)
        return _format_number(value), None
    except CalculatorError as exc:
        return "—", str(exc)
    except ZeroDivisionError:
        return "—", "Деление на ноль"
    except (SyntaxError, ValueError, TypeError, OverflowError):
        return "—", "Проверьте выражение"


def parse_datetime(text: str, now: datetime | None = None) -> datetime | None:
    """Разбирает дату/время в нескольких привычных форматах."""
    value = str(text or "").strip()
    if not value:
        return None
    now = now or datetime.now()
    formats = (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%d.%m %H:%M",
        "%d.%m",
        "%H:%M",
    )
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":
            parsed = now.replace(hour=parsed.hour, minute=parsed.minute,
                                 second=0, microsecond=0)
            if parsed <= now:
                parsed += timedelta(days=1)
        elif fmt == "%d.%m":
            parsed = parsed.replace(year=now.year)
            if parsed.date() < now.date():
                parsed = parsed.replace(year=now.year + 1)
        elif fmt == "%d.%m %H:%M":
            parsed = parsed.replace(year=now.year)
            if parsed < now:
                parsed = parsed.replace(year=now.year + 1)
        return parsed
    return None


def format_duration(seconds: float) -> str:
    """Форматирует длительность как 03:04:05 или 2 д 03:04:05."""
    total = max(0, int(round(float(seconds or 0))))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} д {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_uptime(seconds: float) -> str:
    total = max(0, int(float(seconds or 0)))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} д {hours:02d}:{minutes:02d}"
    return f"{hours:02d}:{minutes:02d}"


def parse_duration(text: str, fallback: int = 300) -> int:
    """Понимает «300», «5 мин», «1 ч 30 мин», «01:30»."""
    value = str(text or "").strip().lower().replace(",", ".")
    if not value:
        return fallback
    if re.fullmatch(r"\d+(?:\.\d+)?", value):
        return max(1, int(float(value)))
    if ":" in value:
        parts = value.split(":")
        try:
            numbers = [int(part) for part in parts[:3]]
        except ValueError:
            return fallback
        if len(numbers) == 2:
            total = numbers[0] * 60 + numbers[1]
        elif len(numbers) == 3:
            total = numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
        else:
            return fallback
        return max(1, total)
    total = 0.0
    found = False
    for pattern, factor in (
            (r"(\d+(?:\.\d+)?)\s*(?:ч|час)", 3600),
            (r"(\d+(?:\.\d+)?)\s*(?:мин|м)", 60),
            (r"(\d+(?:\.\d+)?)\s*(?:с|сек)", 1)):
        match = re.search(pattern, value)
        if match:
            total += float(match.group(1)) * factor
            found = True
    if not found:
        return fallback
    return max(1, int(total))


def format_speed(bytes_per_second: float) -> str:
    value = max(0.0, float(bytes_per_second or 0))
    if value < 1024:
        return f"{int(value)} Б/с"
    if value < 1024 ** 2:
        return f"{value / 1024:.0f} КБ/с"
    if value < 1024 ** 3:
        text = f"{value / 1024 ** 2:.1f}".replace(".", ",")
        return f"{text} МБ/с"
    text = f"{value / 1024 ** 3:.1f}".replace(".", ",")
    return f"{text} ГБ/с"


def format_bytes(value: float) -> str:
    size = max(0.0, float(value or 0))
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            if unit == "Б":
                return f"{int(size)} {unit}"
            text = f"{size:.1f}".replace(".", ",")
            return f"{text} {unit}"
        size /= 1024
    return "0 Б"


def parse_todo(text: str) -> list[tuple[str, bool]]:
    """Разбирает список дел: [x], [ ], ✓, ☐, обычные строки."""
    items: list[tuple[str, bool]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        done = False
        if re.match(r"^\[[xXхХ]\]\s*", line):
            done = True
            line = re.sub(r"^\[[xXхХ]\]\s*", "", line)
        elif re.match(r"^\[\s*\]\s*", line):
            line = re.sub(r"^\[\s*\]\s*", "", line)
        elif line.startswith(("✓", "☑", "✔")):
            done = True
            line = line[1:].strip()
        elif line.startswith(("☐", "○", "•", "-", "*")):
            line = line[1:].strip()
        if line:
            items.append((line, done))
    return items


def parse_plans(text: str) -> list[str]:
    """Разбирает планы на день: по одному пункту на строку."""
    items: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^(?:[-*•✓☐☑✔]|\[\s*[xXхХ]?\s*\])\s*", "", line)
        line = re.sub(r"^\d+[.)]\s+", "", line)
        if line:
            items.append(line)
    return items


def parse_plan_done(value: str, count: int) -> set[int]:
    """Разбирает отметки выполненных планов: «0,2» или «0 2»."""
    done: set[int] = set()
    for token in re.split(r"[,;\s]+", str(value or "").strip()):
        if not token:
            continue
        try:
            index = int(token)
        except ValueError:
            continue
        if 0 <= index < count:
            done.add(index)
    return done


def format_plan_done(indices: set[int] | list[int]) -> str:
    return ",".join(str(index) for index in sorted(set(indices)))


def toggle_plan_done(value: str, index: int, count: int) -> str:
    done = parse_plan_done(value, count)
    if index in done:
        done.remove(index)
    elif 0 <= index < count:
        done.add(index)
    return format_plan_done(done)


AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".ogg", ".oga", ".flac", ".m4a", ".aac", ".opus",
    ".wma", ".aiff", ".aif",
}

MUSIC_SOURCES: dict[str, str] = {
    "auto": "Авто",
    "browser": "Браузер",
    "spotify": "Spotify",
    "soundcloud": "SoundCloud",
    "yandex": "Яндекс Музыка",
    "file": "Локальный файл",
}


def normalize_music_url(text: str) -> str:
    """Приводит ссылку или путь к виду, понятному QDesktopServices."""
    value = str(text or "").strip().strip('"').strip("'").strip()
    if not value:
        return ""
    if value.lower().startswith("file://"):
        return value
    if not re.match(r"^[a-zA-Z]:[\\/]", value) and \
            re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):
        return value
    path = Path(value)
    try:
        if path.exists():
            return path.resolve().as_uri()
    except OSError:
        pass
    if path.suffix.lower() in AUDIO_EXTENSIONS:
        return value
    lowered = value.lower()
    if lowered.startswith(("www.", "soundcloud.com/", "open.spotify.com/",
                           "music.yandex.", "music.yandex.ru/",
                           "yandex.ru/music", "yandex.com/music")):
        return "https://" + value
    if "." in value.split("/", 1)[0] and " " not in value:
        return "https://" + value
    return value


def music_source(source: str, url: str) -> str:
    """Определяет сервис: auto, browser, spotify, soundcloud, yandex, file."""
    selected = str(source or "auto").strip().lower()
    if selected in MUSIC_SOURCES and selected != "auto":
        return selected
    value = str(url or "").strip()
    lowered = value.lower()
    if not value:
        return "browser"
    if lowered.startswith("spotify:") or "open.spotify.com" in lowered:
        return "spotify"
    if "soundcloud.com" in lowered:
        return "soundcloud"
    if ("music.yandex." in lowered or "yandex.ru/music" in lowered
            or "yandex.com/music" in lowered):
        return "yandex"
    if lowered.startswith("file://"):
        return "file"
    try:
        if Path(value).exists():
            return "file"
    except OSError:
        pass
    if re.match(r"^[a-zA-Z]:[\\/]", value):
        return "file"
    return "browser"


def music_source_label(source: str) -> str:
    return MUSIC_SOURCES.get(source, MUSIC_SOURCES["browser"])


def browser_music_url(url: str) -> str:
    """Веб-адрес для ссылок вида spotify:track:…"""
    value = str(url or "").strip()
    match = re.match(r"^spotify:(track|album|playlist|artist):(.+)$",
                     value, re.IGNORECASE)
    if match:
        return f"https://open.spotify.com/{match.group(1)}/{match.group(2)}"
    return normalize_music_url(value)


def is_audio_url(url: str) -> bool:
    """Можно ли проиграть ссылку/файл встроенным плеером."""
    value = str(url or "").strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("file://"):
        path_text = lowered[7:]
    else:
        try:
            path_text = urlsplit(lowered).path
        except ValueError:
            path_text = lowered
    suffix = Path(path_text).suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return True
    try:
        path = Path(value)
        return path.exists() and path.is_file()
    except OSError:
        return False


def quote_of_day(now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.now()
    index = now.date().toordinal() % len(QUOTES)
    return QUOTES[index]


def parse_worldclock(text: str) -> list[tuple[str, Any]]:
    """Разбирает строки «Москва +3», «Лондон» или «Токио=9»."""
    result: list[tuple[str, Any]] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        name = line
        offset_text = ""
        if "=" in line:
            name, offset_text = line.rsplit("=", 1)
        else:
            match = re.match(
                r"^(.*?)\s+(?:utc|gmt)?\s*([+-]?\d{1,2}(?:[.,]\d{1,2})?)$",
                line, re.IGNORECASE,
            )
            if match:
                name, offset_text = match.group(1), match.group(2)
        name = name.strip()
        if not name:
            continue
        zone = None
        if offset_text.strip():
            try:
                hours = float(offset_text.strip().replace(",", "."))
                zone = timezone(timedelta(hours=hours))
            except (ValueError, OverflowError):
                zone = None
        if zone is None:
            zone_name = CITY_ZONES.get(name.casefold())
            if zone_name:
                try:
                    zone = ZoneInfo(zone_name)
                except Exception:
                    zone = None
        if zone is not None:
            result.append((name, zone))
    return result[:4]


def time_in_zone(zone, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if now.tzinfo is None:
        now = now.astimezone()
    try:
        return now.astimezone(zone).strftime("%H:%M")
    except Exception:
        return "--:--"


def _greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Доброе утро"
    if 12 <= hour < 18:
        return "Добрый день"
    if 18 <= hour < 23:
        return "Добрый вечер"
    return "Доброй ночи"


def build_placeholders(state, data: dict | None,
                       now: datetime | None = None) -> dict[str, str]:
    """Значения для подстановок no-code модуля."""
    now = now or datetime.now()
    data = data or {}
    metrics = data.get("metrics") or {}
    weather = data.get("weather") or {}

    def metric(name: str, key: str, fallback):
        block_data = metrics.get(name) or {}
        value = block_data.get(key)
        return fallback if value is None else value

    battery_percent = (metrics.get("battery") or {}).get("percent")
    temp = weather.get("temp")
    seconds = state.show_seconds if state is not None else False
    time_fmt = "%H:%M:%S" if seconds else "%H:%M"
    uptime_seconds = metric("uptime", "seconds", 0)
    city = weather.get("city") or getattr(state, "city", "") or "Москва"

    values = {
        "time": now.strftime(time_fmt),
        "date": now.strftime("%d.%m.%Y"),
        "weekday": WEEKDAYS[now.weekday()],
        "greeting": _greeting(now.hour),
        "cpu": f"{int(metric('cpu', 'percent', 0))}%",
        "memory": f"{int(metric('memory', 'percent', 0))}%",
        "battery": ("—" if battery_percent is None
                    else f"{int(battery_percent)}%"),
        "disk": f"{int(metric('disk', 'percent', 0))}%",
        "city": str(city),
        "temp": "—" if temp is None else f"{temp}°",
        "uptime": format_uptime(uptime_seconds),
        "processes": str(int(metric("processes", "count", 0))),
        "net_down": format_speed(metric("network", "down", 0)),
        "net_up": format_speed(metric("network", "up", 0)),
    }
    return values


def apply_placeholders(template: str, values: dict[str, str]) -> str:
    """Подставляет {ключи} в текст, неизвестные ключи оставляет как есть."""
    if not template:
        return ""

    def replace(match: re.Match) -> str:
        key = match.group(1).casefold()
        return str(values.get(key, match.group(0)))

    return re.sub(r"\{([A-Za-zА-Яа-я_]+)\}", replace, str(template))
