"""
core/mac_overlay.py
Связка вкладки «Твики» с глобальной macOS-панелью (macos_global_overlay.py).

Скрипт-оверлей сам читает настройки рядом с собой, поэтому здесь только
три типа функций: собрать конфиг, синхронизировать его с проектом,
экспортировать набор «скрипт + конфиг + readme» в папку пользователя.

Экспорт работает на любой системе (например, подготовить папку на Windows,
чтобы перенести на Mac).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from core.tweaks import MacTweaks

logger = logging.getLogger("gridly.mac_overlay")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OVERLAY_SCRIPT = PROJECT_ROOT / "macos_global_overlay.py"
OVERLAY_REQUIREMENTS = PROJECT_ROOT / "requirements-macos.txt"
OVERLAY_README = PROJECT_ROOT / "MACOS_OVERLAY.md"
TITLEBAR_MODULE = PROJECT_ROOT / "macos_titlebar_wrap.py"

# Файл настроек, который читает сам оверлей (лежит рядом со скриптом).
SIDECAR_NAME = "macos_overlay.json"


def overlay_config(tweaks: MacTweaks | None) -> dict:
    """Плоский конфиг в терминах скрипта-оверлея."""
    t = tweaks or MacTweaks()
    return {
        "enabled": bool(t.overlay_enabled),
        "level": "floating" if t.overlay_level == "floating" else "main_menu",
        "max_apps": max(4, min(30, int(t.overlay_max_apps))),
        "clock": bool(t.overlay_clock),
        "titlebar_enabled": bool(t.titlebar_wrap_enabled),
        "titlebar_bundles": parse_bundles(t.titlebar_wrap_bundles),
    }


def parse_bundles(raw: str) -> list[str]:
    """«a.b.c, d.e.f» → ['a.b.c', 'd.e.f'] без пустых и дублей."""
    seen: list[str] = []
    for item in str(raw or "").split(","):
        bundle = item.strip()
        if bundle and bundle not in seen:
            seen.append(bundle)
    return seen


def sidecar_path(base_dir: Path | str | None = None) -> Path:
    """Путь к macos_overlay.json рядом со скриптом-оверлеем."""
    base = Path(base_dir) if base_dir else PROJECT_ROOT
    return base / SIDECAR_NAME


def write_config(config: dict, path: Path | str | None = None) -> Path | None:
    """Пишет конфиг оверлея; ошибка логируется и не роняет UI."""
    target = Path(path) if path else sidecar_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(target)
        return target
    except OSError as exc:
        logger.error("Не удалось записать конфиг overlay: %s", exc)
        return None


def sync_config(tweaks: MacTweaks | None,
                base_dir: Path | str | None = None) -> Path | None:
    """Обновляет macos_overlay.json текущими значениями вкладки «Твики»."""
    config = overlay_config(tweaks)
    path = sidecar_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    return write_config(config, path)


def export_overlay(tweaks: MacTweaks | None, dest_dir: Path | str | None = None
                   ) -> list[Path]:
    """Собирает автономный набор для переноса на Mac:
    скрипт + requirements + инструкция + macos_overlay.json.
    """
    config = overlay_config(tweaks)
    if dest_dir:
        base = Path(dest_dir)
        base.mkdir(parents=True, exist_ok=True)
    else:
        base = PROJECT_ROOT

    copied: list[Path] = []
    for source in (OVERLAY_SCRIPT, TITLEBAR_MODULE, OVERLAY_REQUIREMENTS,
                   OVERLAY_README):
        if source.exists():
            copied.append(shutil.copy2(source, base / source.name))

    config_path = write_config(config, base / SIDECAR_NAME)
    if config_path is not None:
        copied.append(config_path)
    return copied
