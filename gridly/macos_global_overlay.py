"""
macos_global_overlay.py
Глобальная macOS-панель (замена Dock) на PyObjC.

Запуск на macOS:
    python3 -m pip install -r requirements-macos.txt
    python3 macos_global_overlay.py

Что делает:
  * окно без рамки, не ворующее фокус;
  * уровень NSMainMenuWindowLevel (или NSFloatingWindowLevel, если выбран
    во вкладке «Твики») — выше обычных окон и Dock;
  * видно на всех Spaces / в полноэкранных приложениях;
  * матовое стекло NSVisualEffectView (HUDWindow);
  * в панели — иконки всех запущенных обычных приложений;
  * клик по иконке активирует приложение, повторный клик скрывает;
  * часы, разделитель и кнопка «…» для приложений, не влезших в панель;
  * приложение работает как accessory: без иконки в Dock, только status item
    в верхнем меню (там же «Скрыть панель» и «Выход»);
  * настройки (часы, число иконок, уровень, вкл/выкл) берутся из
    macos_overlay.json рядом со скриптом — его пишет вкладка «Твики» Gridly.

Важно: macOS не даёт публичного API, чтобы полностью убрать системный Dock.
Панель рисуется ПОВЕРХ него (level 24 > level Dock 20). Если системный Dock
мешает, включи автоматическое скрытие Dock в System Settings → Desktop & Dock.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import objc
from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSApplicationDidChangeScreenParametersNotification,
    NSBackingStoreBuffered,
    NSBezelStyleRegularSquare,
    NSButton,
    NSColor,
    NSDate,
    NSDateFormatter,
    NSFont,
    NSFontWeightMedium,
    NSImage,
    NSImageOnly,
    NSImageScaleProportionallyDown,
    NSLayoutAttributeCenterY,
    NSLayoutConstraint,
    NSLocale,
    NSFloatingWindowLevel,
    NSMainMenuWindowLevel,
    NSMakePoint,
    NSMakeRect,
    NSMakeSize,
    NSMenu,
    NSMenuItem,
    NSPanel,
    NSScreen,
    NSStackView,
    NSStatusBar,
    NSTextAlignmentCenter,
    NSTextField,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSVariableStatusItemLength,
    NSView,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorIgnoresCycle,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWorkspaceDidLaunchApplicationNotification,
    NSWorkspaceDidTerminateApplicationNotification,
)
from Foundation import NSNotificationCenter, NSObject, NSTimer
from Quartz import CALayer

# Заголовки окон: модуль лежит рядом; если PyObjC не хватает — панель работает.
try:
    from macos_titlebar_wrap import TitlebarController, ensure_accessibility
    _TITLEBAR_IMPORT_ERROR = None
except Exception as _exc:  # pragma: no cover - зависит от окружения macOS
    TitlebarController = None
    ensure_accessibility = None
    _TITLEBAR_IMPORT_ERROR = _exc


# ---------------------------------------------------------------------------
# Настройки внешнего вида
# ---------------------------------------------------------------------------
PANEL_HEIGHT = 64.0
PANEL_CORNER = 18.0
ICON_SIZE = 40.0
BUTTON_SIZE = 46.0
MAX_VISIBLE_APPS = 14
CLOCK_WIDTH = 156.0
CLOCK_FORMAT = "EEE, d MMM  HH:mm"
CLOCK_LOCALE = "ru_RU"

# Пассивная панель не должна становиться key. Если на конкретной версии
# macOS кнопки реагируют только со второго клика, поставь True:
# nonactivating-панель всё равно не сделает приложение активным.
PANEL_CAN_BECOME_KEY = False


# ---------------------------------------------------------------------------
# Настройки из Gridly (вкладка «Твики» / macos_overlay.json)
# ---------------------------------------------------------------------------
def _load_overlay_settings() -> dict:
    """Читает конфиг рядом со скриптом, затем data/tweaks.json проекта.

    Возвращает {} при их отсутствии — тогда работают значения по умолчанию.
    """
    here = Path(__file__).resolve().parent
    candidates = (
        here / "macos_overlay.json",
        here.parent / "data" / "tweaks.json",
    )
    for path in candidates:
        try:
            if not path.exists():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Не удалось прочитать {path.name}: {exc}")
            continue
        if not isinstance(raw, dict):
            continue
        if "macos_overlay" in raw and isinstance(raw["macos_overlay"], dict):
            return dict(raw["macos_overlay"])
        if "overlay_enabled" in raw:  # плоский dict из data/tweaks.json
            return {
                "enabled": raw.get("overlay_enabled"),
                "level": raw.get("overlay_level"),
                "max_apps": raw.get("overlay_max_apps"),
                "clock": raw.get("overlay_clock"),
                "titlebar_enabled": raw.get("titlebar_wrap_enabled"),
                "titlebar_bundles": raw.get("titlebar_wrap_bundles"),
            }
        return dict(raw)  # одиночный sidecar со схемой оверлея
    return {}


_OVERLAY_SETTINGS = _load_overlay_settings()

USE_FLOATING_LEVEL = (
    _OVERLAY_SETTINGS.get("level") == "floating"
)
SHOW_CLOCK = bool(_OVERLAY_SETTINGS.get("clock", True))
try:
    _max_apps = int(_OVERLAY_SETTINGS.get("max_apps", MAX_VISIBLE_APPS))
except (TypeError, ValueError):
    _max_apps = MAX_VISIBLE_APPS
MAX_VISIBLE_APPS = max(4, min(30, _max_apps))

PANEL_ENABLED = bool(_OVERLAY_SETTINGS.get("enabled", True))
TITLEBAR_ENABLED = bool(_OVERLAY_SETTINGS.get("titlebar_enabled", False))


def _titlebar_bundles() -> list[str]:
    raw = _OVERLAY_SETTINGS.get("titlebar_bundles") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def _titlebar_heights() -> dict[str, int]:
    result: dict[str, int] = {}
    raw = _OVERLAY_SETTINGS.get("titlebar_heights") or {}
    if isinstance(raw, dict):
        for bundle, value in raw.items():
            try:
                result[str(bundle)] = int(value)
            except (TypeError, ValueError):
                continue
    return result


_CLOCK_FORMATTER = None


def round_view(view, radius: float) -> None:
    """Скругляет слой NSView (панель и кнопки)."""
    view.setWantsLayer_(True)
    layer = view.layer()
    if isinstance(layer, CALayer):
        layer.setCornerRadius_(radius)
        layer.setMasksToBounds_(True)


def clock_text() -> str:
    """Текущее время и дата в формате панели."""
    global _CLOCK_FORMATTER
    if _CLOCK_FORMATTER is None:
        _CLOCK_FORMATTER = NSDateFormatter.alloc().init()
        _CLOCK_FORMATTER.setDateFormat_(CLOCK_FORMAT)
        _CLOCK_FORMATTER.setLocale_(
            NSLocale.localeWithLocaleIdentifier_(CLOCK_LOCALE)
        )
    return _CLOCK_FORMATTER.stringFromDate_(NSDate.date())


class OverlayContentView(NSVisualEffectView):
    """Стеклянный фон панели, который принимает первый клик."""

    def acceptsFirstMouse_(self, event):
        # Панель неактивна; первый клик должен сразу попадать в кнопку,
        # а не уходить на активацию приложения.
        return True

    def mouseDownCanMoveWindow(self):
        return False


class OverlayButton(NSButton):
    """Кнопка, срабатывающая по первому клику в неактивной панели."""

    def acceptsFirstMouse_(self, event):
        return True

    def shouldDelayWindowOrderingForEvent_(self, event):
        # Не поднимать окно и не менять активное приложение до mouseUp.
        return True


class OverlayPanel(NSPanel):
    """Безрамочная неактивирующая панель поверх всех окон."""

    def init(self):
        style = (NSWindowStyleMaskBorderless
                 | NSWindowStyleMaskNonactivatingPanel)
        rect = NSMakeRect(0, 0, 420, PANEL_HEIGHT)
        self = objc.super(OverlayPanel, self).initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        if self is None:
            return None

        # 1. Системный уровень окна: выше обычных окон и системного Dock.
        self.setLevel_(NSFloatingWindowLevel if USE_FLOATING_LEVEL
                       else NSMainMenuWindowLevel)

        # 2. Все Spaces, Mission Control и полноэкранные приложения.
        self.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
            | NSWindowCollectionBehaviorIgnoresCycle
        )

        # 3. Безрамочное, прозрачное, неактивирующее окно.
        self.setOpaque_(False)
        self.setBackgroundColor_(NSColor.clearColor())
        self.setHasShadow_(True)
        self.setHidesOnDeactivate_(False)
        self.setCanHide_(False)
        self.setReleasedWhenClosed_(False)
        self.setExcludedFromWindowsMenu_(True)
        self.setMovableByWindowBackground_(False)
        self.setAcceptsMouseMovedEvents_(True)
        self.setFloatingPanel_(True)
        self.setBecomesKeyOnlyIfNeeded_(True)
        self.setWorksWhenModal_(True)

        # 4. Матовое стекло.
        effect = OverlayContentView.alloc().initWithFrame_(rect)
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        round_view(effect, PANEL_CORNER)
        self.setContentView_(effect)
        self.effect = effect

        # 5. Горизонтальный стек: иконки приложений + часы.
        stack = NSStackView.alloc().init()
        stack.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
        stack.setSpacing_(8.0)
        stack.setAlignment_(NSLayoutAttributeCenterY)
        stack.setTranslatesAutoresizingMaskIntoConstraints_(False)
        effect.addSubview_(stack)
        NSLayoutConstraint.activateConstraints_([
            stack.centerXAnchor().constraintEqualToAnchor_(
                effect.centerXAnchor()),
            stack.centerYAnchor().constraintEqualToAnchor_(
                effect.centerYAnchor()),
            stack.leadingAnchor().constraintGreaterThanOrEqualToAnchor_constant_(
                effect.leadingAnchor(), 14.0),
            stack.trailingAnchor().constraintLessThanOrEqualToAnchor_constant_(
                effect.trailingAnchor(), -14.0),
            stack.heightAnchor().constraintEqualToConstant_(BUTTON_SIZE),
        ])
        self.stack = stack
        self.clock_label = None
        self._all_apps = []
        self.setContentSize_(NSMakeSize(420, PANEL_HEIGHT))
        return self

    # Панель не должна становиться key/main — она не ворует фокус.
    def canBecomeKeyWindow(self):
        return PANEL_CAN_BECOME_KEY

    def canBecomeMainWindow(self):
        return False

    # ---------------------------------------------------------------- apps
    def _running_apps(self):
        apps = []
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            try:
                if app.activationPolicy() != NSApplicationActivationPolicyRegular:
                    continue
                if app.processIdentifier() == os.getpid():
                    continue
                apps.append(app)
            except Exception:
                continue
        apps.sort(key=lambda a: (a.localizedName() or "").casefold())
        return apps

    def _app_button(self, app):
        icon = app.icon()
        if icon is None:
            return None
        icon = icon.copy()
        icon.setSize_(NSMakeSize(ICON_SIZE, ICON_SIZE))
        button = OverlayButton.alloc().initWithFrame_(
            NSMakeRect(0, 0, BUTTON_SIZE, BUTTON_SIZE)
        )
        button.setImage_(icon)
        button.setImagePosition_(NSImageOnly)
        button.setImageScaling_(NSImageScaleProportionallyDown)
        button.setBordered_(False)
        button.setBezelStyle_(NSBezelStyleRegularSquare)
        button.setTarget_(self)
        button.setAction_("activateApp:")
        button.setTag_(app.processIdentifier())
        button.setToolTip_(app.localizedName() or "Приложение")
        round_view(button, 9.0)
        button.widthAnchor().constraintEqualToConstant_(
            BUTTON_SIZE).setActive_(True)
        button.heightAnchor().constraintEqualToConstant_(
            BUTTON_SIZE).setActive_(True)
        return button

    def _more_button(self):
        button = OverlayButton.alloc().initWithFrame_(
            NSMakeRect(0, 0, 38, 38)
        )
        button.setTitle_("…")
        button.setBordered_(False)
        button.setFont_(NSFont.systemFontOfSize_weight_(20.0,
                                                        NSFontWeightMedium))
        button.setTarget_(self)
        button.setAction_("showMoreApps:")
        button.setToolTip_("Остальные приложения")
        button.widthAnchor().constraintEqualToConstant_(38.0).setActive_(True)
        button.heightAnchor().constraintEqualToConstant_(38.0).setActive_(True)
        return button

    def _separator(self):
        line = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 1, 28))
        line.setWantsLayer_(True)
        line.layer().setBackgroundColor_(
            NSColor.colorWithWhite_alpha_(1.0, 0.18).CGColor()
        )
        line.widthAnchor().constraintEqualToConstant_(1.0).setActive_(True)
        line.heightAnchor().constraintEqualToConstant_(28.0).setActive_(True)
        return line

    def _clock_widget(self):
        label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(0, 0, CLOCK_WIDTH, 20)
        )
        label.setStringValue_(clock_text())
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setAlignment_(NSTextAlignmentCenter)
        label.setFont_(NSFont.systemFontOfSize_weight_(12.0,
                                                        NSFontWeightMedium))
        label.setTextColor_(NSColor.whiteColor())
        label.widthAnchor().constraintEqualToConstant_(
            CLOCK_WIDTH).setActive_(True)
        return label

    def _content_width(self):
        """Суммарная ширина иконок, разделителя и часов."""
        views = self.stack.arrangedSubviews()
        if not views:
            return 0.0
        total = sum(float(view.fittingSize().width) for view in views)
        total += float(self.stack.spacing()) * (len(views) - 1)
        return total

    def rebuild(self):
        """Пересобирает иконки приложений и подгоняет ширину панели."""
        for view in list(self.stack.arrangedSubviews()):
            self.stack.removeArrangedSubview_(view)
            view.removeFromSuperview()

        self._all_apps = self._running_apps()
        visible = self._all_apps[:MAX_VISIBLE_APPS]
        for app in visible:
            button = self._app_button(app)
            if button is not None:
                self.stack.addArrangedSubview_(button)

        if not visible:
            empty = NSTextField.alloc().initWithFrame_(
                NSMakeRect(0, 0, 180, 20)
            )
            empty.setStringValue_("Нет приложений")
            empty.setBezeled_(False)
            empty.setDrawsBackground_(False)
            empty.setEditable_(False)
            empty.setSelectable_(False)
            empty.setTextColor_(NSColor.secondaryLabelColor())
            empty.setFont_(NSFont.systemFontOfSize_(12.0))
            self.stack.addArrangedSubview_(empty)

        if len(self._all_apps) > MAX_VISIBLE_APPS:
            self.stack.addArrangedSubview_(self._more_button())

        if SHOW_CLOCK:
            self.stack.addArrangedSubview_(self._separator())
            self.clock_label = self._clock_widget()
            self.stack.addArrangedSubview_(self.clock_label)

        width = max(300.0, self._content_width() + 28.0)
        screen = NSScreen.mainScreen()
        if screen is not None:
            width = min(width, screen.frame().size.width - 24.0)
        self.setContentSize_(NSMakeSize(width, PANEL_HEIGHT))
        self.stack.layoutSubtreeIfNeeded()
        self.center_panel()

    def center_panel(self):
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        # frame(), а не visibleFrame(): панель должна лежать поверх
        # области системного Dock, а не над ней.
        area = screen.frame()
        frame = self.frame()
        x = area.origin.x + (area.size.width - frame.size.width) / 2.0
        y = area.origin.y + 10.0
        self.setFrameOrigin_(NSMakePoint(x, y))

    # ------------------------------------------------------------- actions
    def _toggle_app(self, app):
        if app is None:
            return
        if app.isActive():
            app.hide()
            return
        if app.isHidden():
            app.unhide()
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

    def activateApp_(self, sender):
        pid = sender.tag()
        app = NSWorkspace.sharedWorkspace().runningApplications()
        for candidate in app:
            if candidate.processIdentifier() == pid:
                self._toggle_app(candidate)
                return

    def activateAppFromMenu_(self, sender):
        pid = sender.tag()
        for candidate in NSWorkspace.sharedWorkspace().runningApplications():
            if candidate.processIdentifier() == pid:
                self._toggle_app(candidate)
                return

    def showMoreApps_(self, sender):
        menu = NSMenu.alloc().init()
        for app in self._all_apps[MAX_VISIBLE_APPS:]:
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                app.localizedName() or "Приложение",
                "activateAppFromMenu:",
                "",
            )
            item.setTarget_(self)
            item.setTag_(app.processIdentifier())
            icon = app.icon()
            if icon is not None:
                icon = icon.copy()
                icon.setSize_(NSMakeSize(18, 18))
                item.setImage_(icon)
            menu.addItem_(item)
        event = NSApplication.sharedApplication().currentEvent()
        if event is not None:
            NSMenu.popUpContextMenu_withEvent_forView_(menu, event, sender)
        else:
            menu.popUpMenuPositioningItem_atLocation_inView_(
                None, NSMakePoint(0, 0), sender
            )

    def updateClock_(self, timer):
        if self.clock_label is not None:
            self.clock_label.setStringValue_(clock_text())


class AppDelegate(NSObject):
    """Создаёт панель, status item и следит за запуском приложений."""

    def applicationDidFinishLaunching_(self, notification):
        self.panel = OverlayPanel.alloc().init()
        if PANEL_ENABLED:
            self.panel.rebuild()
            self.panel.orderFrontRegardless()

        self._build_status_item()
        if not PANEL_ENABLED:
            self.toggle_item.setTitle_("Показать панель")
        self.titlebar = None
        self._start_titlebar()

        center = NSWorkspace.sharedWorkspace().notificationCenter()
        center.addObserver_selector_name_object_(
            self, "appsChanged:",
            NSWorkspaceDidLaunchApplicationNotification, None)
        center.addObserver_selector_name_object_(
            self, "appsChanged:",
            NSWorkspaceDidTerminateApplicationNotification, None)
        center.addObserver_selector_name_object_(
            self, "spaceChanged:",
            NSWorkspaceActiveSpaceDidChangeNotification, None)

        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "screenChanged:",
            NSApplicationDidChangeScreenParametersNotification, None)

        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "tick:", None, True
        )

    def _start_titlebar(self):
        if not TITLEBAR_ENABLED:
            return
        if TitlebarController is None:
            print("Заголовки окон недоступны: "
                  f"{_TITLEBAR_IMPORT_ERROR}")
            return
        bundles = _titlebar_bundles()
        if not bundles:
            print("Заголовки окон: список приложений пуст "
                  "(titlebar_bundles в macos_overlay.json).")
            return
        if not ensure_accessibility(prompt=True):
            print("Заголовки окон не заменены: нет доступа "
                  "«Универсальный доступ». Выдайте его и перезапустите.")
            return
        controller = TitlebarController.alloc().init()
        controller.configure(bundles, _titlebar_heights())
        controller.start()
        self.titlebar = controller

    def _build_status_item(self):
        bar = NSStatusBar.systemStatusBar()
        self.status_item = bar.statusItemWithLength_(
            NSVariableStatusItemLength
        )
        button = self.status_item.button()
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "dock.rectangle", None
        )
        if image is not None:
            button.setImage_(image)
        else:
            button.setTitle_("Dock")

        menu = NSMenu.alloc().init()
        self.toggle_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Скрыть панель", "togglePanel:", ""
        )
        self.toggle_item.setTarget_(self)
        menu.addItem_(self.toggle_item)
        menu.addItem_(NSMenuItem.separatorItem())
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Выход", "quitApp:", "q"
        )
        quit_item.setTarget_(self)
        menu.addItem_(quit_item)
        self.status_item.setMenu_(menu)

    def appsChanged_(self, notification):
        # Можно было бы обновлять только изменившееся приложение,
        # но полная пересборка проще и надёжнее.
        self.panel.rebuild()

    def screenChanged_(self, notification):
        # Сменилось разрешение / подключили монитор — пересчитать ширину
        # и заново отцентрировать панель.
        self.panel.rebuild()

    def spaceChanged_(self, notification):
        # После переключения Space панель иногда уходит за окна;
        # возвращаем её на передний план, не активируя приложение.
        if self.panel.isVisible():
            self.panel.orderFrontRegardless()

    def tick_(self, timer):
        self.panel.updateClock_(timer)

    def togglePanel_(self, sender):
        if self.panel.isVisible():
            self.panel.orderOut_(None)
            self.toggle_item.setTitle_("Показать панель")
        else:
            self.panel.rebuild()
            self.panel.orderFrontRegardless()
            self.toggle_item.setTitle_("Скрыть панель")

    def quitApp_(self, sender):
        NSApplication.sharedApplication().terminate_(None)

    def applicationWillTerminate_(self, notification):
        if getattr(self, "titlebar", None) is not None:
            self.titlebar.stop()
            self.titlebar = None
        if getattr(self, "timer", None) is not None:
            self.timer.invalidate()
            self.timer = None
        NSWorkspace.sharedWorkspace().notificationCenter().removeObserver_(self)
        NSNotificationCenter.defaultCenter().removeObserver_(self)

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False

    def applicationSupportsSecureRestorableState_(self, app):
        return True


def main() -> int:
    if not PANEL_ENABLED and not TITLEBAR_ENABLED:
        print("Панель и заголовки окон выключены во вкладке «Твики» Gridly "
              "(macos_overlay.json: enabled=false, titlebar_enabled=false).")
        return 0

    app = NSApplication.sharedApplication()

    # Системный агент: никакой иконки в Dock.
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    # Не даём Python собрать delegate/панель сборщиком мусора.
    global _delegate
    _delegate = delegate

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
