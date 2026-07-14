"""Finestra principale."""
import json
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import fileops  # noqa: E402
from .computer import ComputerView  # noqa: E402
from .miller import MillerView  # noqa: E402
from .models import FileItem  # noqa: E402
from .pathbar import PathBar  # noqa: E402
from .preview import PreviewPanel  # noqa: E402
from .sidebar import Sidebar  # noqa: E402

CSS = """
/* card centrale: la classe "view" (aggiunta dal codice) fornisce lo sfondo
   dell'area contenuti del tema, come la lista file di Nautilus */
.content-pane {
  border-radius: 25px;
  /* schiarisce lo sfondo del tema: visibile nei temi scuri,
     invisibile su sfondi già chiari */
  background-image: linear-gradient(alpha(white, 0.07), alpha(white, 0.07));
}
/* le listview non devono coprire lo sfondo della card */
.content-pane listview {
  background: transparent;
}
.miller-column { border-right: 1px solid alpha(currentColor, 0.12); }

/* pulsantino menu (⋯) sulle righe cartella */
.row-menu-button {
  padding: 0;
  min-width: 24px;
  min-height: 24px;
  opacity: 0.55;
}
.row-menu-button:hover { opacity: 1; }

/* chip dei preferiti nella vista Computer */
.fav-chip {
  padding: 6px 14px;
  border-radius: 9999px;
}

/* maniglia di ridimensionamento colonna */
.column-handle { background: transparent; }
.column-handle:hover { background: alpha(currentColor, 0.15); }

/* separatori dei paned invisibili (restano trascinabili) */
paned > separator,
paned > separator.wide {
  background-color: transparent;
  background-image: none;
  border: none;
  box-shadow: none;
  opacity: 0;
}

/* path bar */
.path-bar-segment { padding: 2px 8px; min-height: 26px; }
.path-bar-current label { font-weight: bold; }
"""


STATE_FILE = os.path.join(GLib.get_user_config_dir(),
                          "millnautilus", "state.json")


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        state = self._load_state()
        super().__init__(**kwargs, title="Millnautilus",
                         default_width=state.get("width", 1200),
                         default_height=state.get("height", 720))
        self._load_css()

        # clipboard interna: (list[Gio.File], cut)
        self._clipboard: tuple[list[Gio.File], bool] | None = None
        # elemento su cui è stato aperto il menu contestuale
        self._context_item: FileItem | None = None
        self._context_column = None

        self._build_ui()
        self._add_actions()
        self._apply_state(state)
        self.connect("close-request", self._on_close_request)

        self.show_computer()

    # ------------------------------------------------------------ stato
    @staticmethod
    def _load_state() -> dict:
        try:
            with open(STATE_FILE, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _apply_state(self, state: dict):
        if state.get("maximized"):
            self.maximize()
        if "sidebar_position" in state:
            self.paned.set_position(state["sidebar_position"])
        if not state.get("panel_visible", True):
            self.panel_toggle.set_active(False)

    def _on_close_request(self, *_):
        width, height = self.get_default_size()
        state = {
            "width": width,
            "height": height,
            "maximized": self.is_maximized(),
            "sidebar_position": self.paned.get_position(),
            "panel_visible": self.panel_toggle.get_active(),
        }
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
        except OSError:
            pass
        return False  # prosegui con la chiusura

    # ------------------------------------------------------------ UI
    def _load_css(self):
        provider = Gtk.CssProvider()
        try:
            provider.load_from_string(CSS)  # GTK >= 4.12
        except AttributeError:
            provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def _build_ui(self):
        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        # paned esterno: sidebar | contenuto (bordo trascinabile)
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL,
                               position=230)
        self.toast_overlay.set_child(self.paned)

        # --- sidebar
        self.sidebar = Sidebar()
        self.sidebar.connect("location-selected",
                             lambda _s, f: self.navigate_to(f))
        sidebar_toolbar = Adw.ToolbarView()
        sidebar_header = Adw.HeaderBar()
        sidebar_header.set_title_widget(
            Adw.WindowTitle(title="Millnautilus"))
        sidebar_toolbar.add_top_bar(sidebar_header)
        sidebar_toolbar.set_content(self.sidebar)
        sidebar_toolbar.set_size_request(170, -1)
        self.sidebar_pane = sidebar_toolbar
        self.paned.set_start_child(sidebar_toolbar)
        self.paned.set_shrink_start_child(False)
        self.paned.set_resize_start_child(False)

        # --- contenuto
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        self.pathbar = PathBar()
        self.pathbar.connect("navigate", lambda _pb, f: self.navigate_to(f))
        header.set_title_widget(self.pathbar)

        sidebar_btn = Gtk.ToggleButton(icon_name="sidebar-show-symbolic",
                                       active=True,
                                       tooltip_text="Mostra/nascondi sidebar")
        sidebar_btn.connect(
            "toggled",
            lambda b: self.sidebar_pane.set_visible(b.get_active()))
        header.pack_start(sidebar_btn)

        up_btn = Gtk.Button(icon_name="go-up-symbolic",
                            tooltip_text="Cartella superiore")
        up_btn.connect("clicked", self._on_go_up)
        header.pack_start(up_btn)

        # toggle preview / info / visibilità pannello: pulsanti circolari
        self.preview_toggle = Gtk.ToggleButton(
            icon_name="image-x-generic-symbolic", active=True,
            tooltip_text="Anteprima", css_classes=["circular"])
        self.info_toggle = Gtk.ToggleButton(
            icon_name="dialog-information-symbolic", group=self.preview_toggle,
            tooltip_text="Informazioni", css_classes=["circular"])
        self.panel_toggle = Gtk.ToggleButton(
            icon_name=self._panel_icon_name(), active=True,
            tooltip_text="Mostra/nascondi pannello laterale",
            css_classes=["circular"])
        toggle_box = Gtk.Box(spacing=6)
        toggle_box.append(self.info_toggle)
        toggle_box.append(self.preview_toggle)
        toggle_box.append(self.panel_toggle)
        header.pack_end(toggle_box)
        self.preview_toggle.connect("toggled", self._on_mode_toggled)
        self.panel_toggle.connect("toggled", self._on_panel_toggled)

        menu = Gio.Menu()
        menu.append("Mostra file nascosti", "win.show-hidden")
        menu.append("Nuova cartella…", "win.new-folder")
        menu.append("Informazioni su Millnautilus", "app.about")
        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                  menu_model=menu)
        header.pack_end(menu_btn)

        toolbar.add_top_bar(header)

        self.miller = MillerView()
        self.miller.connect("selection-changed", self._on_selection_changed)
        self.miller.connect("location-changed", self._on_location_changed)
        self.miller.connect("file-activated", self._on_file_activated)
        self.miller.connect("files-dropped", self._on_files_dropped)

        pane = Gtk.Box(css_classes=["content-pane", "view"],
                       margin_top=12, margin_bottom=12,
                       margin_start=12, margin_end=6, hexpand=True)
        pane.set_overflow(Gtk.Overflow.HIDDEN)
        pane.set_size_request(280, -1)

        self.computer = ComputerView()
        self.computer.connect("location-selected",
                              lambda _c, f: self.navigate_to(f))
        self.view_stack = Gtk.Stack(hexpand=True)
        self.view_stack.add_named(self.miller, "miller")
        self.view_stack.add_named(self.computer, "computer")
        pane.append(self.view_stack)
        self.content_pane = pane

        self.preview = PreviewPanel()
        self.preview.connect("step",
                             lambda _p, delta: self.miller.step_selection(delta))
        self.preview.set_margin_top(12)
        self.preview.set_margin_bottom(12)
        self.preview.set_margin_end(12)
        self.preview.set_margin_start(6)

        # paned interno: colonne | preview (bordo trascinabile)
        content_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        content_paned.set_start_child(pane)
        content_paned.set_resize_start_child(True)
        content_paned.set_shrink_start_child(False)
        content_paned.set_end_child(self.preview)
        content_paned.set_resize_end_child(False)
        content_paned.set_shrink_end_child(False)

        toolbar.set_content(content_paned)
        self.paned.set_end_child(toolbar)
        self.paned.set_shrink_end_child(False)

    # ------------------------------------------------------------ azioni
    def _add_actions(self):
        app = self.get_application()
        actions = [
            ("copy", self._on_copy, ["<Ctrl>c"]),
            ("cut", self._on_cut, ["<Ctrl>x"]),
            ("paste", self._on_paste, ["<Ctrl>v"]),
            ("rename", self._on_rename, ["F2"]),
            ("trash", self._on_trash, ["Delete"]),
            ("new-folder", self._on_new_folder, ["<Ctrl><Shift>n"]),
            ("open-item", self._on_open_item, None),
            ("open-with", self._on_open_with, None),
            ("open-new-window", self._on_open_new_window, ["<Ctrl>n"]),
            ("copy-path", self._on_copy_path, None),
            ("properties", self._on_properties, ["<Alt>Return"]),
            ("bookmark", self._on_bookmark, None),
            ("reload", lambda *_: self.miller.reload_all(), ["<Ctrl>r", "F5"]),
            ("edit-location", lambda *_: self.pathbar.start_edit(),
             ["<Ctrl>l"]),
        ]
        for name, callback, accels in actions:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
            if accels:
                app.set_accels_for_action(f"win.{name}", accels)

        show_hidden = Gio.SimpleAction.new_stateful(
            "show-hidden", None, GLib.Variant.new_boolean(False))
        show_hidden.connect("change-state", self._on_show_hidden)
        self.add_action(show_hidden)
        app.set_accels_for_action("win.show-hidden", ["<Ctrl>h"])

    # ------------------------------------------------------------ helpers
    def show_toast(self, message: str):
        self.toast_overlay.add_toast(Adw.Toast(title=message))

    def set_context_item(self, item: FileItem, column):
        self._context_item = item
        self._context_column = column

    def _target_item(self) -> FileItem | None:
        return self._context_item or self.miller.get_selected()

    def _target_dir(self) -> Gio.File | None:
        item = self._target_item()
        if item and item.is_dir:
            return item.gfile
        return self.miller.current_dir

    def navigate_to(self, gfile: Gio.File):
        self.view_stack.set_visible_child_name("miller")
        self.miller.set_root(gfile)

    def show_computer(self):
        """Mostra la panoramica risorse in stile "My Computer"."""
        self.computer.refresh()
        self.view_stack.set_visible_child_name("computer")
        self.pathbar.set_placeholder("Computer")
        self.set_title("Computer")
        self.preview.set_file(None)
        self.preview.set_position(0, 0)

    def reveal(self, gfile: Gio.File, info: bool = False):
        """Mostra la cartella genitore con `gfile` selezionato (D-Bus)."""
        self.miller.reveal(gfile)
        if info:
            self.info_toggle.set_active(True)
        else:
            self.preview_toggle.set_active(True)

    def _after_op(self, error, message="Fatto"):
        if error:
            self.show_toast(error)
        else:
            self.show_toast(message)
        self.miller.reload_all()
        self.sidebar.refresh()
        return False

    # ------------------------------------------------------------ callbacks
    def _on_selection_changed(self, _miller, item):
        self._context_item = None
        self.preview.set_file(item)
        self.preview.set_position(*self.miller.selection_info())

    def _on_location_changed(self, _miller, gfile: Gio.File):
        self.pathbar.set_location(gfile)
        self.set_title(gfile.get_basename() or gfile.get_uri())

    def _on_file_activated(self, _miller, item: FileItem):
        launcher = Gtk.FileLauncher(file=item.gfile)
        launcher.launch(self, None, self._on_launch_done)

    def _on_launch_done(self, launcher, result):
        try:
            launcher.launch_finish(result)
        except GLib.Error as err:
            self.show_toast(f"Impossibile aprire: {err.message}")

    def _on_go_up(self, _btn):
        if self.miller.root:
            parent = self.miller.root.get_parent()
            if parent:
                self.navigate_to(parent)

    def _panel_icon_name(self) -> str:
        """Prima icona disponibile nel tema per 'pannello destro'."""
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for name in ("sidebar-show-right-symbolic",
                     "view-sidebar-end-symbolic",
                     "view-right-pane-symbolic"):
            if theme.has_icon(name):
                return name
        return "view-paged-symbolic"

    def _on_mode_toggled(self, toggle):
        self.preview.set_mode("preview" if toggle.get_active() else "info")
        # cambiare modalità riapre il pannello se era nascosto
        if not self.panel_toggle.get_active():
            self.panel_toggle.set_active(True)

    def _on_panel_toggled(self, toggle):
        visible = toggle.get_active()
        self.preview.set_visible(visible)
        # a pannello nascosto il margine destro pareggia gli altri (12px)
        self.content_pane.set_margin_end(6 if visible else 12)

    def _on_show_hidden(self, action, value):
        action.set_state(value)
        self.miller.set_show_hidden(value.get_boolean())

    # --- clipboard
    def _on_copy(self, *_):
        item = self._target_item()
        if item:
            self._clipboard = ([item.gfile], False)
            self.show_toast(f"Copiato: {item.name}")

    def _on_cut(self, *_):
        item = self._target_item()
        if item:
            self._clipboard = ([item.gfile], True)
            self.show_toast(f"Tagliato: {item.name}")

    def _on_paste(self, *_):
        if not self._clipboard:
            self.show_toast("Nessun elemento da incollare")
            return
        files, cut = self._clipboard
        dest = self._target_dir()
        if dest is None:
            return
        if cut:
            self._clipboard = None
        fileops.transfer(files, dest, move=cut,
                         on_done=lambda err: self._after_op(
                             err, "Spostato" if cut else "Copiato"))

    # --- operazioni
    def _on_trash(self, *_):
        item = self._target_item()
        if item:
            fileops.trash([item.gfile],
                          lambda err: self._after_op(err, "Spostato nel cestino"))

    def _on_rename(self, *_):
        item = self._target_item()
        if not item:
            return
        dialog = Adw.AlertDialog(heading="Rinomina",
                                 body=f"Nuovo nome per «{item.name}»")
        entry = Gtk.Entry(text=item.name, activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Annulla")
        dialog.add_response("rename", "Rinomina")
        dialog.set_response_appearance("rename",
                                       Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")

        def on_response(_dlg, response):
            new_name = entry.get_text().strip()
            if response == "rename" and new_name and new_name != item.name:
                fileops.rename(item.gfile, new_name,
                               lambda err: self._after_op(err, "Rinominato"))

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_new_folder(self, *_):
        dest = self.miller.current_dir
        if dest is None:
            return
        dialog = Adw.AlertDialog(heading="Nuova cartella")
        entry = Gtk.Entry(placeholder_text="Nome cartella",
                          activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Annulla")
        dialog.add_response("create", "Crea")
        dialog.set_response_appearance("create",
                                       Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")

        def on_response(_dlg, response):
            name = entry.get_text().strip()
            if response == "create" and name:
                fileops.new_folder(dest, name,
                                   lambda err: self._after_op(err, "Creata"))

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_open_item(self, *_):
        item = self._target_item()
        if item:
            self._on_file_activated(None, item)

    def _on_open_with(self, *_):
        item = self._target_item()
        if not item:
            return
        launcher = Gtk.FileLauncher(file=item.gfile)
        try:
            launcher.set_always_ask(True)  # GTK >= 4.12
        except AttributeError:
            pass
        launcher.launch(self, None, self._on_launch_done)

    def _on_open_new_window(self, *_):
        item = self._target_item()
        gfile = (item.gfile if item and item.is_dir
                 else self._target_dir())
        if gfile is None:
            return
        win = MainWindow(application=self.get_application())
        win.present()
        win.navigate_to(gfile)

    def _on_copy_path(self, *_):
        item = self._target_item()
        if item:
            self.get_clipboard().set(item.path_str)
            self.show_toast("Percorso copiato")

    def _on_properties(self, *_):
        self.panel_toggle.set_active(True)
        self.info_toggle.set_active(True)
        # forza il refresh se la modalità info era già attiva
        self.preview.set_mode("info")

    def _on_bookmark(self, *_):
        item = self._target_item()
        if item and item.is_dir:
            Sidebar.add_bookmark(item.gfile, item.name)
            self.show_toast(f"Aggiunto ai preferiti: {item.name}")
        else:
            self.show_toast("Seleziona una cartella")

    def _on_files_dropped(self, _miller, files, dest_dir, move):
        fileops.transfer(list(files), dest_dir, move=move,
                         on_done=lambda err: self._after_op(
                             err, "Spostato" if move else "Copiato"))
