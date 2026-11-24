"""Etichette colore su file e cartelle.

Le etichette stanno in un file JSON accanto a places.json, così si
sincronizzano allo stesso modo tra più macchine: se MILLNAUTILUS_PLACES punta
a una cartella sincronizzata (Koofr, pCloud, …) anche tags.json finisce lì.
In alternativa si può indicare un file a parte con MILLNAUTILUS_TAGS.

I percorsi sono salvati in forma portabile (vedi placestore.encode): un file
in "xdg:DOCUMENTS/progetto" viene ritrovato anche su una macchina dove la
cartella si chiama "Documents".

Millnautilus aggiorna il file quando rinomina, sposta, cestina o elimina un
elemento; le operazioni fatte con altri programmi non vengono viste, e
l'etichetta resta sul vecchio percorso.
"""
import json
import os
import threading
from functools import lru_cache

from gi.repository import Gio, GLib, GObject

from . import placestore

# (id, etichetta, (colore su tema chiaro, colore su tema scuro)): l'id è
# quello salvato nel file. Tavolozza gruvbox: le tinte "neutral" sul chiaro,
# le "bright" sullo scuro, come fa gruvbox stesso nelle due varianti.
TAGS = (
    ("red", "Rosso", ("#cc241d", "#fb4934")),
    ("yellow", "Giallo", ("#d79921", "#fabd2f")),
    ("green", "Verde", ("#98971a", "#b8bb26")),
    ("blue", "Blu", ("#458588", "#83a598")),
)

TAG_IDS = frozenset(tag_id for tag_id, _label, _color in TAGS)

# posizione "virtuale" della vista che elenca i file con un'etichetta
TAG_SCHEME = "millnautilus-tag"

# attributo GVfs usato dalla prima versione delle etichette: viene letto solo
# per importare nel file JSON quel che era già stato etichettato
LEGACY_ATTRIBUTE = "metadata::millnautilus-tag"


def _tags_file() -> str:
    override = os.environ.get("MILLNAUTILUS_TAGS")
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.dirname(placestore.PLACES_FILE), "tags.json")


TAGS_FILE = _tags_file()


# ---------------------------------------------------------------- notifiche
class _Notifier(GObject.Object):
    """Emette "changed" quando le etichette cambiano (anche dall'esterno)."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}


notifier = _Notifier()


def _notify():
    # le scritture possono arrivare dai thread delle operazioni su file
    GLib.idle_add(lambda: notifier.emit("changed") and False)


# ---------------------------------------------------------------- archivio
_lock = threading.RLock()
_data: dict[str, str] = {}
_stamp: tuple | None = None  # (mtime, size) del file all'ultima lettura
_monitor: Gio.FileMonitor | None = None


def _file_stamp() -> tuple | None:
    try:
        st = os.stat(TAGS_FILE)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _load() -> dict[str, str]:
    """Contenuto aggiornato del file (riletto solo se è cambiato)."""
    global _data, _stamp
    stamp = _file_stamp()
    if stamp == _stamp:
        return _data
    data = {}
    try:
        with open(TAGS_FILE, encoding="utf-8") as fh:
            raw = json.load(fh)
        entries = raw.get("tags", {}) if isinstance(raw, dict) else {}
        data = {token: tag for token, tag in entries.items()
                if isinstance(token, str) and tag in TAG_IDS}
    except (OSError, ValueError):
        # file assente, oppure a metà scrittura da parte del programma di
        # sincronizzazione: si tiene quel che si aveva
        if stamp is not None and _data:
            return _data
    _data, _stamp = data, stamp
    return _data


def _save(data: dict[str, str]):
    """Scrittura atomica: chi sincronizza non vede mai un file a metà."""
    global _data, _stamp
    os.makedirs(os.path.dirname(TAGS_FILE), exist_ok=True)
    tmp = f"{TAGS_FILE}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "tags": dict(sorted(data.items()))}, fh,
                  indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, TAGS_FILE)
    _data, _stamp = data, _file_stamp()


@lru_cache(maxsize=8192)
def _token(uri: str) -> str:
    return placestore.encode(uri)


def _modify(change) -> bool:
    """Rilegge il file, applica `change(data)` e salva se qualcosa cambia.

    Rileggere subito prima di scrivere evita di cancellare le etichette
    arrivate nel frattempo da un'altra macchina.
    """
    with _lock:
        data = dict(_load())
        if not change(data):
            return False
        _save(data)
    _notify()
    return True


# ---------------------------------------------------------------- API
def get(uri: str) -> str | None:
    with _lock:
        return _load().get(_token(uri))


def getter():
    """Funzione uri → etichetta su un'unica lettura del file: per ordinare
    molti elementi senza ricontrollare il file a ogni confronto."""
    with _lock:
        data = _load()
    return lambda uri: data.get(_token(uri))


# posizione di ogni colore nell'ordinamento per etichetta
ORDER = {tag_id: index for index, (tag_id, _l, _c) in enumerate(TAGS)}


def set_tag(uris: list[str], tag: str | None):
    """Assegna `tag` (None = toglie) agli URI. Solleva OSError."""
    if tag is not None and tag not in TAG_IDS:
        raise ValueError(f"etichetta sconosciuta: {tag}")

    def change(data):
        changed = False
        for uri in uris:
            token = _token(uri)
            if tag is None:
                changed |= data.pop(token, None) is not None
            elif data.get(token) != tag:
                data[token] = tag
                changed = True
        return changed

    _modify(change)


def uris_with(tag: str) -> list[str]:
    """URI (validi su questa macchina) degli elementi con `tag`."""
    with _lock:
        tokens = [t for t, value in _load().items() if value == tag]
    uris = []
    for token in tokens:
        uri = placestore.decode(token)
        if uri:
            uris.append(uri)
    return uris


def counts() -> dict[str, int]:
    with _lock:
        values = list(_load().values())
    return {tag_id: values.count(tag_id) for tag_id in TAG_IDS}


def _rekey(data: dict, old: str, new: str | None) -> bool:
    """Sposta (o con new=None elimina) la chiave `old` e i suoi figli."""
    prefix = old + "/"
    moved = [k for k in data if k == old or k.startswith(prefix)]
    for key in moved:
        tag = data.pop(key)
        if new is not None:
            data[new + key[len(old):]] = tag
    return bool(moved)


def moved(src: Gio.File, dest: Gio.File):
    """Un elemento è stato rinominato o spostato: l'etichetta lo segue
    (anche quelle dei file contenuti, se è una cartella)."""
    old, new = _token(src.get_uri()), _token(dest.get_uri())
    if old != new:
        try:
            _modify(lambda data: _rekey(data, old, new))
        except OSError:
            pass


def removed(gfile: Gio.File):
    """Un elemento è stato cestinato o eliminato."""
    old = _token(gfile.get_uri())
    try:
        _modify(lambda data: _rekey(data, old, None))
    except OSError:
        pass


def import_legacy(items) -> None:
    """Porta nel file JSON le etichette salvate nei metadati GVfs dalla
    versione precedente, poi le toglie dai metadati."""
    found = []
    for item in items:
        info = item.info
        if not info.has_attribute(LEGACY_ATTRIBUTE):
            continue
        value = info.get_attribute_string(LEGACY_ATTRIBUTE)
        if value in TAG_IDS:
            found.append((item, value))
    if not found:
        return

    def change(data):
        for item, value in found:
            data.setdefault(_token(item.uri), value)
        return True

    try:
        _modify(change)
    except OSError:
        return
    for item, _value in found:
        try:
            item.gfile.set_attribute(
                LEGACY_ATTRIBUTE, Gio.FileAttributeType.INVALID, None,
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)
        except (GLib.Error, TypeError):
            pass


def watch():
    """Ricarica quando il file cambia da fuori (sincronizzazione)."""
    global _monitor
    if _monitor is not None:
        return
    try:
        _monitor = Gio.File.new_for_path(TAGS_FILE).monitor_file(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
    except GLib.Error:
        return

    def on_changed(*_):
        with _lock:
            before = dict(_data)
            after = _load()
        if after != before:
            notifier.emit("changed")

    _monitor.connect("changed", on_changed)


# ---------------------------------------------------------------- vista
def location(tag: str) -> Gio.File:
    return Gio.File.new_for_uri(f"{TAG_SCHEME}:///{tag}")


def tag_of_location(gfile: Gio.File | None) -> str | None:
    """Etichetta mostrata da una posizione virtuale, None se non lo è."""
    if gfile is None or gfile.get_uri_scheme() != TAG_SCHEME:
        return None
    tag = gfile.get_uri().rstrip("/").rsplit("/", 1)[-1]
    return tag if tag in TAG_IDS else None


def label_for(tag: str | None) -> str:
    return next((label for tag_id, label, _ in TAGS if tag_id == tag), "")


def location_title(gfile: Gio.File) -> str | None:
    tag = tag_of_location(gfile)
    return f"Etichetta: {label_for(tag)}" if tag else None


def css(dark: bool = False) -> str:
    """Regole CSS per i pallini colorati, per il tema chiaro o scuro."""
    rules = [
        ".tag-dot { min-width: 10px; min-height: 10px;"
        " border-radius: 9999px; }",
        # pulsanti del menu contestuale
        ".tag-picker { margin: 2px 6px; }",
        ".tag-picker button { min-width: 28px; min-height: 28px;"
        " padding: 0; border-radius: 9999px; }",
        ".tag-picker button .tag-dot { min-width: 16px; min-height: 16px; }",
        ".tag-picker button.tag-current { box-shadow: inset 0 0 0 2px"
        " alpha(currentColor, 0.6); }",
        # sidebar: il pallino prende il posto dell'icona (16px)
        ".sidebar-tag-dot { margin: 3px; }",
    ]
    for tag_id, _label, (light, dark_color) in TAGS:
        color = dark_color if dark else light
        rules.append(f".tag-dot.tag-{tag_id} {{ background-color: {color}; }}")
    return "\n".join(rules) + "\n"
