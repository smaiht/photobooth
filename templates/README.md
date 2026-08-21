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

Печать и экранное превью используют один и тот же блок: координаты и кегль
умножаются на тот же коэффициент, что и фотослоты. Второго набора размеров нет.
Текст не кешируется и рисуется при каждой композиции.

```json
"print_layout": {
    "background": "grid_bg.png",
    "photos": [ ... ],
    "texts": [
        {
            "position": {"x": 3000, "y": 2295},
            "rotate": "none",
            "_rotate_options": ["none", "cw", "ccw"],
            "font": "Comfortaa-VariableFont_wght.ttf",
            "weight": 600,
            "_weight_comment": "Ось wght переменного шрифта, 300..700 у Comfortaa. Для статичного TTF игнорируется.",
            "color": "#ffffff",
            "stroke_width": 8,
            "stroke_color": "#8c3b2e",
            "line_spacing": 1.15,
            "lines": [
                {"text": "{dd} {month_ru} {yyyy}", "size": 96, "weight": 700},
                {
                    "text": "парк Горького",
                    "size": 54,
                    "color": "#ffe9c8",
                    "stroke_width": 4,
                    "stroke_color": "#00000080"
                }
            ]
        }
    ],
    "_texts_date_tokens": ["{dd}.{mm}.{yyyy}", "{dd} {month_ru} {yyyy}"]
}
```

`font`, `weight`, `size`, `color`, `stroke_width`, `stroke_color` и
`line_spacing` на уровне блока — значения по умолчанию; строка переопределяет
только то, что ей нужно. Так путь к шрифту не дублируется в каждой строке и не
может разъехаться. `stroke_width` задаёт толщину обводки в пикселях полного
печатного растра и по умолчанию равен `0`. `stroke_color` поддерживает
`#rrggbb` и `#rrggbbaa`; если его не указать, используется цвет самого текста.

`position` — одна точка в координатах полного `print_size`. В ней автоматически
центрируется весь многострочный блок. Ширины и высоты у блока нет: текст и
обводка свободно рисуются вокруг точки и ограничиваются только краями самого
печатного листа. `rotate` поворачивает весь блок вокруг этой же точки.

Поддерживаются ровно два токена даты: `{dd}.{mm}.{yyyy}` даёт `08.08.2026`, а
`{dd} {month_ru} {yyyy}` — `8 августа 2026`. Русские месяцы стоят в родительном
падеже и заданы в коде: embedded Python работает в локали `C`, где `strftime`
вернул бы `August`. Дата берётся из времени начала сессии, поэтому съёмка в 23:59
не печатает завтрашнее число, а превью и отпечаток всегда совпадают.

Шрифты берутся по имени файла из `assets/fonts`; путь с `..` отклоняется.
Подпись стоит держать внутри `print_trim.visible_size` — у borderless-печати
реально срезается до `55 px` с краёв. `rotate` нужен там, где повёрнуты кадры: у
strips подпись с `"ccw"` поворачивается вместе с полоской. Вторая физическая
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
