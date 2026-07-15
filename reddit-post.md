# Suggested title

**I vibe-coded Millnautilus: a GTK4/libadwaita file explorer with Miller columns (macOS-style column view)**

# Post body

Hi r/gnome!

I've always missed a proper column view (Miller columns) in Nautilus, so I decided to build my own little file explorer around that idea: **Millnautilus**, written in Python with GTK4 and libadwaita.

Full disclosure up front: **this project is entirely vibe-coded** — I described what I wanted, iterated on screenshots and feedback, and let AI write the code. I'm sharing it as a fun experiment, not as a polished production app. That said, it already does quite a lot:

* **Miller columns navigation** — select a folder and the next column opens; each column is resizable by dragging its edge, and has its **own sort order** (name, size, creation/modification date, persisted per directory)
* **"Computer" overview** as the start page — cards for places, disks with usage bars, network mounts and bookmark chips, inspired by the excellent [nautilus-my-computer](https://github.com/yannmasoch/nautilus-my-computer)
* **Sidebar** with XDG places, drives (GVolumeMonitor), SFTP/SMB via GVfs, and bookmarks shared with Nautilus
* **Preview/details panel** with a toggle: image and text previews, system thumbnails for documents, detailed file info, prev/next arrows to flick through files
* File operations: copy/cut/paste, rename, trash, new folder, drag & drop between columns, context menus everywhere
* **`org.freedesktop.FileManager1` D-Bus interface**, a `.desktop` entry with `inode/directory` handler — so it can act as your default file manager, including "Show in folder" from browsers
* Window size, panel state and per-folder sorting are all remembered between sessions

It follows your GTK theme and icon theme (looks great with Fluent + a custom dark theme, which is what I use).

Repo: https://github.com/paolocalosso/millnautilus

It's Python + PyGObject, no build step: clone it, install `python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gvfs-backends`, run `python3 millnautilus.py`.

I'd love feedback — especially from people who miss column view in GNOME as much as I do. Bug reports welcome, but keep expectations calibrated: it's a vibe-coded weekend project that grew features fast. 😄
