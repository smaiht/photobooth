from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent
PHOTOS_DIR = BASE_DIR / "photos"
TEMPLATES_DIR = BASE_DIR / "templates"
FRONTEND_DIR = BASE_DIR / "frontend"
EDSDK_DLL = BASE_DIR / "EDSDK_Win" / "EDSDK_64" / "Dll" / "EDSDK.dll"

PHOTOS_DIR.mkdir(exist_ok=True)

# Session settings — override per event via admin panel
DEFAULT_CONFIG = {
    "countdown_seconds": 5,
    "freeze_seconds": 1,
    "num_photos": 4,
    "template_select_timeout": 5,
    "default_template": "strip",
    "mirror_live_view": True,
    "print_enabled": True,
    "upload_enabled": False,
    "upload_endpoint": "",
    "printer_name": "",
}


def load_event_config(event_dir: Path | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if event_dir and (event_dir / "config.json").exists():
        cfg.update(json.loads((event_dir / "config.json").read_text()))
    return cfg
