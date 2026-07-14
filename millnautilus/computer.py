"""Vista "Computer": panoramica delle risorse con utilizzo disco."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .sidebar import Sidebar  # noqa: E402

FS_ATTRS = "filesystem::size,filesystem::free"

REMOTE_SCHEMES = ("sftp", "ssh", "smb", "ftp", "dav", "davs", "nfs")


class ComputerView(Gtk.ScrolledWindow):
    """Griglia di card in stile "My Computer"."""

    __gsignals__ = {
        "location-selected": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    def __init__(self):
        super().__init__(hexpand=True, vexpand=True,
                         hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.monitor = Gio.VolumeMonitor.get()
        clamp = Adw.Clamp(maximum_size=1000,
                          margin_top=24, margin_bottom=24,
                          margin_start=20, margin_end=20)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        clamp.set_child(self.box)
        self.set_child(clamp)

    # ------------------------------------------------------------ build
    def refresh(self):
        while (child := self.box.get_first_child()) is not None:
            self.box.remove(child)

        home = Gio.File.new_for_path(GLib.get_home_dir())
        places = [
            self._card("user-home", "Home", gfile=home, usage=True),
            self._card("drive-harddisk", "File system",
                       gfile=Gio.File.new_for_path("/"), usage=True),
            self._card("user-trash", "Cestino",
                       gfile=Gio.File.new_for_uri("trash:///")),
        ]
        self._section("Posizioni", places)

        disks, network = [], []
        seen = set()
        for volume in self.monitor.get_volumes():
            mount = volume.get_mount()
            if mount:
                seen.add(mount.get_root().get_uri())
            disks.append(self._card(
                volume.get_icon(), volume.get_name(),
                gfile=mount.get_root() if mount else None,
                volume=volume, usage=mount is not None,
                subtitle=None if mount else "Non montato"))
        for mount in self.monitor.get_mounts():
            root = mount.get_root()
            if root.get_uri() in seen:
                continue
            scheme = root.get_uri_scheme() or ""
            card = self._card(mount.get_icon(), mount.get_name(),
                              gfile=root, usage=True)
            (network if scheme in REMOTE_SCHEMES else disks).append(card)
        self._section("Dischi", disks)
        self._section("Rete", network)
        self._favorites_section()

    def _favorites_section(self):
        bookmarks = Sidebar._read_bookmarks()
        if not bookmarks:
            return
        label = Gtk.Label(label="Preferiti", xalign=0,
                          margin_top=14, margin_bottom=4)
        label.add_css_class("heading")
        label.add_css_class("dim-label")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                           column_spacing=8, row_spacing=8,
                           homogeneous=False, max_children_per_line=5,
                           min_children_per_line=1)
        for uri, title in bookmarks:
            flow.append(self._favorite_chip(uri, title))
        self.box.append(label)
        self.box.append(flow)

    def _favorite_chip(self, uri: str, title: str) -> Gtk.Button:
        content = Gtk.Box(spacing=8)
        content.append(Gtk.Image.new_from_icon_name("starred-symbolic"))
        name = Gtk.Label(label=title,
                         ellipsize=Pango.EllipsizeMode.END, max_width_chars=24)
        content.append(name)
        chip = Gtk.Button(css_classes=["card", "fav-chip"])
        chip.set_child(content)
        chip.connect(
            "clicked",
            lambda *_: self.emit("location-selected",
                                 Gio.File.new_for_uri(uri)))
        return chip

    def _section(self, title: str, cards: list):
        cards = [c for c in cards if c is not None]
        if not cards:
            return
        label = Gtk.Label(label=title, xalign=0,
                          margin_top=14, margin_bottom=4)
        label.add_css_class("heading")
        label.add_css_class("dim-label")
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                           column_spacing=12, row_spacing=12,
                           homogeneous=True, max_children_per_line=3,
                           min_children_per_line=1)
        for card in cards:
            flow.append(card)
        self.box.append(label)
        self.box.append(flow)

    # ------------------------------------------------------------ card
    def _card(self, icon, title: str, gfile: Gio.File | None = None,
              volume: Gio.Volume | None = None, usage: bool = False,
              subtitle: str | None = None) -> Gtk.Button:
        content = Gtk.Box(spacing=14, margin_top=10, margin_bottom=10,
                          margin_start=12, margin_end=12)
        image = Gtk.Image(pixel_size=48)
        if isinstance(icon, str):
            image.set_from_icon_name(icon)
        else:
            image.set_from_gicon(icon)
        content.append(image)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                           valign=Gtk.Align.CENTER, hexpand=True)
        name = Gtk.Label(label=title, xalign=0,
                         ellipsize=Pango.EllipsizeMode.MIDDLE)
        name.add_css_class("heading")
        text_box.append(name)

        sub = Gtk.Label(label=subtitle or "", xalign=0,
                        ellipsize=Pango.EllipsizeMode.END)
        sub.add_css_class("dim-label")
        sub.add_css_class("caption")
        sub.set_visible(bool(subtitle))
        text_box.append(sub)

        bar = Gtk.ProgressBar(visible=False)
        bar.add_css_class("osd")  # barra sottile
        text_box.append(bar)
        content.append(text_box)

        button = Gtk.Button(css_classes=["card"], hexpand=True)
        button.set_child(content)
        button.connect("clicked", self._on_card_clicked, gfile, volume)

        if usage and gfile is not None:
            self._query_usage(gfile, sub, bar)
        return button

    def _query_usage(self, gfile: Gio.File, sub: Gtk.Label,
                     bar: Gtk.ProgressBar):
        def on_info(f, result):
            try:
                info = f.query_filesystem_info_finish(result)
            except GLib.Error:
                return
            size = info.get_attribute_uint64("filesystem::size")
            free = info.get_attribute_uint64("filesystem::free")
            if not size:
                return
            used = size - free
            sub.set_text(f"{GLib.format_size(free)} liberi di "
                         f"{GLib.format_size(size)}")
            sub.set_visible(True)
            bar.set_fraction(used / size)
            bar.set_visible(True)

        gfile.query_filesystem_info_async(FS_ATTRS, GLib.PRIORITY_DEFAULT,
                                          None, on_info)

    # ------------------------------------------------------------ click
    def _on_card_clicked(self, _btn, gfile, volume):
        if gfile is not None:
            self.emit("location-selected", gfile)
            return
        if volume is None:
            return
        op = Gtk.MountOperation.new(self.get_root())

        def on_mounted(vol, result):
            try:
                vol.mount_finish(result)
            except GLib.Error:
                return
            mount = vol.get_mount()
            if mount:
                self.emit("location-selected", mount.get_root())

        volume.mount(Gio.MountMountFlags.NONE, op, None, on_mounted)
