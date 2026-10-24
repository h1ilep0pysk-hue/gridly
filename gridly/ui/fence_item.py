"""
ui/fence_item.py
Один элемент внутри fence: иконка и имя без расширения.
Поддерживает настройки размера, подписи и оформления из FenceStyle.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QFileInfo, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PyQt6.QtWidgets import (QFileIconProvider, QLabel, QVBoxLayout, QWidget)

from core.storage import FenceStyle

ITEM_W = 76
ITEM_H = 84
ICON_SIZE = QSize(40, 40)

_icon_provider = QFileIconProvider()


def icon_for(path: str) -> QIcon:
    return _icon_provider.icon(QFileInfo(path))


def display_name(path: str) -> str:
    """'Chrome.lnk' -> 'Chrome'. Папки показываем целиком."""
    p = Path(path)
    if p.is_dir():
        return p.name
    return p.stem or p.name


class FenceItemWidget(QWidget):
    double_clicked = pyqtSignal(str)

    def __init__(self, path: str, parent: QWidget | None = None,
                 style: FenceStyle | None = None):
        super().__init__(parent)
        self.path = path
        self.style = style or FenceStyle()
        self._hovered = False
        self.setToolTip(path)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setMouseTracking(True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 3)
        lay.setSpacing(2)
        self._lay = lay

        self.icon_lbl = QLabel()
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_lbl.setStyleSheet("background: transparent;")
        self.icon_lbl.setMinimumHeight(20)

        self.name_lbl = QLabel(display_name(path))
        self.name_lbl.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        self.name_lbl.setWordWrap(True)
        self.name_lbl.setStyleSheet("background: transparent;")

        lay.addWidget(self.icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.name_lbl, 1)
        self.apply_style(self.style)

    # ------------------------------------------------------------------ API
    def apply_style(self, style: FenceStyle) -> None:
        self.style = style
        width = max(40, int(style.item_width))
        height = max(44, int(style.item_height))
        self.setFixedSize(width, height)

        icon_size = max(16, min(int(style.item_icon_size),
                                width - 8, height - 24))
        self.icon_lbl.setPixmap(
            icon_for(self.path).pixmap(QSize(icon_size, icon_size))
        )
        self.name_lbl.setVisible(bool(style.show_item_labels))

        font = QFont()
        font.setFamily("Segoe UI")
        font.setPixelSize(max(8, int(style.item_text_size)))
        self.name_lbl.setFont(font)
        self.name_lbl.setStyleSheet(
            "background: transparent;"
            f" color: {style.item_text_color};"
            f" font-size: {max(8, int(style.item_text_size))}px;"
        )
        self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        style = self.style
        radius = max(0, min(int(style.item_radius),
                            self.width() // 2, self.height() // 2))

        base = QColor(style.item_bg)
        if not base.isValid():
            base = QColor("#ffffff")
        alpha = max(0, min(255, int(style.item_bg_alpha)))
        if self._hovered:
            alpha = max(alpha, max(0, min(255, int(style.item_hover_alpha))))
        if alpha > 0:
            base.setAlpha(alpha)
            p.setBrush(base)
            p.setPen(QPen(QColor(255, 255, 255, 22), 1.0))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1),
                              radius, radius)
        p.end()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.path)
