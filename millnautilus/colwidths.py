"""Persistenza della larghezza delle colonne per percorso."""
import json
import os

from gi.repository import GLib

WIDTHS_FILE = os.path.join(GLib.get_user_config_dir(),
                           "millnautilus", "column_widths.json")

_widths: dict | None = None


def _load() -> dict:
    global _widths
    if _widths is None:
        try:
            with open(WIDTHS_FILE, encoding="utf-8") as fh:
                _widths = json.load(fh)
        except (OSError, ValueError):
            _widths = {}
    return _widths


def get_width(uri: str) -> int | None:
    value = _load().get(uri)
    return int(value) if isinstance(value, (int, float)) else None


def set_width(uri: str, width: int):
    widths = _load()
    widths[uri] = int(width)
    try:
        os.makedirs(os.path.dirname(WIDTHS_FILE), exist_ok=True)
        with open(WIDTHS_FILE, "w", encoding="utf-8") as fh:
            json.dump(widths, fh)
    except OSError:
        pass
