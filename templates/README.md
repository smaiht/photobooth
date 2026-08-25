# Template tools

## Проверить новые фоны

Один запуск для grid и полосок. Файлы фона пакета не меняются; результат лежит
в `templates/<pack>/checks/<имя-исходника>/`: layout, красный trim и cut без trim.

```bash
venv/bin/python templates/generate_template_checks.py birthday \
  --grid templates/birthday/draft.png \
  --strip templates/birthday/strip11.png \
  --photos marketing/samples/dimaolya/source
```

```bash
venv/bin/python templates/generate_template_checks.py birthday \
  --photos marketing/samples/dimaolya/source
```

Можно оставить только `--grid` или только `--strip`. Чтобы проверить несколько
фонов, перечисли их после нужного ключа.
Без `--photos` будут серые слоты.








## Сборка фона для grid и single

`generate_grid_background.py` масштабирует выбранную картинку ровно до
`3688x2480` и сохраняет её как `grid_bg.png` рядом с исходником.

```bash
venv/bin/python templates/generate_grid_background.py templates/birthday/draft.png
```

## Сборка фона для двух полосок

`generate_strip_background.py` масштабирует вертикальный исходник до
`1240x3688`, ставит справа его зеркальную копию и поворачивает получившийся
лист на 90 градусов против часовой стрелки. Результат `3688x2480` сохраняется
как `strip_bg.png` рядом с исходником.

```bash
venv/bin/python templates/generate_strip_background.py templates/birthday/draft.png
```








# Template inspection helpers


## Ручные проверки шаблонов

`generate_template_checks.py` — только ручной диагностический скрипт. Приложение
его не вызывает. Экран выбора отдельно собирает реальные JPEG-превью с фотографиями
в `photos/<session>/previews`; уменьшенные статичные слои кешируются рядом с
фонами как `*_preview.jpg` и `*_preview.png`.

Ручной генератор сначала создаёт layout checks с серыми фотослотами, затем прямо
поверх них добавляет красные полупрозрачные зоны `print_trim`. Поэтому в trim
checks тоже остаются плейсхолдеры фотографий, настроенные `foreground` и `texts`.
Все результаты лежат отдельно в `<pack>/checks/`, исходные background-файлы не
изменяются.

Запуск для одного или нескольких pack:

```bash
venv/bin/python templates/generate_template_checks.py birthday
venv/bin/python templates/generate_template_checks.py birthday park_universal
```

Без названий обрабатываются все pack:

```bash
venv/bin/python templates/generate_template_checks.py
```


Имена файлов сгруппированы по шаблону:

- `layout_<template>_full.png` — полный лист с серыми фотослотами;
- `layout_strips_1.png` и `layout_strips_2.png` — обе физические полоски;
- `trim_<template>_full.png` — полный лист с плейсхолдерами и красным trim;
- `trim_strips_1.png` и `trim_strips_2.png` — обе полоски с правильной внешней
  стороной trim.

Шаблон, в котором посетитель должен выбрать один из снятых кадров, помечается
`"photo_choice": true` и обязан иметь единственный слот с `photo_index: 0`.
Во время сессии backend подставляет в этот слот выбранный оригинал и готовит
рамочное превью для каждого кадра. Безрамочные превью и печать используют
центральный `cover` на полный `print_size`, без background/foreground шаблона.

## Текстовый слой: дата и подписи

`print_layout.texts` описывает текст, который рисуется последним:
`background → фотографии → foreground → texts`. Ничего не запекается в
статичные слои, поэтому их уменьшенные кеши `*_preview.jpg` и `*_preview.png`
остаются нетронутыми, а дату не нужно перерисовывать вручную под каждый ивент.

Печать и экранное превью используют один и тот же объект: координаты и кегль
умножаются на тот же коэффициент, что и фотослоты. Второго набора размеров нет.
Текст не кешируется и рисуется при каждой композиции.

```json
"print_layout": {
    "background": "grid_bg.png",
    "photos": [ ... ],
    "texts": [
        {
            "text": "{dd} {month_ru} {yyyy}\nпарк Горького",
            "position": {"x": 3000, "y": 2295},
            "align": "center",
            "angle": 0,
            "skew": {"x": 0, "y": 0},
            "flip": {"x": false, "y": false},
            "font": "Comfortaa-VariableFont_wght.ttf",
            "size": 96,
            "weight": 600,
            "color": "#ffffff",
            "stroke_width": 8,
            "stroke_color": "#8c3b2e",
            "line_spacing": 1.15,
            "char_spacing": 0,
            "underline": false,
            "linethrough": false
        }
    ],
    "_texts_date_tokens": ["{dd}.{mm}.{yyyy}", "{dd} {month_ru} {yyyy}"]
}
```

Все свойства относятся ко всему объекту, включая строки после явного `\n`.
Посимвольных и построчных стилей нет: если частям подписи нужны разные кегли,
цвета или шрифты, это отдельные элементы `texts`. `font` — точное имя файла
шрифта, поэтому italic-face также хранится отдельным файлом. `char_spacing`
задаётся в тысячных долях em, как в Fabric.js. `stroke_width` — абсолютная
толщина внешней обводки в пикселях полного растра; `stroke_color` поддерживает
`#rrggbb` и `#rrggbbaa`.

`position` — якорь в координатах полного `print_size`: при `align: left` это
левый край текста, при `center` — центр, при `right` — правый край. По вертикали
якорь всегда находится в центре объекта. Ширины, высоты, автоматического
переноса и `scale` нет; новую строку создаёт только `\n`. `angle` задаётся в
градусах по часовой стрелке, `skew.x/y` — наклоны в градусах, `flip.x/y` —
зеркальное отражение вокруг якоря.

Поддерживаются ровно два токена даты: `{dd}.{mm}.{yyyy}` даёт `08.08.2026`, а
`{dd} {month_ru} {yyyy}` — `8 августа 2026`. Русские месяцы стоят в родительном
падеже и заданы в коде: embedded Python работает в локали `C`, где `strftime`
вернул бы `August`. Дата берётся из времени начала сессии, поэтому съёмка в 23:59
не печатает завтрашнее число, а превью и отпечаток всегда совпадают.

Шрифт сначала ищется рядом с `config.json` текущего шаблона, затем — по имени
файла в общем каталоге `assets/fonts`; путь с `..` отклоняется.
Подпись стоит держать внутри `print_trim.visible_size` — у borderless-печати
реально срезается до `55 px` с краёв. У strips текст обычно получает
`"angle": -90`, чтобы повернуться вместе с полоской. Вторая физическая
половина листа требует отдельной записи в `texts`, точно так же, как дублируются
восемь фотослотов.

Текст — это оформление, а не то, за что заплатил гость. Ненайденный шрифт,
неразобранный цвет или незнакомый токен пишутся в `photobooth.log` как `ERROR`,
и этот блок просто не рисуется: лист всё равно печатается, без подписи.
Ошибкой конфигурации считается только структурная опечатка в паке —
например, `texts` не список или `position` за пределами листа.

`generate_template_checks.py` рисует этот же текстовый слой в обоих видах
ручных проверок, поэтому layout check показывает его положение, а trim check —
попадает ли подпись под физический обрез.

Дополнительные библиотеки устанавливать не нужно: скрипт использует только
стандартную библиотеку Python и Pillow, уже зафиксированный в
`requirements.txt`.
