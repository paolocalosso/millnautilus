"""Modalità a due riquadri indipendenti, in stile Total Commander.

Ogni riquadro ha la propria barra del percorso e la propria vista a colonne:
si naviga separatamente e le operazioni usano l'altro riquadro come
destinazione predefinita.
"""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib, GObject, Gtk  # noqa: E402

from .miller import MillerView  # noqa: E402
from .pathbar import PathBar  # noqa: E402


class FilePane(Gtk.Box):
    """Un riquadro: barra del percorso più vista a colonne."""

    __gsignals__ = {
        # il riquadro è stato usato: diventa quello attivo
        "activated": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("file-pane")

        self.pathbar = PathBar()
        self.pathbar.set_margin_top(4)
        self.pathbar.set_margin_bottom(4)
        self.pathbar.set_margin_start(6)
        self.pathbar.set_margin_end(6)
        self.pathbar.connect("navigate", lambda _p, f: self.navigate_to(f))

        self.miller = MillerView()
        self.miller.connect("location-changed",
                            lambda _m, f: self.pathbar.set_location(f))

        self.append(self.pathbar)
        self.append(self.miller)

        # qualsiasi click dentro il riquadro lo rende attivo; la fase di
        # cattura serve a intercettarlo prima che lo consumino le colonne
        click = Gtk.GestureClick(button=0)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", lambda *_: self.emit("activated"))
        self.add_controller(click)

    def navigate_to(self, gfile: Gio.File):
        self.miller.set_root(gfile)

    @property
    def current_dir(self) -> Gio.File | None:
        return self.miller.current_dir

    def set_active(self, active: bool):
        if active:
            self.add_css_class("pane-active")
        else:
            self.remove_css_class("pane-active")


class DualPaneView(Gtk.Paned):
    """Due riquadri affiancati, con uno solo attivo per volta."""

    __gsignals__ = {
        "active-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL,
                         wide_handle=True)
        self.left = FilePane()
        self.right = FilePane()
        for pane in (self.left, self.right):
            pane.connect("activated", self._on_pane_activated)
            self.set_resize_start_child(True)
            self.set_resize_end_child(True)
        self.set_start_child(self.left)
        self.set_end_child(self.right)
        self.active = self.left
        self.left.set_active(True)

    @property
    def panes(self) -> tuple[FilePane, FilePane]:
        return (self.left, self.right)

    @property
    def inactive(self) -> FilePane:
        return self.right if self.active is self.left else self.left

    def _on_pane_activated(self, pane: FilePane):
        self.set_active_pane(pane)

    def set_active_pane(self, pane: FilePane):
        if pane is self.active:
            return
        self.active.set_active(False)
        self.active = pane
        pane.set_active(True)
        self.emit("active-changed")

    def switch_active(self):
        """Scambia il riquadro attivo (Tab)."""
        self.set_active_pane(self.inactive)

    def ensure_locations(self, primary: Gio.File | None):
        """Riempie i riquadri vuoti: l'attivo con `primary`, l'altro con Home."""
        home = Gio.File.new_for_path(GLib.get_home_dir())
        if self.left.miller.root is None:
            self.left.navigate_to(primary or home)
        if self.right.miller.root is None:
            self.right.navigate_to(home)
