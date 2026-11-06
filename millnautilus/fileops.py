"""Operazioni su file (copia, spostamento, cestino, rinomina) via Gio."""
import os
import shutil
import subprocess
import threading
import time
from collections import deque

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


def _copy_recursive(src: Gio.File, dest: Gio.File, cancellable, tracker=None):
    info = src.query_info("standard::type,standard::size",
                          Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
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
                            cancellable, tracker)
        enumerator.close(cancellable)
    else:
        if tracker is not None:
            tracker.set_name(src.get_basename() or "")
        src.copy(dest, COPY_FLAGS, cancellable, _tracker_report(tracker), None)
        if tracker is not None:
            tracker.file_done(info.get_size())


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
               state: dict, tracker=None):
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
        _transfer_one(child, dest, False, cancellable, tracker, handler, state)
    enumerator.close(cancellable)


def _transfer_one(src: Gio.File, dest_dir: Gio.File, move: bool, cancellable,
                  tracker, handler, state: dict):
    """Trasferisce un singolo elemento, risolvendo i conflitti di nome."""
    name = src.get_basename() or "file"
    dest = dest_dir.get_child(name)
    decision = None
    if dest.query_exists(cancellable):
        decision = _decide(src, dest, handler, state)
        if decision == CANCEL:
            raise _Cancelled()
        if decision == SKIP:
            # i byte saltati vanno comunque scalati, o la stima resta indietro
            if tracker is not None:
                tracker.file_done(file_size(src, cancellable))
            return
        if decision == RENAME:
            dest = _unique_dest(dest_dir, name)
            decision = None

    if decision == MERGE and _is_dir(src, cancellable):
        _merge_dir(src, dest, cancellable, handler, state, tracker)
        if move:
            _delete_recursive(src, cancellable)
        return

    flags = COPY_FLAGS
    if decision == REPLACE:
        flags |= Gio.FileCopyFlags.OVERWRITE
    report = _tracker_report(tracker)
    directory = _is_dir(src, cancellable)
    size = 0 if directory else file_size(src, cancellable)
    if tracker is not None and not directory:
        tracker.set_name(name)
    if move:
        try:
            src.move(dest, flags, cancellable, report, None)
            if tracker is not None and not directory:
                tracker.file_done(size)
            return
        except GLib.Error as err:
            # move tra filesystem diversi non supportato per le cartelle
            if err.code not in (Gio.IOErrorEnum.WOULD_RECURSE,
                                Gio.IOErrorEnum.NOT_SUPPORTED):
                raise
            _copy_recursive(src, dest, cancellable, tracker)
            _delete_recursive(src, cancellable)
            return
    try:
        src.copy(dest, flags, cancellable, report, None)
        if tracker is not None and not directory:
            tracker.file_done(size)
    except GLib.Error as err:
        if err.code != Gio.IOErrorEnum.WOULD_RECURSE:
            raise
        _copy_recursive(src, dest, cancellable, tracker)


SIZE_ATTRS = "standard::size,standard::type"


def _dir_size(gfile: Gio.File, cancellable) -> int:
    total = 0
    stack = [gfile]
    while stack:
        current = stack.pop()
        try:
            enumerator = current.enumerate_children(
                "standard::name," + SIZE_ATTRS,
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
        except GLib.Error:
            continue
        while (info := enumerator.next_file(cancellable)) is not None:
            if info.get_file_type() == Gio.FileType.DIRECTORY:
                stack.append(current.get_child(info.get_name()))
            else:
                total += info.get_size()
        enumerator.close(cancellable)
    return total


def _total_size(files: list[Gio.File], cancellable) -> int:
    """Byte complessivi da trasferire: serve per percentuale e tempo residuo."""
    total = 0
    for gfile in files:
        try:
            info = gfile.query_info(
                SIZE_ATTRS, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                cancellable)
        except GLib.Error:
            continue
        if info.get_file_type() == Gio.FileType.DIRECTORY:
            total += _dir_size(gfile, cancellable)
        else:
            total += info.get_size()
    return total


def file_size(gfile: Gio.File, cancellable=None) -> int:
    try:
        return gfile.query_info(
            "standard::size", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            cancellable).get_size()
    except GLib.Error:
        return 0


class _Tracker:
    """Tiene il conto dei byte trasferiti e ne ricava velocità e stima.

    La velocità è misurata su una finestra scorrevole di pochi secondi: usare
    la media dall'inizio darebbe un valore che non reagisce più ai
    rallentamenti (tipici verso dispositivi USB o di rete).
    """

    WINDOW = 3.0       # secondi di storico per la velocità
    MIN_INTERVAL = 0.15  # limita gli aggiornamenti dell'interfaccia

    def __init__(self, total_bytes: int, on_progress):
        self.total = total_bytes
        self.done = 0        # byte dei file già conclusi
        self.current = 0     # byte del file in corso
        self.name = ""
        self.on_progress = on_progress
        self._samples: deque = deque()
        self._last_emit = 0.0

    @property
    def transferred(self) -> int:
        return self.done + self.current

    def set_name(self, name: str):
        self.name = name
        self.emit(force=True)

    def update_current(self, current_bytes: int):
        self.current = current_bytes
        self.emit()

    def file_done(self, size: int):
        self.done += size
        self.current = 0
        self.emit(force=True)

    def _speed(self, now: float, done: int) -> float | None:
        self._samples.append((now, done))
        while len(self._samples) > 1 and now - self._samples[0][0] > self.WINDOW:
            self._samples.popleft()
        if len(self._samples) < 2:
            return None
        span = self._samples[-1][0] - self._samples[0][0]
        moved = self._samples[-1][1] - self._samples[0][1]
        if span < 0.5 or moved <= 0:
            return None
        return moved / span

    def emit(self, force: bool = False):
        if self.on_progress is None:
            return
        now = time.monotonic()
        if not force and now - self._last_emit < self.MIN_INTERVAL:
            return
        self._last_emit = now
        done = self.transferred
        speed = self._speed(now, done)
        eta = None
        if speed and self.total and self.total > done:
            eta = (self.total - done) / speed
        fraction = (done / self.total) if self.total else 0.0
        GLib.idle_add(self.on_progress, min(1.0, fraction), self.name,
                      {"done": done, "total": self.total,
                       "speed": speed, "eta": eta})


def _tracker_report(tracker: "_Tracker | None"):
    """Callback di avanzamento da passare a Gio.File.copy/move."""
    if tracker is None:
        return None

    def report(current_bytes, _total_bytes, *_):
        tracker.update_current(current_bytes)

    return report


def transfer(files: list[Gio.File], dest_dir: Gio.File, move: bool,
             on_done, cancellable: Gio.Cancellable | None = None,
             on_progress=None, conflict_handler=None):
    """Copia o sposta `files` in `dest_dir` in un thread.

    on_done(error_message | None) viene chiamata nel main loop; on_progress,
    se presente, riceve (frazione, nome del file in corso, statistiche) dove
    le statistiche sono byte fatti/totali, velocità e stima. conflict_handler
    (src, dest) -> (decisione, applica_a_tutti) viene invocata dal thread di
    lavoro quando il nome esiste già: deve bloccarsi finché l'utente sceglie.
    """
    def worker():
        error = None
        state: dict = {}
        tracker = None
        try:
            if on_progress is not None:
                GLib.idle_add(on_progress, 0.0, "Calcolo dimensioni…", None)
                tracker = _Tracker(_total_size(files, cancellable),
                                   on_progress)
            for src in files:
                if tracker is not None:
                    tracker.set_name(src.get_basename() or "file")
                _transfer_one(src, dest_dir, move, cancellable, tracker,
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


# formati offerti dalla finestra "Comprimi": (etichetta, estensione)
ARCHIVE_FORMATS = (
    ("ZIP", ".zip"),
    ("tar.gz", ".tar.gz"),
    ("tar.xz", ".tar.xz"),
    ("7z", ".7z"),
)


def _archive_entries(paths: list[str]):
    """Coppie (percorso reale, nome dentro l'archivio)."""
    for path in paths:
        base = os.path.basename(path.rstrip("/"))
        if os.path.isdir(path):
            yield path, base
            for root, dirs, files in os.walk(path):
                relative = os.path.relpath(root, path)
                arc_root = base if relative == "." \
                    else os.path.join(base, relative)
                for name in dirs:      # anche le cartelle vuote
                    yield os.path.join(root, name), \
                        os.path.join(arc_root, name)
                for name in files:
                    yield os.path.join(root, name), \
                        os.path.join(arc_root, name)
        else:
            yield path, base


def _write_archive(paths: list[str], target: str, extension: str,
                   cancellable, on_progress):
    entries = list(_archive_entries(paths))
    total = len(entries) or 1

    def step(index: int, arcname: str):
        if cancellable is not None and cancellable.is_cancelled():
            raise _Cancelled()
        if on_progress is not None:
            GLib.idle_add(on_progress, index / total,
                          os.path.basename(arcname), None)

    if extension == ".zip":
        import zipfile
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, (src, arcname) in enumerate(entries):
                step(index, arcname)
                archive.write(src, arcname)
        return

    import tarfile
    mode = "w:gz" if extension == ".tar.gz" else "w:xz"
    with tarfile.open(target, mode) as archive:
        for index, (src, arcname) in enumerate(entries):
            step(index, arcname)
            archive.add(src, arcname=arcname, recursive=False)


def compress(files: list[Gio.File], dest_dir: Gio.File, name: str,
             extension: str, on_done,
             cancellable: Gio.Cancellable | None = None, on_progress=None):
    """Crea un archivio con `files` dentro `dest_dir`."""
    def worker():
        error = None
        try:
            if dest_dir.get_path() is None:
                raise RuntimeError(
                    "Compressione non supportata su posizioni remote")
            paths = []
            for gfile in files:
                path = gfile.get_path()
                if not path:
                    raise RuntimeError(
                        "Compressione non supportata su posizioni remote")
                paths.append(path)

            dest = _unique_dest(dest_dir, name)
            target = dest.get_path()
            if extension == ".7z":
                tool = shutil.which("7z") or shutil.which("7za")
                if tool is None:
                    raise RuntimeError("7z non disponibile: installa p7zip")
                result = subprocess.run([tool, "a", "-y", target, *paths],
                                        capture_output=True)
                if result.returncode != 0:
                    message = result.stderr.decode(errors="replace").strip()
                    raise RuntimeError(message or
                                       f"7z: errore {result.returncode}")
            else:
                _write_archive(paths, target, extension, cancellable,
                               on_progress)
        except _Cancelled:
            error = None
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
