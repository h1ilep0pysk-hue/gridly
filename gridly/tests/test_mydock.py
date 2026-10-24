"""Тесты MyDock и блокировки обычного MacDock (offscreen, без Win32)."""
import unittest
from types import SimpleNamespace
from unittest import mock

import _qt_env  # noqa: F401  (настраивает sys.path и стаб blur_effect)
from _qt_env import qapp

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QGuiApplication

from core import win_shell
from core.tweaks import MacTweaks
from ui.mac_dock import MacDock
from ui.mydock import DockApp, MyDockBar, _GlyphBase


def _tweaks(**kw) -> MacTweaks:
    base = dict(enabled=True, dock_enabled=True, mydock_enabled=True,
                dock_autohide=False)
    base.update(kw)
    return MacTweaks(**base)


class _WinStubs:
    """Подменяет Win32-функции core.win_shell на время теста."""

    def __init__(self, pinned=None, windows=None):
        self.pinned = list(pinned or [])
        self.windows = list(windows or [])
        self.toggle = mock.MagicMock(return_value="")
        self._patches = [
            mock.patch.object(win_shell, "list_pinned",
                              side_effect=lambda *a, **k: list(self.pinned)),
            mock.patch.object(win_shell, "list_windows",
                              side_effect=lambda *a, **k: list(self.windows)),
            mock.patch.object(win_shell, "toggle_window", self.toggle),
            mock.patch.object(win_shell, "launch_path",
                              mock.MagicMock(return_value=True)),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class MacDockLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_locked_dock_never_shows(self):
        dock = MacDock(_tweaks(mydock_enabled=False, dock_enabled=True))
        dock.apply_tweaks(_tweaks(mydock_enabled=False))

        dock.set_locked(True)
        self.assertFalse(dock.isVisible())

        dock.apply_tweaks(_tweaks(mydock_enabled=False))
        self.assertFalse(dock.isVisible(), "apply_tweaks не должен показывать")

        dock._reveal()
        self.assertFalse(dock.isVisible(), "_reveal не должен показывать")

        dock._poll_edge()
        self.assertFalse(dock.isVisible(), "_poll_edge не должен показывать")
        self.assertFalse(dock._edge_timer.isActive())
        self.assertFalse(dock._hide_timer.isActive())

        dock.set_locked(False)
        self.assertTrue(dock.isVisible(), "после разблокировки панель вернулась")

    def test_lock_stops_autohide_timers_and_blur(self):
        dock = MacDock(_tweaks(mydock_enabled=False, dock_autohide=True))
        dock.apply_tweaks(_tweaks(mydock_enabled=False, dock_autohide=True))
        self.assertTrue(dock._edge_timer.isActive())

        dock.set_locked(True)
        self.assertFalse(dock._edge_timer.isActive())
        self.assertFalse(dock._hide_timer.isActive())
        self.assertFalse(dock._blur_enabled)

        dock._apply_blur()  # отложенный вызов не должен включить размытие
        self.assertFalse(dock._blur_enabled)
        dock.leaveEvent(QEvent(QEvent.Type.Leave))
        self.assertFalse(dock._hide_timer.isActive())


class MyDockBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def test_disabled_mydock_stays_hidden(self):
        with _WinStubs():
            bar = MyDockBar(_tweaks(mydock_enabled=False))
            bar.apply_tweaks(_tweaks(mydock_enabled=False))
            self.assertFalse(bar.isVisible())
            bar.suspend()

    def test_enabled_mydock_shows_and_suspend_hides(self):
        with _WinStubs():
            bar = MyDockBar(_tweaks())
            bar.apply_tweaks(_tweaks())
            self.assertTrue(bar.isVisible())
            self.assertTrue(bar._refresh_timer.isActive())
            self.assertTrue(bar._topmost_timer.isActive())

            bar.suspend()
            self.assertFalse(bar.isVisible())
            self.assertFalse(bar._refresh_timer.isActive())
            self.assertFalse(bar._topmost_timer.isActive())
            self.assertFalse(bar._edge_timer.isActive())

    def test_repopulate_removes_old_glyphs(self):
        """Старые иконки не должны оставаться видимыми после смены набора."""
        with _WinStubs(pinned=[]) as stubs:
            bar = MyDockBar(_tweaks())
            bar.apply_tweaks(_tweaks())
            stubs.windows = [
                SimpleNamespace(hwnd=1, title="Notes", exe="C:/n/notes.exe",
                                pid=1),
                SimpleNamespace(hwnd=2, title="Browser",
                                exe="C:/b/browser.exe", pid=2),
            ]
            bar.refresh()
            stubs.windows = [
                SimpleNamespace(hwnd=3, title="Mail", exe="C:/m/mail.exe",
                                pid=3),
            ]
            bar.refresh()

            # Скрытые (снятые с layout) иконки не должны числиться видимыми.
            visible = [g for g in bar.findChildren(_GlyphBase)
                       if not g.isHidden()]
            self.assertEqual(
                sorted(id(g) for g in visible),
                sorted(id(g) for g, _ in bar._buttons),
                "в окне остались видимые иконки, которых нет в _buttons")
            bar.suspend()

    def test_clicking_running_app_toggles_its_window(self):
        with _WinStubs() as stubs:
            bar = MyDockBar(_tweaks())
            app = DockApp("Notes", "", hwnds=[7], running=True)
            bar._activate(app)
            stubs.toggle.assert_called_once_with(7)
            bar.suspend()

    def test_only_running_apps_are_listed(self):
        """Закреплённое, но не запущенное приложение в доке не показываем."""
        from ui.mydock import collect_apps
        with _WinStubs(pinned=[{"name": "Calc", "path": "C:/c/calc.exe"}],
                       windows=[]):
            self.assertEqual(collect_apps(), [])
        with _WinStubs(pinned=[{"name": "Calc", "path": "C:/c/calc.exe"}],
                       windows=[SimpleNamespace(hwnd=5, title="Calc",
                                                exe="C:/c/calc.exe", pid=5)]):
            apps = collect_apps()
            self.assertEqual([a.name for a in apps], ["Calc"])

    def test_no_system_glyphs_in_bar(self):
        with _WinStubs():
            bar = MyDockBar(_tweaks())
            bar.apply_tweaks(_tweaks())
            actions = [item for _g, item in bar._buttons]
            self.assertNotIn("finder", actions)
            self.assertNotIn("trash", actions)
            bar.suspend()

    def test_app_glyph_always_has_pixmap(self):
        """Иконка не остаётся пустой, даже если реальная не отрисовалась."""
        from ui.mydock import AppGlyph
        glyph = AppGlyph(DockApp("Notes", "", hwnds=[1], running=True))
        self.assertFalse(glyph._icon_pixmap(40).isNull())
        glyph.deleteLater()

    def test_bar_fits_all_icons_and_stays_on_screen(self):
        """Док вмещает все иконки и не уезжает за нижний край экрана."""
        windows = [SimpleNamespace(hwnd=i, title=f"App{i}",
                                   exe=f"C:/a/app{i}.exe", pid=i)
                   for i in range(1, 6)]
        with _WinStubs(windows=windows):
            bar = MyDockBar(_tweaks())
            bar.apply_tweaks(_tweaks())
            glyphs = [g for g, _ in bar._buttons]
            needed = sum(g.width() for g in glyphs)
            self.assertGreaterEqual(bar.width(), needed)
            self.assertEqual(len(glyphs), 5)  # только запущенные приложения
            screen = QGuiApplication.primaryScreen().geometry()
            self.assertLessEqual(bar.geometry().bottom(), screen.bottom())
            bar.suspend()

    def test_bar_returns_to_anchor_after_being_moved(self):
        """Док возвращается на якорь, если его сдвинули извне."""
        from PyQt6.QtCore import QPoint
        with _WinStubs():
            bar = MyDockBar(_tweaks())
            bar.apply_tweaks(_tweaks())
            anchor = bar._anchor
            self.assertIsNotNone(anchor)
            bar.move(anchor + QPoint(37, -11))
            bar._keep_on_top()
            self.assertEqual(bar.pos(), anchor)
            bar.suspend()

    def test_bar_size_does_not_change_on_hover_or_idle(self):
        """Размер панели и иконок постоянный: без приближения и сжатия."""
        with _WinStubs():
            bar = MyDockBar(_tweaks(dock_size=56))
            bar.apply_tweaks(_tweaks(dock_size=56))
            before = bar.height()
            bar._keep_on_top()
            self.assertEqual(bar.height(), before)
            self.assertEqual(bar._current_base(), 56)
            bar.suspend()

    def test_system_finder_request_is_emitted(self):
        with _WinStubs():
            bar = MyDockBar(_tweaks())
            seen = []
            bar.systemRequested.connect(seen.append)
            bar._on_system("fences")
            bar._on_system("launchpad")
            self.assertEqual(seen, ["fences", "launchpad"])
            bar.suspend()


if __name__ == "__main__":
    unittest.main()
