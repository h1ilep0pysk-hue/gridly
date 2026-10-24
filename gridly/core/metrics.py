"""
core/metrics.py
Сбор данных для системных виджетов: ЦП, память, батарея, диск.
"""

from __future__ import annotations

import os
import time

from core.widget_storage import WidgetState

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

if psutil is not None:
    # Первый вызов cpu_percent() всегда возвращает 0 — заранее прогреваем.
    try:
        psutil.cpu_percent(interval=None)
    except Exception:  # pragma: no cover
        pass

# Для скорости сети нужны два замера подряд.
_last_net_sample: tuple[float, float, float] | None = None
_last_net_rate: tuple[float, float] = (0.0, 0.0)


def _gb(value: float) -> float:
    return value / (1024 ** 3)


def empty_metric_data() -> dict:
    return {
        "percent": 0,
        "cores": "—",
        "used": 0.0,
        "total": 0.0,
        "plugged": None,
        "secsleft": None,
        "free": 0.0,
        "letter": "C:",
        "error": None,
    }


def _network_data() -> dict:
    """Скорость сети считается по разнице счётчиков между вызовами."""
    global _last_net_sample, _last_net_rate
    io = psutil.net_io_counters()
    now = time.monotonic()
    down = up = 0.0
    if _last_net_sample is not None:
        elapsed = now - _last_net_sample[0]
        if elapsed >= 0.2:
            down = max(0.0, (io.bytes_recv - _last_net_sample[1]) / elapsed)
            up = max(0.0, (io.bytes_sent - _last_net_sample[2]) / elapsed)
            _last_net_rate = (down, up)
        else:
            down, up = _last_net_rate
    _last_net_sample = (now, float(io.bytes_recv), float(io.bytes_sent))
    return {
        "down": down,
        "up": up,
        "total_down": float(io.bytes_recv),
        "total_up": float(io.bytes_sent),
        "error": None,
    }


def _uptime_data() -> dict:
    boot = float(psutil.boot_time())
    return {
        "seconds": max(0.0, time.time() - boot),
        "boot": boot,
        "error": None,
    }


def _processes_data() -> dict:
    return {"count": len(psutil.pids()), "error": None}


def collect_all_metrics(interval: int = 2) -> dict[str, dict]:
    """Снимок всех системных показателей для составного виджета."""
    if psutil is None:
        message = "Модуль psutil не установлен"
        data = empty_metric_data()
        data["error"] = message
        return {
            "cpu": dict(data),
            "memory": dict(data),
            "battery": dict(data),
            "disk": dict(data),
            "network": {"down": 0.0, "up": 0.0, "total_down": 0.0,
                        "total_up": 0.0, "error": message},
            "uptime": {"seconds": 0.0, "boot": None, "error": message},
            "processes": {"count": 0, "error": message},
        }

    result: dict[str, dict] = {}
    try:
        result["cpu"] = {
            "percent": int(round(psutil.cpu_percent(interval=None))),
            "cores": psutil.cpu_count(logical=True) or "—",
            "interval": interval,
        }
    except Exception as exc:  # pragma: no cover — зависит от системы
        result["cpu"] = {**empty_metric_data(), "error": str(exc)}

    try:
        vm = psutil.virtual_memory()
        result["memory"] = {
            "percent": int(round(vm.percent)),
            "used": _gb(vm.total - vm.available),
            "total": _gb(vm.total),
        }
    except Exception as exc:  # pragma: no cover
        result["memory"] = {**empty_metric_data(), "error": str(exc)}

    try:
        battery = psutil.sensors_battery()
        if battery is None:
            result["battery"] = {"percent": None, "plugged": None,
                                 "secsleft": None}
        else:
            secs = battery.secsleft
            if secs in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
                secs = None
            result["battery"] = {
                "percent": int(round(battery.percent)),
                "plugged": bool(battery.power_plugged),
                "secsleft": secs,
            }
    except Exception as exc:  # pragma: no cover
        result["battery"] = {**empty_metric_data(), "error": str(exc)}

    try:
        letter = os.environ.get("SystemDrive", "C:")
        usage = psutil.disk_usage(f"{letter}\\")
        result["disk"] = {
            "percent": int(round(usage.percent)),
            "free": _gb(usage.free),
            "total": _gb(usage.total),
            "letter": letter,
        }
    except Exception as exc:  # pragma: no cover
        result["disk"] = {**empty_metric_data(), "error": str(exc)}

    try:
        result["network"] = _network_data()
    except Exception as exc:  # pragma: no cover
        result["network"] = {"down": 0.0, "up": 0.0, "total_down": 0.0,
                             "total_up": 0.0, "error": str(exc)}

    try:
        result["uptime"] = _uptime_data()
    except Exception as exc:  # pragma: no cover
        result["uptime"] = {"seconds": 0.0, "boot": None, "error": str(exc)}

    try:
        result["processes"] = _processes_data()
    except Exception as exc:  # pragma: no cover
        result["processes"] = {"count": 0, "error": str(exc)}

    return result


def collect_metric_data(state: WidgetState) -> dict:
    if psutil is None:
        return {
            "percent": 0,
            "cores": "—",
            "used": 0.0,
            "total": 0.0,
            "plugged": None,
            "secsleft": None,
            "free": 0.0,
            "letter": "C:",
            "error": "Модуль psutil не установлен",
        }

    kind = state.kind
    try:
        if kind == "cpu":
            return {
                "percent": int(round(psutil.cpu_percent(interval=None))),
                "cores": psutil.cpu_count(logical=True) or "—",
                "interval": state.interval,
            }

        if kind == "memory":
            vm = psutil.virtual_memory()
            return {
                "percent": int(round(vm.percent)),
                "used": _gb(vm.total - vm.available),
                "total": _gb(vm.total),
            }

        if kind == "battery":
            battery = psutil.sensors_battery()
            if battery is None:
                return {"percent": None, "plugged": None, "secsleft": None}
            secs = battery.secsleft
            if secs in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
                secs = None
            return {
                "percent": int(round(battery.percent)),
                "plugged": bool(battery.power_plugged),
                "secsleft": secs,
            }

        if kind == "disk":
            letter = os.environ.get("SystemDrive", "C:")
            usage = psutil.disk_usage(f"{letter}\\")
            return {
                "percent": int(round(usage.percent)),
                "free": _gb(usage.free),
                "total": _gb(usage.total),
                "letter": letter,
            }
    except Exception as exc:  # psutil на некоторых системах может падать
        return {
            "percent": 0,
            "cores": "—",
            "used": 0.0,
            "total": 0.0,
            "plugged": None,
            "secsleft": None,
            "free": 0.0,
            "letter": "C:",
            "error": str(exc),
        }

    return {"percent": 0}
