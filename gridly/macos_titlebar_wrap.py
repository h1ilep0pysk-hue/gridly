"""
macos_titlebar_wrap.py
Замена нативного заголовка окон выбранных приложений собственной плашкой
(кнопки закрыть / свернуть / развернуть + название). macOS, PyObjC.

Модуль — библиотека: его запускает macos_global_overlay.py, когда в
настройках включено «Заголовки окон». Работает в том же процессе и на том
же цикле событий, что и панель.

Как это работает
  * Accessibility (AXUIElement): читаем и двигаем чужие окна, нажимаем
    их нативные кнопки (AXPress). Нужно право «Универсальный доступ».
  * CoreGraphics (CGWindowListCopyWindowInfo): слой и порядок окон.
    Если над полосой заголовка окно другого процесса — плашка скрывается.
    Права «Запись экрана» не нужны: берём только границы и PID.
  * Координаты: AX и CG — начало в левом верхнем углу главного экрана,
    AppKit — в левом нижнем. Пересчёт через высоту главного экрана.
  * NSPanel без рамки, nonactivating (не крадёт фокус), уровень =
    слой целевого окна + 1.
  * Синхронизация: таймер ~60 Гц. Перетаскивание плашки двигает окно
    сразу, в обработчике мыши.

Ограничения
  * Нативный заголовок не удаляется, он закрывается плашкой.
  * Высота 28 pt по умолчанию. У окон с тулбаром (Safari, Mail) и у Chrome
    с вкладками задайте свою высоту в titlebar_heights.
  * Полноэкранные окна, листы и поповеры пропускаются.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import objc
from AppKit import (NSBezierPath, NSColor, NSEvent, NSFont,
                    NSFontAttributeName, NSForegroundColorAttributeName,
                    NSObject, NSPanel, NSScreen, NSString, NSTimer, NSView,
                    NSWorkspace)
from ApplicationServices import (AXIsProcessTrustedWithOptions,
                                 AXUIElementCopyAttributeValue,
                                 AXUIElementCreateApplication,
                                 AXUIElementPerformAction,
                                 AXUIElementSetAttributeValue,
                                 AXUIElementSetMessagingTimeout,
                                 AXValueCreate, AXValueGetValue,
                                 kAXTrustedCheckOptionPrompt,
                                 kAXValueCGPointType, kAXValueCGSizeType)
from CoreFoundation import CFEqual
from Quartz import (CGPoint, CGWindowListCopyWindowInfo,
                    kCGNullWindowID, kCGWindowBounds, kCGWindowLayer,
                    kCGWindowListExcludeDesktopElements,
                    kCGWindowListOptionOnScreenOnly, kCGWindowOwnerPID)

TITLEBAR_DEFAULT = 28
TICK_HZ = 60
DISCOVERY_EVERY = 30          # поиск новых окон раз в N тиков
AX_TIMEOUT = 0.25             # не даём зависшему приложению тормозить нас

BUTTON_X = (16.0, 36.0, 56.0)  # центры кнопок по X от левого края плашки
BUTTON_R = 6.5
BUTTON_COLORS = (
    (1.000, 0.373, 0.341),    # закрыть
    (0.996, 0.737, 0.180),    # свернуть
    (0.157, 0.784, 0.251),    # развернуть
)
AX_OK = 0


def ensure_accessibility(prompt: bool = False) -> bool:
    """True, если процессу выдан доступ «Универсальный доступ»."""
    return bool(AXIsProcessTrustedWithOptions(
        {kAXTrustedCheckOptionPrompt: bool(prompt)}))


# ------------------------------------------------------------ AX-хелперы
def ax_get(element, attribute):
    err, value = AXUIElementCopyAttributeValue(element, attribute, None)
    return value if err == AX_OK else None


def ax_point(element):
    value = ax_get(element, "AXPosition")
    if value is None:
        return None
    ok, pt = AXValueGetValue(value, kAXValueCGPointType, None)
    return (float(pt.x), float(pt.y)) if ok else None


def ax_size(element):
    value = ax_get(element, "AXSize")
    if value is None:
        return None
    ok, sz = AXValueGetValue(value, kAXValueCGSizeType, None)
    return (float(sz.width), float(sz.height)) if ok else None


def ax_set_point(element, x: float, y: float) -> bool:
    value = AXValueCreate(kAXValueCGPointType, CGPoint(x, y))
    return AXUIElementSetAttributeValue(element, "AXPosition", value) == AX_OK


# ------------------------------------------------------------ геометрия
def _primary_height() -> float:
    return float(NSScreen.screens()[0].frame().size.height)


def _ax_strip_to_appkit(x, y, w, strip):
    return ((x, _primary_height() - y - strip), (w, strip))


def _intersects(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


@dataclass
class _CGEntry:
    pid: int
    layer: int
    x: float
    y: float
    w: float
    h: float


class WindowSnapshot:
    """Окна экрана front-to-back. Один вызов CG на тик."""

    def __init__(self):
        raw = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly
            | kCGWindowListExcludeDesktopElements,
            kCGNullWindowID,
        ) or []
        self.entries: list[_CGEntry] = []
        for info in raw:
            b = info.get(kCGWindowBounds) or {}
            self.entries.append(_CGEntry(
                pid=int(info.get(kCGWindowOwnerPID, 0)),
                layer=int(info.get(kCGWindowLayer, 0)),
                x=float(b.get("X", 0)), y=float(b.get("Y", 0)),
                w=float(b.get("Width", 0)), h=float(b.get("Height", 0)),
            ))

    def index_of(self, pid: int, frame):
        x, y, w, h = frame
        for i, e in enumerate(self.entries):
            if (e.pid == pid and abs(e.x - x) <= 2 and abs(e.y - y) <= 2
                    and abs(e.w - w) <= 2 and abs(e.h - h) <= 2):
                return i
        return None

    def covered(self, idx: int, strip: int, own_pid: int) -> bool:
        target = self.entries[idx]
        band = (target.x, target.y, target.w, float(strip))
        for other in self.entries[:idx]:          # только окна сверху
            if other.pid in (target.pid, own_pid):
                continue
            if other.layer != target.layer:
                continue
            if _intersects((other.x, other.y, other.w, other.h), band):
                return True
        return False


# ------------------------------------------------------------ плашка
class TitlebarView(NSView):
    """Рисует плашку и обрабатывает клики: кнопки, перетаскивание, зум."""

    def initWithFrame_(self, frame):
        self = objc.super(TitlebarView, self).initWithFrame_(frame)
        if self is None:
            return None
        self.model = None
        self._drag = None
        return self

    def acceptsFirstMouse_(self, event):
        return True

    def isOpaque(self):
        return True

    def drawRect_(self, rect):
        model = self.model
        bounds = self.bounds()
        NSColor.colorWithCalibratedWhite_alpha_(0.14, 1.0).set()
        NSBezierPath.fillRect_(bounds)

        cy = bounds.size.height / 2.0
        for cx, (r, g, bl) in zip(BUTTON_X, BUTTON_COLORS):
            NSColor.colorWithCalibratedRed_green_blue_alpha_(
                r, g, bl, 1.0).set()
            NSBezierPath.bezierPathWithOvalInRect_(
                ((cx - BUTTON_R, cy - BUTTON_R),
                 (BUTTON_R * 2, BUTTON_R * 2))).fill()

        title = (model.title if model else "") or ""
        attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
            NSForegroundColorAttributeName:
                NSColor.colorWithCalibratedWhite_alpha_(0.92, 1.0),
        }
        text = NSString.stringWithString_(title)
        size = text.sizeWithAttributes_(attrs)
        text.drawAtPoint_withAttributes_(
            ((bounds.size.width - size.width) / 2.0,
             (bounds.size.height - size.height) / 2.0),
            attrs,
        )

    def _button_at(self, point):
        cy = self.bounds().size.height / 2.0
        for i, cx in enumerate(BUTTON_X):
            if (point.x - cx) ** 2 + (point.y - cy) ** 2 <= (BUTTON_R + 2) ** 2:
                return i
        return None

    def mouseDown_(self, event):
        model = self.model
        if model is None:
            return
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        idx = self._button_at(point)
        if idx is not None:
            model.press(idx)
            return
        if event.clickCount() == 2:           # двойной клик по плашке = зум
            model.press(2)
            return
        pos = model.current_position() or (0.0, 0.0)
        self._drag = (NSEvent.mouseLocation(), pos)

    def mouseDragged_(self, event):
        if self._drag is None or self.model is None:
            return
        start, (ox, oy) = self._drag
        now = NSEvent.mouseLocation()
        # AppKit: y растёт вверх, AX: y растёт вниз.
        self.model.move_to(ox + (now.x - start.x), oy - (now.y - start.y))

    def mouseUp_(self, event):
        self._drag = None


def _make_panel(strip: int):
    rect = ((0.0, 0.0), (100.0, float(strip)))
    style = 0 | (1 << 7)                     # borderless | nonactivatingPanel
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, 2, False)               # 2 = NSBackingStoreBuffered
    view = TitlebarView.alloc().initWithFrame_(rect)
    panel.setContentView_(view)
    panel.setFloatingPanel_(False)           # иначе NSPanel поднимет уровень
    panel.setOpaque_(True)
    panel.setHasShadow_(False)
    panel.setHidesOnDeactivate_(False)
    panel.setReleasedWhenClosed_(False)
    panel.setBecomesKeyOnlyIfNeeded_(True)
    # canJoinAllSpaces | stationary | fullScreenAuxiliary
    panel.setCollectionBehavior_((1 << 0) | (1 << 4) | (1 << 8))
    panel.setLevel_(1)
    return panel, view


# ------------------------------------------------------------ окно
class ManagedWindow:
    """Одно чужое окно и его плашка."""

    def __init__(self, ax_window, pid: int, strip: int):
        self.ax = ax_window
        self.pid = pid
        self.strip = strip
        self.title = ""
        self._frame = None          # (x, y, w, h), AX-координаты
        self._layer = 0
        self._placed_key = None
        self._visible = False
        self.panel, self.view = _make_panel(strip)
        self.view.model = self

    def current_position(self):
        return ax_point(self.ax)

    def move_to(self, x: float, y: float) -> None:
        """Двигает окно из мыши и сразу переставляет плашку."""
        if not ax_set_point(self.ax, x, y):
            return
        if self._frame is not None:
            _, _, w, h = self._frame
            self._frame = (x, y, w, h)
            self._place()

    def press(self, idx: int) -> None:
        attr = ("AXCloseButton", "AXMinimizeButton", "AXZoomButton")[idx]
        button = ax_get(self.ax, attr)
        if button is not None:
            AXUIElementPerformAction(button, "AXPress")

    def sync(self, snap: WindowSnapshot, own_pid: int) -> bool:
        """Обновляет плашку по окну. False — окно исчезло."""
        pos = ax_point(self.ax)
        size = ax_size(self.ax)
        if pos is None or size is None:
            return False
        self._frame = (pos[0], pos[1], size[0], size[1])

        title = ax_get(self.ax, "AXTitle") or ""
        if title != self.title:
            self.title = title
            self.view.setNeedsDisplay_(True)

        if ax_get(self.ax, "AXMinimized") or ax_get(self.ax, "AXFullScreen"):
            self._hide()
            return True

        idx = snap.index_of(self.pid, self._frame)
        if idx is None or snap.covered(idx, self.strip, own_pid):
            self._hide()
            return True

        self._layer = snap.entries[idx].layer
        self._place()
        return True

    def _place(self) -> None:
        x, y, w, _ = self._frame
        key = (x, y, w, self.strip, self._layer)
        if key != self._placed_key:
            self.panel.setLevel_(self._layer + 1)
            self.panel.setFrame_display_(
                _ax_strip_to_appkit(x, y, w, self.strip), True)
            self._placed_key = key
        if not self._visible:
            self.panel.orderFront_(None)
            self._visible = True

    def _hide(self) -> None:
        if self._visible:
            self.panel.orderOut_(None)
            self._visible = False

    def destroy(self) -> None:
        self._hide()


# ------------------------------------------------------------ контроллер
class TitlebarController(NSObject):
    """Ведёт все обёрнутые окна. Создавать через alloc().init() + configure()."""

    def init(self):
        self = objc.super(TitlebarController, self).init()
        if self is None:
            return None
        self.bundles: set[str] = set()
        self.heights: dict[str, int] = {}
        self.managed: list[ManagedWindow] = []
        self.own_pid = os.getpid()
        self.tick_count = 0
        self.timer = None
        return self

    @objc.python_method
    def configure(self, bundles, heights=None) -> None:
        self.bundles = set(bundles)
        self.heights = dict(heights or {})

    @objc.python_method
    def start(self) -> None:
        if self.timer is not None:
            return
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0 / TICK_HZ, self, "tick:", None, True)

    @objc.python_method
    def stop(self) -> None:
        if self.timer is not None:
            self.timer.invalidate()
            self.timer = None
        for mw in self.managed:
            mw.destroy()
        self.managed = []

    @objc.python_method
    def _strip_for(self, bundle_id: str) -> int:
        return int(self.heights.get(bundle_id, TITLEBAR_DEFAULT))

    @objc.python_method
    def discover(self) -> None:
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            bundle_id = app.bundleIdentifier()
            if bundle_id not in self.bundles:
                continue
            pid = int(app.processIdentifier())
            ax_app = AXUIElementCreateApplication(pid)
            AXUIElementSetMessagingTimeout(ax_app, AX_TIMEOUT)
            for win in ax_get(ax_app, "AXWindows") or []:
                if ax_get(win, "AXRole") != "AXWindow":
                    continue
                if ax_get(win, "AXSubrole") not in ("AXStandardWindow",
                                                    "AXDialog"):
                    continue
                if any(CFEqual(mw.ax, win) for mw in self.managed):
                    continue
                self.managed.append(ManagedWindow(
                    win, pid, self._strip_for(bundle_id)))

    def tick_(self, timer) -> None:
        self.tick_count += 1
        if self.tick_count % DISCOVERY_EVERY == 1:
            self.discover()
        snap = WindowSnapshot()
        alive = []
        for mw in self.managed:
            if mw.sync(snap, self.own_pid):
                alive.append(mw)
            else:
                mw.destroy()
        self.managed = alive
