"""Interfaccia D-Bus org.freedesktop.FileManager1.

Usata da GNOME Shell, browser ("Mostra nella cartella"), ecc.
"""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib  # noqa: E402

FM1_XML = """
<node>
  <interface name='org.freedesktop.FileManager1'>
    <method name='ShowFolders'>
      <arg type='as' name='URIs' direction='in'/>
      <arg type='s' name='StartupId' direction='in'/>
    </method>
    <method name='ShowItems'>
      <arg type='as' name='URIs' direction='in'/>
      <arg type='s' name='StartupId' direction='in'/>
    </method>
    <method name='ShowItemProperties'>
      <arg type='as' name='URIs' direction='in'/>
      <arg type='s' name='StartupId' direction='in'/>
    </method>
  </interface>
</node>
"""

FM1_NAME = "org.freedesktop.FileManager1"
FM1_PATH = "/org/freedesktop/FileManager1"


class FileManager1:
    """Registra ed espone l'interfaccia FileManager1 sull'app."""

    def __init__(self, app):
        self.app = app
        self._reg_id = 0
        self._own_id = 0

    def register(self, connection: Gio.DBusConnection):
        node = Gio.DBusNodeInfo.new_for_xml(FM1_XML)
        self._reg_id = connection.register_object(
            FM1_PATH, node.interfaces[0], self._on_method_call, None, None)
        # REPLACE funziona solo se l'attuale proprietario (es. Nautilus)
        # consente la sostituzione; altrimenti il nome resta a lui finché gira
        self._own_id = Gio.bus_own_name_on_connection(
            connection, FM1_NAME,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT
            | Gio.BusNameOwnerFlags.REPLACE,
            None, None)

    def unregister(self, connection: Gio.DBusConnection):
        if self._reg_id:
            connection.unregister_object(self._reg_id)
            self._reg_id = 0
        if self._own_id:
            Gio.bus_unown_name(self._own_id)
            self._own_id = 0

    # ------------------------------------------------------------ chiamate
    def _on_method_call(self, connection, sender, path, iface, method,
                        params, invocation):
        try:
            args = params.unpack()
            uris = list(args[0]) if args else []
            if method == "ShowFolders":
                self._show(uris, reveal=False, info=False)
            elif method == "ShowItems":
                self._show(uris, reveal=True, info=False)
            elif method == "ShowItemProperties":
                self._show(uris, reveal=True, info=True)
            else:
                invocation.return_error_literal(
                    Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD,
                    f"Metodo sconosciuto: {method}")
                return
            invocation.return_value(None)
        except Exception as err:  # noqa: BLE001
            invocation.return_error_literal(
                Gio.dbus_error_quark(), Gio.DBusError.FAILED, str(err))

    def _show(self, uris: list[str], reveal: bool, info: bool):
        if not uris:
            return

        def do_show():
            self.app.activate()
            win = self.app.props.active_window
            if win is None:
                return False
            gfile = Gio.File.new_for_uri(uris[0])
            if reveal:
                win.reveal(gfile, info=info)
            else:
                win.navigate_to(gfile)
            win.present()
            return False

        GLib.idle_add(do_show)
