"""
ui/fence_widget.py
Toolchain: Python 3.11, PyQt6.

Fence: панель с заголовком и иконками файлов.
Раскладки:
  grid       — сетка с переносом по ширине
  vertical   — один столбец, прокрутка вниз
  horizontal — одна строка, прокрутка вправо
  folder     — свёрнут в один ярлык, при наведении раскрывается в сетку

Стиль fence полностью настраивается через core.storage.FenceStyle:
градиенты, текстуры, рамки, тени, свечение, акриловое размытие,
типографика заголовка и параметры элементов.
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import (Qt, QLineF, QPoint, QPointF, QRect, QRectF, QSize,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import (QAction, QBrush, QColor, QCursor, QDragEnterEvent,
                         QDropEvent, QFont, QFontMetricsF, QIcon,
                         QLinearGradient, QMouseEvent, QPainter,
                         QPainterPath, QPen, QPixmap, QRadialGradient)
from PyQt6.QtWidgets import (QHBoxLayout, QInputDialog, QLabel, QMenu,
                             QPushButton, QScrollArea, QVBoxLayout, QWidget)

from core.storage import FenceItem, FenceState, hex_to_bgr
from ui.blur_effect import (DWMWCP_DEFAULT, DWMWCP_ROUND,
                            DWMWCP_ROUNDSMALL, disable_blur,
                            enable_fence_blur, set_window_corner_preference)
from ui.fence_item import FenceItemWidget, ITEM_H, ITEM_W, icon_for

RESIZE_MARGIN = 8
HEADER_HEIGHT = 30
PAD = 8
SPACING = 6
FOLDER_COLLAPSED = (140, 140)
FOLDER_COLS = 3
FOLDER_MAX_H = 480

LAYOUT_NAMES = {
    "grid": "Сетка",
    "vertical": "Вертикальный",
    "horizontal": "Горизонтальный",
    "folder": "Папка (раскрывается при наведении)",
}


def _qcolor(value: str, fallback: str = "#ffffff") -> QColor:
    color = QColor(value)
    return color if color.isValid() else QColor(fallback)


def _rgba(value: str, alpha: int) -> str:
    c = _qcolor(value)
    return f"rgba({c.red()},{c.green()},{c.blue()},{max(0, min(255, alpha))})"


def _clamped_color(value: str, alpha: int, fallback: str = "#ffffff") -> QColor:
    c = _qcolor(value, fallback)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def make_pin_icon(locked: bool, size: int = 32) -> QIcon:
    """Рисует пластиковую чертёжную кнопку (канцелярскую кнопку).

    locked=True  — белая пластиковая головка;
    locked=False — серая пластиковая головка.
    """
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.scale(size / 32.0, size / 32.0)

    if locked:
        top = QColor(255, 255, 255)
        bottom = QColor(205, 205, 205)
        edge = QColor(245, 245, 245)
        needle = QColor(220, 220, 220)
    else:
        top = QColor(205, 205, 205)
        bottom = QColor(110, 110, 110)
        edge = QColor(155, 155, 155)
        needle = QColor(135, 135, 135)

    head_rect = QRectF(7, 4, 18, 14)
    grad = QRadialGradient(QPointF(12, 8), 16)
    grad.setColorAt(0.0, top)
    grad.setColorAt(0.55, bottom.lighter(115))
    grad.setColorAt(1.0, bottom)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(edge, 0.8))
    p.drawEllipse(head_rect)

    highlight = QRadialGradient(QPointF(11, 7), 8)
    highlight.setColorAt(0.0, QColor(255, 255, 255, 190))
    highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(highlight))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(8, 5, 11, 9))

    p.setPen(QPen(needle, 2.2, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    p.drawLine(QLineF(QPointF(16, 17), QPointF(16, 28)))
    p.end()
    return QIcon(pm)


class FenceTitleLabel(QLabel):
    """Заголовок с тенью и свечением, нарисованными QPainter'ом."""

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self._style = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")

    def apply_style(self, style) -> None:
        self._style = style
        font = QFont(style.title_font or "Segoe UI")
        font.setPixelSize(max(8, int(style.title_size)))
        try:
            font.setWeight(QFont.Weight(int(style.title_weight)))
        except (ValueError, TypeError):
            font.setWeight(QFont.Weight.DemiBold)
        font.setItalic(bool(style.title_italic))
        if style.title_letter_spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                                  float(style.title_letter_spacing))
        self.setFont(font)
        align = {
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
            "left": Qt.AlignmentFlag.AlignLeft,
        }.get(style.title_align, Qt.AlignmentFlag.AlignLeft)
        self.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self.update()

    def paintEvent(self, event) -> None:
        style = self._style
        if style is None:
            super().paintEvent(event)
            return

        text = self.text()
        if not text:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = QRectF(self.contentsRect())
        metrics = QFontMetricsF(self.font())
        draw_text = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                       max(1, int(rect.width())))
        align = int(self.alignment())

        def paint_at(dx: float, dy: float, color: QColor) -> None:
            p.setPen(color)
            p.drawText(rect.translated(QPointF(dx, dy)), align, draw_text)

        # Свечение: несколько мягких контуров вокруг текста.
        if style.title_glow:
            radius = max(1, int(style.title_glow_radius))
            alpha = max(0, min(255, int(style.title_glow_alpha)))
            for ring, scale in ((radius, 0.20), (max(1, radius // 2), 0.38)):
                for angle in range(0, 360, 45):
                    a = math.radians(angle)
                    paint_at(math.cos(a) * ring, math.sin(a) * ring,
                             _clamped_color(style.title_glow_color,
                                            int(alpha * scale)))

        # Тень текста.
        if style.title_shadow:
            blur = max(0, int(style.title_shadow_blur))
            spread = max(1, blur + 1)
            alpha = max(0, min(255, int(style.title_shadow_alpha)))
            for i in range(spread, 0, -1):
                paint_at(style.title_shadow_offset_x + i * 0.35,
                         style.title_shadow_offset_y + i * 0.35,
                         _clamped_color(style.title_shadow_color,
                                        int(alpha / (i + 1))))

        paint_at(0, 0, _qcolor(style.title_color))
        p.end()


class FenceWidget(QWidget):
    geometry_changed = pyqtSignal(str)
    items_changed = pyqtSignal(str)
    launch_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    layout_changed = pyqtSignal(str)
    title_changed = pyqtSignal(str)
    lock_changed = pyqtSignal(str, bool)
    behavior_changed = pyqtSignal(str)
    customize_requested = pyqtSignal(str)

    def __init__(self, state: FenceState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self._locked = bool(state.locked)
        self._drag_pos: QPoint | None = None
        self._resizing = False
        self._resize_edge: str | None = None
        self._resize_start_geom = QRect()
        self._resize_start_mouse = QPoint()
        self._expanded = False
        self._item_widgets: list[FenceItemWidget] = []
        self._blur_enabled = False
        self._mac_tweaks = None
        self._last_top_flag = bool(state.always_on_top)

        self.setWindowFlags(self._window_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(250)
        self._hover_timer.timeout.connect(self._maybe_collapse)

        self._build_ui()
        self.move(state.x, state.y)
        if state.layout == "folder":
            self.resize(*FOLDER_COLLAPSED)
            self.scroll.hide()
        else:
            self.resize(state.width, state.height)
        self._rebuild_items()
        self.apply_style()

    # ------------------------------------------------------------------ UI
    def _window_flags(self) -> Qt.WindowType:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.state.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    def _header_height(self) -> int:
        if not self.state.style.header_visible:
            return 0
        return max(22, min(120, int(self.state.style.header_height)))

    def _effect_margin(self) -> int:
        style = self.state.style
        margin = 0
        if style.shadow_enabled:
            margin = max(margin,
                         abs(style.shadow_offset_x) + abs(style.shadow_offset_y)
                         + max(2, style.shadow_blur))
        if style.glow_enabled:
            margin = max(margin, max(2, style.glow_radius))
        return min(36, margin + (4 if margin else 0))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root_layout = root

        header = QWidget(self)
        header.setObjectName("fenceHeader")
        header.setFixedHeight(HEADER_HEIGHT)
        self.header = header
        h = QHBoxLayout(header)
        h.setContentsMargins(10, 0, 4, 0)
        h.setSpacing(2)

        self.title_label = FenceTitleLabel(self.state.title)
        self.title_label.setToolTip("Двойной клик — переименовать")

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setToolTip("Удалить fence")
        self.close_btn.clicked.connect(
            lambda _c=False: self.delete_requested.emit(self.state.id)
        )

        self.lock_btn = QPushButton()
        self.lock_btn.setFixedSize(22, 22)
        self.lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lock_btn.setToolTip("Закрепить fence (запретить перемещение)")
        self.lock_btn.setIcon(make_pin_icon(False))
        self.lock_btn.setIconSize(QSize(16, 16))
        self.lock_btn.clicked.connect(self._toggle_lock)

        h.addWidget(self.title_label, 1)
        h.addWidget(self.lock_btn)
        h.addWidget(self.close_btn)
        root.addWidget(header)

        self.canvas = QWidget()
        self.canvas.setStyleSheet("background: transparent;")

        self.scroll = QScrollArea(self)
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")
        root.addWidget(self.scroll, 1)

    # ------------------------------------------------------------- styling
    def apply_style(self) -> None:
        """Применяет сохранённые настройки стиля к окну."""
        style = self.state.style
        radius = max(0, min(80, self._mac_radius(style.corner_radius)))

        opacity = max(0, min(255, int(style.opacity)))
        self.setWindowOpacity(opacity / 255.0)

        margin = self._effect_margin()
        self._root_layout.setContentsMargins(margin, margin, margin, margin)

        self.header.setVisible(bool(style.header_visible))
        header_h = self._header_height()
        if style.header_visible:
            self.header.setFixedHeight(header_h)
        header_alpha = self._mac_alpha(style.header_alpha)
        header_bg = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {_rgba(style.header_bg, header_alpha)},"
            f" stop:1 {_rgba(style.header_bg2, header_alpha)})"
            if style.header_gradient
            else _rgba(style.header_bg, header_alpha)
        )
        self.header.setStyleSheet(
            f"#fenceHeader {{ background: {header_bg};"
            f" border-top-left-radius: {radius}px;"
            f" border-top-right-radius: {radius}px; }}"
        )

        self.title_label.setText(self.state.title)
        self.title_label.apply_style(style)

        self.close_btn.setVisible(bool(style.show_close_button))
        self.close_btn.setStyleSheet(
            f"QPushButton {{ color: {style.title_color}; background: transparent;"
            " border: none; font-size: 12px; }"
            "QPushButton:hover { background: rgba(230, 70, 70, 200);"
            " border-radius: 4px; }"
        )
        self.lock_btn.setVisible(bool(style.show_lock_button))
        self.lock_btn.setIcon(make_pin_icon(self._locked))
        self.lock_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            "QPushButton:hover { background: rgba(200, 200, 200, 150);"
            " border-radius: 4px; }"
        )
        self._update_lock_visual()

        for item in self._item_widgets:
            item.apply_style(style)
        self._relayout()
        self._apply_blur(style)
        self._apply_system_corners()
        self.update()

    def _mac_alpha(self, value: int) -> int:
        """Делает фон прозрачнее, пока включён macOS-стиль."""
        tweaks = self._mac_tweaks
        if tweaks is not None and tweaks.enabled and tweaks.glass:
            return min(int(value), max(42, 185 - int(tweaks.translucency)))
        return int(value)

    def _mac_radius(self, value: int) -> int:
        tweaks = self._mac_tweaks
        if tweaks is not None and tweaks.enabled and tweaks.rounded:
            return int(tweaks.corner_radius)
        return int(value)

    def apply_mac_tweaks(self, tweaks) -> None:
        """Применяет общий macOS-стиль без изменения сохранённого FenceStyle."""
        self._mac_tweaks = tweaks
        self.apply_style()

    def _apply_blur(self, style) -> None:
        mac_blur = bool(
            self._mac_tweaks is not None
            and self._mac_tweaks.enabled
            and self._mac_tweaks.fence_blur
        )
        if style.blur_enabled or mac_blur:
            tint = hex_to_bgr(style.bg_color)
            alpha = int(style.blur_alpha)
            if mac_blur:
                alpha = max(alpha, min(
                    235, 65 + int(self._mac_tweaks.blur_strength)
                ))
            try:
                enable_fence_blur(int(self.winId()), tint, alpha)
                self._blur_enabled = True
            except Exception:
                self._blur_enabled = False
        elif self._blur_enabled:
            try:
                disable_blur(int(self.winId()))
            except Exception:
                pass
            self._blur_enabled = False

    def _apply_system_corners(self) -> None:
        tweaks = self._mac_tweaks
        if tweaks is None:
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        if (tweaks.enabled and tweaks.rounded
                and self.state.style.corner_radius > 0):
            preference = DWMWCP_ROUND \
                if self.state.style.corner_radius >= 14 else DWMWCP_ROUNDSMALL
        else:
            preference = DWMWCP_DEFAULT
        try:
            set_window_corner_preference(hwnd, preference)
        except Exception:
            pass

    def _update_lock_visual(self) -> None:
        self.lock_btn.setIcon(make_pin_icon(self._locked))
        self.lock_btn.setToolTip(
            "Открепить fence (разрешить перемещение)"
            if self._locked
            else "Закрепить fence (запретить перемещение)"
        )

    def set_title(self, title: str) -> None:
        title = title.strip()
        if not title or title == self.state.title:
            return
        self.state.title = title
        self.title_label.setText(title)
        self.title_changed.emit(self.state.id)

    def rename(self) -> None:
        new_title, ok = QInputDialog.getText(
            self, "Переименовать fence", "Новое название:",
            text=self.state.title,
        )
        if ok:
            self.set_title(new_title)

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self.state.locked = self._locked
        self._update_lock_visual()
        self.lock_changed.emit(self.state.id, self._locked)

    def _toggle_lock(self) -> None:
        self.set_locked(not self._locked)

    def set_always_on_top(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.state.always_on_top:
            return
        self.state.always_on_top = enabled
        was_visible = self.isVisible()
        self.setWindowFlags(self._window_flags())
        if was_visible:
            self.show()
            self.move(self.state.x, self.state.y)
        self.behavior_changed.emit(self.state.id)

    # ------------------------------------------------------------ geometry
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.state.style.header_visible
                and event.position().y() <= self._header_height()):
            self.rename()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------ items
    def _rebuild_items(self) -> None:
        for w in self._item_widgets:
            w.deleteLater()
        self._item_widgets = []
        for item in self.state.items:
            w = FenceItemWidget(item.path, self.canvas, self.state.style)
            w.double_clicked.connect(self.launch_requested.emit)
            w.show()
            self._item_widgets.append(w)
        self._relayout()
        self.update()

    def _item_dims(self) -> tuple[int, int]:
        return (max(40, int(self.state.style.item_width)),
                max(44, int(self.state.style.item_height)))

    def _layout_pad(self) -> int:
        return max(0, int(self.state.style.padding))

    def _layout_gap(self) -> int:
        return max(0, int(self.state.style.spacing))

    def _cols_for(self, n: int, viewport_w: int) -> int:
        layout = self.state.layout
        if layout == "vertical":
            return 1
        if layout == "horizontal":
            return max(1, n)
        if layout == "folder":
            return FOLDER_COLS
        item_w, _ = self._item_dims()
        gap = self._layout_gap()
        pad = self._layout_pad()
        return max(1, (viewport_w - 2 * pad + gap) // (item_w + gap))

    def _relayout(self) -> None:
        if self.state.layout == "folder" and not self._expanded:
            for w in self._item_widgets:
                w.hide()
            return
        for w in self._item_widgets:
            w.show()

        vp = self.scroll.viewport()
        vw, vh = max(vp.width(), 1), max(vp.height(), 1)
        n = len(self._item_widgets)
        cols = self._cols_for(n, vw)
        rows = max(1, math.ceil(n / cols))

        item_w, item_h = self._item_dims()
        gap = self._layout_gap()
        pad = self._layout_pad()
        for i, w in enumerate(self._item_widgets):
            r, c = divmod(i, cols)
            w.move(pad + c * (item_w + gap), pad + r * (item_h + gap))

        content_w = pad * 2 + cols * item_w + (cols - 1) * gap
        content_h = pad * 2 + rows * item_h + (rows - 1) * gap

        if self.state.layout == "horizontal":
            self.canvas.setFixedSize(max(content_w, vw), vh)
            self.scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            self.canvas.setFixedSize(vw, max(content_h, vh))
            self.scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._mac_tweaks is not None and self._mac_tweaks.enabled:
            QTimer.singleShot(0, lambda: self._apply_blur(self.state.style))
            QTimer.singleShot(0, self._apply_system_corners)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    # --------------------------------------------------------- layouts
    def set_layout(self, layout: str) -> None:
        if layout == self.state.layout:
            return
        self.state.layout = layout
        self._expanded = False
        self._hover_timer.stop()
        if layout == "folder":
            self.resize(*FOLDER_COLLAPSED)
            self.scroll.hide()
        else:
            self.resize(self.state.width, self.state.height)
            self.scroll.show()
        self._relayout()
        self.update()
        self.layout_changed.emit(self.state.id)

    def _folder_expanded_size(self) -> tuple[int, int]:
        n = max(1, len(self.state.items))
        rows = math.ceil(n / FOLDER_COLS)
        item_w, item_h = self._item_dims()
        gap = self._layout_gap()
        pad = self._layout_pad()
        margin = self._effect_margin() * 2
        w = pad * 2 + FOLDER_COLS * item_w + (FOLDER_COLS - 1) * gap + margin
        h = (self._header_height() + pad * 2 + rows * item_h
             + (rows - 1) * gap + margin)
        return w, min(h, FOLDER_MAX_H)

    def _expand(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self.resize(*self._folder_expanded_size())
        self.scroll.show()
        self._relayout()
        self.update()

    def _collapse(self) -> None:
        if not self._expanded:
            return
        self._expanded = False
        self.resize(*FOLDER_COLLAPSED)
        self.scroll.hide()
        self._relayout()
        self.update()

    def _maybe_collapse(self) -> None:
        inside = self.rect().contains(self.mapFromGlobal(QCursor.pos()))
        if not inside:
            self._collapse()

    # --------------------------------------------------------- painting
    def _card_rect(self) -> QRectF:
        m = self._effect_margin()
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    @staticmethod
    def _radius_for(card: QRectF, radius: int) -> float:
        return max(0.0, min(float(radius),
                            card.width() / 2.0, card.height() / 2.0))

    def _paint_shadow(self, p: QPainter, card: QRectF, radius: float,
                      style) -> None:
        if not style.shadow_enabled:
            return
        color = _qcolor(style.shadow_color, "#000000")
        base_alpha = max(0, min(255, int(style.shadow_alpha)))
        blur = max(2, int(style.shadow_blur))
        steps = max(3, min(12, blur // 3 + 2))
        offset = QPointF(style.shadow_offset_x, style.shadow_offset_y)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(steps, 0, -1):
            spread = blur * i / steps
            alpha = int(base_alpha * (0.14 + 0.50 * (1 - i / steps)))
            p.setBrush(_clamped_color(style.shadow_color, alpha))
            rect = card.translated(offset).adjusted(
                -spread, -spread, spread, spread)
            p.drawRoundedRect(rect, radius + spread, radius + spread)

    def _paint_glow(self, p: QPainter, card: QRectF, radius: float,
                    style) -> None:
        if not style.glow_enabled:
            return
        alpha = max(0, min(255, int(style.glow_alpha)))
        glow = max(2, int(style.glow_radius))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, factor in ((glow, 0.12), (glow * 0.62, 0.22),
                              (glow * 0.30, 0.38)):
            p.setPen(QPen(_clamped_color(style.glow_color,
                                         int(alpha * factor)),
                          max(1.0, width)))
            p.drawRoundedRect(card.adjusted(-width / 2, -width / 2,
                                             width / 2, width / 2),
                              radius + width / 2, radius + width / 2)

    def _paint_texture(self, p: QPainter, card: QRectF, radius: float,
                       style) -> None:
        if style.texture == "none" or style.texture_alpha <= 0:
            return
        p.save()
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        p.setClipPath(path)
        color = _qcolor(style.texture_color)
        color.setAlpha(max(0, min(255, int(style.texture_alpha))))
        scale = max(6, int(style.texture_scale))
        pen = QPen(color, 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        if style.texture == "dots":
            y = card.top() + scale / 2
            row = 0
            while y < card.bottom():
                x = card.left() + (scale / 2 if row % 2 == 0 else scale)
                while x < card.right():
                    p.drawPoint(QPointF(x, y))
                    x += scale
                y += scale
                row += 1
        elif style.texture == "grid":
            x = card.left()
            while x < card.right():
                p.drawLine(QPointF(x, card.top()), QPointF(x, card.bottom()))
                x += scale
            y = card.top()
            while y < card.bottom():
                p.drawLine(QPointF(card.left(), y), QPointF(card.right(), y))
                y += scale
        elif style.texture == "diagonal":
            step = scale
            x = card.left() - card.height()
            while x < card.right():
                p.drawLine(QPointF(x, card.bottom()),
                           QPointF(x + card.height(), card.top()))
                x += step
        elif style.texture == "noise":
            rng = random.Random(424242)
            count = min(900, max(40, int(card.width() * card.height()
                                         / max(36, scale * scale))))
            for _ in range(count):
                x = card.left() + rng.random() * card.width()
                y = card.top() + rng.random() * card.height()
                p.drawPoint(QPointF(x, y))
        p.restore()

    def _paint_background(self, p: QPainter, card: QRectF, radius: float,
                          style) -> None:
        mode = style.bg_mode
        if mode in ("gradient", "glass"):
            angle = math.radians(int(style.gradient_angle))
            center = card.center()
            length = max(card.width(), card.height()) * 0.65
            grad = QLinearGradient(
                center - QPointF(math.cos(angle) * length,
                                 math.sin(angle) * length),
                center + QPointF(math.cos(angle) * length,
                                 math.sin(angle) * length),
            )
            alpha = self._mac_alpha(style.gradient_alpha)
            c1 = _clamped_color(style.bg_color, alpha)
            c2 = _clamped_color(style.bg_color2, alpha)
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            p.setBrush(grad)
        else:
            p.setBrush(_clamped_color(
                style.bg_color, self._mac_alpha(style.bg_alpha)
            ))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(card, radius, radius)

        if mode == "glass":
            p.save()
            path = QPainterPath()
            path.addRoundedRect(card, radius, radius)
            p.setClipPath(path)
            sheen = QLinearGradient(card.topLeft(),
                                    QPointF(card.left(),
                                            card.top() + card.height() * 0.62))
            sheen.setColorAt(0.0, QColor(255, 255, 255, 48))
            sheen.setColorAt(0.55, QColor(255, 255, 255, 10))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(sheen)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(card)
            p.restore()

        self._paint_texture(p, card, radius, style)

    def _paint_inner_shadow(self, p: QPainter, card: QRectF, radius: float,
                            style) -> None:
        if not style.inner_shadow_enabled:
            return
        blur = max(1, int(style.inner_shadow_blur))
        alpha = max(0, min(255, int(style.inner_shadow_alpha)))
        color = _qcolor(style.inner_shadow_color, "#000000")
        p.save()
        path = QPainterPath()
        path.addRoundedRect(card, radius, radius)
        p.setClipPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(blur, 0, -1):
            c = QColor(color)
            c.setAlpha(max(1, int(alpha * (i / max(1, blur)) * 0.20)))
            p.setPen(QPen(c, 1.4))
            p.drawRoundedRect(
                card.translated(style.inner_shadow_offset_x,
                                style.inner_shadow_offset_y)
                .adjusted(i, i, -i, -i),
                max(0, radius - i), max(0, radius - i),
            )
        p.restore()

    def _pen_style(self, name: str) -> Qt.PenStyle:
        return {
            "dashed": Qt.PenStyle.DashLine,
            "dotted": Qt.PenStyle.DotLine,
            "none": Qt.PenStyle.NoPen,
        }.get(name, Qt.PenStyle.SolidLine)

    def _paint_border(self, p: QPainter, card: QRectF, radius: float,
                      style) -> None:
        if style.border_style == "none" or style.border_width <= 0:
            return
        width = max(0.0, float(style.border_width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_clamped_color(style.border_color, style.border_alpha),
                      width, self._pen_style(style.border_style)))
        p.drawRoundedRect(card.adjusted(width / 2, width / 2,
                                        -width / 2, -width / 2),
                          radius, radius)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        style = self.state.style
        card = self._card_rect()
        radius = self._radius_for(
            card, self._mac_radius(style.corner_radius)
        )

        self._paint_shadow(p, card, radius, style)
        self._paint_glow(p, card, radius, style)
        self._paint_background(p, card, radius, style)
        self._paint_inner_shadow(p, card, radius, style)
        self._paint_border(p, card, radius, style)

        if self.state.layout == "folder" and not self._expanded:
            self._paint_folder_preview(p, card)
        p.end()

    def _paint_folder_preview(self, p: QPainter, card: QRectF) -> None:
        style = self.state.style
        top = card.top() + self._header_height()
        area = QRectF(card.left(), top, card.width(), card.bottom() - top)
        if not self.state.items:
            p.setPen(_clamped_color(style.item_text_color, 160))
            p.drawText(area, Qt.AlignmentFlag.AlignCenter, "пусто")
            return

        size = max(32, min(96, int(style.item_icon_size) + 24))
        icon_rect = QRect(
            int(area.center().x() - size // 2),
            int(area.center().y() - size // 2 - 8),
            size, size,
        )
        icon_for(self.state.items[0].path).paint(p, icon_rect)

        count = len(self.state.items)
        if count > 1:
            p.setPen(_clamped_color(style.item_text_color, 210))
            font = QFont(p.font())
            font.setPixelSize(max(8, int(style.item_text_size)))
            p.setFont(font)
            p.drawText(
                QRect(int(area.left()), icon_rect.bottom() + 4,
                      int(area.width()), 18),
                Qt.AlignmentFlag.AlignCenter,
                f"+{count - 1}",
            )

    # ------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = url.toLocalFile()
                if not any(it.path == path for it in self.state.items):
                    self.state.items.append(FenceItem(path=path))
        self._rebuild_items()
        self.items_changed.emit(self.state.id)
        event.acceptProposedAction()

    # ----------------------------------------------- move / resize
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        edge = self._hit_test_resize(pos)
        if edge and self.state.layout != "folder":
            self._resizing = True
            self._resize_edge = edge
            self._resize_start_geom = self.geometry()
            self._resize_start_mouse = event.globalPosition().toPoint()
        elif (self.state.style.header_visible
              and pos.y() <= self._header_height()):
            if not self._locked:
                self._drag_pos = event.globalPosition().toPoint() - self.pos()
            else:
                self._drag_pos = None

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._resizing:
            self._perform_resize(event.globalPosition().toPoint())
            return
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            return
        edge = None
        if self.state.layout != "folder":
            edge = self._hit_test_resize(event.position().toPoint())
        self.setCursor(self._cursor_for_edge(edge) if edge
                       else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._resizing or self._drag_pos is not None:
            self._resizing = False
            self._resize_edge = None
            self._drag_pos = None
            self._sync_state_geometry()
            self.geometry_changed.emit(self.state.id)

    def _hit_test_resize(self, pos: QPoint) -> str | None:
        r = self.rect()
        left = pos.x() <= RESIZE_MARGIN
        right = pos.x() >= r.width() - RESIZE_MARGIN
        bottom = pos.y() >= r.height() - RESIZE_MARGIN
        if right and bottom:
            return "br"
        if left and bottom:
            return "bl"
        if right:
            return "r"
        if bottom:
            return "b"
        if left:
            return "l"
        return None

    @staticmethod
    def _cursor_for_edge(edge: str) -> Qt.CursorShape:
        return {
            "r": Qt.CursorShape.SizeHorCursor,
            "l": Qt.CursorShape.SizeHorCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
        }[edge]

    def _perform_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._resize_start_mouse
        geom = QRect(self._resize_start_geom)
        if "r" in self._resize_edge:
            geom.setWidth(max(180, geom.width() + delta.x()))
        if "l" in self._resize_edge:
            geom.setLeft(geom.left() + delta.x())
        if "b" in self._resize_edge:
            geom.setHeight(max(120, geom.height() + delta.y()))
        self.setGeometry(geom)

    def _sync_state_geometry(self) -> None:
        self.state.x = self.x()
        self.state.y = self.y()
        if self.state.layout != "folder":
            self.state.width = self.width()
            self.state.height = self.height()

    # ------------------------------------------------- hover / folder
    def enterEvent(self, event) -> None:
        self._hover_timer.stop()
        if self.state.layout == "folder":
            self._expand()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self.state.layout == "folder":
            self._hover_timer.start()
        super().leaveEvent(event)

    # ---------------------------------------------------- context menu
    def _show_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)

        customize_act = QAction("Тонкая настройка…", menu)
        customize_act.triggered.connect(
            lambda _c=False: self.customize_requested.emit(self.state.id)
        )
        menu.addAction(customize_act)

        rename_act = QAction("Переименовать", menu)
        rename_act.triggered.connect(lambda _c=False: self.rename())
        menu.addAction(rename_act)

        menu.addSeparator()
        for key, label in LAYOUT_NAMES.items():
            act = QAction(label, menu)
            act.setCheckable(True)
            act.setChecked(self.state.layout == key)
            act.triggered.connect(lambda _c=False, k=key: self.set_layout(k))
            menu.addAction(act)

        menu.addSeparator()
        lock_act = QAction("Открепить" if self._locked else "Закрепить", menu)
        lock_act.triggered.connect(lambda _c=False: self.set_locked(not self._locked))
        menu.addAction(lock_act)

        top_act = QAction("Поверх всех окон", menu)
        top_act.setCheckable(True)
        top_act.setChecked(self.state.always_on_top)
        top_act.triggered.connect(
            lambda checked=False: self.set_always_on_top(checked)
        )
        menu.addAction(top_act)

        menu.addSeparator()
        del_act = QAction("Удалить fence", menu)
        del_act.triggered.connect(
            lambda _c=False: self.delete_requested.emit(self.state.id)
        )
        menu.addAction(del_act)
        menu.exec(self.mapToGlobal(pos))
