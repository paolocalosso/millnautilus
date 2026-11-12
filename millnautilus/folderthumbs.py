"""Anteprime delle cartelle: la prima immagine contenuta, in miniatura."""
import threading
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib  # noqa: E402

# lato massimo dell'immagine caricata (basta anche per schermi HiDPI)
THUMB_SIZE = 64
# elementi esaminati al massimo per cartella: le cartelle enormi non devono
# rallentare la vista
MAX_SCANNED = 200

_ATTRS = ",".join([
    "standard::name", "standard::content-type", "standard::is-hidden",
    "standard::type", "thumbnail::path", "thumbnail::is-valid",
])

# (uri, mtime) -> Gdk.Texture oppure None (nessuna anteprima)
_cache: dict[tuple[str, int], Gdk.Texture | None] = {}
# richieste in corso: (uri, mtime) -> callback in attesa
_pending: dict[tuple[str, int], list] = {}
_lock = threading.Lock()
# pochi thread: le anteprime arrivano un po' alla volta senza saturare il disco
_executor = ThreadPoolExecutor(max_workers=2,
                               thread_name_prefix="folder-thumbs")


def lookup(item, on_ready) -> Gdk.Texture | None:
    """Anteprima della cartella `item` se già pronta, altrimenti None.

    Se non è ancora stata calcolata, la calcola in background e chiama
    `on_ready(texture)` nel thread principale (solo se ne esiste una).
    Funziona solo sulle cartelle locali: su quelle remote enumerare il
    contenuto di ogni riga sarebbe troppo lento.
    """
    path = item.gfile.get_path()
    if path is None:
        return None
    key = (item.uri, item.modified_ts)
    if key in _cache:
        return _cache[key]
    with _lock:
        waiting = _pending.get(key)
        if waiting is not None:
            waiting.append(on_ready)
            return None
        _pending[key] = [on_ready]
    _executor.submit(_compute, key, item.gfile)
    return None


def _compute(key, folder: Gio.File):
    pixbuf = None
    try:
        pixbuf = _find_preview(folder)
    except GLib.Error:
        pass
    GLib.idle_add(_deliver, key, pixbuf)


def _find_preview(folder: Gio.File) -> GdkPixbuf.Pixbuf | None:
    """Miniatura della prima immagine (per nome) nella cartella."""
    enumerator = folder.enumerate_children(
        _ATTRS, Gio.FileQueryInfoFlags.NONE, None)
    candidates = []
    try:
        for _ in range(MAX_SCANNED):
            info = enumerator.next_file(None)
            if info is None:
                break
            if info.get_is_hidden():
                continue
            if info.get_file_type() != Gio.FileType.REGULAR:
                continue
            if not (info.get_content_type() or "").startswith("image/"):
                continue
            candidates.append(info)
    finally:
        enumerator.close(None)

    candidates.sort(key=lambda i: i.get_name().casefold())
    for info in candidates:
        pixbuf = _load_thumbnail(folder.get_child(info.get_name()), info)
        if pixbuf is not None:
            return pixbuf
    return None


def _load_thumbnail(gfile: Gio.File, info: Gio.FileInfo):
    """Usa la thumbnail di sistema se valida, altrimenti l'immagine stessa."""
    sources = []
    thumb = info.get_attribute_byte_string("thumbnail::path")
    if thumb and info.get_attribute_boolean("thumbnail::is-valid"):
        sources.append(thumb)
    if gfile.get_path():
        sources.append(gfile.get_path())
    for source in sources:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                source, THUMB_SIZE, THUMB_SIZE, True)
        except GLib.Error:
            continue
        # rispetta l'orientamento EXIF delle foto
        pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
        return _crop_square(pixbuf)
    return None


def _crop_square(pixbuf: GdkPixbuf.Pixbuf) -> GdkPixbuf.Pixbuf:
    """Ritaglio quadrato centrato, così riempie tutto il riquadro."""
    width, height = pixbuf.get_width(), pixbuf.get_height()
    side = min(width, height)
    return pixbuf.new_subpixbuf((width - side) // 2, (height - side) // 2,
                                side, side)


def _deliver(key, pixbuf):
    texture = Gdk.Texture.new_for_pixbuf(pixbuf) if pixbuf else None
    _cache[key] = texture
    with _lock:
        callbacks = _pending.pop(key, [])
    if texture is not None:
        for callback in callbacks:
            callback(texture)
    return False
