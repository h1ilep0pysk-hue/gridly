"""Общая настройка для тестов: offscreen Qt и стаб ui.blur_effect.

ui/blur_effect.py вызывает ctypes.windll при импорте, поэтому вне Windows
его нужно заменить заглушкой. Win32-функции из core.win_shell подменяются
в самих тестах через unittest.mock.
"""
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.platform != "win32" and "ui.blur_effect" not in sys.modules:
    _stub = types.ModuleType("ui.blur_effect")
    _stub.enable_fence_blur = lambda *a, **k: None
    _stub.disable_blur = lambda *a, **k: None
    _stub.DWMWCP_DEFAULT = 0
    _stub.DWMWCP_ROUND = 2
    _stub.DWMWCP_ROUNDSMALL = 3
    _stub.set_window_corner_preference = lambda *a, **k: None
    _stub.DWMWCP_DONOTROUND = 1
    _stub.hide_window_border = lambda *a, **k: False
    sys.modules["ui.blur_effect"] = _stub


def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
