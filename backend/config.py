from pathlib import Path
import json
import math
import re

ROOT_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = ROOT_DIR / "frontend"
TEMPLATES_DIR = ROOT_DIR / "templates"
EDSDK_DLL = ROOT_DIR / "EDSDK_Win" / "EDSDK_64" / "Dll" / "EDSDK.dll"

PHOTOS_DIR = ROOT_DIR / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)

PRINT_JOBS_DIR = ROOT_DIR / "photos_print_jobs"
PRINT_JOBS_DIR.mkdir(exist_ok=True)

CAMERA_CONFIG_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_TRUE_VALUES = {"1", "true", "yes", "on", "да", "вкл"}
_FALSE_VALUES = {"0", "false", "no", "off", "нет", "выкл"}


def load_event_config() -> dict:
    config_path = ROOT_DIR / "config_app.json"
    # This file is always written as UTF-8. An implicit Windows-locale decoder
    # corrupts Cyrillic event names after a restart.
    return json.loads(config_path.read_text(encoding="utf-8"))


def _coerce_camera_scalar(raw_value: str, prototype):
    value = raw_value.strip()
    if isinstance(prototype, bool):
        normalized = value.casefold()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        raise ValueError(
            "ожидается boolean: true/false, yes/no, on/off или 1/0")
    if type(prototype) is int:
        if not re.fullmatch(r"[+-]?\d+", value):
            raise ValueError("ожидается целое число")
        return int(value, 10)
    if type(prototype) is float:
        try:
            result = float(value)
        except ValueError as exc:
            raise ValueError("ожидается число") from exc
        if not math.isfinite(result):
            raise ValueError("число должно быть конечным")
        return result
    if isinstance(prototype, str):
        if not value:
            raise ValueError("строковое значение не может быть пустым")
        return value
    raise ValueError(
        f"тип поля {type(prototype).__name__} нельзя менять через Telegram")


def _coerce_camera_value(field: str, raw_value: str, config: dict):
    current = config[field]
    options = config.get(f"_{field}_options")
    if isinstance(options, list) and options:
        for option in options:
            try:
                candidate = _coerce_camera_scalar(raw_value, option)
            except ValueError:
                continue
            if isinstance(option, str):
                if candidate.casefold() == option.casefold():
                    return option
            elif type(candidate) is type(option) and candidate == option:
                return option
        available = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
        raise ValueError(f"недопустимое значение; доступно: {available}")
    return _coerce_camera_scalar(raw_value, current)


def update_camera_config_field(
    field: str,
    raw_value: str,
    config_path: Path | None = None,
) -> tuple[str, object, object, bool]:
    """Type-check and atomically update one public camera config field."""
    normalized_field = str(field or "").strip().lower()
    if normalized_field.startswith("_"):
        raise ValueError("служебные поля камеры нельзя изменять")
    if not CAMERA_CONFIG_FIELD_RE.fullmatch(normalized_field):
        raise ValueError("некорректное имя параметра камеры")
    if not isinstance(raw_value, str):
        raise ValueError("значение параметра должно быть строкой")

    path = Path(config_path) if config_path is not None else ROOT_DIR / "config_camera.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("config_camera.json должен содержать JSON-объект")
    if normalized_field not in config:
        raise ValueError(f"неизвестный параметр камеры: {normalized_field}")

    old_value = config[normalized_field]
    new_value = _coerce_camera_value(normalized_field, raw_value, config)
    if type(old_value) is type(new_value) and old_value == new_value:
        return normalized_field, old_value, new_value, False

    config[normalized_field] = new_value
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return normalized_field, old_value, new_value, True
