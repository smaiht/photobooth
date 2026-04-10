from pathlib import Path
import json
import sys

# PyInstaller extracts bundled files to sys._MEIPASS
# When running from source, use the project root
if getattr(sys, 'frozen', False):
    BUNDLE_DIR = Path(sys._MEIPASS)
    RUN_DIR = Path(sys.executable).parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent.parent
    RUN_DIR = BUNDLE_DIR

# Bundled assets (read-only, inside exe)
FRONTEND_DIR = BUNDLE_DIR / "frontend"
TEMPLATES_DIR = BUNDLE_DIR / "templates"
EDSDK_DLL = BUNDLE_DIR / "EDSDK_Win" / "EDSDK_64" / "Dll" / "EDSDK.dll"

# Runtime data (writable, next to exe)
PHOTOS_DIR = RUN_DIR / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)

# Session settings
DEFAULT_CONFIG = {
    "countdown_seconds": 5,
    "freeze_seconds": 1,
    "num_photos": 4,
    "template_select_timeout": 5,
    "default_template": "strip",
    "mirror_live_view": True,
    "print_enabled": False,
    "printer_name": "",
    "hot_folder": "",
    "tg_enabled": False,
    "tg_bot_token": "",
    "tg_chat_id": "",
}


def load_event_config(event_dir: Path | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    # Check for config next to exe first, then in bundled templates
    for config_path in [
        RUN_DIR / "config.json",
        TEMPLATES_DIR / "default" / "config.json",
    ]:
        if config_path.exists():
            cfg.update(json.loads(config_path.read_text()))
            break
    if event_dir and (event_dir / "config.json").exists():
        cfg.update(json.loads((event_dir / "config.json").read_text()))
    return cfg
