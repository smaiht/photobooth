# Photobooth

Фотобудка: Canon EDSDK + сублимационный принтер + сенсорный экран.
FastAPI backend + pywebview fullscreen window.

## Структура

```
photobooth/
  python/              ← Python 3.12 embedded + pip + все пакеты
  backend/             ← FastAPI, камера, принтер, облако
  frontend/            ← HTML/CSS/JS интерфейс
  templates/           ← шаблоны печати
  bin/                 ← ffmpeg
  EDSDK_Win/           ← Canon SDK
  app.py               ← точка входа
  requirements.txt
```

`python/` — портативный Python со всеми зависимостями. Заменяет venv.
Создаётся автоматически (см. ниже). В git не хранится.

## Установка

### Вариант А: из релиза (рекомендуется)

```
Скачать photobooth-win.zip из GitHub Releases → распаковать в C:\photobooth\
```

ZIP содержит всё: код, .git, python/ с пакетами. Готово к запуску.

### Вариант Б: из git clone

```
git clone → script_devstart.bat
```

Скрипт сам скачает embedded Python, поставит pip и пакеты.

### Результат одинаковый

Оба варианта дают идентичную структуру. Взаимозаменяемы.

## Запуск

```
Разработка:    script_devstart.bat     (git pull + pip install + app.py --dev)
Продакшен:     _setup_windows.bat      (киоск-режим, автозапуск при загрузке)
```

## Сборка релиза (GitHub Actions)

При каждом push в main:

```
GitHub Actions (windows-latest)
  → checkout репо
  → скачивает Python 3.12 embedded с python.org
  → pip install -r requirements.txt
  → пакует всё (код + .git + python/) в ZIP
  → публикует как GitHub Release "latest"
```

Постоянная ссылка: `Releases → latest → photobooth-win.zip`

## Обновление

```
Telegram /update или /update_small
  → VPS скачивает full release или ZIP исходников с GitHub
  → VPS перезаписывает artifacts/full.zip или artifacts/small.zip
  → VPS последним обновляет status.json
  → администратор отправляет /restart

Запуск app.py
  → читает status.json с Яндекс Диска
  → сравнивает SHA-256 активного ZIP с .update_hash
  → скачивает ZIP и проверяет размер + SHA-256
  → распаковывает поверх приложения, сохраняя локальные настройки
  → записывает новый hash и перезапускается
```

`/update` публикует полный Windows-релиз с embedded Python. `/update_small`
публикует только код без `python/`, `bin/` и `EDSDK_Win/`. Для обычных правок
кода достаточно small. Full после выхода будки применяет одноразовый PowerShell
скрипт, поэтому может заменить заблокированные `python.exe`, DLL и PYD без
постоянного launcher-сервиса.

`status.json` хранит записи для full и small, а поле `active` указывает, какую
из них устанавливать. Отдельного номера версии нет: версия — полный SHA-256 ZIP.

Будке доступ к GitHub не нужен: GitHub использует только VPS при публикации,
а будка всегда получает обновление через Яндекс Диск.

## Киоск-режим

`_setup_windows.bat` (от админа):
1. Создаёт/проверяет `python/` (через `_ensure_python.bat`)
2. Создаёт пользователя Photobooth
3. Shell = `python\pythonw.exe app.py` (вместо explorer.exe)
4. Автологин без пароля

Выход: Ctrl+Alt+Del → сменить пользователя.
Откат: `_undo_setup.bat`

## Облако

Основной transport — публичный REST API Яндекс Диска с OAuth-токеном.
Перед ивентом отдельная папка задаётся Telegram-командой `/event Название`.
После подтверждения команда атомарно обновляет `yadisk_folder` в конфигурациях
будки и VPS.
Все фото, печатный макет и видео остаются в корне этой папки, поэтому после
ивента её можно опубликовать в интерфейсе Диска и передать владельцу одну ссылку.

Доставка сессии работает как durable outbox:

1. Будка сохраняет полную сессию в локальную очередь `yadisk_queue.json`.
2. Все медиа последовательно загружаются и проверяются по размеру и MD5.
3. Последним загружается JSON-манифест в `_sessions/inbox`.
4. VPS скачивает и проверяет все файлы, отправляет их в Telegram.
5. После успеха VPS переносит манифест в `_sessions/done`; медиа не удаляются.

Команды, ответы и логи используют приватную папку
`photobooth_system/control`; обновления — `photobooth_system/updates`.

## Telegram-команды

- `/event Свадьба Ивановых 2026` — создать и активировать папку на будке и VPS;
- `/status` — state, камера, event, очередь и версия будки;
- `/run` — запустить фотосессию;
- `/logs`, `/clear_logs` — получить или очистить лог;
- `/restart` — подтверждённый перезапуск;
- `/update_small`, `/update` — опубликовать обновление; установка после `/restart`;
- `/link` — опубликовать активную event-папку и вернуть публичную ссылку.

Смена event отклоняется, пока идёт сессия или локальная загрузка. Сессию команда
не прерывает; после освобождения будки команду нужно повторить.

## Смена аккаунта Диска

Никаких ID ресурсов или аккаунта в коде нет. Нужно заменить `YADISK_TOKEN` в
`.env` будки и VPS, перезапустить оба процесса, выполнить `/event ...`, затем
`/update_small` или `/update`. Системные папки создаются автоматически; данные
старого аккаунта не копируются.
