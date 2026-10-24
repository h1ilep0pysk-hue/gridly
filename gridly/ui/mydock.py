"""
ui/mydock.py
MyDock — копия MyDockFinder (панель приложений внизу экрана Windows).

Реализовано на PyQt6 + Win32 (ядро MyDockFinder):

  * нижний док-бар с настоящими иконками приложений;
  * закреплённые ярлыки берутся с панели задач
    (Quick Launch\\User Pinned\\TaskBar), как в оригинале;
  * запущенные приложения добавляются в док динамически (в оригинале —
    «динамические иконки запущенных программ»);
  * клик = активация, повторный клик по активному окну = свернуть в док;
  * точки запущенных приложений под иконками;
  * увеличение иконки при наведении с «волной» по соседям;
  * системное стекло через Acrylic blur, тёмная/светлая тема;
  * авто-скрытие с появлением у нижнего края экрана;
  * системные иконки: Finder (панель Gridly), Launchpad, Корзина;
  * ПКМ по иконке: активировать/свернуть/свернуть все/закрыть окна.

За рамками копии (в оригинале это D3D-анимации и внешние сервисы):
анимации сворачивания «джинн», предпросмотр окон по наведению,
счётчик непрочитанных сообщений, полоса прогресса загрузок, погода.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from PyQt6.QtCore import (QEasingCurve, QFileInfo, QPoint, QPropertyAnimation,
                          QPointF, QRectF, QSize, Qt, QTimer, pyqtProperty,
                          pyqtSignal)
from PyQt6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QIcon,
                         QLinearGradient, QPainter, QPalette, QPen, QPixmap)
from PyQt6.QtWidgets import (QApplication, QBoxLayout, QFileIconProvider,
                             QFrame, QMenu, QStyle, QWidget)

from core import win_shell
from core.storage import DATA_DIR, hex_to_bgr
from core.tweaks import MacTweaks
from ui.blur_effect import (disable_blur, enable_fence_blur,
                            hide_window_border)
from ui.mac_dock import make_dock_icon

logger = logging.getLogger("gridly.mydock")

_SYSTEM_SKIP_EXE = {
    "applicationframehost", "runtimebroker", "textinputhost", "searchhost",
    "shellexperiencehost", "startmenuexperiencehost", "widgets",
    "lockapp", "sihost", "ctfmon",
}


class _IconCache:
    """Кэш иконок ярлыков и exe-файлов."""

    def __init__(self) -> None:
        self._provider: QFileIconProvider | None = None
        self._cache: dict[str, QIcon] = {}

    def get(self, path: str) -> QIcon:
        if not path:
            return QIcon()
        key = path.casefold()
        if key not in self._cache:
            if self._provider is None:
                self._provider = QFileIconProvider()
            icon = self._provider.icon(QFileInfo(path))
            if icon.isNull():
                app = QApplication.instance()
                if app is not None:
                    icon = app.style().standardIcon(
                        QStyle.StandardPixmap.SP_ComputerIcon)
            self._cache[key] = icon
        return self._cache[key]


_ICONS = _IconCache()


def _fallback_icon(name: str, size: int = 64) -> QIcon:
    """Плейсхолдер для программ без извлекаемой иконки (UWP)."""
    seed = int(hashlib.md5(name.encode("utf-8", "ignore")).hexdigest()[:6], 16)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor.fromHsl(seed % 360, 165, 170))
    painter.setPen(QPen(QColor(255, 255, 255, 70), 2.0))
    radius = size * 0.235
    painter.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), radius, radius)
    font = QFont()
    font.setPixelSize(int(size * 0.44))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QPen(QColor(255, 255, 255, 235), 2.0))
    painter.drawText(QRectF(0, 0, size, size),
                     Qt.AlignmentFlag.AlignCenter,
                     (name[:1] or "?").upper())
    painter.end()
    return QIcon(pixmap)


class DockApp:
    """Пункт дока: закреплённый ярлык или запущенное приложение."""

    __slots__ = ("name", "path", "hwnds", "running", "icon")

    def __init__(self, name: str, path: str = "",
                 hwnds: list[int] | None = None, running: bool = False):
        self.name = name
        self.path = path
        self.hwnds = list(hwnds or [])
        self.running = running
        self.icon = _ICONS.get(path) if path else QIcon()

    def signature(self) -> tuple:
        return (self.name, self.path, len(self.hwnds), tuple(self.hwnds))


def collect_apps(debug: list | None = None) -> list[DockApp]:
    """Закреплённые ярлыки + динамические запущенные приложения."""
    items: list[DockApp] = []

    groups: dict[str, list[int]] = {}
    titles: dict[str, str] = {}
    for info in win_shell.list_windows(debug=debug):
        exe = (info.exe or "")
        stem = Path(exe).stem.casefold() if exe else ""
        if stem in _SYSTEM_SKIP_EXE:
            continue
        key = (f"exe:{exe.casefold()}" if exe
               else f"win:{info.title.casefold()}")
        groups.setdefault(key, []).append(info.hwnd)
        titles[key] = info.title

    taken: set[str] = set()
    for entry in win_shell.list_pinned():
        stem = Path(entry["path"]).stem.casefold()
        key = f"exe:{stem}.exe"
        if key not in groups:
            for candidate in list(groups):
                if candidate.startswith("exe:") and \
                        stem in Path(candidate[4:]).stem.casefold():
                    key = candidate
                    break
        hwnds = groups.get(key, [])
        taken.add(key)
        # Как в macOS: в доке только запущенные приложения.
        if hwnds:
            items.append(DockApp(entry["name"], entry["path"],
                                 hwnds=hwnds, running=True))

    for key, hwnds in groups.items():
        if key in taken:
            continue
        name = titles[key]
        exe = key[4:] if key.startswith("exe:") else ""
        items.append(DockApp(name, exe, hwnds=hwnds, running=True))
    return items


HOVER_LIFT = 4.0    # на сколько px иконка приподнимается при наведении

# Распределение дока по низу экрана (там, где раньше вырезалась панель задач):
# панель растягивается на всю свободную ширину, зазоры между иконками
# уравниваются. Приложений мало — зазоры растут до максимума, много — нет.
_FILL_SIDE = 12      # отступ панели от краёв экрана, px
_FILL_MIN_GAP = 3    # минимальный зазор, px
_FILL_MAX_GAP = 44   # максимальный зазор, px


def _glyph_size(tweaks: MacTweaks) -> int:
    return max(36, min(84, int(tweaks.dock_size)))


class _GlyphBase(QWidget):
    """Общая база иконки дока: увеличение, точки, подпись."""

    def __init__(self, tooltip: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._base = 54
        self._labels = False
        self._dots = True
        self._magnify = True
        self._animations = True
        self._hovered = False
        self._zoom = 0.0
        self._dark = True
        self._accent = QColor("#0a84ff")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self._anim = QPropertyAnimation(self, b"zoom", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._update_size()

    def configure(self, base: int, labels: bool, dots: bool,
                  magnify: bool, animations: bool) -> None:
        self._base = int(base)
        self._labels = bool(labels)
        self._dots = bool(dots)
        self._magnify = bool(magnify)
        self._animations = bool(animations)
        self._update_size()
        self.update()

    def _update_size(self) -> None:
        # Ячейка почти вплотную к иконке: промежутки задаёт сама панель.
        height = self._base + 12          # 5 px над иконкой, 7 px под точкой
        if self._labels:
            height += 15
        self.setFixedSize(QSize(self._base + 2, height))

    def set_dark(self, dark: bool) -> None:
        if self._dark != dark:
            self._dark = bool(dark)
            self.update()

    def set_accent(self, color: QColor) -> None:
        self._accent = QColor(color)
        self.update()

    # zoom ------------------------------------------------------------
    def get_zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float) -> None:
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._zoom) > 0.004:
            self._zoom = value
            self.update()

    zoom = pyqtProperty(float, fget=get_zoom, fset=set_zoom)

    def animate_zoom(self, target: float) -> None:
        if not self._animations:
            self.set_zoom(target)
            return
        self._anim.stop()
        self._anim.setStartValue(self._zoom)
        self._anim.setEndValue(max(0.0, min(1.0, float(target))))
        self._anim.start()

    def set_hovered(self, value: bool) -> None:
        self._hovered = bool(value)
        self.update()

    # события ----------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:
        bar = self.parent()
        if isinstance(bar, MyDockBar):
            bar.update_magnification()
        super().mouseMoveEvent(event)

    def resolution_scale(self) -> float:
        # Без приближения: иконка только чуть приподнимается при наведении.
        return 1.0

    def icon_top(self) -> float:
        """Y верхнего края иконки: 5 px от краёв, при наведении — подъём."""
        return 5.0 - HOVER_LIFT * self._zoom

    def icon_rect(self) -> QRectF:
        """Область иконки — та же формула, что и при отрисовке.

        По ней же считается клик, поэтому хитбокс совпадает с картинкой.
        """
        size = self._base * self.resolution_scale()
        x = (self.width() - size) / 2.0
        return QRectF(x, self.icon_top(), size, size)

    def paint_dot(self, painter: QPainter) -> None:
        if not self._dots or not getattr(self, "running", False):
            return
        center = QPointF(self.width() / 2.0, self.height() - 4.0)
        radius = max(2.2, self._base * 0.055)
        color = QColor(self._accent)
        color.setAlpha(235 if self._dark else 215)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)


class AppGlyph(_GlyphBase):
    """Реальная иконка приложения в Dock."""

    appClicked = pyqtSignal(object)

    def __init__(self, app: DockApp, parent: QWidget | None = None):
        super().__init__(app.name, parent)
        self.app = app

    @property
    def running(self) -> bool:
        return self.app.running

    def sync(self, app: DockApp) -> None:
        self.app = app
        self.setToolTip(app.name)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and \
                self.icon_rect().adjusted(-4, -4, 4, 4).contains(
                    QPointF(event.position())):
            self.appClicked.emit(self.app)
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._show_menu()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _show_menu(self) -> None:
        app = self.app
        bar = self.parent()
        dark = self._dark
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: rgba(30,31,36,246); color: #f4f4f6;"
            " border: 1px solid rgba(255,255,255,32); border-radius: 9px;"
            " padding: 4px; }"
            "QMenu::item { padding: 5px 16px; border-radius: 6px; }"
            "QMenu::item:selected { background: rgba(255,255,255,26); }"
            if dark else
            "QMenu { background: rgba(250,250,252,248); color: #1d1d1f;"
            " border: 1px solid rgba(0,0,0,26); border-radius: 9px;"
            " padding: 4px; }"
            "QMenu::item { padding: 5px 16px; border-radius: 6px; }"
            "QMenu::item:selected { background: rgba(0,0,0,22); }"
        )
        if app.running:
            foreground = win_shell.IS_WINDOWS \
                and win_shell.window_is_foreground(app.hwnds[0])
            menu.addAction(
                "Свернуть в Dock" if foreground else "Активировать",
                lambda: bar._activate(app))
            if len(app.hwnds) > 1:
                menu.addAction(
                    f"Свернуть все ({len(app.hwnds)})",
                    lambda: bar._minimize_all(app))
                menu.addSeparator()
                menu.addAction(
                    "Закрыть все окна" if len(app.hwnds) > 1
                    else "Закрыть окно",
                    lambda: bar._close_all(app))
            else:
                menu.addSeparator()
                menu.addAction("Закрыть окно", lambda: bar._close_all(app))
        else:
            menu.addAction("Запустить", lambda: bar._launch(app))
        menu.exec(self.mapToGlobal(
            QPoint(self.width(), self.height())))

    def _icon_pixmap(self, px: int) -> QPixmap:
        """Пиксмап иконки; если реальная иконка не отрисовалась — запасная."""
        icon = self.app.icon if self.app.path else QIcon()
        if not icon.isNull():
            pixmap = icon.pixmap(px, px)
            if not pixmap.isNull():
                return pixmap
        return _fallback_icon(self.app.name).pixmap(px, px)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        icon_px = int(self._base * self.resolution_scale())
        pixmap = self._icon_pixmap(icon_px)
        # Размер в логических пикселях: при масштабе 125/150% центрирование
        # не съезжает.
        size = pixmap.deviceIndependentSize()
        if not pixmap.isNull():
            painter.drawPixmap(
                QPointF((self.width() - size.width()) / 2.0,
                        self.icon_top()),
                pixmap)
        self.paint_dot(painter)
        painter.end()


class SysGlyph(_GlyphBase):
    """Системная иконка дока (Finder / Launchpad / Корзина)."""

    systemClicked = pyqtSignal(str)

    def __init__(self, action: str, label: str,
                 parent: QWidget | None = None):
        super().__init__(label, parent)
        self.action = action
        self.pixmap_icon = make_dock_icon(
            action if action != "trash" else "trash", 64)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and \
                self.rect().contains(event.position().toPoint()):
            self.systemClicked.emit(self.action)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        icon_px = self._base * self.resolution_scale()
        pixmap = self.pixmap_icon.pixmap(int(icon_px), int(icon_px))
        if not pixmap.isNull():
            size = pixmap.deviceIndependentSize()
            painter.drawPixmap(
                QPointF((self.width() - size.width()) / 2.0,
                        self.icon_top()),
                pixmap)
        painter.end()


def _separator(dark: bool) -> QFrame:
    line = QFrame()
    line.setFixedSize(1, 30)
    line.setStyleSheet(
        f"QFrame {{ background: rgba(255,255,255,{46 if dark else 36});"
        f" border: none; }}")
    return line


class MyDockBar(QWidget):
    """Копия MyDock: панель приложений внизу экрана."""

    systemRequested = pyqtSignal(str)

    def __init__(self, tweaks: MacTweaks | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.tweaks = tweaks or MacTweaks()
        self._buttons: list[tuple[_GlyphBase, object]] = []
        self._signature: tuple | None = None
        self._apps: list[DockApp] = []
        self._hidden_by_autohide = False
        self._blur_enabled = False
        self._locked = False

        self.setWindowTitle("Gridly MyDock")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(3)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self.refresh)

        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(250)
        self._topmost_timer.timeout.connect(self._keep_on_top)

        # Якорь — единственная позиция дока. Пересчитывается только при
        # изменении геометрии основного экрана.
        self._anchor: QPoint | None = None
        self._top_ticks = 0
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            screen.geometryChanged.connect(lambda _r: self._reposition())
            screen.availableGeometryChanged.connect(
                lambda _r: self._reposition())

        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(120)
        self._edge_timer.timeout.connect(self._poll_edge)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(700)
        self._hide_timer.timeout.connect(self._autohide)

        self.refresh()
        self.apply_tweaks(self.tweaks)

    # ------------------------------------------------------------- config
    def set_locked(self, locked: bool) -> None:
        """Пока MyDock работает, обычный Dock Gridly функцию уступает."""
        if self._locked != locked:
            self._locked = bool(locked)
            if self._locked:
                self._edge_timer.stop()
                self._hide_timer.stop()
                self._hidden_by_autohide = False
                self.hide()
                self._disable_blur()

    def suspend(self) -> None:
        """Полностью останавливает MyDock: таймеры, показ и размытие."""
        self._refresh_timer.stop()
        self._edge_timer.stop()
        self._hide_timer.stop()
        self._topmost_timer.stop()
        self._hidden_by_autohide = False
        self.hide()
        self._disable_blur()

    def _current_base(self) -> int:
        """Размер иконок всегда один — без приближения и сжатия."""
        return _glyph_size(self.tweaks)

    def _keep_on_top(self) -> None:
        """Возвращает док на якорь и поверх Пуска/панели задач.

        Возврат на якорь — каждые 250 мс (дёшево, без перерисовки).
        Перестановка z-порядка — раз в секунду: частые SetWindowPos дают
        рывки отрисовки.
        """
        if not self.isVisible():
            return
        if self._anchor is not None and self.pos() != self._anchor:
            self.move(self._anchor)
        self._top_ticks = (self._top_ticks + 1) % 4
        if self._top_ticks == 0:
            win_shell.raise_topmost(int(self.winId()))

    def _dump_debug(self) -> None:
        """Диагностика: все окна и причина, почему они не в доке.

        Включается переменной окружения GRIDLY_DOCK_DEBUG=1; файл —
        data/dock_debug.txt.
        """
        rows: list = []
        collect_apps(debug=rows)
        lines = [f"hwnd\t{'shown?':8}\tclass\ttitle\treason"]
        for hwnd, title, cls, reason in rows:
            lines.append(f"{hwnd}\t{reason:8}\t{cls}\t{title}")
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            (DATA_DIR / "dock_debug.txt").write_text(
                "\n".join(lines), encoding="utf-8")
        except OSError:
            pass

    def _is_dark(self) -> bool:
        if self.tweaks.appearance == "dark":
            return True
        if self.tweaks.appearance == "light":
            return False
        palette = QGuiApplication.palette()
        return palette.color(
            QPalette.ColorRole.Window).lightness() < 128

    def apply_tweaks(self, tweaks: MacTweaks) -> None:
        self.tweaks = tweaks
        dark = self._is_dark()
        enabled = bool(tweaks.enabled and tweaks.mydock_enabled) \
            and not self._locked
        for glyph, _item in self._buttons:
            glyph.set_dark(dark)
            glyph.set_accent(QColor(tweaks.accent))
            glyph.configure(self._current_base(), tweaks.dock_labels,
                            tweaks.dock_dots, tweaks.dock_magnify,
                            tweaks.animations)
        self._apply_distribution()
        self._reposition()
        self.update()

        if not enabled:
            self._refresh_timer.stop()
            self._topmost_timer.stop()
            self._edge_timer.stop()
            self._hide_timer.stop()
            self._hidden_by_autohide = False
            self.hide()
            self._disable_blur()
            return

        self._refresh_timer.start()
        self._topmost_timer.start()
        if tweaks.dock_autohide:
            self._edge_timer.start()
            if not self._cursor_near_edge():
                self._hidden_by_autohide = True
                self.hide()
                return
        else:
            self._edge_timer.stop()
            self._hidden_by_autohide = False
        self._reveal()

    # ------------------------------------------------------------ refresh
    def _log_window_state(self, rows: list) -> None:
        """Пишет в консоль, какие окна попали в док и почему остальные нет.

        Лог пишется только когда набор окон меняется, а не каждый тик.
        """
        sig = tuple((h, t, r) for h, t, _c, r in rows if t)
        if sig == getattr(self, "_log_sig", None):
            return
        self._log_sig = sig
        shown = [t for _h, t, _c, r in rows if r == "shown" and t]
        logger.info("MyDock: в доке %d окон: %s",
                    len(shown), " | ".join(shown) or "-")
        for _h, title, cls, reason in rows:
            if title and reason != "shown":
                logger.info("MyDock: окно не в доке (%s): %r [class=%s]",
                            reason, title, cls)

    def refresh(self) -> None:
        if os.environ.get("GRIDLY_DOCK_DEBUG"):
            self._dump_debug()
        rows: list = []
        self._apps = collect_apps(debug=rows)
        self._log_window_state(rows)
        # Пересобираем иконки только когда меняется набор приложений.
        # Смена окна, точки или числа окон — обновляем иконки на месте.
        signature = tuple((app.name, app.path) for app in self._apps)
        if signature != self._signature:
            self._signature = signature
            self._repopulate()
        else:
            fresh_by_key = {(app.name, app.path): app for app in self._apps}
            for glyph, item in self._buttons:
                if isinstance(item, DockApp):
                    fresh_by_key.get((item.name, item.path)) and \
                        glyph.sync(fresh_by_key[(item.name, item.path)])

    def _repopulate(self) -> None:
        # takeAt() снимает виджет только с layout: без hide/deleteLater старые
        # иконки остались бы видимыми поверх новых.
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._buttons = []

        dark = self._is_dark()
        tweaks = self.tweaks

        usable = self._fill_width()
        cell = self._current_base() + 2     # ширина одной ячейки-иконки
        if usable > 0:
            # cell + зазор на иконку; зазор при минимумах уже заложен.
            max_apps = max(3, (usable - 2 * _FILL_SIDE) // (cell + 4))
        else:
            max_apps = 12
        for app in self._apps[:max_apps]:
            glyph = AppGlyph(app)
            glyph.appClicked.connect(self._activate)
            self._layout.addWidget(glyph)
            self._buttons.append((glyph, app))

        for glyph, _item in self._buttons:
            glyph.set_dark(dark)
            glyph.set_accent(QColor(tweaks.accent))
            glyph.configure(self._current_base(), tweaks.dock_labels,
                            tweaks.dock_dots, tweaks.dock_magnify,
                            tweaks.animations)
        self._apply_distribution()
        self._reposition()
        self.update()

    # ------------------------------------------------------------ actions
    def _launch(self, app: DockApp) -> None:
        if app.path:
            win_shell.launch_path(app.path)

    def _activate(self, app: DockApp) -> None:
        if not app.running:
            self._launch(app)
        elif app.hwnds:
            win_shell.toggle_window(app.hwnds[0])

    def _minimize_all(self, app: DockApp) -> None:
        for hwnd in app.hwnds:
            win_shell.minimize_window(hwnd)

    def _close_all(self, app: DockApp) -> None:
        for hwnd in app.hwnds:
            win_shell.close_window(hwnd)

    def _on_system(self, action: str) -> None:
        if action == "trash":
            win_shell.open_recycle_bin()
            return
        self.systemRequested.emit(action)

    # ------------------------------------------------------ magnification
    def update_magnification(self) -> None:
        if not self.tweaks.dock_magnify:
            return
        pos = QCursor.pos()
        for glyph, _item in self._buttons:
            center = glyph.mapToGlobal(glyph.rect().center())
            distance = abs(QPointF(pos.x(), pos.y()).x() - center.x())
            falloff = glyph.width() * 1.15
            zoom = max(0.0, 1.0 - distance / falloff) ** 1.6
            glyph.set_zoom(zoom)
            glyph.set_hovered(zoom > 0.55)

    def mouseMoveEvent(self, event) -> None:
        self.update_magnification()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        for glyph, _item in self._buttons:
            glyph.animate_zoom(0.0)
            glyph.set_hovered(False)
        if self.tweaks.dock_autohide and self.isVisible():
            self._hide_timer.start()
        super().leaveEvent(event)

    # ------------------------------------------------------------- layout
    def _fill_width(self) -> int:
        """Свободная ширина низа экрана под док.

        Панель задач прячет мак-оболочка — значит, весь низ экрана
        (там, где раньше вырезалась панель) отдан доку. Иначе укладываемся
        в доступную область, не наступая на живую панель задач.
        """
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 0
        if self.tweaks.enabled and self.tweaks.shell_enabled:
            geo = screen.geometry()
        else:
            geo = screen.availableGeometry()
        return max(160, geo.width() - 2 * _FILL_SIDE)

    def _apply_distribution(self) -> None:
        """Заполняет пустую ширину дока равными промежутками.

        Оставшееся место делится на n + 1 частей: по одной на каждый зазор
        между иконками и по одной на левый и правый край. Панель занимает
        почти весь низ экрана, иконки всегда одинакового размера — пустота
        уходит в зазоры, а не в раздутые ячейки.
        """
        widgets = [self._layout.itemAt(i).widget()
                   for i in range(self._layout.count())]
        usable = self._fill_width()
        content = 0
        for widget in widgets:
            content += widget.sizeHint().width()
        if usable <= 0 or not widgets:
            gap = 6
        else:
            gap = (usable - content) / (len(widgets) + 1)
            gap = max(_FILL_MIN_GAP, min(_FILL_MAX_GAP, int(gap)))
        self._layout.setContentsMargins(gap, 4, gap, 4)
        self._layout.setSpacing(gap)

    def _reposition(self) -> None:
        # Всегда основной монитор: позиция не зависит от курсора.
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        # Панель задач Windows прячет только мак-оболочка; тогда док садится
        # на самый низ экрана, иначе — над видимой панелью задач.
        if self.tweaks.enabled and self.tweaks.shell_enabled:
            geo = screen.geometry()
            bottom_gap = 3
        else:
            geo = screen.availableGeometry()
            bottom_gap = 6
        self._fit()
        x = geo.left() + (geo.width() - self.width()) // 2
        # Видимая панель вписана в окно с отступом 4 px с каждой стороны,
        # поэтому нижний край панели = низ окна − 4 + зазор.
        y = geo.bottom() - self.height() + 4 - bottom_gap
        self._anchor = QPoint(max(geo.left(), x), y)
        if self.pos() != self._anchor:
            self.move(self._anchor)

    def _fit(self) -> None:
        """Подгоняет размер окна под актуальный layout.

        adjustSize() до пересчёта layout давал старую ширину (видны только
        первые иконки) и высоту (док съезжал вниз), поэтому layout сначала
        активируется, а размер берётся из totalSizeHint.
        """
        self._layout.invalidate()
        self._layout.activate()
        self.resize(self._layout.totalSizeHint())

    # ------------------------------------------------------------ autohide
    def _cursor_near_edge(self) -> bool:
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.availableGeometry()
        return QCursor.pos().y() >= geo.bottom() - 7

    def _poll_edge(self) -> None:
        if not (self.tweaks.enabled and self.tweaks.mydock_enabled
                and self.tweaks.dock_autohide):
            return
        if self._hidden_by_autohide:
            if self._cursor_near_edge():
                self._reveal()
        elif self.isVisible() and \
                not self.geometry().adjusted(-10, -10, 10, 4).contains(
                    QCursor.pos()) and not self._hide_timer.isActive():
            self._hide_timer.start()

    def _autohide(self) -> None:
        if not (self.tweaks.enabled and self.tweaks.mydock_enabled
                and self.tweaks.dock_autohide):
            return
        if self.geometry().adjusted(-4, -4, 4, 4).contains(QCursor.pos()):
            return
        self._hidden_by_autohide = True
        self.hide()

    def _reveal(self) -> None:
        self._hidden_by_autohide = False
        self._hide_timer.stop()
        self.show()
        self.raise_()
        QTimer.singleShot(0, self._apply_blur)

    # ---------------------------------------------------------------- blur
    def _apply_blur(self) -> None:
        if not self.isVisible():
            self._disable_blur()
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        # Убираем только системную рамку. Скругление углов не трогаем:
        # без него фон становится квадратным.
        hide_window_border(hwnd)
        if not self.tweaks.dock_glass:
            self._disable_blur()
            return
        alpha = max(40, min(210, 170 - int(self.tweaks.translucency)))
        tint = "#1c1c1e" if self._is_dark() else "#f2f3f7"
        try:
            enable_fence_blur(hwnd, hex_to_bgr(tint), alpha)
            self._blur_enabled = True
        except Exception:
            self._blur_enabled = False

    def _disable_blur(self) -> None:
        if not self._blur_enabled:
            return
        try:
            disable_blur(int(self.winId()))
        except Exception:
            pass
        self._blur_enabled = False

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        radius = min(rect.height() / 2.0, 26.0)
        dark = self._is_dark()

        if self.tweaks.shadows:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 95))
            painter.drawRoundedRect(rect.translated(0, 4), radius, radius)

        if self.tweaks.dock_glass:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if dark:
                gradient.setColorAt(0.0, QColor(50, 52, 60, 224))
                gradient.setColorAt(0.55, QColor(29, 30, 36, 216))
                gradient.setColorAt(1.0, QColor(17, 18, 22, 208))
            else:
                gradient.setColorAt(0.0, QColor(255, 255, 255, 230))
                gradient.setColorAt(0.55, QColor(244, 245, 249, 222))
                gradient.setColorAt(1.0, QColor(232, 234, 240, 214))
            painter.setBrush(gradient)
        else:
            painter.setBrush(QColor(27, 28, 33, 245) if dark
                             else QColor(246, 247, 250, 250))
        if self.tweaks.dock_glass:
            # В режиме стекла серую обводку не рисуем — только стекло.
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 42) if dark
                                else QColor(0, 0, 0, 30), 1.0))
        painter.drawRoundedRect(rect, radius, radius)

        if self.tweaks.dock_glass:
            sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if dark:
                sheen.setColorAt(0.0, QColor(255, 255, 255, 36))
                sheen.setColorAt(0.45, QColor(255, 255, 255, 4))
                sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            else:
                sheen.setColorAt(0.0, QColor(255, 255, 255, 208))
                sheen.setColorAt(0.45, QColor(255, 255, 255, 38))
                sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(sheen)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1),
                                    radius - 1, radius - 1)
        painter.end()

    # -------------------------------------------------------------- events
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._reposition()
        QTimer.singleShot(0, self._apply_blur)

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        super().enterEvent(event)
