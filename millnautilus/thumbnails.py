"""Miniature: anteprima dei file e dei file contenuti nelle cartelle."""
import threading
from concurrent.futures import ThreadPoolExecutor

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Gdk, GdkPixbuf, Gio, GLib  # noqa: E402

try:
    # generatore di miniature di GNOME (lo stesso di Nautilus): crea quelle
    # mancanti per PDF, video, documenti… Opzionale.
    gi.require_version("GnomeDesktop", "4.0")
    from gi.repository import GnomeDesktop  # noqa: E402
    _factory = GnomeDesktop.DesktopThumbnailFactory.new(
        GnomeDesktop.DesktopThumbnailSize.LARGE)
except (ImportError, ValueError):
    _factory = None

# lato massimo delle miniature caricate (basta anche per schermi HiDPI)
THUMB_SIZE = 64
# oltre questa dimensione un'immagine senza miniatura non viene caricata
MAX_IMAGE_BYTES = 64 * 1024 * 1024
# elementi esaminati al massimo per cartella e miniature nella pila
MAX_SCANNED = 200
STACK_SIZE = 3

_ATTRS = ",".join([
    "standard::name", "standard::content-type", "standard::is-hidden",
    "standard::type", "standard::size", "time::modified",
    "thumbnail::path", "thumbnail::is-valid",
])

# (tipo, uri, mtime) -> Gdk.Texture oppure None (nessuna miniatura)
_cache: dict[tuple, Gdk.Texture | None] = {}
# richieste in corso: chiave -> callback in attesa
_pending: dict[tuple, list] = {}
_lock = threading.Lock()
# pochi thread: le miniature arrivano un po' alla volta senza saturare il disco
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbs")


def lookup(item, on_ready) -> Gdk.Texture | None:
    """Miniatura di `item` se già pronta, altrimenti None.

    Per un file è la sua anteprima; per una cartella una piccola pila con le
    miniature dei primi file contenuti. Se non è ancora stata calcolata, la
    calcola in background e chiama `on_ready(texture)` nel thread principale
    (solo se ne esiste una).
    """
    if item.is_dir:
        # enumerare il contenuto di ogni riga sarebbe troppo lento in remoto
        if item.gfile.get_path() is None:
            return None
        key = ("dir", item.uri, item.modified_ts)
        work = _folder_stack
    else:
        key = ("file", item.uri, item.modified_ts)
        work = _file_thumbnail
    if key in _cache:
        return _cache[key]
    with _lock:
        waiting = _pending.get(key)
        if waiting is not None:
            waiting.append(on_ready)
            return None
        _pending[key] = [on_ready]
    _executor.submit(_compute, key, work, item.gfile, item.info)
    return None


def _compute(key, work, gfile, info):
    pixbuf = None
    try:
        pixbuf = work(gfile, info)
    except GLib.Error:
        pass
    GLib.idle_add(_deliver, key, pixbuf)


def _deliver(key, pixbuf):
    texture = Gdk.Texture.new_for_pixbuf(pixbuf) if pixbuf else None
    _cache[key] = texture
    with _lock:
        callbacks = _pending.pop(key, [])
    if texture is not None:
        for callback in callbacks:
            callback(texture)
    return False


# ------------------------------------------------------------------ file
def _file_thumbnail(gfile: Gio.File, info: Gio.FileInfo, generate=True):
    """Miniatura di sistema se valida; altrimenti la genera (se possibile)
    o, per le immagini locali, carica l'immagine stessa ridotta."""
    thumb = info.get_attribute_byte_string("thumbnail::path")
    if thumb and info.get_attribute_boolean("thumbnail::is-valid"):
        pixbuf = _load_scaled(thumb)
        if pixbuf is not None:
            return pixbuf
    if generate:
        pixbuf = _generate(gfile, info)
        if pixbuf is not None:
            return pixbuf
    ctype = info.get_content_type() or ""
    path = gfile.get_path()
    if (ctype.startswith("image/") and path
            and info.get_size() <= MAX_IMAGE_BYTES):
        return _load_scaled(path)
    return None


def _generate(gfile: Gio.File, info: Gio.FileInfo):
    """Crea e salva la miniatura con il generatore di GNOME."""
    if _factory is None:
        return None
    uri = gfile.get_uri()
    ctype = info.get_content_type() or ""
    dt = info.get_modification_date_time()
    mtime = dt.to_unix() if dt else 0
    if (not _factory.can_thumbnail(uri, ctype, mtime)
            or _factory.has_valid_failed_thumbnail(uri, mtime)):
        return None
    try:
        pixbuf = _factory.generate_thumbnail(uri, ctype, None)
    except GLib.Error:
        _factory.create_failed_thumbnail(uri, mtime, None)
        return None
    if pixbuf is None:
        return None
    try:
        _factory.save_thumbnail(pixbuf, uri, mtime, None)
    except GLib.Error:
        pass
    return _fit(pixbuf)


def _load_scaled(path: str):
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            path, THUMB_SIZE, THUMB_SIZE, True)
    except GLib.Error:
        return None
    # rispetta l'orientamento EXIF delle foto
    return pixbuf.apply_embedded_orientation() or pixbuf


def _fit(pixbuf: GdkPixbuf.Pixbuf) -> GdkPixbuf.Pixbuf:
    """Riduce entro THUMB_SIZE mantenendo le proporzioni."""
    width, height = pixbuf.get_width(), pixbuf.get_height()
    scale = THUMB_SIZE / max(width, height)
    if scale >= 1:
        return pixbuf
    return pixbuf.scale_simple(max(1, round(width * scale)),
                               max(1, round(height * scale)),
                               GdkPixbuf.InterpType.BILINEAR)


# --------------------------------------------------------------- cartelle
def _folder_stack(folder: Gio.File, _info):
    """Pila con le miniature dei primi file (per nome) della cartella.

    Usa solo miniature già esistenti e immagini: generarne di nuove per ogni
    cartella mostrata sarebbe troppo costoso.
    """
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
            candidates.append(info)
    finally:
        enumerator.close(None)

    candidates.sort(key=lambda i: i.get_name().casefold())
    thumbs = []
    for info in candidates:
        child = folder.get_child(info.get_name())
        pixbuf = _file_thumbnail(child, info, generate=False)
        if pixbuf is not None:
            thumbs.append(pixbuf)
            if len(thumbs) == STACK_SIZE:
                break
    return _compose_stack(thumbs) if thumbs else None


def _compose_stack(thumbs: list) -> GdkPixbuf.Pixbuf:
    """Dispone le miniature come carte sfalsate, la prima davanti."""
    canvas = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8,
                                  THUMB_SIZE, THUMB_SIZE)
    canvas.fill(0x00000000)
    step = 8
    card = THUMB_SIZE - step * (STACK_SIZE - 1)
    border = 3
    count = len(thumbs)
    # la prima carta in basso a sinistra, le altre dietro verso l'alto a destra
    for index in reversed(range(count)):
        x = index * step
        y = (count - 1 - index) * step + step * (STACK_SIZE - count)
        # contorno grigio sottile e cornice bianca: visibili su ogni tema
        canvas.new_subpixbuf(x, y, card, card).fill(0x9a9a9aff)
        canvas.new_subpixbuf(x + 1, y + 1, card - 2, card - 2).fill(
            0xffffffff)
        inner = card - 2 * border
        square = _crop_square(thumbs[index]).scale_simple(
            inner, inner, GdkPixbuf.InterpType.BILINEAR)
        square.copy_area(0, 0, inner, inner, canvas, x + border, y + border)
    return canvas


def _crop_square(pixbuf: GdkPixbuf.Pixbuf) -> GdkPixbuf.Pixbuf:
    """Ritaglio quadrato centrato, così riempie tutta la carta."""
    width, height = pixbuf.get_width(), pixbuf.get_height()
    side = min(width, height)
    return pixbuf.new_subpixbuf((width - side) // 2, (height - side) // 2,
                                side, side)
