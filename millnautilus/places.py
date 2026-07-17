"""Ordine personalizzato delle voci nella sezione "Posizioni"."""
import json
import os

from gi.repository import GLib

ORDER_FILE = os.path.join(GLib.get_user_config_dir(),
                          "millnautilus", "places_order.json")


def load_order() -> list[str]:
    try:
        with open(ORDER_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [str(u) for u in data] if isinstance(data, list) else []


def save_order(uris: list[str]):
    try:
        os.makedirs(os.path.dirname(ORDER_FILE), exist_ok=True)
        with open(ORDER_FILE, "w", encoding="utf-8") as fh:
            json.dump(uris, fh)
    except OSError:
        pass


def apply_order(uris: list[str]) -> list[str]:
    """Riordina `uris` secondo l'ordine salvato; le voci non presenti
    nell'ordine salvato restano in coda nell'ordine di partenza."""
    saved = load_order()
    rank = {u: i for i, u in enumerate(saved)}
    return sorted(uris, key=lambda u: rank.get(u, len(saved) + uris.index(u)))


def reorder(current: list[str], dragged: str, target: str, after: bool):
    """Sposta `dragged` prima/dopo `target` nella lista `current` e salva."""
    order = [u for u in current if u != dragged]
    if target not in order:
        order.append(dragged)
    else:
        idx = order.index(target)
        order.insert(idx + 1 if after else idx, dragged)
    save_order(order)
