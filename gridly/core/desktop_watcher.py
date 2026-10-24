"""
core/desktop_watcher.py
Target: Windows 10/11 x64. Toolchain: Python 3.11, pywin32, PyQt6.

Низкоуровневый мышиный хук WH_MOUSE_LL детектирует двойной клик по пустому
месту рабочего стола и сигналит в Qt-поток. Хук и message loop живут в одном
QThread. Windows молча снимает хук, если callback не укладывается в
LowLevelHooksTimeout, поэтому хук переустанавливается периодически.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import time

import win32con
import win32api
import win32gui

from PyQt6.QtCore import QThread, pyqtSignal

from core.win32_utils import is_desktop_click_target

logger = logging.getLogger("gridly.desktop_watcher")

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
HC_ACTION = 0
REINSTALL_INTERVAL_S = 30


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wt.POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wt.WPARAM, ctypes.POINTER(MSLLHOOKSTRUCT)
)

ctypes.windll.user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, LowLevelMouseProc, wt.HINSTANCE, wt.DWORD,
]
ctypes.windll.user32.SetWindowsHookExW.restype = wt.HHOOK
ctypes.windll.user32.CallNextHookEx.argtypes = [
    wt.HHOOK, ctypes.c_int, wt.WPARAM, ctypes.POINTER(MSLLHOOKSTRUCT),
]
ctypes.windll.user32.CallNextHookEx.restype = ctypes.c_long
ctypes.windll.user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]


class DesktopDoubleClickWatcher(QThread):
    """Эмитит desktop_double_clicked() при двойном клике по рабочему столу."""

    desktop_double_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._hook = None
        self._last_down_time = 0
        self._last_down_pos = (0, 0)
        self._keep_running = True
        self._os_thread_id = 0
        self._proc_ref = LowLevelMouseProc(self._ll_mouse_proc)  # держим ref от GC

    def _ll_mouse_proc(self, nCode, wParam, lParam):
        try:
            if nCode == HC_ACTION and wParam == WM_LBUTTONDOWN:
                info = lParam.contents
                now = info.time
                pos = (info.pt.x, info.pt.y)

                dbl_time = ctypes.windll.user32.GetDoubleClickTime()
                cx = win32api.GetSystemMetrics(win32con.SM_CXDOUBLECLK)
                cy = win32api.GetSystemMetrics(win32con.SM_CYDOUBLECLK)

                is_double = (
                    now - self._last_down_time <= dbl_time
                    and abs(pos[0] - self._last_down_pos[0]) <= cx
                    and abs(pos[1] - self._last_down_pos[1]) <= cy
                )

                if is_double:
                    hwnd = win32gui.WindowFromPoint(pos)
                    cls = win32gui.GetClassName(hwnd) if hwnd else "<none>"
                    logger.info("double-click at %s hwnd=0x%X class=%s",
                                pos, hwnd or 0, cls)
                    if is_desktop_click_target(hwnd):
                        self.desktop_double_clicked.emit()
                    self._last_down_time = 0  # сброс, чтобы не было тройного клика
                else:
                    self._last_down_time = now
                    self._last_down_pos = pos
        except Exception:
            logger.exception("Ошибка в mouse hook callback")

        return ctypes.windll.user32.CallNextHookEx(
            self._hook, nCode, wParam, lParam
        )

    def _install_hook(self) -> bool:
        self._hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._proc_ref, None, 0
        )
        if not self._hook:
            logger.error("SetWindowsHookExW провалился: %s",
                         ctypes.windll.kernel32.GetLastError())
            return False
        logger.info("WH_MOUSE_LL установлен")
        return True

    def _remove_hook(self) -> None:
        if self._hook:
            ctypes.windll.user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def run(self) -> None:
        self._os_thread_id = win32api.GetCurrentThreadId()
        if not self._install_hook():
            return

        msg = wt.MSG()
        PM_REMOVE = 0x0001
        last_reinstall = time.monotonic()

        while self._keep_running:
            if ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == win32con.WM_QUIT:
                    break
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.01)

            if time.monotonic() - last_reinstall >= REINSTALL_INTERVAL_S:
                self._remove_hook()
                self._install_hook()
                last_reinstall = time.monotonic()

        self._remove_hook()

    def stop(self) -> None:
        self._keep_running = False
        if self._os_thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._os_thread_id, win32con.WM_QUIT, 0, 0
            )
        self.wait(1000)