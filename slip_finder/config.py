"""Настройки приложения: %LOCALAPPDATA%\\slip-finder\\settings.json."""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "slip-finder"
SETTINGS_FILE = APP_DIR / "settings.json"
DEFAULTS = {"logs_dir": r"C:\Arcus2\logs", "port": 8765}


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        log.exception("Не удалось прочитать %s, беру значения по умолчанию", SETTINGS_FILE)
    return data


def save(data: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
