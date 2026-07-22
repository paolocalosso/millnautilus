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
        # selezione multipla: numero elementi
        "multi-selection-changed": (GObject.SignalFlags.RUN_FIRST, None,
                                    (int,)),
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
        # Colonna che vogliamo tenere a fuoco (l'ultima aperta). Finché è
        # impostata, la riportiamo a destra a ogni cambio di layout.
        self._scroll_target: MillerColumn | None = None
        # True solo mentre siamo noi a spostare lo scroll, per distinguere
        # dallo scroll manuale dell'utente.
        self._pinning = False
        hadj = self.get_hadjustment()
        hadj.connect("changed", self._on_hadj_changed)
        hadj.connect("value-changed", self._on_hadj_value_changed)

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

    def reveal(self, target: Gio.File):
        """Naviga alla cartella genitore e seleziona `target`."""
        parent = target.get_parent()
        if parent is None:
            self.set_root(target)
            return
        self.set_root(parent)
        if self.columns:
            self.columns[0].select_file(target)

    def _truncate(self, depth: int):
        while len(self.columns) > depth:
            col = self.columns.pop()
            if col is self._scroll_target:
                self._scroll_target = None
            self.box.remove(col)

    def _add_column(self, directory: Gio.File):
        col = MillerColumn(directory, depth=len(self.columns),
                           show_hidden=self.show_hidden)
        col.connect("item-selected", self._on_item_selected)
        col.connect("multi-selected", self._on_multi_selected)
        col.connect("item-activated", self._on_item_activated)
        col.connect("files-dropped",
                    lambda c, files, move:
                    self.emit("files-dropped", files, c.directory, move))
        self.columns.append(col)
        self.box.append(col)
        # Aggancio l'ultima colonna e la riporto a destra subito (idle) e a
        # ogni successivo cambio di layout: l'upper dell'aggiustamento cresce
        # in più passi mentre il contenuto si carica in modo asincrono, ma la
        # colonna è già a fuoco perché la larghezza è nota da subito. Nessun
        # timer: il "pin" viene rilasciato solo quando l'utente scorre via.
        self._scroll_target = col
        GLib.idle_add(self._scroll_to_end)

    def _on_hadj_changed(self, _adj):
        # Il layout è cambiato (colonna aggiunta/rimossa o finestra
        # ridimensionata): se stiamo seguendo una colonna, riportala a fuoco.
        if self._scroll_target is not None:
            self._scroll_to_end()

    def _on_hadj_value_changed(self, adj):
        # Se lo scroll non è stato impostato da noi ed è visibilmente lontano
        # dalla fine, l'utente ha scrollato a sinistra: smetto di inseguire.
        if self._pinning or self._scroll_target is None:
            return
        max_value = adj.get_upper() - adj.get_page_size()
        if adj.get_value() < max_value - 1:
            self._scroll_target = None

    def _scroll_to_end(self):
        adj = self.get_hadjustment()
        self._pinning = True
        adj.set_value(max(adj.get_lower(),
                          adj.get_upper() - adj.get_page_size()))
        self._pinning = False
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

    def _on_multi_selected(self, column: MillerColumn, count: int):
        self._truncate(column.depth + 1)
        self.emit("location-changed", column.directory)
        self.emit("multi-selection-changed", count)

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

    def get_selected_items(self) -> list[FileItem]:
        """Elementi selezionati nella colonna attiva (anche multipli)."""
        for col in reversed(self.columns):
            items = col.get_selected_items()
            if items:
                return items
        return []

    def _selected_column(self) -> MillerColumn | None:
        for col in reversed(self.columns):
            if col.get_selected_items():
                return col
        return None

    def active_column(self) -> MillerColumn | None:
        return self._selected_column() or (
            self.columns[-1] if self.columns else None)

    def step_selection(self, delta: int):
        """Sposta la selezione di `delta` nella colonna attiva."""
        col = self._selected_column()
        if col is None:
            if self.columns and self.columns[-1].store.get_n_items() > 0:
                self.columns[-1].select_position(0)
            return
        pos = col.selected_position()
        if pos is None:
            return
        new = pos + delta
        if 0 <= new < col.store.get_n_items():
            col.select_position(new)

    def selection_info(self) -> tuple[int, int]:
        """(indice 1-based, totale) nella colonna attiva, o (0, 0)."""
        col = self._selected_column()
        if col is None or len(col.get_selected_items()) != 1:
            return (0, 0)
        return (col.selected_position() + 1, col.store.get_n_items())
