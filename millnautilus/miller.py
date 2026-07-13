"""Vista a colonne (Miller view)."""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, GObject, Gtk  # noqa: E402

from .column import MillerColumn  # noqa: E402
from .models import FileItem  # noqa: E402


class MillerView(Gtk.ScrolledWindow):
    """Contenitore orizzontale di MillerColumn."""

    __gsignals__ = {
        # FileItem selezionato in una colonna qualsiasi (o None)
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # cambia la posizione corrente (Gio.File)
        "location-changed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # doppio click su file non-directory
        "file-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # drop di file: (list[Gio.File], Gio.File destinazione, move)
        "files-dropped": (GObject.SignalFlags.RUN_FIRST, None,
                          (object, object, bool)),
    }

    def __init__(self):
        super().__init__(vscrollbar_policy=Gtk.PolicyType.NEVER,
                         hexpand=True, vexpand=True)
        self.show_hidden = False
        self.box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_child(self.box)
        self.columns: list[MillerColumn] = []
        self.root: Gio.File | None = None

    # ------------------------------------------------------------ navigazione
    @property
    def current_dir(self) -> Gio.File | None:
        """Direttorio 'attivo': quello della colonna più profonda."""
        if not self.columns:
            return self.root
        for col in reversed(self.columns):
            sel = col.get_selected()
            if sel is not None:
                return sel.gfile if sel.is_dir else col.directory
        return self.columns[-1].directory

    def set_root(self, directory: Gio.File):
        self.root = directory
        self._truncate(0)
        self._add_column(directory)
        self.emit("location-changed", directory)
        self.emit("selection-changed", None)

    def _truncate(self, depth: int):
        while len(self.columns) > depth:
            col = self.columns.pop()
            self.box.remove(col)

    def _add_column(self, directory: Gio.File):
        col = MillerColumn(directory, depth=len(self.columns),
                           show_hidden=self.show_hidden)
        col.connect("item-selected", self._on_item_selected)
        col.connect("item-activated", self._on_item_activated)
        col.connect("files-dropped",
                    lambda c, files, move:
                    self.emit("files-dropped", files, c.directory, move))
        self.columns.append(col)
        self.box.append(col)
        GLib.idle_add(self._scroll_to_end)

    def _scroll_to_end(self):
        adj = self.get_hadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    # ------------------------------------------------------------ callbacks
    def _on_item_selected(self, column: MillerColumn, item):
        if item is None:
            return
        self._truncate(column.depth + 1)
        if item.is_dir:
            self._add_column(item.gfile)
            self.emit("location-changed", item.gfile)
        else:
            self.emit("location-changed", column.directory)
        self.emit("selection-changed", item)

    def _on_item_activated(self, column: MillerColumn, item: FileItem):
        if not item.is_dir:
            self.emit("file-activated", item)

    # ------------------------------------------------------------ utilità
    def set_show_hidden(self, show: bool):
        self.show_hidden = show
        for col in self.columns:
            col.set_show_hidden(show)

    def reload_dir(self, directory: Gio.File):
        """Ricarica le colonne che mostrano `directory` (dopo operazioni)."""
        for col in self.columns:
            if col.directory.equal(directory):
                col.reload()

    def reload_all(self):
        for col in self.columns:
            col.reload()

    def get_selected(self) -> FileItem | None:
        for col in reversed(self.columns):
            sel = col.get_selected()
            if sel is not None:
                return sel
        return None
