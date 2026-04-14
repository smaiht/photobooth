from pathlib import Path
import json

ROOT_DIR = Path(__file__).resolve().parent.parent

FRONTEND_DIR = ROOT_DIR / "frontend"
TEMPLATES_DIR = ROOT_DIR / "templates"
EDSDK_DLL = ROOT_DIR / "EDSDK_Win" / "EDSDK_64" / "Dll" / "EDSDK.dll"

PHOTOS_DIR = ROOT_DIR / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)


def load_event_config() -> dict:
    config_path = ROOT_DIR / "config_app.json"
    return json.loads(config_path.read_text())
