"""Operazioni su file (copia, spostamento, cestino, rinomina) via Gio."""
import os
import shutil
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GLib  # noqa: E402

COPY_FLAGS = Gio.FileCopyFlags.NOFOLLOW_SYMLINKS


MEASURE_ATTRS = "standard::name,standard::type,standard::size"


def measure_directory(gfile: Gio.File, on_update,
                      cancellable: Gio.Cancellable | None = None):
    """Calcola ricorsivamente dimensione e conteggi in un thread.

    on_update(total_bytes, n_files, n_dirs, finished) viene chiamata nel
    main loop periodicamente e una volta al termine.
    """
    def worker():
        total = n_files = n_dirs = 0
        stack = [gfile]
        last_emit = time.monotonic()
        while stack:
            if cancellable is not None and cancellable.is_cancelled():
                return
            current = stack.pop()
            try:
                enumerator = current.enumerate_children(
                    MEASURE_ATTRS,
                    Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
            except GLib.Error:
                continue
            while True:
                try:
                    info = enumerator.next_file(cancellable)
                except GLib.Error:
                    break
                if info is None:
                    break
                if info.get_file_type() == Gio.FileType.DIRECTORY:
                    n_dirs += 1
                    stack.append(current.get_child(info.get_name()))
                else:
                    n_files += 1
                    total += info.get_size()
                now = time.monotonic()
                if now - last_emit > 0.3:
                    last_emit = now
                    GLib.idle_add(on_update, total, n_files, n_dirs, False)
            try:
                enumerator.close(cancellable)
            except GLib.Error:
                pass
        GLib.idle_add(on_update, total, n_files, n_dirs, True)

    threading.Thread(target=worker, daemon=True).start()


def _unique_dest(dest_dir: Gio.File, name: str) -> Gio.File:
    dest = dest_dir.get_child(name)
    if not dest.query_exists(None):
        return dest
    stem, dot, ext = name.partition(".")
    for i in range(1, 1000):
        candidate = (f"{stem} (copia {i}){dot}{ext}" if dot
                     else f"{name} (copia {i})")
        dest = dest_dir.get_child(candidate)
        if not dest.query_exists(None):
            return dest
    raise RuntimeError("Impossibile trovare un nome disponibile")


def _copy_recursive(src: Gio.File, dest: Gio.File, cancellable):
    info = src.query_info("standard::type", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                          cancellable)
    if info.get_file_type() == Gio.FileType.DIRECTORY:
        try:
            dest.make_directory(cancellable)
        except GLib.Error as err:
            if err.code != Gio.IOErrorEnum.EXISTS:
                raise
        enumerator = src.enumerate_children(
            "standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            cancellable)
        while (child_info := enumerator.next_file(cancellable)) is not None:
            name = child_info.get_name()
            _copy_recursive(src.get_child(name), dest.get_child(name),
                            cancellable)
        enumerator.close(cancellable)
    else:
        src.copy(dest, COPY_FLAGS, cancellable, None, None)


def _delete_recursive(gfile: Gio.File, cancellable):
    info = gfile.query_info("standard::type",
                            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                            cancellable)
    if info.get_file_type() == Gio.FileType.DIRECTORY:
        enumerator = gfile.enumerate_children(
            "standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            cancellable)
        while (child := enumerator.next_file(cancellable)) is not None:
            _delete_recursive(gfile.get_child(child.get_name()), cancellable)
        enumerator.close(cancellable)
    gfile.delete(cancellable)


# decisioni possibili su un conflitto di nomi
REPLACE, MERGE, RENAME, SKIP, CANCEL = (
    "replace", "merge", "rename", "skip", "cancel")


class _Cancelled(Exception):
    """L'utente ha annullato l'intera operazione."""


def _decide(src: Gio.File, dest: Gio.File, handler, state: dict) -> str:
    """Chiede cosa fare, ricordando un'eventuale scelta "per tutti"."""
    if state.get("apply_all"):
        return state["apply_all"]
    if handler is None:
        return RENAME  # nessuna interfaccia: comportamento prudente
    decision, apply_all = handler(src, dest)
    if apply_all:
        state["apply_all"] = decision
    return decision


def _is_dir(gfile: Gio.File, cancellable) -> bool:
    return gfile.query_file_type(
        Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
        cancellable) == Gio.FileType.DIRECTORY


def _merge_dir(src: Gio.File, dest: Gio.File, cancellable, handler,
               state: dict):
    """Unisce il contenuto di `src` in `dest`, già esistente."""
    try:
        dest.make_directory_with_parents(cancellable)
    except GLib.Error as err:
        if err.code != Gio.IOErrorEnum.EXISTS:
            raise
    enumerator = src.enumerate_children(
        "standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
        cancellable)
    while (info := enumerator.next_file(cancellable)) is not None:
        child = src.get_child(info.get_name())
        _transfer_one(child, dest, False, cancellable, None, handler, state)
    enumerator.close(cancellable)


def _transfer_one(src: Gio.File, dest_dir: Gio.File, move: bool, cancellable,
                  report, handler, state: dict):
    """Trasferisce un singolo elemento, risolvendo i conflitti di nome."""
    name = src.get_basename() or "file"
    dest = dest_dir.get_child(name)
    decision = None
    if dest.query_exists(cancellable):
        decision = _decide(src, dest, handler, state)
        if decision == CANCEL:
            raise _Cancelled()
        if decision == SKIP:
            return
        if decision == RENAME:
            dest = _unique_dest(dest_dir, name)
            decision = None

    if decision == MERGE and _is_dir(src, cancellable):
        _merge_dir(src, dest, cancellable, handler, state)
        if move:
            _delete_recursive(src, cancellable)
        return

    flags = COPY_FLAGS
    if decision == REPLACE:
        flags |= Gio.FileCopyFlags.OVERWRITE
    if move:
        try:
            src.move(dest, flags, cancellable, report, None)
            return
        except GLib.Error as err:
            # move tra filesystem diversi non supportato per le cartelle
            if err.code not in (Gio.IOErrorEnum.WOULD_RECURSE,
                                Gio.IOErrorEnum.NOT_SUPPORTED):
                raise
            _copy_recursive(src, dest, cancellable)
            _delete_recursive(src, cancellable)
            return
    try:
        src.copy(dest, flags, cancellable, report, None)
    except GLib.Error as err:
        if err.code != Gio.IOErrorEnum.WOULD_RECURSE:
            raise
        _copy_recursive(src, dest, cancellable)


def _progress_reporter(on_progress, index: int, total: int, name: str):
    """Callback di avanzamento per Gio.File.copy, con limitazione a 10/s."""
    if on_progress is None:
        return None
    state = {"last": 0.0}

    def report(current_bytes, total_bytes, *_):
        now = time.monotonic()
        if now - state["last"] < 0.1 and current_bytes != total_bytes:
            return
        state["last"] = now
        share = (current_bytes / total_bytes) if total_bytes else 0.0
        GLib.idle_add(on_progress, (index + share) / total, name)

    return report


def transfer(files: list[Gio.File], dest_dir: Gio.File, move: bool,
             on_done, cancellable: Gio.Cancellable | None = None,
             on_progress=None, conflict_handler=None):
    """Copia o sposta `files` in `dest_dir` in un thread.

    on_done(error_message | None) viene chiamata nel main loop; on_progress,
    se presente, riceve (frazione, nome del file in corso). conflict_handler
    (src, dest) -> (decisione, applica_a_tutti) viene invocata dal thread di
    lavoro quando il nome esiste già: deve bloccarsi finché l'utente sceglie.
    """
    def worker():
        error = None
        total = len(files) or 1
        state: dict = {}
        try:
            for index, src in enumerate(files):
                name = src.get_basename() or "file"
                if on_progress is not None:
                    GLib.idle_add(on_progress, index / total, name)
                report = _progress_reporter(on_progress, index, total, name)
                _transfer_one(src, dest_dir, move, cancellable, report,
                              conflict_handler, state)
        except _Cancelled:
            error = None
        except GLib.Error as err:
            error = None if err.matches(Gio.io_error_quark(),
                                        Gio.IOErrorEnum.CANCELLED) \
                else err.message
        except Exception as err:  # noqa: BLE001
            error = str(err)
        GLib.idle_add(on_done, error)

    threading.Thread(target=worker, daemon=True).start()


def make_links(files: list[Gio.File], dest_dir: Gio.File, on_done,
               cancellable: Gio.Cancellable | None = None):
    """Crea collegamenti simbolici a `files` dentro `dest_dir`."""
    def worker():
        error = None
        try:
            for src in files:
                target = src.get_path()
                if not target:
                    raise RuntimeError(
                        "Collegamenti non supportati per posizioni remote")
                name = src.get_basename() or "collegamento"
                dest = _unique_dest(dest_dir, name)
                dest.make_symbolic_link(target, cancellable)
        except GLib.Error as err:
            error = err.message
        except Exception as err:  # noqa: BLE001
            error = str(err)
        GLib.idle_add(on_done, error)

    threading.Thread(target=worker, daemon=True).start()


def trash(files: list[Gio.File], on_done):
    """Sposta nel cestino (async, in thread per gestire più file)."""
    def worker():
        error = None
        try:
            for gfile in files:
                gfile.trash(None)
        except GLib.Error as err:
            error = err.message
        GLib.idle_add(on_done, error)

    threading.Thread(target=worker, daemon=True).start()


def delete(files: list[Gio.File], on_done,
           cancellable: Gio.Cancellable | None = None, on_progress=None):
    """Elimina definitivamente (ricorsivo), senza passare dal cestino."""
    def worker():
        error = None
        total = len(files) or 1
        try:
            for index, gfile in enumerate(files):
                if on_progress is not None:
                    GLib.idle_add(on_progress, index / total,
                                  gfile.get_basename() or "")
                _delete_recursive(gfile, cancellable)
        except GLib.Error as err:
            error = None if err.matches(Gio.io_error_quark(),
                                        Gio.IOErrorEnum.CANCELLED) \
                else err.message
        except Exception as err:  # noqa: BLE001
            error = str(err)
        GLib.idle_add(on_done, error)

    threading.Thread(target=worker, daemon=True).start()


# estensioni composte da togliere per ricavare il nome della cartella
COMPOUND_SUFFIXES = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst",
                     ".tar.lzma", ".tgz", ".tbz2", ".txz")

# strumenti esterni per i formati che shutil non gestisce (7z, rar, …)
EXTRACT_TOOLS = (
    ("7z", lambda src, dst: ["7z", "x", "-y", f"-o{dst}", src]),
    ("7za", lambda src, dst: ["7za", "x", "-y", f"-o{dst}", src]),
    ("unar", lambda src, dst: ["unar", "-f", "-o", dst, src]),
    ("bsdtar", lambda src, dst: ["bsdtar", "-x", "-f", src, "-C", dst]),
)


def archive_basename(path: str) -> str:
    """Nome dell'archivio senza estensione (gestisce .tar.gz e simili)."""
    name = os.path.basename(path)
    lower = name.lower()
    for suffix in COMPOUND_SUFFIXES:
        if lower.endswith(suffix):
            return name[:-len(suffix)]
    stem = os.path.splitext(name)[0]
    return stem or name


def _extract_one(src_path: str, dest_path: str):
    try:
        shutil.unpack_archive(src_path, dest_path)
        return
    except (shutil.ReadError, ValueError):
        pass  # formato non gestito da shutil: prova gli strumenti esterni
    for tool, build_argv in EXTRACT_TOOLS:
        if not shutil.which(tool):
            continue
        result = subprocess.run(build_argv(src_path, dest_path),
                                capture_output=True)
        if result.returncode == 0:
            return
        message = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(message or f"{tool}: errore {result.returncode}")
    raise RuntimeError("Formato non supportato: installa p7zip o unar")


def extract(files: list[Gio.File], dest_dir: Gio.File, into_subdir: bool,
            on_done, on_progress=None):
    """Estrae archivi in `dest_dir`.

    Con `into_subdir` ogni archivio finisce in una cartella che porta il suo
    stesso nome, altrimenti il contenuto viene estratto direttamente.
    """
    def worker():
        error = None
        try:
            base_path = dest_dir.get_path()
            if not base_path:
                raise RuntimeError(
                    "Estrazione non supportata su posizioni remote")
            total = len(files) or 1
            for index, src in enumerate(files):
                src_path = src.get_path()
                if not src_path:
                    raise RuntimeError(
                        "Estrazione non supportata su posizioni remote")
                if on_progress is not None:
                    GLib.idle_add(on_progress, index / total,
                                  src.get_basename() or "")
                target = base_path
                if into_subdir:
                    folder = _unique_dest(dest_dir,
                                          archive_basename(src_path))
                    folder.make_directory_with_parents(None)
                    target = folder.get_path()
                _extract_one(src_path, target)
        except GLib.Error as err:
            error = err.message
        except Exception as err:  # noqa: BLE001
            error = str(err)
        GLib.idle_add(on_done, error)

    threading.Thread(target=worker, daemon=True).start()


def rename(gfile: Gio.File, new_name: str, on_done):
    def callback(f, result):
        try:
            f.set_display_name_finish(result)
            on_done(None)
        except GLib.Error as err:
            on_done(err.message)

    gfile.set_display_name_async(new_name, GLib.PRIORITY_DEFAULT,
                                 None, callback)


def new_folder(parent: Gio.File, name: str, on_done):
    def callback(f, result):
        try:
            f.make_directory_finish(result)
            on_done(None)
        except GLib.Error as err:
            on_done(err.message)

    parent.get_child(name).make_directory_async(
        GLib.PRIORITY_DEFAULT, None, callback)
