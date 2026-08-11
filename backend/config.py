from pathlib import Path
import json
import math
import re

from .camera.constants import (
    CAMERA_NUMERIC_RANGES,
    CAMERA_VALUE_MAPS,
    CAMERA_VALUE_RESOLVERS,
    numeric_range_error,
)

ROOT_DIR = Path(__file__).resolve().parent.parent

ASSETS_DIR = ROOT_DIR / "assets"
FRONTEND_DIR = ROOT_DIR / "frontend"
TEMPLATES_DIR = ROOT_DIR / "templates"
EDSDK_DLL = ROOT_DIR / "EDSDK_Win" / "EDSDK_64" / "Dll" / "EDSDK.dll"

PHOTOS_DIR = ROOT_DIR / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)

PRINT_JOBS_DIR = ROOT_DIR / "photos_print_jobs"
PRINT_JOBS_DIR.mkdir(exist_ok=True)

CAMERA_CONFIG_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
CAMERA_PRESET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# Presets live under a service key, so "/presets ..." can never overwrite them
# and they stay out of the public-field validation.
PRESETS_FIELD = "_presets"
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


def _available_text(values) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _coerce_camera_value(field: str, raw_value: str, config: dict):
    current = config[field]
    resolver = CAMERA_VALUE_RESOLVERS.get(field)
    if resolver is not None:
        # Av/Tv/ISO are validated against the EDSDK maps, not against a plain
        # JSON list, so Telegram can never store a value the camera code would
        # silently skip. "/iso 100" arrives as a string and becomes int 100;
        # "/iso auto" stays the string "auto".
        resolved = resolver(raw_value.strip())
        if resolved is None:
            raise ValueError(
                "недопустимое значение; доступно: "
                f"{_available_text(CAMERA_VALUE_MAPS[field])}")
        return resolved[0]
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
        raise ValueError(
            f"недопустимое значение; доступно: {_available_text(options)}")
    value = _coerce_camera_scalar(raw_value, current)
    # A number that merely parses is not automatically usable: focus_delay is
    # awaited by the camera worker and min_free_disk_gib gates every session.
    range_error = numeric_range_error(field, value)
    if range_error is not None:
        raise ValueError(range_error)
    return value


def _write_camera_config(path: Path, config: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_camera_config(config_path: Path | None) -> tuple[Path, dict]:
    path = (
        Path(config_path)
        if config_path is not None
        else ROOT_DIR / "config_camera.json"
    )
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("config_camera.json должен содержать JSON-объект")
    return path, config


def _normalized_camera_field(field: str) -> str:
    normalized = str(field or "").strip().lower()
    if normalized.startswith("_"):
        raise ValueError("служебные поля камеры нельзя изменять")
    if not CAMERA_CONFIG_FIELD_RE.fullmatch(normalized):
        raise ValueError("некорректное имя параметра камеры")
    return normalized


def _raw_camera_text(raw_value) -> str:
    """Accept the shapes a messenger or a JSON preset can deliver."""
    # Telegram always delivers a string, but a VPS build or a preset may hold a
    # JSON number. Accept both instead of rejecting "/iso 200" on a type detail.
    if isinstance(raw_value, bool):
        return "true" if raw_value else "false"
    if isinstance(raw_value, int):
        return str(raw_value)
    if isinstance(raw_value, float):
        return repr(raw_value)
    if not isinstance(raw_value, str):
        raise ValueError("значение параметра должно быть строкой")
    return raw_value


def update_camera_config_field(
    field: str,
    raw_value: str,
    config_path: Path | None = None,
) -> tuple[str, object, object, bool]:
    """Type-check and atomically update one public camera config field."""
    normalized_field = _normalized_camera_field(field)
    raw_value = _raw_camera_text(raw_value)
    path, config = _load_camera_config(config_path)
    if normalized_field not in config:
        raise ValueError(f"неизвестный параметр камеры: {normalized_field}")

    old_value = config[normalized_field]
    new_value = _coerce_camera_value(normalized_field, raw_value, config)
    if type(old_value) is type(new_value) and old_value == new_value:
        return normalized_field, old_value, new_value, False

    config[normalized_field] = new_value
    _write_camera_config(path, config)
    return normalized_field, old_value, new_value, True


def camera_presets(config: dict) -> dict:
    """Named lighting presets stored as data in config_camera.json."""
    presets = config.get(PRESETS_FIELD)
    if presets is None:
        return {}
    if not isinstance(presets, dict):
        raise ValueError(f"{PRESETS_FIELD} должен быть JSON-объектом")
    return presets


def _preset_names(config: dict) -> list[str]:
    names = []
    for name in camera_presets(config):
        if isinstance(name, str) and name.startswith("_"):
            continue
        if not isinstance(name, str) or not CAMERA_PRESET_NAME_RE.fullmatch(name):
            raise ValueError(f"некорректное имя пресета: {name!r}")
        names.append(name)
    return names


def preset_names(config_path: Path | None = None) -> list[str]:
    _, config = _load_camera_config(config_path)
    return _preset_names(config)


def apply_camera_preset(
    name: str,
    config_path: Path | None = None,
) -> tuple[str, dict[str, tuple[object, object]], str]:
    """Validate a whole preset, then write every field in one atomic update.

    A preset is all-or-nothing on purpose: applying half of it would leave the
    booth in a combination the operator never chose, and a wrong exposure is
    only visible after the event.
    """
    requested = str(name or "").strip().lower()
    if not CAMERA_PRESET_NAME_RE.fullmatch(requested):
        raise ValueError("некорректное имя пресета")
    path, config = _load_camera_config(config_path)
    presets = camera_presets(config)
    available = _preset_names(config)
    if not available:
        raise ValueError("в config_camera.json нет пресетов")
    if requested not in available:
        raise ValueError(
            f"неизвестный пресет; доступно: {', '.join(sorted(available))}")

    preset = presets[requested]
    if not isinstance(preset, dict):
        raise ValueError(f"пресет {requested} должен быть JSON-объектом")
    label = preset.get("_label", requested)
    hint = preset.get("_hint", "")
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"пресет {requested}: _label должен быть строкой")
    if not isinstance(hint, str):
        raise ValueError(f"пресет {requested}: _hint должен быть строкой")
    label = label.strip()
    hint = hint.strip()

    fields = {
        field: value for field, value in preset.items()
        if not str(field).startswith("_")
    }
    if not fields:
        raise ValueError(f"пресет {requested} не содержит параметров")

    changes: dict[str, tuple[object, object]] = {}
    for field, value in fields.items():
        normalized_field = _normalized_camera_field(field)
        if normalized_field not in config:
            raise ValueError(
                f"пресет {requested}: неизвестный параметр камеры "
                f"{normalized_field}")
        new_value = _coerce_camera_value(
            normalized_field,
            _raw_camera_text(value),
            config,
        )
        old_value = config[normalized_field]
        if type(old_value) is not type(new_value) or old_value != new_value:
            changes[normalized_field] = (old_value, new_value)

    if not changes:
        return label, {}, hint

    for field, (_old, new_value) in changes.items():
        config[field] = new_value
    _write_camera_config(path, config)
    return label, changes, hint
