"""
core/win_shell.py
Замена системной оболочки Windows: панель задач, список окон и запуск
программ.

Модуль инкапсулирует Win32-вызовы, которые нужны macOS-оболочке:
  * скрытие/возврат панели задач (включая панели на втором мониторе);
  * скрытие окон Gridly с панели задач (WS_EX_TOOLWINDOW);
  * перечисление верхнеуровневых окон для переключателя;
  * запуск ярлыков из меню «Пуск» и с рабочего стола;
  * глобальные горячие клавиши.

Все функции терпимы к средам без Windows: в этом случае они ничего не
делают, чтобы модуль можно было импортировать в тестах.
"""

from __future__ import annotations

import atexit
import ctypes
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("gridly.win_shell")

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
else:  # pragma: no cover - на Windows эта ветка не выполняется
    wt = None
    user32 = kernel32 = dwmapi = None

# --- Win32-константы -------------------------------------------------------
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SW_HIDE = 0
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GW_OWNER = 4
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_SPACE = 0x20
VK_W = 0x57
VK_L = 0x4C
VK_ESCAPE = 0x1B
VK_G = 0x47
WM_HOTKEY = 0x0312
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

_SKIP_CLASSES = {
    "Progman",
    "WorkerW",
    "Shell_TrayWnd",
    "Shell_SecondaryTrayWnd",
    "ForegroundStaging",
    "MultitaskingViewFrame",
    "Windows.UI.Core.CoreWindow",
    "ApplicationManager_DesktopShellWindow",
}

_HIDDEN_BY_US = False
_WATCHDOG: subprocess.Popen | None = None
_ATEXIT_REGISTERED = False


# --- Инициализация ctypes --------------------------------------------------
def _setup_prototypes() -> None:
    if not IS_WINDOWS:
        return
    user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowW.restype = wt.HWND
    user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowExW.restype = wt.HWND
    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(
        ctypes.c_bool, wt.HWND, wt.LPARAM), wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindow.restype = wt.BOOL
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user32.GetWindow.restype = wt.HWND
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.BringWindowToTop.restype = wt.BOOL
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.AttachThreadInput.restype = wt.BOOL
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.SetWindowPos.argtypes = [
        wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetWindowPos.restype = wt.BOOL
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.RegisterHotKey.restype = wt.BOOL
    user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wt.BOOL
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

    long_ptr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    long_ptr.argtypes = [wt.HWND, ctypes.c_int]
    long_ptr.restype = ctypes.c_ssize_t
    set_long_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    set_long_ptr.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_long_ptr.restype = ctypes.c_ssize_t


if IS_WINDOWS:
    _setup_prototypes()


# --- Панель задач ----------------------------------------------------------
def taskbar_handles() -> list[int]:
    """Возвращает HWND основной и дополнительных панелей задач."""
    if not IS_WINDOWS:
        return []
    handles: list[int] = []
    main = user32.FindWindowW("Shell_TrayWnd", None)
    if main:
        handles.append(int(main))

    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _lparam):
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buffer, 64)
        if buffer.value == "Shell_SecondaryTrayWnd":
            handles.append(int(hwnd))
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return handles


def _watchdog_code() -> str:
    """Код отдельного процесса, который вернёт панель задач после падения."""
    return r"""
import ctypes, sys
parent = int(sys.argv[1])
u = ctypes.windll.user32
k = ctypes.windll.kernel32
u.FindWindowW.restype = ctypes.c_void_p
u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
h = k.OpenProcess(0x00100000, False, parent)
if h:
    k.WaitForSingleObject(h, 0xFFFFFFFF)
    k.CloseHandle(h)
hwnd = u.FindWindowW("Shell_TrayWnd", None)
if hwnd:
    u.ShowWindow(hwnd, 5)
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                 ctypes.c_void_p)
def cb(hwnd, lp):
    b = ctypes.create_unicode_buffer(64)
    u.GetClassNameW(hwnd, b, 64)
    if b.value == "Shell_SecondaryTrayWnd":
        u.ShowWindow(hwnd, 5)
    return True
u.EnumWindows(WNDENUMPROC(cb), 0)
"""


def start_taskbar_watchdog() -> None:
    """Запускает сторожевой процесс, если он ещё не запущен."""
    global _WATCHDOG
    if not IS_WINDOWS or _WATCHDOG is not None:
        return
    try:
        _WATCHDOG = subprocess.Popen(
            [sys.executable, "-c", _watchdog_code(), str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    except OSError as exc:
        logger.warning("Не удалось запустить watchdog панели задач: %s", exc)
        _WATCHDOG = None


def stop_taskbar_watchdog() -> None:
    global _WATCHDOG
    if _WATCHDOG is None:
        return
    try:
        if _WATCHDOG.poll() is None:
            _WATCHDOG.terminate()
    except OSError:
        pass
    _WATCHDOG = None


def _restore_on_exit() -> None:
    show_taskbar(force=True)


def hide_taskbar() -> None:
    """Прячет панель задач Windows и запускает сторожевой процесс."""
    global _HIDDEN_BY_US, _ATEXIT_REGISTERED
    if not IS_WINDOWS:
        return
    handles = taskbar_handles()
    if not handles:
        return
    if not _HIDDEN_BY_US:
        _HIDDEN_BY_US = True
        if not _ATEXIT_REGISTERED:
            atexit.register(_restore_on_exit)
            _ATEXIT_REGISTERED = True
    for hwnd in handles:
        user32.ShowWindow(hwnd, SW_HIDE)
    start_taskbar_watchdog()


def ensure_taskbar_hidden() -> None:
    """Повторно прячет панель задач, если Explorer её восстановил."""
    if not IS_WINDOWS or not _HIDDEN_BY_US:
        return
    for hwnd in taskbar_handles():
        if user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, SW_HIDE)


def show_taskbar(force: bool = False) -> None:
    """Возвращает панель задач. force нужен сторожевому процессу."""
    global _HIDDEN_BY_US
    if not IS_WINDOWS:
        return
    if not _HIDDEN_BY_US and not force:
        return
    for hwnd in taskbar_handles():
        user32.ShowWindow(hwnd, SW_SHOW)
    _HIDDEN_BY_US = False
    stop_taskbar_watchdog()


# --- Окна ------------------------------------------------------------------
@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    exe: str


def _window_class(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def _is_cloaked(hwnd: int) -> bool:
    if not IS_WINDOWS:
        return False
    cloaked = ctypes.c_int(0)
    try:
        dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
    except OSError:
        return False
    return cloaked.value != 0


def process_path(pid: int) -> str:
    if not IS_WINDOWS or not pid:
        return ""
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(
                handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
    finally:
        kernel32.CloseHandle(handle)
    return ""


def _window_pid(hwnd: int) -> int:
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def list_windows(exclude_pids: set[int] | None = None,
                 debug: list | None = None) -> list[WindowInfo]:
    """Перечисляет видимые верхнеуровневые окна приложений.

    debug — необязательный список: в него добавляются (hwnd, title, class,
    причина отбрасывания | "shown") для диагностики.
    """
    if not IS_WINDOWS:
        return []
    exclude = set(exclude_pids or ())
    result: list[WindowInfo] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def note(hwnd, title, cls, reason):
        if debug is not None:
            debug.append((int(hwnd), title, cls, reason))
        return True

    def callback(hwnd, _lparam):
        title = _window_title(hwnd)
        cls = _window_class(hwnd)
        if not user32.IsWindowVisible(hwnd):
            return note(hwnd, title, cls, "not visible")
        if user32.GetWindow(hwnd, GW_OWNER):
            return note(hwnd, title, cls, "owned")
        if not title:
            return note(hwnd, title, cls, "no title")
        if cls in _SKIP_CLASSES:
            return note(hwnd, title, cls, "skip class")
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        style = get_long(hwnd, GWL_EXSTYLE)
        if style & WS_EX_TOOLWINDOW:
            return note(hwnd, title, cls, "tool window")
        if _is_cloaked(hwnd):
            return note(hwnd, title, cls, "cloaked")
        rect = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return note(hwnd, title, cls, "no rect")
        # Свёрнутое окно Windows отдаёт вырожденный прямоугольник: это не
        # «слишком маленькое» окно, а обычное окно приложения в доке.
        minimized = bool(user32.IsIconic(hwnd))
        if not minimized and (rect.right - rect.left < 80
                              or rect.bottom - rect.top < 60):
            return note(hwnd, title, cls, "too small")
        pid = _window_pid(hwnd)
        if pid in exclude or pid == os.getpid():
            return note(hwnd, title, cls, "excluded pid")
        result.append(WindowInfo(
            hwnd=int(hwnd), title=title, pid=pid,
            exe=process_path(pid),
        ))
        return note(hwnd, title, cls, "shown")

    user32.EnumWindows(callback_type(callback), 0)
    result.sort(key=lambda item: item.title.casefold())
    return result


def activate_window(hwnd: int) -> None:
    """Поднимает окно приложения и переводит на него фокус."""
    if not IS_WINDOWS:
        return
    try:
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
        foreground = user32.GetForegroundWindow()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        source_thread = user32.GetWindowThreadProcessId(foreground, None)
        attached = False
        if source_thread and source_thread != target_thread:
            attached = bool(user32.AttachThreadInput(
                source_thread, target_thread, True))
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        if attached:
            user32.AttachThreadInput(source_thread, target_thread, False)
        if current_thread == target_thread:
            user32.SetForegroundWindow(hwnd)
    except OSError as exc:
        logger.debug("Не удалось активировать окно %s: %s", hwnd, exc)


def minimize_all_windows(exclude_pids: set[int] | None = None) -> None:
    if not IS_WINDOWS:
        return
    for info in list_windows(exclude_pids):
        try:
            user32.ShowWindow(info.hwnd, SW_MINIMIZE)
        except OSError:
            pass


# --- Taskbar buttons -------------------------------------------------------
def _set_exstyle(hwnd: int, style: int) -> None:
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    current = get_long(hwnd, GWL_EXSTYLE)
    if current == style:
        return
    set_long(hwnd, GWL_EXSTYLE, style)
    user32.SetWindowPos(
        hwnd, None, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        | SWP_FRAMECHANGED,
    )


def hide_from_taskbar(hwnd: int) -> None:
    """Убирает кнопку окна с панели задач, оставляя окно рабочим."""
    if not IS_WINDOWS or not hwnd:
        return
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    style = get_long(hwnd, GWL_EXSTYLE)
    _set_exstyle(hwnd, (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)


def show_in_taskbar(hwnd: int) -> None:
    if not IS_WINDOWS or not hwnd:
        return
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    style = get_long(hwnd, GWL_EXSTYLE)
    _set_exstyle(hwnd, style & ~WS_EX_TOOLWINDOW)


def pin_window(hwnd: int) -> None:
    """Поднимает окно поверх остальных (аналог NSFloatingWindowLevel)."""
    if not IS_WINDOWS or not hwnd:
        return
    user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


def raise_topmost(hwnd: int) -> None:
    """Возвращает окно наверх топ-диапазона, не активируя его.

    Пуск и панель задач при открытии встают поверх дока; периодический
    вызов возвращает док поверх них.
    """
    pin_window(hwnd)


# --- Закреплённые приложения панели задач ----------------------------------
def list_pinned(limit: int = 48) -> list[dict]:
    """Ярлыки, закреплённые на панели задач (как в MyDockFinder)."""
    if not IS_WINDOWS:
        return []
    app_data = os.environ.get("APPDATA")
    if not app_data:
        return []
    roots = [
        Path(app_data) / "Microsoft" / "Internet Explorer" / "Quick Launch"
        / "User Pinned" / "TaskBar",
        Path(app_data) / "Microsoft" / "Internet Explorer" / "Quick Launch"
        / "User Pinned" / "ImplicitAppShortcuts",
    ]
    found: dict[str, dict] = {}
    for root in roots:
        try:
            entries = list(root.glob("*.lnk")) if root.exists() else []
        except OSError:
            entries = []
        for path in entries:
            name = path.stem.strip()
            key = name.casefold()
            if not name or key in found:
                continue
            found[key] = {"name": name, "path": str(path)}
    apps = sorted(found.values(), key=lambda item: item["name"].casefold())
    return apps[:limit]


def minimize_window(hwnd: int) -> None:
    """Сворачивает конкретное окно (в Dock, как в macOS)."""
    if not IS_WINDOWS or not hwnd:
        return
    try:
        user32.ShowWindow(int(hwnd), SW_MINIMIZE)
    except OSError:
        pass


def close_window(hwnd: int) -> None:
    """Посылает окну WM_CLOSE (вежливое закрытие)."""
    if not IS_WINDOWS or not hwnd:
        return
    try:
        user32.PostMessageW(int(hwnd), 0x0010, 0, 0)  # WM_CLOSE
    except OSError:
        pass


def window_is_foreground(hwnd: int) -> bool:
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        return bool(user32.GetForegroundWindow() == hwnd)
    except OSError:
        return False


def toggle_window(hwnd: int) -> str:
    """Клик по иконке Dock: активировать / свернуть."""
    if not IS_WINDOWS or not hwnd:
        return ""
    if user32.GetForegroundWindow() == hwnd and \
            not user32.IsIconic(hwnd):
        minimize_window(hwnd)
        return "minimized"
    activate_window(hwnd)
    return "activated"


def open_recycle_bin() -> bool:
    """Открывает Корзину (аналог Trash в Dock)."""
    if not IS_WINDOWS:
        return False
    try:
        os.startfile("shell:RecycleBinFolder")  # type: ignore[attr-defined]
        return True
    except OSError as exc:
        logger.warning("Не удалось открыть Корзину: %s", exc)
        return False


# --- Ярлыки и программы ----------------------------------------------------
_SKIP_APP_WORDS = (
    "uninstall", "удалить", "деинсталл", "readme", "read me", "help",
    "справка", "website", "сайт", "документация", "documentation",
)


def _iter_shortcuts(root: Path):
    try:
        for path in root.rglob("*"):
            if path.suffix.lower() in (".lnk", ".url", ".exe"):
                yield path
    except OSError:
        return


def list_apps(limit: int = 160) -> list[dict]:
    """Собирает ярлыки из меню «Пуск» и с рабочего стола."""
    roots: list[Path] = []
    program_data = os.environ.get("ProgramData")
    app_data = os.environ.get("APPDATA")
    user_profile = os.environ.get("USERPROFILE")
    public = os.environ.get("PUBLIC")
    if program_data:
        roots.append(Path(program_data) / "Microsoft" / "Windows"
                     / "Start Menu" / "Programs")
    if app_data:
        roots.append(Path(app_data) / "Microsoft" / "Windows"
                     / "Start Menu" / "Programs")
    if user_profile:
        roots.append(Path(user_profile) / "Desktop")
    if public:
        roots.append(Path(public) / "Desktop")

    found: dict[str, dict] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in _iter_shortcuts(root):
            name = path.stem.strip()
            if not name or name.startswith("."):
                continue
            lower = name.casefold()
            if any(word in lower for word in _SKIP_APP_WORDS):
                continue
            if lower in found:
                continue
            found[lower] = {"name": name, "path": str(path)}
    apps = sorted(found.values(), key=lambda item: item["name"].casefold())
    return apps[:limit]


def launch_path(path: str) -> bool:
    """Запускает ярлык, документ или программу."""
    if not path:
        return False
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except (OSError, AttributeError) as exc:
        logger.warning("Не удалось запустить %s: %s", path, exc)
        return False


# --- Горячие клавиши -------------------------------------------------------
def register_hotkey(hotkey_id: int, modifiers: int, virtual_key: int) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return bool(user32.RegisterHotKey(
            None, int(hotkey_id), int(modifiers), int(virtual_key)))
    except OSError:
        return False


def unregister_hotkey(hotkey_id: int) -> None:
    if not IS_WINDOWS:
        return
    try:
        user32.UnregisterHotKey(None, int(hotkey_id))
    except OSError:
        pass
