"""Applicazione Adwaita."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .fm1 import FileManager1  # noqa: E402
from .window import MainWindow  # noqa: E402

APP_ID = "org.paolo.Millnautilus"


class MillnautilusApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self._fm1 = FileManager1(self)
        self._add_actions()

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._fm1.own()

    def do_shutdown(self):
        self._fm1.unown()
        Adw.Application.do_shutdown(self)

    def _add_actions(self):
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(application=self)
        win.present()

    def do_open(self, files, n_files, hint):
        self.do_activate()
        win = self.props.active_window
        if files and win:
            win.navigate_to(files[0])

    def _on_about(self, *_):
        dialog = Adw.AboutDialog(
            application_name="Millnautilus",
            application_icon="system-file-manager",
            developer_name="Paolo",
            version="0.1.0",
            comments="File explorer con vista a colonne (Miller view)",
            license_type=Gtk.License.GPL_3_0,
        )
        dialog.present(self.props.active_window)
