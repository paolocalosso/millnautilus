"""Sidebar: posizioni, dispositivi, rete/SFTP, preferiti."""
import os
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

BOOKMARKS_FILE = os.path.join(GLib.get_user_config_dir(),
                              "gtk-3.0", "bookmarks")


def _xdg(directory) -> str | None:
    return GLib.get_user_special_dir(directory)


class SidebarRow(Gtk.ListBoxRow):
    def __init__(self, icon_name: str, title: str, gfile: Gio.File | None,
                 volume: Gio.Volume | None = None, action: str | None = None,
                 mount: Gio.Mount | None = None):
        super().__init__()
        self.gfile = gfile
        self.volume = volume
        self.mount = mount
        self.title = title
        self.section = None
        self.action = action  # es. "connect-sftp"
        box = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6,
                      margin_start=10, margin_end=10)
        box.append(Gtk.Image.new_from_icon_name(icon_name))
        label = Gtk.Label(label=title, xalign=0,
                          ellipsize=Pango.EllipsizeMode.END)
        box.append(label)
        self.set_child(box)


class Sidebar(Gtk.Box):
    __gsignals__ = {
        # naviga verso Gio.File
        "location-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        self.listbox.connect("row-activated", self._on_row_activated)
        self.listbox.set_header_func(self._header_func)

        scroller = Gtk.ScrolledWindow(vexpand=True,
                                      hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.listbox)
        self.append(scroller)

        self.monitor = Gio.VolumeMonitor.get()
        for signal in ("volume-added", "volume-removed", "mount-added",
                       "mount-removed", "drive-connected",
                       "drive-disconnected"):
            self.monitor.connect(signal, lambda *_: self.refresh())

        self._bookmark_monitor = None
        self._watch_bookmarks()

        self._context_row: SidebarRow | None = None
        self._setup_actions()
        self.refresh()

    # ------------------------------------------------------------ azioni menu
    def _setup_actions(self):
        group = Gio.SimpleActionGroup()
        for name, callback in [
            ("open", self._ctx_open),
            ("bookmark-add", self._ctx_bookmark_add),
            ("bookmark-remove", self._ctx_bookmark_remove),
            ("unmount", self._ctx_unmount),
            ("copy-path", self._ctx_copy_path),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            group.add_action(action)
        self.insert_action_group("sidebar", group)

    # ------------------------------------------------------------ costruzione
    def refresh(self):
        while (row := self.listbox.get_row_at_index(0)) is not None:
            self.listbox.remove(row)

        # Posizioni principali
        computer_row = SidebarRow("computer-symbolic", "Computer", None,
                                  action="show-computer")
        computer_row.section = "Posizioni"
        self.listbox.append(computer_row)

        home = Gio.File.new_for_path(GLib.get_home_dir())
        self._add("user-home-symbolic", "Home", home, section="Posizioni")
        for icon, label, xdg_dir in [
            ("folder-documents-symbolic", "Documenti",
             GLib.UserDirectory.DIRECTORY_DOCUMENTS),
            ("folder-download-symbolic", "Scaricati",
             GLib.UserDirectory.DIRECTORY_DOWNLOAD),
            ("folder-pictures-symbolic", "Immagini",
             GLib.UserDirectory.DIRECTORY_PICTURES),
            ("folder-music-symbolic", "Musica",
             GLib.UserDirectory.DIRECTORY_MUSIC),
            ("folder-videos-symbolic", "Video",
             GLib.UserDirectory.DIRECTORY_VIDEOS),
        ]:
            path = _xdg(xdg_dir)
            if path and os.path.isdir(path):
                self._add(icon, label, Gio.File.new_for_path(path),
                          section="Posizioni")
        self._add("user-trash-symbolic", "Cestino",
                  Gio.File.new_for_uri("trash:///"), section="Posizioni")
        self._add("drive-harddisk-symbolic", "File system",
                  Gio.File.new_for_path("/"), section="Posizioni")

        # Dispositivi (volumi montabili + mount attivi)
        seen_mounts = set()
        for volume in self.monitor.get_volumes():
            mount = volume.get_mount()
            if mount:
                seen_mounts.add(mount.get_root().get_uri())
            icon = "drive-removable-media-symbolic"
            row = SidebarRow(icon, volume.get_name(),
                             mount.get_root() if mount else None,
                             volume=volume, mount=mount)
            row.section = "Dispositivi"
            self._attach_menu(row)
            self.listbox.append(row)
        for mount in self.monitor.get_mounts():
            root = mount.get_root()
            if root.get_uri() in seen_mounts:
                continue
            scheme = root.get_uri_scheme() or ""
            icon = ("folder-remote-symbolic" if scheme in
                    ("sftp", "ssh", "smb", "ftp", "dav", "davs", "nfs")
                    else "drive-removable-media-symbolic")
            section = "Rete" if scheme not in ("file", "") else "Dispositivi"
            self._add(icon, mount.get_name(), root, section=section,
                      mount=mount)

        # Rete
        connect_row = SidebarRow("network-server-symbolic",
                                 "Connetti al server…", None,
                                 action="connect-server")
        connect_row.section = "Rete"
        self.listbox.append(connect_row)

        # Preferiti
        for uri, label in self._read_bookmarks():
            self._add("starred-symbolic", label, Gio.File.new_for_uri(uri),
                      section="Preferiti")

    def _add(self, icon: str, title: str, gfile: Gio.File, section: str,
             mount: Gio.Mount | None = None):
        row = SidebarRow(icon, title, gfile, mount=mount)
        row.section = section
        self._attach_menu(row)
        self.listbox.append(row)

    # ------------------------------------------------------------ menu ctx
    def _attach_menu(self, row: SidebarRow):
        gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture.connect("pressed", self._on_row_right_click, row)
        row.add_controller(gesture)

    def _on_row_right_click(self, gesture, n_press, x, y, row: SidebarRow):
        self._context_row = row
        menu = Gio.Menu()

        section1 = Gio.Menu()
        if row.gfile is not None:
            section1.append("Apri", "sidebar.open")
            section1.append("Copia percorso", "sidebar.copy-path")
        menu.append_section(None, section1)

        section2 = Gio.Menu()
        if row.section == "Preferiti":
            section2.append("Rimuovi dai preferiti", "sidebar.bookmark-remove")
        elif (row.gfile is not None
              and (row.gfile.get_uri_scheme() or "file") != "trash"):
            section2.append("Aggiungi ai preferiti", "sidebar.bookmark-add")
        menu.append_section(None, section2)

        mount = row.mount or (row.volume.get_mount() if row.volume else None)
        if mount is not None and mount.can_unmount():
            section3 = Gio.Menu()
            section3.append("Smonta", "sidebar.unmount")
            menu.append_section(None, section3)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(row)
        popover.set_has_arrow(False)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()

    def _ctx_open(self, *_):
        row = self._context_row
        if row and row.gfile is not None:
            self.emit("location-selected", row.gfile)
        elif row and row.volume is not None:
            self._mount_volume(row.volume)

    def _ctx_copy_path(self, *_):
        row = self._context_row
        if row and row.gfile is not None:
            text = row.gfile.get_path() or row.gfile.get_uri()
            self.get_clipboard().set(text)
            self._toast("Percorso copiato")

    def _ctx_bookmark_add(self, *_):
        row = self._context_row
        if row and row.gfile is not None:
            self.add_bookmark(row.gfile, row.title)
            self._toast(f"Aggiunto ai preferiti: {row.title}")
            self.refresh()

    def _ctx_bookmark_remove(self, *_):
        row = self._context_row
        if row and row.gfile is not None:
            self.remove_bookmark(row.gfile)
            self._toast(f"Rimosso dai preferiti: {row.title}")
            self.refresh()

    def _ctx_unmount(self, *_):
        row = self._context_row
        if row is None:
            return
        mount = row.mount or (row.volume.get_mount() if row.volume else None)
        if mount is None:
            return
        op = Gtk.MountOperation.new(self.get_root())

        def on_unmounted(m, result):
            try:
                m.unmount_with_operation_finish(result)
                self._toast(f"Smontato: {row.title}")
            except GLib.Error as err:
                self._toast(f"Smontaggio fallito: {err.message}")
            self.refresh()

        mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, op,
                                     None, on_unmounted)

    def _header_func(self, row, before):
        section = getattr(row, "section", None)
        before_section = getattr(before, "section", None) if before else None
        if section and section != before_section:
            label = Gtk.Label(label=section, xalign=0,
                              margin_start=12, margin_top=10, margin_bottom=4)
            label.add_css_class("dim-label")
            label.add_css_class("caption-heading")
            row.set_header(label)
        else:
            row.set_header(None)

    # ------------------------------------------------------------ preferiti
    @staticmethod
    def _read_bookmarks():
        bookmarks = []
        try:
            with open(BOOKMARKS_FILE, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(" ", 1)
                    uri = parts[0]
                    label = (parts[1] if len(parts) > 1
                             else GLib.uri_unescape_string(
                                 uri.rsplit("/", 1)[-1], None) or uri)
                    bookmarks.append((uri, label))
        except OSError:
            pass
        return bookmarks

    def _watch_bookmarks(self):
        gfile = Gio.File.new_for_path(BOOKMARKS_FILE)
        try:
            self._bookmark_monitor = gfile.monitor_file(
                Gio.FileMonitorFlags.NONE, None)
            self._bookmark_monitor.connect("changed",
                                           lambda *_: self.refresh())
        except GLib.Error:
            pass

    @staticmethod
    def add_bookmark(gfile: Gio.File, label: str):
        os.makedirs(os.path.dirname(BOOKMARKS_FILE), exist_ok=True)
        line = f"{gfile.get_uri()} {label}\n"
        try:
            with open(BOOKMARKS_FILE, encoding="utf-8") as fh:
                if any(l.split(" ", 1)[0] == gfile.get_uri()
                       for l in fh if l.strip()):
                    return
        except OSError:
            pass
        with open(BOOKMARKS_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)

    @staticmethod
    def remove_bookmark(gfile: Gio.File):
        uri = gfile.get_uri()
        try:
            with open(BOOKMARKS_FILE, encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            return
        kept = [l for l in lines
                if not l.strip() or l.split(" ", 1)[0].strip() != uri]
        with open(BOOKMARKS_FILE, "w", encoding="utf-8") as fh:
            fh.writelines(kept)

    # ------------------------------------------------------------ interazione
    def _on_row_activated(self, listbox, row: SidebarRow):
        if row.action == "connect-server":
            self._connect_server_dialog()
        elif row.action == "show-computer":
            win = self.get_root()
            if hasattr(win, "show_computer"):
                win.show_computer()
        elif row.gfile is not None:
            self.emit("location-selected", row.gfile)
        elif row.volume is not None:
            self._mount_volume(row.volume)

    def _mount_volume(self, volume: Gio.Volume):
        win = self.get_root()
        op = Gtk.MountOperation.new(win)

        def on_mounted(vol, result):
            try:
                vol.mount_finish(result)
            except GLib.Error as err:
                self._toast(f"Mount fallito: {err.message}")
                return
            mount = vol.get_mount()
            if mount:
                self.emit("location-selected", mount.get_root())
            self.refresh()

        volume.mount(Gio.MountMountFlags.NONE, op, None, on_mounted)

    # ------------------------------------------------------------ SFTP
    def _connect_server_dialog(self):
        win = self.get_root()
        dialog = Adw.AlertDialog(
            heading="Connetti al server",
            body="Indirizzo del server (es. sftp://utente@host/percorso)")
        entry = Gtk.Entry(placeholder_text="sftp://utente@host/",
                          activates_default=True)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Annulla")
        dialog.add_response("connect", "Connetti")
        dialog.set_response_appearance("connect",
                                       Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("connect")

        def on_response(dlg, response):
            if response == "connect" and entry.get_text().strip():
                self._mount_uri(entry.get_text().strip())

        dialog.connect("response", on_response)
        dialog.present(win)

    def _mount_uri(self, uri: str):
        gfile = Gio.File.new_for_uri(uri)
        win = self.get_root()
        op = Gtk.MountOperation.new(win)

        def on_mounted(f, result):
            try:
                f.mount_enclosing_volume_finish(result)
            except GLib.Error as err:
                # già montato → naviga comunque
                if err.code != Gio.IOErrorEnum.ALREADY_MOUNTED:
                    self._toast(f"Connessione fallita: {err.message}")
                    return
            self.emit("location-selected", gfile)
            self.refresh()

        gfile.mount_enclosing_volume(Gio.MountMountFlags.NONE, op,
                                     None, on_mounted)

    def _toast(self, message: str):
        win = self.get_root()
        if hasattr(win, "show_toast"):
            win.show_toast(message)
