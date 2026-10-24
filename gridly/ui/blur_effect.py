"""
ui/blur_effect.py
Target: Windows 10 1803+ / Windows 11, x64. Toolchain: Python 3.11.

Включает Acrylic blur-behind на HWND через недокументированный
SetWindowCompositionAttribute (ntdll/user32). Fallback — DWM
стандартный blur (DwmEnableBlurBehindWindow), доступный на всех Win10+.

Сигнатура SetWindowCompositionAttribute НЕ документирована Microsoft
напрямую в MSDN (известна из реверса dwmapi/user32), но стабильно
используется множеством opensource-проектов (например, глубоко в
Windows Terminal/ряде blur-tweaker тулов) с Win10 1803 по Win11 24H2.
Структуры ACCENT_POLICY / WINDOWCOMPOSITIONATTRIBDATA ниже — ABI,
реверснутый сообществом; на будущих сборках Windows может измениться
без предупреждения (// PLACEHOLDER: если перестанет работать —
проверить offset'ы через `dumpbin /exports user32.dll` + сверку с
ReactOS header'ами composition private API).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi


class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),   # ABGR
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(ACCENT_POLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


# accent states (ABI реверснут из user32, не из публичной документации)
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
WCA_ACCENT_POLICY = 19


def apply_acrylic(hwnd: int, tint_bgr: int = 0x2B2B2B, tint_alpha: int = 160) -> bool:
    """
    tint_bgr: цвет подложки в 0xBBGGRR (не RGB!).
    tint_alpha: 0..255 — непрозрачность акрилового тонирования
                (НЕ альфа всего окна — за это отвечает set_window_alpha
                из win32_utils, они комбинируются).
    Возвращает True при успехе, False — если API недоступен
    (тогда вызывающий код должен откатиться на apply_dwm_blur).
    """
    return _set_accent(hwnd, ACCENT_ENABLE_ACRYLICBLURBEHIND,
                       tint_bgr, tint_alpha)


def disable_blur(hwnd: int) -> bool:
    """Выключает акриловый/фоновый blur для окна."""
    return _set_accent(hwnd, ACCENT_DISABLED, 0, 0)


def _set_accent(hwnd: int, state: int, tint_bgr: int,
                tint_alpha: int) -> bool:
    gradient_color = (tint_alpha << 24) | (tint_bgr & 0xFFFFFF)  # AABBGGRR

    accent = ACCENT_POLICY()
    accent.AccentState = state
    accent.AccentFlags = 2
    accent.GradientColor = gradient_color
    accent.AnimationId = 0

    data = WINDOWCOMPOSITIONATTRIBDATA()
    data.Attribute = WCA_ACCENT_POLICY
    data.Data = ctypes.pointer(accent)
    data.SizeOfData = ctypes.sizeof(accent)

    try:
        set_window_composition = user32.SetWindowCompositionAttribute
    except AttributeError:
        return False

    ok = set_window_composition(wt.HWND(hwnd), ctypes.byref(data))
    return bool(ok)


class DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = [
        ("dwFlags", wt.DWORD),
        ("fEnable", wt.BOOL),
        ("hRgnBlur", wt.HANDLE),
        ("fTransitionOnMaximized", wt.BOOL),
    ]


DWM_BB_ENABLE = 0x1


def apply_dwm_blur(hwnd: int) -> bool:
    """Документированный, но менее красивый blur (без акрилового тонирования)."""
    bb = DWM_BLURBEHIND()
    bb.dwFlags = DWM_BB_ENABLE
    bb.fEnable = True
    bb.hRgnBlur = None
    bb.fTransitionOnMaximized = False
    hr = dwmapi.DwmEnableBlurBehindWindow(wt.HWND(hwnd), ctypes.byref(bb))
    return hr == 0  # S_OK


def enable_fence_blur(hwnd: int, tint_bgr: int = 0x2B2B2B, tint_alpha: int = 160) -> None:
    if not apply_acrylic(hwnd, tint_bgr, tint_alpha):
        apply_dwm_blur(hwnd)


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3


DWMWA_BORDER_COLOR = 34
DWMWA_COLOR_NONE = 0xFFFFFFFE


def hide_window_border(hwnd: int) -> bool:
    """Убирает системную рамку окна в Windows 11 (DWMWA_BORDER_COLOR)."""
    if not hwnd:
        return False
    value = ctypes.c_uint(DWMWA_COLOR_NONE)
    try:
        hr = dwmapi.DwmSetWindowAttribute(
            wt.HWND(hwnd), DWMWA_BORDER_COLOR,
            ctypes.byref(value), ctypes.sizeof(value),
        )
    except (AttributeError, OSError, TypeError):
        return False
    return hr == 0


def set_window_corner_preference(hwnd: int,
                                 preference: int = DWMWCP_ROUND) -> bool:
    """Включает системное скругление углов окна в Windows 11."""
    if not hwnd:
        return False
    value = ctypes.c_int(int(preference))
    try:
        hr = dwmapi.DwmSetWindowAttribute(
            wt.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(value), ctypes.sizeof(value),
        )
    except (AttributeError, OSError, TypeError):
        return False
    return hr == 0
