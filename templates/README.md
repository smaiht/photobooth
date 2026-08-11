# Template inspection helpers

## Photo-slot layout preview

`generate_layout_previews.py` создаёт полноразмерную PNG-копию каждого фона и
закрывает все фотослоты однотонными серыми прямоугольниками без рамок. Размеры
и координаты берутся непосредственно из `photo_size_px` и
`print_layout.photos`, поэтому картинка показывает области, которые займут
реальные фотографии. Если в `print_layout.foreground` настроен прозрачный
верхний слой, он накладывается поверх серых слотов — в том же порядке, что и при
настоящей печати.

Запуск для одного template pack:

```bash
python3 templates/generate_layout_previews.py park08082026
```

На Windows с embedded Python:

```bat
python\python.exe templates\generate_layout_previews.py kvas01aug26
```

Без имени pack скрипт обрабатывает все конфигурации:

```bash
python3 templates/generate_layout_previews.py
```

Для шаблонов `grid`, `single` и `strips` рядом с исходными фонами
появятся `grid_layout_preview.png`, `single_layout_preview.png` и
`strips_layout_preview.png`. Исходные background-
файлы не изменяются. Эти PNG предназначены только для ручной проверки и не
используются приложением. Они не связаны с runtime-кешами слоёв
`*_preview.jpg` и `*_preview.png`, которые приложение создаёт автоматически для
экранного выбора шаблона с реальными фотографиями.

Для каждого шаблона с `preview_split: "horizontal"` дополнительно создаётся
`<template>_single_strip_layout_preview.png`: генератор берёт первую
горизонтальную половину полного layout preview и поворачивает её по
`preview_rotation`. Например, `strips_single_strip_layout_preview.png` имеет
ориентацию одной готовой вертикальной полоски.

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
            "box": {"x": 2500, "y": 2180, "width": 1000, "height": 230},
            "align": "right",
            "_align_options": ["left", "center", "right"],
            "valign": "middle",
            "_valign_options": ["top", "middle", "bottom"],
            "rotate": "none",
            "_rotate_options": ["none", "cw", "ccw"],
            "font": "Comfortaa-VariableFont_wght.ttf",
            "weight": 600,
            "_weight_comment": "Ось wght переменного шрифта, 300..700 у Comfortaa. Для статичного TTF игнорируется.",
            "color": "#ffffff",
            "line_spacing": 1.15,
            "lines": [
                {"text": "{dd} {month_ru} {yyyy}", "size": 96, "weight": 700},
                {"text": "парк Горького", "size": 54, "color": "#ffe9c8"}
            ]
        }
    ],
    "_texts_date_tokens": ["{dd}.{mm}.{yyyy}", "{dd} {month_ru} {yyyy}"]
}
```

`font`, `weight`, `size`, `color` и `line_spacing` на уровне блока — значения по
умолчанию; строка переопределяет только то, что ей нужно. Так путь к шрифту не
дублируется в каждой строке и не может разъехаться.

Поддерживаются ровно два токена даты: `{dd}.{mm}.{yyyy}` даёт `08.08.2026`, а
`{dd} {month_ru} {yyyy}` — `8 августа 2026`. Русские месяцы стоят в родительном
падеже и заданы в коде: embedded Python работает в локали `C`, где `strftime`
вернул бы `August`. Дата берётся из времени начала сессии, поэтому съёмка в 23:59
не печатает завтрашнее число, а превью и отпечаток всегда совпадают.

Шрифты берутся по имени файла из `assets/fonts`; путь с `..` отклоняется.
`box` задаётся в координатах полного `print_size`. Подпись стоит держать внутри
`print_trim.visible_size` — у borderless-печати реально срезается до `55 px` с
краёв. `rotate` нужен там, где повёрнуты кадры: у strips подпись с `"ccw"`
поворачивается вместе с полоской. Вторая физическая половина листа требует
отдельной записи в `texts`, точно так же, как дублируются восемь фотослотов.

Текст — это оформление, а не то, за что заплатил гость. Ненайденный шрифт,
неразобранный цвет или незнакомый токен пишутся в `photobooth.log` как `ERROR`,
и этот блок просто не рисуется: лист всё равно печатается, без подписи.
Ошибкой конфигурации считается только структурная опечатка в паке —
например, `texts` не список или `box` за пределами листа.

Оба скрипта проверки, `generate_layout_previews.py` и
`generate_trim_overlays.py`, тоже рисуют этот слой, поэтому служебные PNG
показывают подпись там же, где её увидит гость. В trim overlay видно, попадает
ли она под физический обрез. Если у двух шаблонов один фон, но разные подписи,
overlay сохраняется как `<фон>_<шаблон>_trim.png`, чтобы файлы не
перезаписывали друг друга.

## Print trim overlay

`generate_trim_overlays.py` проходит по всем template packs с файлом
`config.json` внутри этой папки. Для каждого background из `print_layout` он
сначала накладывает настроенный `foreground`, если он есть, а затем создаёт
PNG-копию с красной полупрозрачной зоной `print_trim`.
Перед генерацией скрипт также проверяет, что `print_trim.visible_size` точно
равен `print_size` за вычетом четырёх trim-значений.

Запуск из корня проекта:

```bash
python3 templates/generate_trim_overlays.py
```

На Windows с embedded Python:

```bat
python\python.exe templates\generate_trim_overlays.py
```

Например, рядом с `grid_bg.png` и `strip_bg.png` появятся
`grid_bg_trim.png` и `strip_bg_trim.png`. Исходные background-файлы не
изменяются. Overlay-копии служат только для визуальной проверки и никогда не
используются компоновщиком или принтером.

Дополнительные библиотеки устанавливать не нужно: скрипт использует только
стандартную библиотеку Python и Pillow, уже зафиксированный в
`requirements.txt`.
