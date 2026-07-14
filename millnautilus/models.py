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
    def modified_str(self) -> str:
        dt = self.info.get_modification_date_time()
        return dt.format("%d/%m/%Y %H:%M") if dt else "—"

    @property
    def modified_ts(self) -> int:
        dt = self.info.get_modification_date_time()
        return dt.to_unix() if dt else 0

    @property
    def created_str(self) -> str:
        dt = self.info.get_creation_date_time()
        return dt.format("%d/%m/%Y %H:%M") if dt else "—"

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
