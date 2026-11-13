"""Preferiti e Posizioni fissate in un unico file.

Per sincronizzarli tra più macchine basta puntare la variabile d'ambiente
MILLNAUTILUS_PLACES a un file dentro una cartella sincronizzata (Koofr,
pCloud, …); altrimenti si usa ~/.config/millnautilus/places.json.

I percorsi sono salvati in forma portabile: le cartelle standard diventano
token tipo "xdg:DOCUMENTS", che su ogni macchina si risolvono nella cartella
giusta anche se GNOME è in un'altra lingua ("Documenti" qui, "Documents" là).
"""
import json
import os

from gi.repository import GLib


def _places_file() -> str:
    override = os.environ.get("MILLNAUTILUS_PLACES")
    if override:
        return os.path.expanduser(override)
    return os.path.join(GLib.get_user_config_dir(),
                        "millnautilus", "places.json")


PLACES_FILE = _places_file()

# posizione usata in passato (dentro il repository): serve solo a migrare
LEGACY_PLACES_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "places.json")

# file GTK condiviso con Nautilus: ci rispecchiamo i preferiti
GTK_BOOKMARKS = os.path.join(GLib.get_user_config_dir(),
                             "gtk-3.0", "bookmarks")

BOOKMARKS, PINNED = "bookmarks", "pinned"

# cartelle standard riconosciute, dalla più specifica alla più generica
XDG_KINDS = (
    ("DESKTOP", GLib.UserDirectory.DIRECTORY_DESKTOP),
    ("DOCUMENTS", GLib.UserDirectory.DIRECTORY_DOCUMENTS),
    ("DOWNLOAD", GLib.UserDirectory.DIRECTORY_DOWNLOAD),
    ("MUSIC", GLib.UserDirectory.DIRECTORY_MUSIC),
    ("PICTURES", GLib.UserDirectory.DIRECTORY_PICTURES),
    ("VIDEOS", GLib.UserDirectory.DIRECTORY_VIDEOS),
    ("PUBLIC_SHARE", GLib.UserDirectory.DIRECTORY_PUBLIC_SHARE),
    ("TEMPLATES", GLib.UserDirectory.DIRECTORY_TEMPLATES),
)


# ---------------------------------------------------------------- portabilità
def _xdg_paths() -> list[tuple[str, str]]:
    """(nome simbolico, percorso) delle cartelle standard di questa macchina.

    Ordinate dal percorso più lungo: una cartella standard può trovarsi
    dentro un'altra e va riconosciuta la più specifica.
    """
    paths = []
    for name, kind in XDG_KINDS:
        path = GLib.get_user_special_dir(kind)
        if path:
            paths.append((name, path.rstrip("/")))
    paths.sort(key=lambda pair: len(pair[1]), reverse=True)
    return paths


def encode(uri: str) -> str:
    """URI → forma portabile da scrivere nel file."""
    if not uri.startswith("file://"):
        return uri  # sftp://, trash:// e simili restano come sono
    path = GLib.filename_from_uri(uri)[0].rstrip("/")
    for name, base in _xdg_paths():
        if path == base:
            return f"xdg:{name}"
        if path.startswith(base + "/"):
            return f"xdg:{name}/{path[len(base) + 1:]}"
    home = GLib.get_home_dir().rstrip("/")
    if path == home:
        return "home:"
    if path.startswith(home + "/"):
        return f"home:{path[len(home) + 1:]}"
    return uri


def decode(token: str) -> str | None:
    """Forma portabile → URI valido su questa macchina (None se introvabile)."""
    if token.startswith("xdg:"):
        name, _, relative = token[4:].partition("/")
        base = next((GLib.get_user_special_dir(kind)
                     for key, kind in XDG_KINDS if key == name), None)
        if not base:
            return None
        path = os.path.join(base, relative) if relative else base
        return GLib.filename_to_uri(path, None)
    if token.startswith("home:"):
        relative = token[5:]
        path = os.path.join(GLib.get_home_dir(), relative) if relative \
            else GLib.get_home_dir()
        return GLib.filename_to_uri(path, None)
    return token


def _label_for(token: str, stored: str) -> str:
    """Per le cartelle standard l'etichetta segue la lingua della macchina."""
    if token.startswith("xdg:") and "/" not in token[4:]:
        uri = decode(token)
        if uri:
            return os.path.basename(GLib.filename_from_uri(uri)[0].rstrip("/"))
    return stored


# ---------------------------------------------------------------- lettura
def _read() -> dict:
    try:
        with open(PLACES_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _migrate()
    if not isinstance(data, dict):
        return {BOOKMARKS: [], PINNED: []}
    return {key: [e for e in data.get(key, [])
                  if isinstance(e, list) and len(e) == 2]
            for key in (BOOKMARKS, PINNED)}


def _write(data: dict):
    try:
        os.makedirs(os.path.dirname(PLACES_FILE), exist_ok=True)
        with open(PLACES_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError:
        return
    _export_gtk_bookmarks(data.get(BOOKMARKS, []))


def _migrate() -> dict:
    """Prima esecuzione: recupera quel che c'è già, senza perdere nulla."""
    # file nella vecchia posizione (dentro il repository): si riusa com'è
    try:
        with open(LEGACY_PLACES_FILE, encoding="utf-8") as fh:
            legacy = json.load(fh)
        if isinstance(legacy, dict):
            data = {key: [e for e in legacy.get(key, [])
                          if isinstance(e, list) and len(e) == 2]
                    for key in (BOOKMARKS, PINNED)}
            _write(data)
            return data
    except (OSError, ValueError):
        pass

    data = {BOOKMARKS: [], PINNED: []}
    try:
        with open(GTK_BOOKMARKS, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                uri, _, label = line.partition(" ")
                data[BOOKMARKS].append(
                    [encode(uri),
                     label or GLib.uri_unescape_string(
                         uri.rsplit("/", 1)[-1], None) or uri])
    except OSError:
        pass

    old_pinned = os.path.join(GLib.get_user_config_dir(),
                              "millnautilus", "pinned.json")
    try:
        with open(old_pinned, encoding="utf-8") as fh:
            for entry in json.load(fh):
                if isinstance(entry, list) and len(entry) == 2:
                    data[PINNED].append([encode(entry[0]), entry[1]])
    except (OSError, ValueError):
        pass
    _write(data)
    return data


def _export_gtk_bookmarks(entries: list):
    """Rispecchia i preferiti nel file GTK, così Nautilus li vede."""
    lines = []
    for token, label in entries:
        uri = decode(token)
        if uri:
            lines.append(f"{uri} {_label_for(token, label)}")
    try:
        os.makedirs(os.path.dirname(GTK_BOOKMARKS), exist_ok=True)
        with open(GTK_BOOKMARKS, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
    except OSError:
        pass


# ---------------------------------------------------------------- API
def load(section: str) -> list[tuple[str, str]]:
    """(uri, etichetta) della sezione, risolti per questa macchina."""
    result = []
    for token, label in _read().get(section, []):
        uri = decode(token)
        if uri:
            result.append((uri, _label_for(token, label)))
    return result


def contains(section: str, uri: str) -> bool:
    token = encode(uri)
    return any(t == token for t, _ in _read().get(section, []))


def add(section: str, uri: str, label: str):
    data = _read()
    token = encode(uri)
    if any(t == token for t, _ in data[section]):
        return
    data[section].append([token, label])
    _write(data)


def remove(section: str, uri: str):
    data = _read()
    token = encode(uri)
    data[section] = [e for e in data[section] if e[0] != token]
    _write(data)


def reorder(section: str, uri: str, target_uri: str, after: bool):
    data = _read()
    token, target = encode(uri), encode(target_uri)
    if token == target:
        return
    entries = data[section]
    dragged = next((e for e in entries if e[0] == token), None)
    if dragged is None:
        return
    entries.remove(dragged)
    index = next((i for i, e in enumerate(entries) if e[0] == target), None)
    entries.insert(len(entries) if index is None
                   else index + 1 if after else index, dragged)
    _write(data)
