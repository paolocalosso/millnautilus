# Millnautilus

File explorer GTK4/libadwaita con vista a colonne (Miller view), ispirato a Nautilus.

## Funzionalità

- **Miller columns**: navigazione a colonne affiancate; selezionando una cartella si apre la colonna successiva
- **Sidebar**: Home e cartelle XDG, cestino, file system, dischi/volumi (GVolumeMonitor), mount di rete, connessione a server SFTP/SMB via GVfs, preferiti (bookmarks GTK condivisi con Nautilus)
- **Pannello destro** con toggle in header bar:
  - *Anteprima*: immagini, file di testo, thumbnail di sistema per PDF/documenti
  - *Informazioni*: tipo, dimensione, data, permessi, proprietario, percorso, numero elementi
- **Operazioni file**: copia/taglia/incolla, rinomina, cestino, nuova cartella, apri con, drag & drop tra colonne (drop = sposta, di default)
- File nascosti con `Ctrl+H`

## Scorciatoie

| Tasti | Azione |
|---|---|
| `Ctrl+C` / `Ctrl+X` / `Ctrl+V` | Copia / Taglia / Incolla |
| `F2` | Rinomina |
| `Canc` | Sposta nel cestino |
| `Ctrl+Shift+N` | Nuova cartella |
| `Ctrl+H` | Mostra file nascosti |
| `F5` / `Ctrl+R` | Ricarica |
| `Ctrl+Q` | Esci |

## Dipendenze

Debian/Ubuntu:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gvfs-backends
```

Fedora:

```bash
sudo dnf install python3-gobject gtk4 libadwaita gvfs-fuse gvfs-sftp
```

Arch:

```bash
sudo pacman -S python-gobject gtk4 libadwaita gvfs gvfs-sftp gvfs-smb
```

Richiede GTK ≥ 4.10 e libadwaita ≥ 1.5 (per `Adw.AlertDialog`/`AboutDialog` con `present(window)`).

## Avvio

```bash
python3 millnautilus.py
```

## Note

- L'anteprima PDF/documenti usa le thumbnail generate dal sistema (`thumbnail::path`); se non esiste ancora una thumbnail viene mostrata l'icona del tipo file
- I preferiti sono letti/scritti in `~/.config/gtk-3.0/bookmarks`, lo stesso file usato da Nautilus
- Le connessioni SFTP usano GVfs: le credenziali sono chieste da `Gtk.MountOperation` e gestite dal portachiavi di sistema

## Struttura

```
millnautilus.py           entry point
millnautilus/
  app.py                 Adw.Application
  window.py              finestra, header bar, azioni e scorciatoie
  miller.py              MillerView (contenitore colonne)
  column.py              MillerColumn (singola colonna, DnD, menu contestuale)
  sidebar.py             sidebar (posizioni, volumi, SFTP, preferiti)
  preview.py             pannello anteprima/informazioni
  fileops.py             operazioni file async via Gio
  models.py              FileItem (Gio.File + Gio.FileInfo)
```
