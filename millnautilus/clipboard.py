"""Utilità per gli appunti di sistema.

Gdk.Clipboard.set() non è affidabile da Python (è una macro variadica in C):
va costruito un Gdk.ContentProvider esplicito, offrendo il testo sia come
valore sia come MIME text/plain, che è quello che cercano i gestori di
appunti come GPaste.
"""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402


def text_provider(text: str) -> Gdk.ContentProvider:
    """Provider che offre `text` nei formati attesi dai gestori di appunti."""
    value = GObject.Value(str, text)
    providers = [Gdk.ContentProvider.new_for_value(value)]
    data = GLib.Bytes.new(text.encode())
    for mime in ("text/plain;charset=utf-8", "text/plain"):
        providers.append(Gdk.ContentProvider.new_for_bytes(mime, data))
    return Gdk.ContentProvider.new_union(providers)


def set_text(widget: Gtk.Widget, text: str) -> bool:
    """Copia `text` negli appunti. Ritorna False se non è stato possibile."""
    try:
        widget.get_clipboard().set_content(text_provider(text))
        return True
    except Exception:  # noqa: BLE001
        return False
