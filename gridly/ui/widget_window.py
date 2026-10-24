"""
ui/widget_window.py
Само окно desktop-виджета и виджет живого предпросмотра.

Окно безрамочное и полупрозрачное, его можно перетаскивать, закреплять
канцелярской кнопкой, настраивать двойным кликом и через контекстное меню.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

from PyQt6.QtCore import (QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer,
                          QUrl, pyqtSignal)
from PyQt6.QtGui import QDesktopServices, QPainter
from PyQt6.QtWidgets import (QLineEdit, QMenu, QPlainTextEdit, QPushButton,
                             QSizePolicy, QWidget)

from core.module_data import (browser_music_url, is_audio_url, music_source,
                              music_source_label, normalize_music_url,
                              parse_duration, parse_plans, toggle_plan_done)
from core.widget_storage import (WidgetState, state_needs_clock,
                                 state_needs_metrics, state_needs_weather)
from core.metrics import collect_all_metrics, collect_metric_data
from core.storage import hex_to_bgr
from ui.blur_effect import (DWMWCP_DEFAULT, DWMWCP_ROUND,
                            DWMWCP_ROUNDSMALL, disable_blur,
                            enable_fence_blur, set_window_corner_preference)
from ui.fence_widget import make_pin_icon
from ui.widget_render import (WidgetPreview, block_rect_at, format_clock,
                              iter_widget_blocks, paint_widget,
                              plan_row_index_at, sample_custom_data,
                              sample_data, widget_card_rect, WEEKDAYS,
                              MONTHS_GENITIVE)


class WidgetWindow(QWidget):
    geometry_changed = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    data_updated = pyqtSignal(str)
    status_changed = pyqtSignal(str, str)
    edit_requested = pyqtSignal(str)
    delete_requested = pyqtSignal(str)
    duplicate_requested = pyqtSignal(str)

    def __init__(self, state: WidgetState, weather_service=None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.data: dict = {}
        self._weather_service = weather_service
        self._drag_offset: QPoint | None = None
        self._hovered = False
        self._timer_signature: tuple | None = None
        self._weather_key = state.id
        self._module_runtime: dict[str, dict] = {}
        self._inline_editor: QWidget | None = None
        self._inline_block_id = ""
        self._committing_editor = False
        self._music_player = None
        self._music_audio = None
        self._music_block_id = ""
        self._music_url = ""
        self._mac_tweaks = None
        self._blur_enabled = False

        self.setWindowTitle(f"Gridly — {state.title}")
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setMinimumSize(180, 110)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

        self._pin_btn = QPushButton(self)
        self._pin_btn.setFixedSize(22, 22)
        self._pin_btn.setIconSize(QSize(15, 15))
        self._pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_btn.setStyleSheet(
            "QPushButton { background: rgba(0, 0, 0, 115);"
            " border: 1px solid rgba(255, 255, 255, 70);"
            " border-radius: 10px; }"
            "QPushButton:hover { background: rgba(0, 0, 0, 175); }"
        )
        self._pin_btn.clicked.connect(self.toggle_lock)
        self._pin_btn.hide()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)

        self._weather_timer = QTimer(self)
        self._weather_timer.setSingleShot(False)
        self._weather_timer.timeout.connect(self.request_weather)

        if self._weather_service is not None:
            self._weather_service.ready.connect(self._on_weather_ready)
            self._weather_service.failed.connect(self._on_weather_failed)

        self._set_initial_data()
        self.apply_state()
        if state_needs_weather(self.state):
            self._initial_weather_timer = QTimer(self)
            self._initial_weather_timer.setSingleShot(True)
            self._initial_weather_timer.setInterval(150)
            self._initial_weather_timer.timeout.connect(self.request_weather)
            self._initial_weather_timer.start()

    # --------------------------------------------------------------- window
    def _apply_window_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.state.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _set_initial_data(self) -> None:
        kind = self.state.kind
        if kind == "weather":
            self.data = {
                "city": self.state.resolved_city or self.state.city,
                "description": "Загрузка погоды…",
                "icon": "weather_cloud",
                "error": None,
            }
        elif kind == "custom":
            self._refresh_custom(initial=True)
        elif kind in ("clock", "date"):
            self._refresh_time()
        else:
            self._refresh_metrics()

    def _position_pin(self) -> None:
        self._pin_btn.move(max(4, self.width() - 30), 6)

    def apply_state(self) -> None:
        """Применяет настройки из редактора к живому окну."""
        if self._inline_editor is not None:
            self._commit_inline_editor()
        state = self.state
        was_visible = self.isVisible()
        desired_top = bool(state.always_on_top)
        has_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        flags_changed = desired_top != has_top
        if flags_changed:
            self._apply_window_flags()

        width = max(180, int(state.width))
        height = max(110, int(state.height))
        if self.size() != QSize(width, height):
            self.resize(width, height)
        self.move(int(state.x), int(state.y))
        self._position_pin()
        if flags_changed and was_visible:
            self.show()

        opacity = max(30, min(255, int(state.style.opacity)))
        self.setWindowOpacity(opacity / 255.0)

        self._apply_lock_visual()
        self._update_timers()
        self._sync_music()
        if state.kind == "weather":
            if not self.data.get("temp") and not self.data.get("error"):
                self.data["description"] = "Загрузка погоды…"
        elif state.kind == "custom":
            if state_needs_metrics(state):
                self.data["metrics"] = collect_all_metrics(state.interval)
            if state_needs_weather(state) and not self.data.get("weather"):
                self.data["weather"] = {
                    "city": state.resolved_city or state.city,
                    "description": "Загрузка погоды…",
                    "icon": "weather_cloud",
                    "error": None,
                }
            self.data["modules"] = self._module_snapshot()
        self._apply_mac_effects()
        self.update()

    def _mac_alpha(self, value: int) -> int:
        tweaks = self._mac_tweaks
        if tweaks is not None and tweaks.enabled and tweaks.glass:
            return min(int(value), max(45, 185 - int(tweaks.translucency)))
        return int(value)

    def apply_mac_tweaks(self, tweaks) -> None:
        """Применяет macOS-размытие и скругление без изменения стиля."""
        self._mac_tweaks = tweaks
        self._apply_mac_effects()
        self.update()

    def _apply_mac_effects(self) -> None:
        tweaks = self._mac_tweaks
        if tweaks is None:
            return
        enabled = bool(tweaks.enabled and tweaks.widget_blur)
        try:
            hwnd = int(self.winId())
        except (RuntimeError, TypeError, ValueError):
            return
        if enabled:
            alpha = max(55, min(210, 65 + int(tweaks.blur_strength)))
            try:
                enable_fence_blur(
                    hwnd, hex_to_bgr(self.state.style.bg), alpha
                )
                self._blur_enabled = True
            except Exception:
                self._blur_enabled = False
        elif self._blur_enabled:
            try:
                disable_blur(hwnd)
            except Exception:
                pass
            self._blur_enabled = False

        if tweaks is None:
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

    def _apply_lock_visual(self) -> None:
        self._pin_btn.setIcon(make_pin_icon(self.state.locked))
        self._pin_btn.setToolTip(
            "Открепить виджет" if self.state.locked else "Закрепить виджет"
        )
        self.setCursor(Qt.CursorShape.ArrowCursor if self.state.locked
                       else Qt.CursorShape.OpenHandCursor)
        if self.state.locked:
            self._pin_btn.show()
        elif not self._hovered:
            self._pin_btn.hide()

    # ---------------------------------------------------------------- timers
    def _update_timers(self) -> None:
        kind = self.state.kind
        interval = max(1, int(self.state.interval))
        if kind == "custom":
            if state_needs_clock(self.state):
                timer_ms = 1000
            elif state_needs_metrics(self.state):
                timer_ms = interval * 1000
            else:
                timer_ms = 0
        elif kind in ("clock", "date"):
            timer_ms = 1000 if kind == "clock" else 30_000
        elif kind in ("cpu", "memory", "battery", "disk"):
            timer_ms = interval * 1000
        else:
            timer_ms = 0

        signature = (kind, interval, self.state.show_seconds,
                     tuple(sorted(module for module in
                                  ({b.module for b in self.state.blocks}
                                   if kind == "custom" else {kind}))))
        if signature != self._timer_signature:
            self._timer_signature = signature
            if timer_ms:
                self._timer.setInterval(timer_ms)
                self._timer.start()
            else:
                self._timer.stop()

        if state_needs_weather(self.state):
            weather_ms = max(1, interval) * 60_000
            if not self._weather_timer.isActive() or \
                    self._weather_timer.interval() != weather_ms:
                self._weather_timer.start(weather_ms)
        else:
            self._weather_timer.stop()

    def _on_timer(self) -> None:
        if self.state.kind == "custom":
            self._refresh_custom()
        elif self.state.kind in ("clock", "date"):
            self._refresh_time()
        else:
            self._refresh_metrics()

    def _refresh_time(self) -> None:
        now = datetime.now()
        if self.state.kind == "date":
            self.data = {
                "day": str(now.day),
                "month": MONTHS_GENITIVE[now.month - 1],
                "weekday": WEEKDAYS[now.weekday()],
                "year": str(now.year),
            }
        else:
            self.data = {
                "time": format_clock(now, self.state.clock_24h,
                                     self.state.show_seconds),
                "date": f"{WEEKDAYS[now.weekday()]}, {now.day} "
                        f"{MONTHS_GENITIVE[now.month - 1]}",
                "greeting": self._greeting(now.hour),
                "seconds": now.second,
            }
        self.update()
        self.data_updated.emit(self.state.id)

    def _refresh_metrics(self) -> None:
        self.data = collect_metric_data(self.state)
        self.update()
        self.data_updated.emit(self.state.id)

    def _refresh_custom(self, initial: bool = False) -> None:
        """Обновляет показатели составного виджета, не теряя погоду."""
        if initial or not isinstance(self.data, dict):
            self.data = {}
        if state_needs_metrics(self.state):
            self.data["metrics"] = collect_all_metrics(self.state.interval)
        else:
            self.data.setdefault("metrics", {})
        if state_needs_weather(self.state):
            if not self.data.get("weather"):
                self.data["weather"] = {
                    "city": self.state.resolved_city or self.state.city,
                    "description": "Загрузка погоды…",
                    "icon": "weather_cloud",
                    "error": None,
                }
        self.data["modules"] = self._module_snapshot()
        self.update()
        self.data_updated.emit(self.state.id)

    # ---------------------------------------------------------- mini modules
    def _runtime(self, block_id: str) -> dict:
        return self._module_runtime.setdefault(block_id, {})

    def _module_snapshot(self) -> dict[str, dict]:
        """Текущее состояние таймеров и секундомеров для отрисовки."""
        now = time.monotonic()
        result: dict[str, dict] = {}
        for block in self.state.blocks:
            if block.module == "stopwatch":
                runtime = self._runtime(block.id)
                running = bool(runtime.get("running"))
                elapsed = float(runtime.get("elapsed", 0.0) or 0.0)
                if running:
                    elapsed += max(0.0, now - float(
                        runtime.get("started", now)
                    ))
                result[block.id] = {
                    "stopwatch_elapsed": elapsed,
                    "stopwatch_running": running,
                }
            elif block.module == "timer":
                duration = float(max(1, parse_duration(
                    block.settings.get("duration", "300")
                )))
                runtime = self._runtime(block.id)
                if "remaining" not in runtime:
                    runtime["remaining"] = duration
                if runtime.get("running"):
                    remaining = max(0.0, float(
                        runtime.get("deadline", now)
                    ) - now)
                    if remaining <= 0:
                        runtime["running"] = False
                        runtime["remaining"] = 0.0
                    else:
                        runtime["remaining"] = remaining
                result[block.id] = {
                    "timer_remaining": float(
                        runtime.get("remaining", duration)
                    ),
                    "timer_running": bool(runtime.get("running")),
                    "timer_duration": duration,
                }
            elif block.module == "music":
                runtime = self._runtime(block.id)
                result[block.id] = {
                    "music_playing": bool(runtime.get("playing")),
                    "music_error": str(runtime.get("error") or ""),
                }
        return result

    def _find_block(self, block_id: str):
        return next((block for block in self.state.blocks
                     if block.id == block_id), None)

    def toggle_module(self, block_id: str) -> None:
        """Старт/пауза таймера или секундомера по клику на блок."""
        block = self._find_block(block_id)
        if block is None:
            return
        now = time.monotonic()
        runtime = self._runtime(block.id)
        if block.module == "stopwatch":
            if runtime.get("running"):
                runtime["elapsed"] = float(runtime.get("elapsed", 0.0)) + max(
                    0.0, now - float(runtime.get("started", now))
                )
                runtime["running"] = False
            else:
                runtime["started"] = now
                runtime["running"] = True
        elif block.module == "timer":
            if runtime.get("running"):
                runtime["remaining"] = max(
                    0.0, float(runtime.get("deadline", now)) - now
                )
                runtime["running"] = False
            else:
                duration = float(max(1, parse_duration(
                    block.settings.get("duration", "300")
                )))
                remaining = float(runtime.get("remaining", duration) or 0.0)
                if remaining <= 0:
                    remaining = duration
                runtime["remaining"] = remaining
                runtime["deadline"] = now + remaining
                runtime["running"] = True
        else:
            return
        self._refresh_custom()

    def reset_module(self, block_id: str) -> None:
        """Сбрасывает таймер или секундомер из панели свойств."""
        block = self._find_block(block_id)
        if block is None:
            return
        runtime = self._runtime(block.id)
        runtime.clear()
        if block.module == "timer":
            runtime["remaining"] = float(max(1, parse_duration(
                block.settings.get("duration", "300")
            )))
            runtime["running"] = False
        elif block.module == "stopwatch":
            runtime["elapsed"] = 0.0
            runtime["running"] = False
        else:
            return
        self._refresh_custom()

    def toggle_plan(self, block_id: str, index: int) -> None:
        """Переключает отметку плана на день по двойному клику."""
        block = self._find_block(block_id)
        if block is None or block.module != "plans":
            return
        items = parse_plans(block.text)
        if not 0 <= index < len(items):
            return
        block.settings["done"] = toggle_plan_done(
            block.settings.get("done", ""), index, len(items)
        )
        self.update()
        self.state_changed.emit(self.state.id)

    # ---------------------------------------------------------------- music
    def _ensure_music_player(self):
        """Лениво создаёт встроенный аудиоплеер (QtMultimedia)."""
        if self._music_player is not None:
            return self._music_player
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer

        self._music_audio = QAudioOutput(self)
        player = QMediaPlayer(self)
        player.setAudioOutput(self._music_audio)
        player.playbackStateChanged.connect(self._on_music_playback)
        player.errorOccurred.connect(self._on_music_error)
        self._music_player = player
        return player

    def _apply_music_volume(self, block) -> None:
        if self._music_audio is None:
            return
        try:
            value = int(float(str(
                block.settings.get("volume", "70")
            ).replace(",", ".")))
        except (TypeError, ValueError):
            value = 70
        self._music_audio.setVolume(max(0, min(100, value)) / 100.0)

    def _on_music_playback(self, state) -> None:
        try:
            if not self._music_block_id:
                return
            from PyQt6.QtMultimedia import QMediaPlayer

            playing = state == QMediaPlayer.PlaybackState.PlayingState
            runtime = self._runtime(self._music_block_id)
            runtime["playing"] = playing
            if playing:
                runtime["error"] = ""
            self._refresh_custom()
        except Exception:
            # Слот не должен ронять приложение при сбое мультимедиа.
            pass

    def _on_music_error(self, error, message: str) -> None:
        try:
            if not self._music_block_id:
                return
            from PyQt6.QtMultimedia import QMediaPlayer

            if error == QMediaPlayer.Error.NoError:
                return
            runtime = self._runtime(self._music_block_id)
            runtime["playing"] = False
            runtime["error"] = "Не удалось воспроизвести"
            self.status_changed.emit(
                self.state.id, message or "Ошибка воспроизведения"
            )
            self._refresh_custom()
        except Exception:
            pass

    def stop_music(self) -> None:
        """Останавливает встроенный плеер при закрытии или смене трека."""
        player = self._music_player
        if player is not None:
            try:
                player.stop()
            except Exception:
                pass
        had_block = bool(self._music_block_id)
        if had_block:
            runtime = self._runtime(self._music_block_id)
            runtime["playing"] = False
            runtime["error"] = ""
        self._music_block_id = ""
        self._music_url = ""
        if had_block and self.state.kind == "custom" \
                and isinstance(self.data, dict):
            self._refresh_custom()

    def _sync_music(self) -> None:
        """Сбрасывает плеер, если трек изменили или блок удалили."""
        if not self._music_block_id:
            return
        block = self._find_block(self._music_block_id)
        if block is None or block.module != "music":
            self.stop_music()
            return
        url = normalize_music_url(block.settings.get("url", ""))
        if url != self._music_url:
            self.stop_music()
            return
        self._apply_music_volume(block)

    def _open_music_link(self, block, url: str) -> None:
        target = browser_music_url(url)
        opened = bool(target) and QDesktopServices.openUrl(QUrl(target))
        runtime = self._runtime(block.id)
        runtime["playing"] = False
        runtime["error"] = "" if opened else "Не удалось открыть ссылку"
        if opened:
            source = music_source(block.settings.get("source", "auto"), url)
            self.status_changed.emit(
                self.state.id,
                f"Открыто в браузере: {music_source_label(source)}"
            )
        else:
            self.status_changed.emit(
                self.state.id, "Не удалось открыть музыкальную ссылку"
            )
        self._refresh_custom()

    def toggle_music(self, block_id: str) -> None:
        """Играет аудио встроенным плеером или открывает сервис в браузере."""
        block = self._find_block(block_id)
        if block is None or block.module != "music":
            return
        url = normalize_music_url(block.settings.get("url", ""))
        if not url:
            self.status_changed.emit(
                self.state.id, "Укажите ссылку на музыку в свойствах"
            )
            return
        source = music_source(block.settings.get("source", "auto"), url)
        if source in ("spotify", "soundcloud", "yandex", "browser") \
                or not is_audio_url(url):
            self._open_music_link(block, url)
            return
        try:
            player = self._ensure_music_player()
            from PyQt6.QtMultimedia import QMediaPlayer
        except Exception:
            # Без QtMultimedia хотя бы открываем ссылку в браузере.
            self._open_music_link(block, url)
            return

        runtime = self._runtime(block.id)
        playing_same = (
            self._music_block_id == block.id
            and player.playbackState()
            == QMediaPlayer.PlaybackState.PlayingState
        )
        if playing_same:
            player.pause()
            runtime["playing"] = False
            self._refresh_custom()
            return
        if self._music_block_id != block.id or self._music_url != url:
            if self._music_block_id and self._music_block_id != block.id:
                previous = self._runtime(self._music_block_id)
                previous["playing"] = False
            player.stop()
            self._music_block_id = block.id
            self._music_url = url
            player.setSource(QUrl(url))
        self._apply_music_volume(block)
        runtime["error"] = ""
        player.play()
        runtime["playing"] = True
        self._refresh_custom()

    # ------------------------------------------------------- inline editing
    def _block_at(self, point: QPointF):
        card = widget_card_rect(QRectF(self.rect()))
        for block, rect in reversed(iter_widget_blocks(self.state, card)):
            if rect.contains(point):
                return block, rect
        return None, QRectF()

    def _begin_inline_edit(self, block, rect: QRectF) -> None:
        self._commit_inline_editor()
        if block.module == "notepad":
            editor: QWidget = QPlainTextEdit(self)
            editor.setPlainText(block.text)
            editor.setPlaceholderText("Заметка…")
            editor.setTabChangesFocus(True)
        else:
            editor = QLineEdit(self)
            if block.module == "calculator":
                editor.setText(block.settings.get("expression", ""))
                editor.setPlaceholderText("Например: 12 × 8 + 5")
            else:
                editor.setText(block.settings.get("value", ""))
                editor.setPlaceholderText("Значение модуля")
        editor.setObjectName("moduleInlineEditor")
        editor.setStyleSheet(
            "QWidget#moduleInlineEditor {"
            " background: rgba(10, 16, 24, 225);"
            " color: #ffffff;"
            " border: 1px solid rgba(138, 180, 255, 210);"
            " border-radius: 7px;"
            " padding: 3px 6px;"
            " selection-background-color: rgba(92, 200, 255, 120);"
            "}"
        )
        font = editor.font()
        font.setPointSize(max(8, min(14, int(rect.height() / 5))))
        editor.setFont(font)
        pad = max(3.0, min(float(block.style.padding), rect.width() / 5,
                           rect.height() / 5))
        area = rect.adjusted(pad, pad, -pad, -pad).toRect()
        if area.width() < 40:
            area.setWidth(40)
        if area.height() < 24:
            area.setHeight(24)
        editor.setGeometry(area)
        editor.installEventFilter(self)
        if isinstance(editor, QLineEdit):
            editor.editingFinished.connect(self._commit_inline_editor)
        self._inline_editor = editor
        self._inline_block_id = block.id
        editor.show()
        editor.setFocus()
        editor.selectAll()

    def _commit_inline_editor(self) -> None:
        if self._committing_editor:
            return
        editor = self._inline_editor
        if editor is None:
            return
        self._committing_editor = True
        try:
            if isinstance(editor, QPlainTextEdit):
                value = editor.toPlainText()
            elif isinstance(editor, QLineEdit):
                value = editor.text()
            else:
                value = ""
            block_id = self._inline_block_id
            self._inline_editor = None
            self._inline_block_id = ""
            editor.removeEventFilter(self)
            editor.hide()
            editor.deleteLater()
            block = self._find_block(block_id)
            if block is not None:
                if block.module == "notepad":
                    block.text = value
                elif block.module == "calculator":
                    block.settings["expression"] = value.strip()
                elif block.module == "user":
                    block.settings["value"] = value.strip()
                    self.apply_state()
                self.state_changed.emit(self.state.id)
            self.setCursor(Qt.CursorShape.ArrowCursor if self.state.locked
                           else Qt.CursorShape.OpenHandCursor)
            self.update()
        finally:
            self._committing_editor = False

    def _commit_editor_if_unfocused(self) -> None:
        editor = self._inline_editor
        if editor is not None and not editor.hasFocus():
            self._commit_inline_editor()

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._inline_editor:
            return super().eventFilter(obj, event)
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._commit_inline_editor()
                return True
            if (isinstance(obj, QPlainTextEdit)
                    and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                    and event.modifiers()
                    & Qt.KeyboardModifier.ControlModifier):
                self._commit_inline_editor()
                return True
        elif event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self._commit_editor_if_unfocused)
        return super().eventFilter(obj, event)

    @staticmethod
    def _greeting(hour: int) -> str:
        if 5 <= hour < 12:
            return "Доброе утро"
        if 12 <= hour < 18:
            return "Добрый день"
        if 18 <= hour < 23:
            return "Добрый вечер"
        return "Доброй ночи"

    def refresh_now(self) -> None:
        if self.state.kind == "custom":
            self._refresh_custom()
            if state_needs_weather(self.state):
                self.request_weather()
        elif self.state.kind in ("clock", "date"):
            self._refresh_time()
        elif self.state.kind == "weather":
            self.request_weather()
        else:
            self._refresh_metrics()

    # --------------------------------------------------------------- weather
    def request_weather(self) -> None:
        if not state_needs_weather(self.state) or self._weather_service is None:
            return
        city = self.state.city.strip()
        if not city:
            if self.state.kind == "custom":
                self.data["weather"] = {
                    "description": "Укажите город", "icon": "weather_cloud",
                    "error": "Укажите город", "city": "",
                }
            else:
                self.data = {"description": "Укажите город",
                             "icon": "weather_cloud",
                             "error": "Укажите город", "city": ""}
            self.status_changed.emit(self.state.id, "Укажите город")
            self.update()
            return

        self.status_changed.emit(self.state.id, "Обновление…")
        self._weather_service.request(self.state.id, city, self.state.units)

    def _on_weather_ready(self, key: str, data: dict) -> None:
        if key != self._weather_key or not state_needs_weather(self.state):
            return
        if str(data.get("query_city", "")).casefold() != \
                self.state.city.strip().casefold():
            return

        data["error"] = None
        if self.state.kind == "custom":
            self.data["weather"] = data
        else:
            self.data = data
        self.state.resolved_city = str(data.get("city") or self.state.city)
        self.state_changed.emit(self.state.id)
        self.status_changed.emit(
            self.state.id, f"Найдено: {self.state.resolved_city}"
        )
        self.update()
        self.data_updated.emit(self.state.id)

    def _on_weather_failed(self, key: str, message: str) -> None:
        if key != self._weather_key or not state_needs_weather(self.state):
            return
        self.status_changed.emit(self.state.id, message)
        if self.state.kind == "custom":
            weather = self.data.setdefault("weather", {})
            if weather.get("temp") is None:
                weather.clear()
                weather.update({
                    "city": self.state.resolved_city or self.state.city,
                    "description": message,
                    "icon": "weather_cloud",
                    "error": message,
                })
                self.update()
                self.data_updated.emit(self.state.id)
        elif self.data.get("temp") is None:
            self.data = {
                "city": self.state.resolved_city or self.state.city,
                "description": message,
                "icon": "weather_cloud",
                "error": message,
            }
            self.update()
            self.data_updated.emit(self.state.id)

    # --------------------------------------------------------------- state
    def toggle_lock(self) -> None:
        self.state.locked = not self.state.locked
        self._apply_lock_visual()
        self.state_changed.emit(self.state.id)
        self.update()

    def set_always_on_top(self, enabled: bool) -> None:
        self.state.always_on_top = enabled
        self.apply_state()
        self.state_changed.emit(self.state.id)

    def rename(self, title: str) -> None:
        self.state.title = title
        self.setWindowTitle(f"Gridly — {title}")
        self.update()

    # --------------------------------------------------------------- events
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        paint_data = self.data
        if self.state.kind == "weather" and not paint_data:
            paint_data = sample_data(self.state.kind, self.state)
        style = self.state.style
        original_alpha = style.bg_alpha
        original_radius = style.corner_radius
        style.bg_alpha = self._mac_alpha(original_alpha)
        tweaks = self._mac_tweaks
        if tweaks is not None and tweaks.enabled and tweaks.rounded:
            style.corner_radius = int(tweaks.corner_radius)
        try:
            paint_widget(p, self.rect(), self.state, paint_data,
                         hovered=self._hovered)
        finally:
            style.bg_alpha = original_alpha
            style.corner_radius = original_radius
            p.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_pin()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._pin_btn.show()
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        if not self.state.locked:
            self._pin_btn.hide()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            point = QPointF(event.position())
            block, rect = self._block_at(point)
            if block is not None:
                if block.module in ("notepad", "calculator", "user"):
                    self._begin_inline_edit(block, rect)
                    event.accept()
                    return
                if block.module in ("timer", "stopwatch"):
                    self._commit_inline_editor()
                    self.toggle_module(block.id)
                    event.accept()
                    return
                if block.module == "music":
                    self._commit_inline_editor()
                    self.toggle_music(block.id)
                    event.accept()
                    return
            if self._inline_editor is not None:
                self._commit_inline_editor()
            if self.state.locked:
                return
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and \
                event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._mac_tweaks is not None and self._mac_tweaks.enabled:
            QTimer.singleShot(0, self._apply_mac_effects)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and \
                self._drag_offset is not None:
            self._drag_offset = None
            self.state.x = self.x()
            self.state.y = self.y()
            self.setCursor(Qt.CursorShape.ArrowCursor if self.state.locked
                           else Qt.CursorShape.OpenHandCursor)
            self.geometry_changed.emit(self.state.id)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            point = QPointF(event.position())
            block, rect = self._block_at(point)
            if block is not None and block.module == "plans":
                index = plan_row_index_at(block, rect, point)
                if index is not None:
                    self.toggle_plan(block.id, index)
                    event.accept()
                    return
            self.edit_requested.emit(self.state.id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event) -> None:
        self.stop_music()
        if self._blur_enabled:
            try:
                disable_blur(int(self.winId()))
            except Exception:
                pass
            self._blur_enabled = False
        super().closeEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        edit = menu.addAction("Настроить")
        lock = menu.addAction("Открепить" if self.state.locked
                              else "Закрепить")
        top = menu.addAction("Поверх всех окон")
        top.setCheckable(True)
        top.setChecked(self.state.always_on_top)
        menu.addSeparator()
        refresh = menu.addAction("Обновить")
        duplicate = menu.addAction("Дублировать")
        menu.addSeparator()
        remove = menu.addAction("Удалить виджет")

        chosen = menu.exec(event.globalPos())
        if chosen is edit:
            self.edit_requested.emit(self.state.id)
        elif chosen is lock:
            self.toggle_lock()
        elif chosen is top:
            self.set_always_on_top(top.isChecked())
        elif chosen is refresh:
            self.refresh_now()
        elif chosen is duplicate:
            self.duplicate_requested.emit(self.state.id)
        elif chosen is remove:
            self.delete_requested.emit(self.state.id)


class WidgetPreviewWidget(QWidget):
    """Карточка живого предпросмотра в конструкторе."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._state: WidgetState | None = None
        self._data: dict | None = None
        self.setFixedHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def set_state(self, state: WidgetState) -> None:
        self._state = state
        self.update()

    def set_data(self, data: dict | None) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event) -> None:
        if self._state is None:
            return
        p = QPainter(self)
        dark = self.palette().color(self.backgroundRole()).lightness() < 128
        data = self._data
        if not data:
            data = sample_data(self._state.kind, self._state)
        WidgetPreview.paint(p, QRectF(self.rect()), self._state, data, dark)
        p.end()
