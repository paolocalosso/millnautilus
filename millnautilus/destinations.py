"""Sottomenu delle destinazioni per copiare/spostare elementi.

Il menu viene costruito al momento dell'apertura, con profondità e numero di
voci limitati: GTK non sa popolare un sottomenu "alla richiesta", quindi
l'intero albero va preparato prima e senza esagerare, altrimenti aprire il
menu contestuale diventa lento.
"""
import time

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib  # noqa: E402

from . import pinned  # noqa: E402
from .sidebar import Sidebar  # noqa: E402

MAX_ENTRIES = 25    # sottocartelle elencate per livello
MAX_DEPTH = 2       # livelli di nidificazione sotto una radice locale
MOUNT_DEPTH = 1     # meno per i mount: FUSE e simili possono essere lenti
TIME_BUDGET = 0.35  # secondi complessivi dedicati a esplorare le cartelle


def build_menu() -> Gio.Menu:
    """Menu "Copia o sposta in" con le destinazioni note."""
    menu = Gio.Menu()

    chooser = Gio.Menu()
    chooser.append("Copia in altra cartella…", "win.copy-to-choose")
    chooser.append("Sposta in altra cartella…", "win.move-to-choose")
    menu.append_section(None, chooser)

    deadline = time.monotonic() + TIME_BUDGET
    roots = Gio.Menu()
    for label, gfile, max_depth in _roots():
        roots.append_submenu(
            label, _folder_menu(gfile, 0, max_depth, deadline))
    menu.append_section(None, roots)
    return menu


def _roots() -> list[tuple[str, Gio.File, int]]:
    """Home, volumi montati, preferiti e posizioni fissate (senza doppioni).

    Il terzo elemento è la profondità di esplorazione concessa: i mount ne
    ricevono meno perché possono essere su rete (pCloud, FUSE, …).
    """
    entries: list[tuple[str, Gio.File, int]] = []
    seen: set[str] = set()

    def add(label: str, gfile: Gio.File, max_depth: int):
        uri = gfile.get_uri()
        if uri in seen or gfile.get_path() is None:
            return  # solo posizioni locali: su remoto sarebbe lentissimo
        seen.add(uri)
        entries.append((label, gfile, max_depth))

    add("Home", Gio.File.new_for_path(GLib.get_home_dir()), MAX_DEPTH)

    monitor = Gio.VolumeMonitor.get()
    for mount in monitor.get_mounts():
        add(mount.get_name(), mount.get_root(), MOUNT_DEPTH)

    for uri, label in pinned.load():
        add(label, Gio.File.new_for_uri(uri), MAX_DEPTH)
    for uri, label in Sidebar._read_bookmarks():
        add(label, Gio.File.new_for_uri(uri), MAX_DEPTH)
    return entries


def _folder_menu(gfile: Gio.File, depth: int, max_depth: int,
                 deadline: float) -> Gio.Menu:
    """Sottomenu di una cartella: percorso, azioni e sottocartelle."""
    menu = Gio.Menu()

    # prima riga: percorso completo, come semplice etichetta non cliccabile
    header = Gio.Menu()
    header.append_item(Gio.MenuItem.new(
        gfile.get_path() or gfile.get_uri(), None))
    menu.append_section(None, header)

    actions = Gio.Menu()
    uri = GLib.Variant("s", gfile.get_uri())
    for label, action in (("Copia qui", "win.copy-to"),
                          ("Sposta qui", "win.move-to")):
        item = Gio.MenuItem.new(label, None)
        item.set_action_and_target_value(action, uri)
        actions.append_item(item)
    menu.append_section(None, actions)

    if depth < max_depth:
        children = Gio.Menu()
        for name, child in _subfolders(gfile, deadline):
            children.append_submenu(
                name, _folder_menu(child, depth + 1, max_depth, deadline))
        if children.get_n_items():
            menu.append_section(None, children)
    return menu


def _subfolders(gfile: Gio.File, deadline: float) -> list[tuple[str, Gio.File]]:
    result: list[tuple[str, Gio.File]] = []
    if time.monotonic() > deadline:
        return result  # tempo esaurito: meglio un menu ridotto che uno lento
    try:
        enumerator = gfile.enumerate_children(
            "standard::name,standard::display-name,standard::type,"
            "standard::is-hidden",
            Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        return result
    try:
        while len(result) < MAX_ENTRIES:
            info = enumerator.next_file(None)
            if info is None:
                break
            if (info.get_file_type() != Gio.FileType.DIRECTORY
                    or info.get_is_hidden()):
                continue
            name = info.get_display_name() or info.get_name()
            result.append((name, gfile.get_child(info.get_name())))
    except GLib.Error:
        pass
    finally:
        try:
            enumerator.close(None)
        except GLib.Error:
            pass
    result.sort(key=lambda pair: pair[0].casefold())
    return result
