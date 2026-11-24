"""Etichette colore su file e cartelle.

L'etichetta è salvata nei metadati GVfs del file (attributo
"metadata::millnautilus-tag", lo stesso meccanismo che Nautilus usa per
emblemi e posizioni delle icone). Così segue il file quando viene rinominato
o spostato, funziona anche sulle risorse di rete montate con GVfs e non
richiede un database a parte. I metadati restano però su questa macchina
(~/.local/share/gvfs-metadata): non viaggiano con le copie né si
sincronizzano altrove.
"""
from gi.repository import Gio, GLib

ATTRIBUTE = "metadata::millnautilus-tag"

# (id, etichetta, colore): l'id è quello salvato nei metadati, il colore
# viene dalla tavolozza GNOME (blue_3, green_3, …)
TAGS = (
    ("red", "Rosso", "#e01b24"),
    ("yellow", "Giallo", "#f6d32d"),
    ("green", "Verde", "#33d17a"),
    ("blue", "Blu", "#3584e4"),
)

TAG_IDS = frozenset(tag_id for tag_id, _label, _color in TAGS)


def label_for(tag: str | None) -> str:
    return next((label for tag_id, label, _ in TAGS if tag_id == tag), "")


def from_info(info: Gio.FileInfo) -> str | None:
    """Etichetta letta da un Gio.FileInfo (None se assente o sconosciuta)."""
    if not info.has_attribute(ATTRIBUTE):
        return None
    value = info.get_attribute_string(ATTRIBUTE)
    return value if value in TAG_IDS else None


def set_tag(gfile: Gio.File, tag: str | None):
    """Scrive (o cancella, con None) l'etichetta di `gfile`.

    Solleva GLib.Error se il file system non supporta i metadati.
    """
    if tag is not None and tag not in TAG_IDS:
        raise ValueError(f"etichetta sconosciuta: {tag}")
    if tag is None:
        try:
            # il tipo INVALID è il modo previsto da GVfs per togliere la chiave
            gfile.set_attribute(ATTRIBUTE, Gio.FileAttributeType.INVALID,
                                None, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                None)
            return
        except (GLib.Error, TypeError):
            pass  # ripiego: stringa vuota, letta come "nessuna etichetta"
    gfile.set_attribute_string(ATTRIBUTE, tag or "",
                               Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)


def css() -> str:
    """Regole CSS per i pallini colorati, generate dalla tavolozza."""
    rules = [
        ".tag-dot { min-width: 10px; min-height: 10px;"
        " border-radius: 9999px; }",
        # pulsanti del menu contestuale
        ".tag-picker { margin: 2px 6px; }",
        ".tag-picker button { min-width: 28px; min-height: 28px;"
        " padding: 0; border-radius: 9999px; }",
        ".tag-picker button .tag-dot { min-width: 16px; min-height: 16px; }",
        ".tag-picker button.tag-current { box-shadow: inset 0 0 0 2px"
        " alpha(currentColor, 0.6); }",
    ]
    for tag_id, _label, color in TAGS:
        rules.append(f".tag-dot.tag-{tag_id} {{ background-color: {color}; }}")
    return "\n".join(rules) + "\n"
