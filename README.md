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
┌─────────────────────────────────────────────┐
│              Запуск app.py                  │
│                   │                         │
│          github.com доступен?               │
│            /              \                 │
│          ДА                НЕТ              │
│           │                 │               │
│       git pull         (TODO) читаем        │
│       pip install      заметку pb_update    │
│       перезапуск       скачиваем ZIP        │
│           │            распаковываем        │
│           │            перезапуск            │
│           │                 │               │
│           └────────┬────────┘               │
│                    │                        │
│             запуск сервера                  │
└─────────────────────────────────────────────┘
```

### Зачем два пути?

В России GitHub периодически блокируется. Если git pull недоступен —
обновление идёт через Яндекс Заметки (VPS-посредник скачивает релиз
с GitHub и кладёт в заметку, будка забирает оттуда).

## Киоск-режим

`_setup_windows.bat` (от админа):
1. Создаёт/проверяет `python/` (через `_ensure_python.bat`)
2. Создаёт пользователя Photobooth
3. Shell = `python\pythonw.exe app.py` (вместо explorer.exe)
4. Автологин без пароля

Выход: Ctrl+Alt+Del → сменить пользователя.
Откат: `_undo_setup.bat`

## Облако

Фото загружаются через Яндекс Заметки (6 слотов).
Персистентная очередь с ретраями. Подробнее: `backend/cloud.py`.
