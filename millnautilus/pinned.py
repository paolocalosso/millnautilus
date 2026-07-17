"""Persistenza delle cartelle fissate nella sezione "Posizioni"."""
import json
import os

from gi.repository import GLib

PINNED_FILE = os.path.join(GLib.get_user_config_dir(),
                           "millnautilus", "pinned.json")


def load() -> list[tuple[str, str]]:
    """Lista di (uri, etichetta) delle posizioni fissate."""
    try:
        with open(PINNED_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    result = []
    for entry in data:
        if isinstance(entry, list) and len(entry) == 2:
            result.append((str(entry[0]), str(entry[1])))
    return result


def _save(entries: list[tuple[str, str]]):
    try:
        os.makedirs(os.path.dirname(PINNED_FILE), exist_ok=True)
        with open(PINNED_FILE, "w", encoding="utf-8") as fh:
            json.dump([list(e) for e in entries], fh)
    except OSError:
        pass


def is_pinned(uri: str) -> bool:
    return any(u == uri for u, _ in load())


def add(uri: str, label: str):
    entries = load()
    if any(u == uri for u, _ in entries):
        return
    entries.append((uri, label))
    _save(entries)


def remove(uri: str):
    _save([(u, l) for u, l in load() if u != uri])
