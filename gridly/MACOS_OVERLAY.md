# macOS-панель поверх всех окон

`macos_global_overlay.py` — самостоятельная PyObjC-панель, которая заменяет
нижний Dock: висит поверх обычных окон и системного Dock, видна на всех
Spaces и не крадёт фокус у активного приложения.

Это не часть Gridly и не требует зависимостей Gridly — только PyObjC.

## Требования

- macOS 11 Big Sur или новее (SF Symbols и `NSVisualEffectMaterialHUDWindow`).
- Python 3.10+ (PyObjC 12 требует 3.10+).
- Установленные Python-пакеты:

```bash
cd /путь/к/gridly
python3 -m venv .venv-macos
source .venv-macos/bin/activate
python3 -m pip install -r requirements-macos.txt
```

Если Python установлен из python.org или Homebrew, используй именно его:
`/usr/bin/python3` из Command Line Tools может не иметь PyObjC.

## Запуск

```bash
source .venv-macos/bin/activate
python3 macos_global_overlay.py
```

После запуска:

- в Dock **не появляется** иконка приложения (activation policy `Accessory`);
- в строке меню появляется иконка `dock.rectangle`;
- внизу экрана — стеклянная панель с иконками запущенных приложений и часами;
- клик по иконке приложения активирует его, повторный клик по активному —
  скрывает;
- кнопка `…` открывает меню приложений, не влезших в панель;
- меню в строке меню: «Скрыть панель» / «Показать панель» и «Выход».

Остановить: «Выход» в меню status item или `Ctrl+C` в терминале.

## Как это устроено

| Требование | Реализация |
| --- | --- |
| Поверх всех окон | `NSPanel.setLevel_(NSMainMenuWindowLevel)` (24 > уровня Dock 20) |
| Все Spaces и fullscreen | `CanJoinAllSpaces \| Stationary \| FullScreenAuxiliary \| IgnoresCycle` |
| Без рамки | `NSWindowStyleMaskBorderless` |
| Неактивирующая панель | `NSWindowStyleMaskNonactivatingPanel`, `setFloatingPanel_(True)`, `canBecomeKeyWindow`/`canBecomeMainWindow` → `False` |
| Матовое стекло | `NSVisualEffectView` с `NSVisualEffectMaterialHUDWindow` |
| Без иконки в Dock | `NSApplicationActivationPolicyAccessory` |
| Первый клик по кнопке | `OverlayButton.acceptsFirstMouse_` → `True` |
| Список приложений | `NSWorkspace.runningApplications()` + уведомления launch/terminate |
| Часы | `NSTimer` раз в секунду, `NSDateFormatter` с локалью `ru_RU` |

Панель позиционируется по `NSScreen.frame()`, а не `visibleFrame()`, поэтому
ложится поверх области системного Dock. При смене разрешения/монитора и
переключении Space панель пересобирается и поднимается заново.

## Ограничения macOS

1. **Полностью убрать системный Dock программно нельзя.** Публичного API для
   этого нет; менять `com.apple.dock` и убивать `Dock.app` — плохая идея.
   Панель рисуется поверх Dock. Чтобы системный Dock не выглядывал по краям,
   включи его автоматическое скрытие:
   System Settings → Desktop & Dock → Automatically hide and show the Dock.
2. **Fullscreen.** Панель использует `FullScreenAuxiliary` и должна появляться
   поверх полноэкранных приложений. Если этого не происходит, проверь
   System Settings → Desktop & Dock → Mission Control → «Displays have
   separate Spaces» и перезапусти панель.
3. **Права.** Для активации приложений через `NSWorkspace` права Accessibility
   не нужны. Они понадобятся, только если добавлять глобальные горячие клавиши
   через event tap.
4. **Gatekeeper.** При запуске из терминала скрипт не требует подписи. Если
   упаковывать в `.app` через py2app, нужно подписывать и notarize.

## Готовый набор из Gridly (вкладка «Твики» → «macOS overlay»)

Во вкладке «Твики» появилась группа **macOS overlay**:

- «Панель включена» — пишет `enabled` в конфиг (выключенная панель при
  запуске сразу завершится с пояснением);
- «Уровень окна поверх системы» — `NSMainMenuWindowLevel` или
  `NSFloatingWindowLevel`;
- «Иконок приложений до кнопки …» — 4…30 (`MAX_VISIBLE_APPS`);
- «Часы в панели» — показать/убрать часы и разделитель.

Каждое изменение пишется в два места:
1. `data/tweaks.json` (стандартные твики Gridly),
2. `macos_overlay.json` рядом с `macos_global_overlay.py` — его читает скрипт.

Кнопка **«Экспортировать overlay…»** собирает в выбранную папку готовый
набор для переноса на Mac: скрипт, `requirements-macos.txt`,
`MACOS_OVERLAY.md` и актуальный `macos_overlay.json`. Скрипт ищет конфиг так:
1. `macos_overlay.json` рядом со скриптом,
2. `data/tweaks.json` проекта (плоские поля `overlay_*`),
3. встроенные значения по умолчанию.

## Установка по шагам (на Mac)

1. Поставь Python 3.10+ (python.org или Homebrew) и Xcode Command Line
   Tools, если их нет: `xcode-select --install`.
2. Создай папку с набором (или клонируй проект) и открой Terminal в ней.
3. ```bash
   python3 -m venv .venv-overlay
   source .venv-overlay/bin/activate
   python3 -m pip install -r requirements-macos.txt
   ```
   Быстрая альтернатива — полный пакет: `python3 -m pip install pyobjc`
   (тяжелее, но ставит всё сразу).
4. Запусти: `python3 macos_global_overlay.py`.

## Разрешения macOS: что реально требуется

| Разрешение | Нужен ли для этой панели | Зачем вообще бывает |
| --- | --- | --- |
| Универсальный доступ (Accessibility) | **Нет** | только если добавить глобальные хоткеи (CGEventTap) или доступ к чужим окнам через AXUIElement |
| Запись экрана (Screen Recording) | **Нет** | для снятия скриншотов/чтения пикселей других окон (CGWindowListCreateImage) |
| Управление папками/файлами (Files & Folders) | **Нет** | скрипт не трогает чужие файлы |
| Уведомления, Автоматизация (Apple Events) | **Нет** | активация приложений идёт через NSWorkspace, без AppleScript |

Вывод: для отображения поверх всех окон, кликов по иконкам и активации
приложений особые разрешения **не нужны** — достаточно обычного права
запускать программы терминалом. Если позже добавишься хоткеи — дай
Terminal/Python право «Универсальный доступ»:
System Settings → Privacy & Security → Accessibility → добавить Terminal
(или исполняемый файл Python из venv).

Если скачал набор из интернета и Gatekeeper ругается на скачиваемый файл:
`xattr -dr com.apple.quarantine macos_global_overlay.py` (только для своих
файлов, либо подписывай/нотаризуй при сборке .app через py2app).

## Автозапуск (LaunchAgent)

Создай `~/Library/LaunchAgents/local.gridly.overlay.plist` (подставь свои пути):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.gridly.overlay</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/ИМЯ/gridly/.venv-macos/bin/python3</string>
        <string>/Users/ИМЯ/gridly/macos_global_overlay.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/gridly-overlay.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/gridly-overlay.err</string>
</dict>
</plist>
```

Загрузка:

```bash
launchctl load -w ~/Library/LaunchAgents/local.gridly.overlay.plist
launchctl unload -w ~/Library/LaunchAgents/local.gridly.overlay.plist  # выключить
```

## Настройка внешнего вида

Константы в начале `macos_global_overlay.py`:

- `PANEL_HEIGHT` — высота панели;
- `PANEL_CORNER` — радиус скругления;
- `ICON_SIZE` / `BUTTON_SIZE` — размер иконки и кнопки;
- `MAX_VISIBLE_APPS` — сколько иконок показывать до кнопки `…`;
- `CLOCK_WIDTH`, `CLOCK_FORMAT`, `CLOCK_LOCALE` — часы;
- `PANEL_CAN_BECOME_KEY` — по умолчанию `False` (панель не становится key).
  Если на твоей версии macOS кнопки реагируют только со второго клика,
  поставь `True`: nonactivating-панель всё равно не активирует приложение.

## Если что-то не работает

- `ModuleNotFoundError: No module named 'AppKit'` — запущен не тот Python.
  Активируй venv и проверь `python3 -c "import AppKit, Quartz"`.
- Кнопки срабатывают со второго клика — поставь `PANEL_CAN_BECOME_KEY = True`
  в начале `macos_global_overlay.py` и перезапусти панель.
- Панель не видна — нажми иконку в строке меню и выбери «Показать панель».
- Панель перекрыта другим окном — проверь, что запущен именно этот скрипт,
  а не старая копия; уровень панели задаётся в `OverlayPanel.init`.
- Панель не появляется на втором мониторе — она живёт на главном экране
  (`NSScreen.mainScreen()`); для мультимониторной версии нужно создавать
  по панели на каждый `NSScreen.screens()`.

## Заголовки окон (плашка вместо нативного заголовка)

Скрипт умеет заменить заголовок окон выбранных приложений собственной
плашкой с кнопками закрыть / свернуть / развернуть и названием. Модуль
`macos_titlebar_wrap.py` лежит рядом со скриптом и работает в том же процессе.

- Включается во вкладке «Твики» → «macOS overlay» → «Заменять заголовки окон
  плашкой Gridly» или вручную: `"titlebar_enabled": true` в `macos_overlay.json`.
- Приложения задаются bundle id через запятую (поле «Приложения» или
  `"titlebar_bundles": ["com.apple.TextEdit", "com.apple.Notes"]`).
  Bundle id приложения: `osascript -e 'id of app "TextEdit"'`.
- Высота заголовка по умолчанию 28 pt. Для окон с объединённым тулбаром
  (Safari, Mail) или вкладками в заголовке (Chrome) задай `"titlebar_heights":
  {"com.apple.Safari": 52}`.
- Нужно право **Универсальный доступ** (Accessibility) для того терминала или
  Python, из которого запускается скрипт. Запись экрана не нужна.

Ограничения: нативный заголовок не удаляется, а закрывается плашкой.
Полноэкранные окна, листы и поповеры не оборачиваются. Угол окна за плашкой
нельзя потянуть за заголовок, но стороны и низ работают как обычно.
