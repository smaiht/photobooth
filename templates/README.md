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
