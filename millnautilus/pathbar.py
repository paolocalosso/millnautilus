"""Path bar stile Nautilus: breadcrumb a pulsanti + modalità editabile."""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gio, GLib, GObject, Gtk  # noqa: E402


class PathBar(Gtk.Stack):
    """Breadcrumb cliccabile; click sullo spazio vuoto (o Ctrl+L) → entry."""

    __gsignals__ = {
        # richiesta di navigazione verso Gio.File
        "navigate": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(hexpand=True,
                         transition_type=Gtk.StackTransitionType.CROSSFADE,
                         transition_duration=120)
        self.add_css_class("path-bar")
        self._location: Gio.File | None = None

        # --- pagina breadcrumb
        outer = Gtk.Box(spacing=2)
        self.buttons_box = Gtk.Box(spacing=2)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_width=True,
            max_content_width=560,
            hexpand=True)
        scroller.set_child(self.buttons_box)
        outer.append(scroller)

        edit_btn = Gtk.Button(icon_name="document-edit-symbolic",
                              tooltip_text="Modifica percorso (Ctrl+L)")
        edit_btn.add_css_class("flat")
        edit_btn.connect("clicked", lambda *_: self.start_edit())
        outer.append(edit_btn)

        # click sullo spazio vuoto della barra → modalità edit
        gesture = Gtk.GestureClick()
        gesture.connect("released", self._on_blank_click)
        outer.add_controller(gesture)

        self.add_named(outer, "buttons")

        # --- pagina entry
        self.entry = Gtk.Entry(width_chars=45, hexpand=True,
                               placeholder_text="Percorso o URI…")
        self.entry.connect("activate", self._on_entry_activate)
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_entry_key)
        self.entry.add_controller(key_ctrl)
        focus_ctrl = Gtk.EventControllerFocus()
        focus_ctrl.connect("leave", lambda *_: self.stop_edit())
        self.entry.add_controller(focus_ctrl)
        self.add_named(self.entry, "entry")

        self.set_visible_child_name("buttons")

    # ------------------------------------------------------------ API
    def set_location(self, gfile: Gio.File):
        self._location = gfile
        self.entry.set_text(gfile.get_path() or gfile.get_uri())
        self._rebuild_buttons(gfile)

    def set_placeholder(self, label: str):
        """Mostra una singola etichetta non navigabile (es. "Computer")."""
        self._location = None
        self.entry.set_text("")
        while (child := self.buttons_box.get_first_child()) is not None:
            self.buttons_box.remove(child)
        placeholder = Gtk.Label(label=label)
        placeholder.add_css_class("heading")
        placeholder.set_margin_start(8)
        placeholder.set_margin_end(8)
        self.buttons_box.append(placeholder)
        self.set_visible_child_name("buttons")

    def start_edit(self):
        self.set_visible_child_name("entry")
        self.entry.grab_focus()
        self.entry.select_region(0, -1)

    def stop_edit(self):
        self.set_visible_child_name("buttons")

    # ------------------------------------------------------------ breadcrumb
    def _rebuild_buttons(self, gfile: Gio.File):
        while (child := self.buttons_box.get_first_child()) is not None:
            self.buttons_box.remove(child)

        # catena di segmenti dalla radice al file corrente
        chain: list[Gio.File] = []
        current = gfile
        home = Gio.File.new_for_path(GLib.get_home_dir())
        while current is not None:
            chain.insert(0, current)
            if current.equal(home):
                break
            current = current.get_parent()

        for i, segment in enumerate(chain):
            btn = Gtk.Button()
            btn.add_css_class("flat")
            btn.add_css_class("path-bar-segment")

            if segment.equal(home):
                content = Gtk.Box(spacing=6)
                content.append(Gtk.Image.new_from_icon_name(
                    "user-home-symbolic"))
                content.append(Gtk.Label(label="Home"))
                btn.set_child(content)
            elif segment.get_parent() is None and segment.get_path() == "/":
                btn.set_child(Gtk.Image.new_from_icon_name(
                    "drive-harddisk-symbolic"))
            else:
                label = segment.get_basename() or self._uri_label(segment)
                btn.set_child(Gtk.Label(label=label))

            if i == len(chain) - 1:
                btn.add_css_class("path-bar-current")

            btn.connect("clicked", self._on_segment_clicked, segment)
            self.buttons_box.append(btn)

            if i < len(chain) - 1:
                sep = Gtk.Label(label="/")
                sep.add_css_class("dim-label")
                self.buttons_box.append(sep)

    @staticmethod
    def _uri_label(gfile: Gio.File) -> str:
        """Etichetta per la radice di un URI remoto (es. sftp)."""
        try:
            uri = GLib.Uri.parse(gfile.get_uri(), GLib.UriFlags.NONE)
            host = uri.get_host()
            scheme = uri.get_scheme()
            if host:
                return f"{scheme}://{host}"
        except GLib.Error:
            pass
        return gfile.get_uri()

    # ------------------------------------------------------------ callbacks
    def _on_segment_clicked(self, _btn, segment: Gio.File):
        self.emit("navigate", segment)

    def _on_blank_click(self, gesture, n_press, x, y):
        # i click sui pulsanti vengono gestiti (e consumati) dai pulsanti;
        # qui arrivano solo i click sullo spazio vuoto
        widget = gesture.get_widget()
        picked = widget.pick(x, y, Gtk.PickFlags.DEFAULT)
        if picked is not None and isinstance(picked, (Gtk.Button, Gtk.Label,
                                                      Gtk.Image)):
            # click su un pulsante o suo contenuto: ignora
            ancestor = picked
            while ancestor is not None and ancestor is not widget:
                if isinstance(ancestor, Gtk.Button):
                    return
                ancestor = ancestor.get_parent()
        self.start_edit()

    def _on_entry_activate(self, entry):
        text = entry.get_text().strip()
        if text:
            gfile = Gio.File.new_for_commandline_arg(text)
            self.emit("navigate", gfile)
        self.stop_edit()

    def _on_entry_key(self, _ctrl, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            if self._location:
                self.entry.set_text(self._location.get_path()
                                    or self._location.get_uri())
            self.stop_edit()
            return True
        return False
