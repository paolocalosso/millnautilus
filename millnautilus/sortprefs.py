"""Persistenza dell'ordinamento per directory."""
import json
import os

from gi.repository import GLib

PREFS_FILE = os.path.join(GLib.get_user_config_dir(),
                          "millnautilus", "sorting.json")

_prefs: dict | None = None


def _load() -> dict:
    global _prefs
    if _prefs is None:
        try:
            with open(PREFS_FILE, encoding="utf-8") as fh:
                _prefs = json.load(fh)
        except (OSError, ValueError):
            _prefs = {}
    return _prefs


def get_sort(uri: str) -> tuple[str, bool]:
    """(criterio, decrescente) salvati per `uri`, default ("name", False)."""
    entry = _load().get(uri)
    if isinstance(entry, list) and len(entry) == 2:
        return str(entry[0]), bool(entry[1])
    return "name", False


def set_sort(uri: str, by: str, descending: bool):
    prefs = _load()
    if by == "name" and not descending:
        prefs.pop(uri, None)  # default: non serve salvarlo
    else:
        prefs[uri] = [by, descending]
    try:
        os.makedirs(os.path.dirname(PREFS_FILE), exist_ok=True)
        with open(PREFS_FILE, "w", encoding="utf-8") as fh:
            json.dump(prefs, fh)
    except OSError:
        pass
