"""
core/win32_utils.py
Низкоуровневая интеграция Gridly с рабочим столом Windows.
Target: Windows 10/11 x64. Toolchain: Python 3.11, pywin32 306+.

Сценарии WorkerW:
  A) explorer создаёт пустой WorkerW после 0x052C (часть сборок Win10/Win11)
  B) explorer не создаёт WorkerW — используем Progman как родителя

Важно: окно Qt создаётся с WS_POPUP. SetParent не переводит такое окно
в дочернее, поэтому перед SetParent стиль меняется на WS_CHILD.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
from dataclasses import dataclass

import win32con
import win32gui

logger = logging.getLogger("gridly.win32")

user32 = ctypes.WinDLL("user32", use_last_error=True)
dwmapi = ctypes.windll.dwmapi  # для DWM blur / acrylic (ui/blur_effect.py)

WM_GRIDLY_SPAWN_WORKERW = 0x052C

FENCE_EX_STYLES = (
    win32con.WS_EX_TOOLWINDOW
    | win32con.WS_EX_NOACTIVATE
    | win32con.WS_EX_LAYERED
)

DESKTOP_CLICK_CLASSES = (
    "SHELLDLL_DefView",
    "SysListView32",
    "Progman",
    "WorkerW",
)

user32.SendMessageTimeoutW.argtypes = [
    wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = ctypes.c_size_t

user32.SetParent.argtypes = [wt.HWND, wt.HWND]
user32.SetParent.restype = wt.HWND

user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long


@dataclass
class DesktopHost:
    """Результат поиска подходящего родителя на рабочем столе."""
    progman: int
    host_hwnd: int
    used_workerw: bool


def _find_progman() -> int:
    hwnd = win32gui.FindWindow("Progman", None)
    if not hwnd:
        raise RuntimeError("Progman не найден — explorer.exe не запущен?")
    return hwnd


def _spawn_workerw(progman: int) -> None:
    """
    lpdwResult — DWORD_PTR (8 байт на x64), поэтому буфер c_size_t.
    Если explorer не отвечает или игнорирует сообщение, уходим в fallback.
    """
    result = ctypes.c_size_t()
    SMTO_NORMAL = 0x0000
    user32.SendMessageTimeoutW(
        progman,
        WM_GRIDLY_SPAWN_WORKERW,
        0, 0,
        SMTO_NORMAL,
        1000,
        ctypes.byref(result),
    )


def _window_has_defview_child(hwnd: int) -> bool:
    found = {"ok": False}

    def _cb(child, _):
        if win32gui.GetClassName(child) == "SHELLDLL_DefView":
            found["ok"] = True
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _cb, None)
    except win32gui.error:
        pass
    return found["ok"]


def _find_empty_workerw() -> int:
    """
    Ищет WorkerW, который идёт сразу ПОСЛЕ WorkerW с SHELLDLL_DefView
    в порядке Z (EnumWindows возвращает окна сверху вниз).
    Чужие WorkerW (например, от Lively) не трогаем.
    """
    workers: list[int] = []

    def _cb(hwnd, _):
        if win32gui.GetClassName(hwnd) == "WorkerW":
            workers.append(hwnd)
        return True

    win32gui.EnumWindows(_cb, None)
    for i, w in enumerate(workers):
        if _window_has_defview_child(w) and i + 1 < len(workers):
            return workers[i + 1]
    return 0


def find_desktop_host() -> DesktopHost:
    progman = _find_progman()
    _spawn_workerw(progman)

    candidate_workerw = _find_empty_workerw()
    if candidate_workerw:
        logger.info("Используем отдельный WorkerW: 0x%X", candidate_workerw)
        return DesktopHost(progman=progman, host_hwnd=candidate_workerw, used_workerw=True)

    logger.warning(
        "Отдельный пустой WorkerW не создан — fallback на Progman (0x%X).",
        progman,
    )
    return DesktopHost(progman=progman, host_hwnd=progman, used_workerw=False)


def _make_child_style(hwnd: int) -> None:
    """Снимает WS_POPUP и ставит WS_CHILD — без этого SetParent не работает."""
    style = user32.GetWindowLongW(hwnd, win32con.GWL_STYLE)
    style = (style & ~win32con.WS_POPUP) | win32con.WS_CHILD
    user32.SetWindowLongW(hwnd, win32con.GWL_STYLE, style)
    win32gui.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED,
    )


def embed_into_desktop(qt_hwnd: int, host: DesktopHost | None = None) -> DesktopHost:
    """
    Встраивает HWND Qt-окна в слой рабочего стола.
    Успех определяется по GetParent после SetParent, а не по возвращаемому значению.
    """
    if host is None:
        host = find_desktop_host()

    _make_child_style(qt_hwnd)

    ctypes.set_last_error(0)
    user32.SetParent(qt_hwnd, host.host_hwnd)
    err = ctypes.get_last_error()

    actual_parent = win32gui.GetParent(qt_hwnd) or 0
    if actual_parent != host.host_hwnd:
        raise RuntimeError(
            f"SetParent не применился: parent=0x{actual_parent:X}, "
            f"ожидали 0x{host.host_hwnd:X}, GetLastError={err}"
        )

    apply_fence_styles(qt_hwnd)
    return host


def apply_fence_styles(hwnd: int) -> None:
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex_style |= FENCE_EX_STYLES
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

    SWP_FLAGS = (
        win32con.SWP_NOMOVE
        | win32con.SWP_NOSIZE
        | win32con.SWP_NOZORDER
        | win32con.SWP_FRAMECHANGED
    )
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)


def set_window_alpha(hwnd: int, alpha: int) -> None:
    LWA_ALPHA = 0x2
    win32gui.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)


def is_desktop_click_target(hwnd: int) -> bool:
    """True, если клик пришёл на пустое место рабочего стола."""
    if not hwnd:
        return False
    return win32gui.GetClassName(hwnd) in DESKTOP_CLICK_CLASSES


def get_hwnd_under_cursor() -> int:
    pt = win32gui.GetCursorPos()
    return win32gui.WindowFromPoint(pt)