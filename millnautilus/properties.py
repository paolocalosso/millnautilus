"""Finestra di dialogo con le proprietà di un elemento."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .models import FileItem  # noqa: E402


class PropertiesDialog(Adw.Dialog):
    """Dialogo proprietà per uno o più elementi selezionati."""

    def __init__(self, items: list[FileItem]):
        super().__init__(title="Proprietà", content_width=440,
                         content_height=560)
        self._items = items
        self._cancellable = Gio.Cancellable()
        self._icon_theme: Gtk.IconTheme | None = None

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        scroller = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                      margin_top=18, margin_bottom=18,
                      margin_start=18, margin_end=18)
        box.append(self._build_header())
        box.append(self._build_list())
        scroller.set_child(box)
        toolbar.set_content(scroller)
        self.set_child(toolbar)

        self.connect("closed", lambda *_: self._cancellable.cancel())

    # ------------------------------------------------------------ intestazione
    def _build_header(self) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        icon = Gtk.Image(pixel_size=96)
        if len(self._items) == 1:
            icon.set_from_paintable(self._lookup_icon(self._items[0], 256))
        else:
            icon.set_from_icon_name("edit-copy-symbolic")
        name = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        name.add_css_class("title-2")
        name.set_text(self._items[0].name if len(self._items) == 1
                      else f"{len(self._items)} elementi selezionati")
        box.append(icon)
        box.append(name)
        return box

    def _lookup_icon(self, item: FileItem, size: int):
        if self._icon_theme is None:
            self._icon_theme = Gtk.IconTheme.get_for_display(
                self.get_display())
        return self._icon_theme.lookup_by_gicon(
            item.info.get_icon(), size, self.get_scale_factor(),
            self.get_direction(), 0)

    # ------------------------------------------------------------ proprietà
    def _build_list(self) -> Gtk.ListBox:
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        if len(self._items) == 1:
            item = self._items[0]
            rows = [
                ("Tipo", Gio.content_type_get_description(item.content_type)
                 or item.content_type),
                ("Dimensione", item.size_str),
                ("Percorso", item.path_str),
                ("Modificato", item.modified_str),
                ("Creato", item.created_str),
                ("Permessi", item.permissions_str),
                ("Proprietario", item.owner_str),
            ]
        else:
            total = sum(i.size for i in self._items if not i.is_dir)
            n_dirs = sum(1 for i in self._items if i.is_dir)
            rows = [
                ("Elementi", f"{len(self._items)} "
                             f"({n_dirs} cartelle, "
                             f"{len(self._items) - n_dirs} file)"),
                ("Dimensione totale file", GLib.format_size(total)),
            ]

        for title, value in rows:
            row = Adw.ActionRow(title=title, subtitle=value or "—",
                                subtitle_selectable=True)
            row.add_css_class("property")
            listbox.append(row)

        for item in (i for i in self._items if i.is_dir):
            if len(self._items) == 1:
                self._count_children(item, listbox)
            break
        return listbox

    def _count_children(self, item: FileItem, listbox: Gtk.ListBox):
        row = Adw.ActionRow(title="Contenuto", subtitle="Conteggio…")
        row.add_css_class("property")
        listbox.append(row)

        def on_enumerated(gfile, result):
            try:
                enumerator = gfile.enumerate_children_finish(result)
            except GLib.Error:
                row.set_subtitle("—")
                return
            count = 0

            def on_next(en, res):
                nonlocal count
                try:
                    infos = en.next_files_finish(res)
                except GLib.Error:
                    return
                if not infos:
                    row.set_subtitle(f"{count} elementi")
                    en.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
                    return
                count += len(infos)
                en.next_files_async(500, GLib.PRIORITY_LOW,
                                    self._cancellable, on_next)

            enumerator.next_files_async(500, GLib.PRIORITY_LOW,
                                        self._cancellable, on_next)

        item.gfile.enumerate_children_async(
            "standard::name", Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_LOW, self._cancellable, on_enumerated)
