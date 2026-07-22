"""Modelli dati."""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, GObject  # noqa: E402

FILE_ATTRS = ",".join([
    "standard::name", "standard::display-name", "standard::type",
    "standard::size", "standard::icon", "standard::symbolic-icon",
    "standard::content-type", "standard::is-hidden", "standard::is-symlink",
    "time::modified", "time::created",
    "unix::mode", "owner::user", "owner::group",
    "thumbnail::path", "access::can-read", "access::can-write",
])


class FileItem(GObject.Object):
    """Wrapper GObject attorno a Gio.File + Gio.FileInfo."""

    __gtype_name__ = "FileItem"

    def __init__(self, gfile: Gio.File, info: Gio.FileInfo):
        super().__init__()
        self.gfile = gfile
        self.info = info
        # numero di elementi (solo cartelle): None = non ancora calcolato,
        # -1 = errore/non leggibile
        self._child_count: int | None = None

    @property
    def name(self) -> str:
        return self.info.get_display_name() or self.gfile.get_basename() or "?"

    @property
    def is_dir(self) -> bool:
        return self.info.get_file_type() == Gio.FileType.DIRECTORY

    @property
    def is_hidden(self) -> bool:
        return self.info.get_is_hidden()

    @property
    def content_type(self) -> str:
        return self.info.get_content_type() or "application/octet-stream"

    @property
    def size(self) -> int:
        return self.info.get_size()

    @property
    def size_str(self) -> str:
        if self.is_dir:
            return "—"
        return GLib.format_size(self.size)

    @property
    def child_count(self) -> int | None:
        return self._child_count

    @property
    def count_str(self) -> str:
        """Numero di elementi della cartella, es. "8 oggetti"."""
        n = self._child_count
        if n is None or n < 0:
            return ""
        return "1 oggetto" if n == 1 else f"{n} oggetti"

    def count_children_async(self, cancellable, on_done):
        """Conta gli elementi non nascosti della cartella (async).

        `on_done(count)` viene invocato quando il conteggio è pronto (subito,
        se già in cache). Il risultato viene memorizzato su `_child_count`.
        """
        if self._child_count is not None:
            on_done(self._child_count)
            return
        if not self.is_dir:
            self._child_count = -1
            on_done(-1)
            return

        counter = {"n": 0}

        def on_next(enumerator, result):
            try:
                infos = enumerator.next_files_finish(result)
            except GLib.Error:
                on_done(-1)
                return
            if not infos:
                enumerator.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
                self._child_count = counter["n"]
                on_done(counter["n"])
                return
            for info in infos:
                if not info.get_is_hidden():
                    counter["n"] += 1
            enumerator.next_files_async(200, GLib.PRIORITY_DEFAULT,
                                        cancellable, on_next)

        def on_enum(gfile, result):
            try:
                enumerator = gfile.enumerate_children_finish(result)
            except GLib.Error:
                self._child_count = -1
                on_done(-1)
                return
            enumerator.next_files_async(200, GLib.PRIORITY_DEFAULT,
                                        cancellable, on_next)

        self.gfile.enumerate_children_async(
            "standard::is-hidden", Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT, cancellable, on_enum)

    @property
    def modified_str(self) -> str:
        dt = self.info.get_modification_date_time()
        return dt.to_local().format("%d/%m/%Y %H:%M") if dt else "—"

    @property
    def modified_ts(self) -> int:
        dt = self.info.get_modification_date_time()
        return dt.to_unix() if dt else 0

    @property
    def modified_compact(self) -> str:
        """Data e ora brevi per le righe: "12 lug 14:30" nell'anno
        corrente, altrimenti "12/07/24 14:30"."""
        dt = self.info.get_modification_date_time()
        if not dt:
            return ""
        dt = dt.to_local()
        now = GLib.DateTime.new_now_local()
        if dt.get_year() == now.get_year():
            return dt.format("%d %b %H:%M")
        return dt.format("%d/%m/%y %H:%M")

    @property
    def created_str(self) -> str:
        dt = self.info.get_creation_date_time()
        return dt.to_local().format("%d/%m/%Y %H:%M") if dt else "—"

    @property
    def created_ts(self) -> int:
        dt = self.info.get_creation_date_time()
        return dt.to_unix() if dt else 0

    @property
    def icon(self):
        """Icona a colori del tema (come la lista file di Nautilus)."""
        return self.info.get_icon() or self.info.get_symbolic_icon()

    @property
    def thumbnail_path(self):
        return self.info.get_attribute_byte_string("thumbnail::path")

    @property
    def uri(self) -> str:
        return self.gfile.get_uri()

    @property
    def path_str(self) -> str:
        return self.gfile.get_path() or self.uri

    @property
    def permissions_str(self) -> str:
        mode = self.info.get_attribute_uint32("unix::mode")
        if not mode:
            return "—"
        perms = ""
        for who in (6, 3, 0):
            for bit, ch in ((4, "r"), (2, "w"), (1, "x")):
                perms += ch if (mode >> who) & bit else "-"
        return perms

    @property
    def owner_str(self) -> str:
        user = self.info.get_attribute_string("owner::user") or "?"
        group = self.info.get_attribute_string("owner::group") or "?"
        return f"{user}:{group}"


SORT_KEYS = {
    "name": lambda i: i.name.casefold(),
    "size": lambda i: (i.size, i.name.casefold()),
    "created": lambda i: (i.created_ts, i.name.casefold()),
    "modified": lambda i: (i.modified_ts, i.name.casefold()),
}


def sort_items(items: list, by: str = "name",
               descending: bool = False) -> list:
    """Ordina con le cartelle sempre prima dei file."""
    key = SORT_KEYS.get(by, SORT_KEYS["name"])
    dirs = sorted((i for i in items if i.is_dir),
                  key=key, reverse=descending)
    files = sorted((i for i in items if not i.is_dir),
                   key=key, reverse=descending)
    return dirs + files
