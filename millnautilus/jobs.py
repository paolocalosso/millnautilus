"""Registro delle operazioni su file in corso.

Serve sia a mostrare la barra di avanzamento, sia a sapere se la finestra può
chiudersi davvero o deve solo sparire finché il lavoro non è finito.
"""
import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GObject  # noqa: E402


class Job(GObject.Object):
    """Una singola operazione (copia, spostamento, eliminazione, …)."""

    __gtype_name__ = "MillnautilusJob"

    def __init__(self, description: str, cancellable: Gio.Cancellable):
        super().__init__()
        self.description = description
        self.cancellable = cancellable
        self.fraction = 0.0
        self.detail = ""


class JobManager(GObject.Object):
    """Elenco condiviso delle operazioni attive."""

    __gtype_name__ = "MillnautilusJobManager"

    __gsignals__ = {
        # qualcosa è cambiato: aggiunta, avanzamento o fine
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # tutte le operazioni sono terminate
        "drained": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self.jobs: list[Job] = []

    def start(self, description: str,
              cancellable: Gio.Cancellable | None = None) -> Job:
        job = Job(description, cancellable or Gio.Cancellable())
        self.jobs.append(job)
        self.emit("changed")
        return job

    def update(self, job: Job, fraction: float, detail: str = ""):
        job.fraction = max(0.0, min(1.0, fraction))
        if detail:
            job.detail = detail
        self.emit("changed")

    def finish(self, job: Job):
        if job in self.jobs:
            self.jobs.remove(job)
        self.emit("changed")
        if not self.jobs:
            self.emit("drained")

    def cancel_all(self):
        for job in list(self.jobs):
            job.cancellable.cancel()

    @property
    def busy(self) -> bool:
        return bool(self.jobs)

    def summary(self) -> tuple[str, float]:
        """Etichetta e avanzamento complessivo da mostrare nella barra."""
        if not self.jobs:
            return "", 0.0
        fraction = sum(j.fraction for j in self.jobs) / len(self.jobs)
        if len(self.jobs) == 1:
            job = self.jobs[0]
            label = f"{job.description} — {job.detail}" if job.detail \
                else job.description
        else:
            label = f"{len(self.jobs)} operazioni in corso"
        return label, fraction


manager = JobManager()
