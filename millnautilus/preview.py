"""Pannello destro: preview del file oppure info dettagliate."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject, Gtk  # noqa: E402

from .models import FileItem  # noqa: E402

PANEL_WIDTH = 300
TEXT_PREVIEW_BYTES = 64 * 1024

TEXT_LIKE = ("application/json", "application/xml", "application/x-shellscript",
             "application/javascript", "application/x-yaml")


class PreviewPanel(Gtk.Box):
    """Stack con due pagine: 'preview' e 'info', selezionabili dall'esterno."""

    __gsignals__ = {
        # richiesta di scorrere la selezione: delta (+1 / -1)
        "step": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_size_request(PANEL_WIDTH, -1)
        self._item: FileItem | None = None
        self._cancellable = Gio.Cancellable()
        self._icon_theme: Gtk.IconTheme | None = None

        self.stack = Gtk.Stack(vexpand=True)
        self.stack.add_named(self._build_placeholder(), "empty")
        self.stack.add_named(self._build_preview_page(), "preview")
        self.stack.add_named(self._build_info_page(), "info")
        self.append(self.stack)
        self.append(self._build_nav_bar())

        self.mode = "preview"  # o "info"

    def _build_nav_bar(self) -> Gtk.Box:
        self.nav_bar = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER,
                               margin_top=6, margin_bottom=6)
        self.prev_btn = Gtk.Button(icon_name="go-previous-symbolic",
                                   tooltip_text="Elemento precedente",
                                   css_classes=["flat", "circular"])
        self.prev_btn.connect("clicked", lambda *_: self.emit("step", -1))
        self.next_btn = Gtk.Button(icon_name="go-next-symbolic",
                                   tooltip_text="Elemento successivo",
                                   css_classes=["flat", "circular"])
        self.next_btn.connect("clicked", lambda *_: self.emit("step", 1))
        self.position_label = Gtk.Label()
        self.position_label.add_css_class("dim-label")
        self.position_label.add_css_class("caption")

        self.nav_bar.append(self.prev_btn)
        self.nav_bar.append(self.position_label)
        self.nav_bar.append(self.next_btn)
        self.nav_bar.set_visible(False)
        return self.nav_bar

    def set_position(self, index: int, total: int):
        """Aggiorna indicatore e sensibilità frecce (index 1-based)."""
        if total <= 0 or index <= 0:
            self.nav_bar.set_visible(False)
            return
        self.nav_bar.set_visible(True)
        self.position_label.set_text(f"{index} / {total}")
        self.prev_btn.set_sensitive(index > 1)
        self.next_btn.set_sensitive(index < total)

    # ------------------------------------------------------------ API
    def set_mode(self, mode: str):
        self.mode = mode
        self._refresh()

    def set_file(self, item: FileItem | None):
        self._cancellable.cancel()
        self._cancellable = Gio.Cancellable()
        self._item = item
        self._refresh()

    def _refresh(self):
        if self._item is None:
            self.stack.set_visible_child_name("empty")
        elif self.mode == "info":
            self._fill_info(self._item)
            self.stack.set_visible_child_name("info")
        else:
            self._fill_preview(self._item)
            self.stack.set_visible_child_name("preview")

    # ------------------------------------------------------------ pagine
    def _build_placeholder(self):
        return Adw.StatusPage(icon_name="view-paged-symbolic",
                              title="Nessuna selezione",
                              description="Seleziona un file per vederne "
                                          "l'anteprima o le informazioni")

    def _build_preview_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                      margin_top=12, margin_bottom=12,
                      margin_start=12, margin_end=12)
        self.preview_picture = Gtk.Picture(can_shrink=True, vexpand=True,
                                           content_fit=Gtk.ContentFit.CONTAIN)
        self.preview_icon = Gtk.Image(pixel_size=128, vexpand=True,
                                      valign=Gtk.Align.CENTER)
        self.preview_text = Gtk.TextView(editable=False, monospace=True,
                                         wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                         cursor_visible=False)
        text_scroller = Gtk.ScrolledWindow(vexpand=True)
        text_scroller.set_child(self.preview_text)
        text_scroller.add_css_class("card")

        self.preview_stack = Gtk.Stack(vexpand=True)
        self.preview_stack.add_named(self.preview_picture, "picture")
        self.preview_stack.add_named(text_scroller, "text")
        self.preview_stack.add_named(self.preview_icon, "icon")

        self.preview_name = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.preview_name.add_css_class("heading")
        self.preview_subtitle = Gtk.Label()
        self.preview_subtitle.add_css_class("dim-label")
        self.preview_subtitle.add_css_class("caption")

        box.append(self.preview_stack)
        box.append(self.preview_name)
        box.append(self.preview_subtitle)
        return box

    def _build_info_page(self):
        scroller = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      margin_top=16, margin_bottom=16,
                      margin_start=12, margin_end=12)
        self.info_icon = Gtk.Image(pixel_size=64)
        self.info_name = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.info_name.add_css_class("title-3")

        self.info_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.info_list.add_css_class("boxed-list")

        box.append(self.info_icon)
        box.append(self.info_name)
        box.append(self.info_list)
        scroller.set_child(box)
        return scroller

    # ------------------------------------------------------------ preview
    def _fill_preview(self, item: FileItem):
        self.preview_name.set_text(item.name)
        self.preview_subtitle.set_text(
            f"{item.content_type} · {item.size_str}")
        ctype = item.content_type

        if ctype.startswith("image/"):
            self.preview_picture.set_file(item.gfile)
            self.preview_stack.set_visible_child_name("picture")
        elif ctype.startswith("text/") or ctype in TEXT_LIKE:
            self._load_text(item)
        elif item.thumbnail_path:
            # documenti (PDF, ODT…): usa la thumbnail generata dal sistema
            self.preview_picture.set_filename(item.thumbnail_path)
            self.preview_stack.set_visible_child_name("picture")
        else:
            self.preview_icon.set_from_paintable(
                self._lookup_icon(item, 256))
            self.preview_stack.set_visible_child_name("icon")

    def _lookup_icon(self, item: FileItem, size: int):
        """Lookup a taglia grande: il tema fornisce la variante scalable."""
        if self._icon_theme is None:
            self._icon_theme = Gtk.IconTheme.get_for_display(
                self.get_display())
        return self._icon_theme.lookup_by_gicon(
            item.info.get_icon(), size, self.get_scale_factor(),
            self.get_direction(), 0)

    def _load_text(self, item: FileItem):
        buffer = self.preview_text.get_buffer()
        buffer.set_text("Caricamento…")
        self.preview_stack.set_visible_child_name("text")
        item.gfile.read_async(GLib.PRIORITY_DEFAULT, self._cancellable,
                              self._on_stream_ready, buffer)

    def _on_stream_ready(self, gfile, result, buffer):
        try:
            stream = gfile.read_finish(result)
        except GLib.Error as err:
            buffer.set_text(f"Impossibile leggere il file:\n{err.message}")
            return
        stream.read_bytes_async(TEXT_PREVIEW_BYTES, GLib.PRIORITY_DEFAULT,
                                self._cancellable, self._on_bytes_read, buffer)

    def _on_bytes_read(self, stream, result, buffer):
        try:
            data = stream.read_bytes_finish(result)
        except GLib.Error as err:
            buffer.set_text(f"Errore di lettura:\n{err.message}")
            return
        finally:
            stream.close_async(GLib.PRIORITY_DEFAULT, None, None, None)
        text = data.get_data().decode("utf-8", errors="replace")
        if data.get_size() >= TEXT_PREVIEW_BYTES:
            text += "\n\n… (anteprima troncata)"
        buffer.set_text(text)

    # ------------------------------------------------------------ info
    def _fill_info(self, item: FileItem):
        self.info_icon.set_from_paintable(self._lookup_icon(item, 128))
        self.info_name.set_text(item.name)

        while (row := self.info_list.get_row_at_index(0)) is not None:
            self.info_list.remove(row)

        rows = [
            ("Tipo", Gio.content_type_get_description(item.content_type)
             or item.content_type),
            ("Dimensione", item.size_str),
            ("Modificato", item.modified_str),
            ("Permessi", item.permissions_str),
            ("Proprietario", item.owner_str),
            ("Percorso", item.path_str),
        ]
        for title, value in rows:
            row = Adw.ActionRow(title=title, subtitle=value or "—",
                                subtitle_selectable=True)
            row.add_css_class("property")
            self.info_list.append(row)

        if item.is_dir:
            self._count_children(item)

    def _count_children(self, item: FileItem):
        row = Adw.ActionRow(title="Contenuto", subtitle="Conteggio…")
        row.add_css_class("property")
        self.info_list.append(row)

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
