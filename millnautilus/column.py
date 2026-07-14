"""Singola colonna della Miller view."""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import (Gdk, Gio, GLib, GObject, Graphene,  # noqa: E402
                           Gtk, Pango)

from .models import FILE_ATTRS, FileItem, sort_items  # noqa: E402

COLUMN_WIDTH = 230

CONTEXT_MENU_XML = [
    ("Apri", "win.open-item"),
    ("Apri con…", "win.open-with"),
    ("Apri in una nuova finestra", "win.open-new-window"),
    None,
    ("Copia", "win.copy"),
    ("Taglia", "win.cut"),
    ("Incolla", "win.paste"),
    ("Copia percorso", "win.copy-path"),
    None,
    ("Rinomina…", "win.rename"),
    ("Sposta nel cestino", "win.trash"),
    None,
    ("Nuova cartella…", "win.new-folder"),
    ("Aggiungi ai preferiti", "win.bookmark"),
    ("Proprietà", "win.properties"),
]


def build_context_menu() -> Gio.Menu:
    menu = Gio.Menu()
    section = Gio.Menu()
    for entry in CONTEXT_MENU_XML:
        if entry is None:
            menu.append_section(None, section)
            section = Gio.Menu()
        else:
            section.append(*entry)
    menu.append_section(None, section)
    return menu


class MillerColumn(Gtk.Box):
    """Colonna: elenco di un singolo direttorio."""

    __gsignals__ = {
        # FileItem selezionato (o None)
        "item-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # doppio click / Enter su un file
        "item-activated": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        # richiesta drop di file in questa cartella: (list[Gio.File], move)
        "files-dropped": (GObject.SignalFlags.RUN_FIRST, None, (object, bool)),
    }

    MIN_WIDTH = 150
    MAX_WIDTH = 800

    def __init__(self, directory: Gio.File, depth: int, show_hidden=False):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.directory = directory
        self.depth = depth
        self.show_hidden = show_hidden
        self._cancellable = Gio.Cancellable()
        self._all_items: list[FileItem] = []
        self._icon_theme: Gtk.IconTheme | None = None
        self._pending_select: Gio.File | None = None
        self._sort_by = "name"
        self._sort_desc = False

        self.set_size_request(COLUMN_WIDTH, -1)
        self.add_css_class("miller-column")

        self._content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                                hexpand=True)
        self._setup_sort_actions()
        self._content.append(self._build_sort_header())

        self.store = Gio.ListStore(item_type=FileItem)
        self.selection = Gtk.SingleSelection(model=self.store,
                                             autoselect=False,
                                             can_unselect=True)
        self.selection.connect("notify::selected-item", self._on_selection)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)

        self.listview = Gtk.ListView(model=self.selection, factory=factory)
        self.listview.set_single_click_activate(False)
        self.listview.connect("activate", self._on_activate)
        self.listview.add_css_class("navigation-sidebar")

        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      vexpand=True)
        scroller.set_child(self.listview)
        self._content.append(scroller)
        self.append(self._content)
        self.append(self._build_resize_handle())

        self._setup_drop_target()
        self.reload()

    # ------------------------------------------------------------ ordinamento
    def _setup_sort_actions(self):
        group = Gio.SimpleActionGroup()
        sort_by = Gio.SimpleAction.new_stateful(
            "sort-by", GLib.VariantType("s"), GLib.Variant("s", "name"))
        sort_by.connect("change-state", self._on_sort_by)
        group.add_action(sort_by)
        sort_desc = Gio.SimpleAction.new_stateful(
            "sort-desc", None, GLib.Variant("b", False))
        sort_desc.connect("change-state", self._on_sort_desc)
        group.add_action(sort_desc)
        self.insert_action_group("col", group)

    def _build_sort_header(self) -> Gtk.Box:
        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Nome", "col.sort-by::name")
        section.append("Dimensione", "col.sort-by::size")
        section.append("Data creazione", "col.sort-by::created")
        section.append("Data modifica", "col.sort-by::modified")
        menu.append_section(None, section)
        section2 = Gio.Menu()
        section2.append("Ordine decrescente", "col.sort-desc")
        menu.append_section(None, section2)

        self.sort_btn = Gtk.MenuButton(
            icon_name="view-sort-descending-symbolic",
            menu_model=menu, halign=Gtk.Align.END, hexpand=True,
            tooltip_text="Ordinamento colonna",
            css_classes=["flat", "column-sort-button"])
        header = Gtk.Box()
        header.append(self.sort_btn)
        return header

    def _on_sort_by(self, action, value):
        action.set_state(value)
        self._sort_by = value.get_string()
        self._populate()

    def _on_sort_desc(self, action, value):
        action.set_state(value)
        self._sort_desc = value.get_boolean()
        self._populate()

    def _build_resize_handle(self) -> Gtk.Box:
        """Maniglia sul bordo destro per ridimensionare la colonna."""
        handle = Gtk.Box()
        handle.set_size_request(6, -1)
        handle.add_css_class("column-handle")
        handle.set_cursor(Gdk.Cursor.new_from_name("col-resize"))

        drag = Gtk.GestureDrag()
        drag.connect("drag-update", self._on_resize_drag, handle)
        handle.add_controller(drag)
        return handle

    def _on_resize_drag(self, gesture, _dx, _dy, handle):
        ok, x, _y = gesture.get_point(None)
        if not ok:
            return
        point = Graphene.Point()
        point.init(x, 0)
        ok, translated = handle.compute_point(self, point)
        if not ok:
            return
        width = max(self.MIN_WIDTH, min(self.MAX_WIDTH, int(translated.x)))
        self.set_size_request(width, -1)

    # ------------------------------------------------------------ caricamento
    def reload(self):
        self._cancellable.cancel()
        self._cancellable = Gio.Cancellable()
        self._all_items = []
        self.store.remove_all()
        self.directory.enumerate_children_async(
            FILE_ATTRS, Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
            self._cancellable, self._on_enumerated)

    def _on_enumerated(self, gfile, result):
        try:
            enumerator = gfile.enumerate_children_finish(result)
        except GLib.Error as err:
            self._show_error(err.message)
            return
        enumerator.next_files_async(200, GLib.PRIORITY_DEFAULT,
                                    self._cancellable, self._on_next_files)

    def _on_next_files(self, enumerator, result):
        try:
            infos = enumerator.next_files_finish(result)
        except GLib.Error:
            return
        if not infos:
            enumerator.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
            self._populate()
            return
        for info in infos:
            child = self.directory.get_child(info.get_name())
            self._all_items.append(FileItem(child, info))
        enumerator.next_files_async(200, GLib.PRIORITY_DEFAULT,
                                    self._cancellable, self._on_next_files)

    def _populate(self):
        items = [i for i in self._all_items
                 if self.show_hidden or not i.is_hidden]
        items = sort_items(items, self._sort_by, self._sort_desc)
        self.store.remove_all()
        self.store.splice(0, 0, items)

        if self._pending_select is not None:
            target = self._pending_select
            self._pending_select = None
            for i, item in enumerate(items):
                if item.gfile.equal(target):
                    self.selection.set_selected(i)
                    self.listview.scroll_to(i, Gtk.ListScrollFlags.NONE, None)
                    break

    def select_file(self, gfile: Gio.File):
        """Seleziona `gfile` appena il contenuto è caricato."""
        self._pending_select = gfile

    def set_show_hidden(self, show: bool):
        self.show_hidden = show
        self._populate()

    def _show_error(self, message: str):
        label = Gtk.Label(label=message, wrap=True, margin_top=12,
                          margin_start=8, margin_end=8)
        label.add_css_class("dim-label")
        self._content.prepend(label)

    # ------------------------------------------------------------ factory
    def _on_setup(self, factory, list_item):
        box = Gtk.Box(spacing=8, margin_top=2, margin_bottom=2)
        box.icon = Gtk.Image(pixel_size=24)
        box.label = Gtk.Label(xalign=0, hexpand=True,
                              ellipsize=Pango.EllipsizeMode.END)
        box.date = Gtk.Label(xalign=1)
        box.date.add_css_class("dim-label")
        box.date.add_css_class("caption")
        box.menu_btn = Gtk.Button(icon_name="view-more-symbolic",
                                  valign=Gtk.Align.CENTER,
                                  css_classes=["flat", "circular",
                                               "row-menu-button"])
        box.menu_btn.connect("clicked", self._on_row_menu_clicked, list_item)
        box.append(box.icon)
        box.append(box.label)
        box.append(box.date)
        box.append(box.menu_btn)
        list_item.set_child(box)

        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_right_click, list_item)
        box.add_controller(gesture)

        drag = Gtk.DragSource(actions=Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drag.connect("prepare", self._on_drag_prepare, list_item)
        box.add_controller(drag)

    def _on_bind(self, factory, list_item):
        item: FileItem = list_item.get_item()
        box = list_item.get_child()
        box.icon.set_from_paintable(self._lookup_icon(item))
        box.label.set_text(item.name)
        box.date.set_text(item.modified_compact)
        box.menu_btn.set_visible(item.is_dir)

    def _lookup_icon(self, item: FileItem):
        """Cerca l'icona a taglia grande (64px): il tema seleziona la
        variante scalable/dettagliata, poi Gtk.Image la scala a pixel_size."""
        if self._icon_theme is None:
            self._icon_theme = Gtk.IconTheme.get_for_display(
                self.get_display())
        return self._icon_theme.lookup_by_gicon(
            item.icon, 64, self.get_scale_factor(),
            self.get_direction(), 0)

    # ------------------------------------------------------------ interazione
    def _on_selection(self, selection, _pspec):
        self.emit("item-selected", selection.get_selected_item())

    def _on_activate(self, listview, position):
        item = self.store.get_item(position)
        if item:
            self.emit("item-activated", item)

    def _popup_context_menu(self, list_item, anchor: Gtk.Widget):
        """Seleziona la riga e apre il menu contestuale ancorato a `anchor`."""
        self.selection.set_selected(list_item.get_position())
        win = self.get_root()
        if hasattr(win, "set_context_item"):
            win.set_context_item(list_item.get_item(), self)
        popover = Gtk.PopoverMenu.new_from_model(build_context_menu())
        popover.set_parent(anchor)
        popover.set_has_arrow(False)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()

    def _on_right_click(self, gesture, n_press, x, y, list_item):
        self._popup_context_menu(list_item, list_item.get_child())

    def _on_row_menu_clicked(self, button, list_item):
        self._popup_context_menu(list_item, button)

    def get_selected(self) -> FileItem | None:
        return self.selection.get_selected_item()

    # ------------------------------------------------------------ drag & drop
    def _on_drag_prepare(self, source, x, y, list_item):
        item: FileItem = list_item.get_item()
        if item is None:
            return None
        try:
            file_list = Gdk.FileList.new_from_list([item.gfile])
            return Gdk.ContentProvider.new_for_value(file_list)
        except Exception:
            return Gdk.ContentProvider.new_for_value(item.uri)

    def _setup_drop_target(self):
        drop = Gtk.DropTarget.new(Gdk.FileList,
                                  Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

    def _on_drop(self, target, value, x, y):
        if not isinstance(value, Gdk.FileList):
            return False
        files = value.get_files()
        drop_obj = target.get_current_drop()
        move = True
        if drop_obj:
            move = bool(drop_obj.get_actions() & Gdk.DragAction.MOVE)
        # non "droppare" una cartella dentro sé stessa
        files = [f for f in files if not f.equal(self.directory)]
        if files:
            self.emit("files-dropped", files, move)
        return True
