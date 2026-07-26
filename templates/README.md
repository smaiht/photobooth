# Template inspection helpers

`generate_trim_overlays.py` проходит по всем template packs с файлом
`config.json` внутри этой папки. Для каждого background из `print_layout` он
создаёт отдельную PNG-копию с красной полупрозрачной зоной `print_trim`.
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
