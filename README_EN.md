# DO Editor (DO编辑器)

[![Download](https://img.shields.io/badge/Download-v2.2.3-0a84ff?style=for-the-badge&logo=github)](https://github.com/GMY2811/DO-Editor/releases/download/v2.2.3/DO-Editor-Setup-v2.2.3.exe)
[![Release](https://img.shields.io/github/v/release/GMY2811/DO-Editor?style=for-the-badge&logo=github)](https://github.com/GMY2811/DO-Editor/releases/latest)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge)](LICENSE)

A lightweight PDF reader and editor for Windows, built with Python + PySide6 + PyMuPDF. It supports reading, annotating, merging, splitting, signing, watermarking, and more, and can open Word documents.

Developer: RAY <gmy.2811@gmail.com>

[简体中文](README.md)

## Download & Install (Recommended)

**Windows users do not need Python — just download the installer and run it.**

Go to the [Releases](../../releases) page, download the latest `DO编辑器-Setup-v*.exe` installer, and double-click to install.

- Supports Windows 10 / 11
- Installer is ~35 MB; ~105 MB on disk after installation
- Optionally associate PDF files with DO Editor during setup
- Includes an uninstaller (via Control Panel or Start Menu)

### Run from Source (Developers)

Requires Python 3.9+. Install the dependencies and run:

```bash
pip install PySide6 PyMuPDF pywin32
python main.py
```

## Features

- **Reading**: continuous scrolling, zoom, page navigation, thumbnail sidebar, multi-tab, clean fullscreen mode
- **Editing**: highlight, underline, strikethrough, rectangle, line, freehand drawing, text (font/size/color), replace text, insert image
- **Merge / Split**: merge multiple files, split by page range / every N pages, extract specific pages
- **Signature**: handwritten signature, text signature, signature library (save/reuse)
- **Watermark**: text watermark (size/color/opacity/rotation/tiled)
- **Copy / Search**: drag to select text and copy, Ctrl+C / Ctrl+V, search with highlighted results
- **Open Word**: convert .docx/.doc to PDF via local Microsoft Word
- **Multilingual**: Chinese / English UI switching
- **Print**: print page by page

## Tech Stack

- [PySide6](https://pypi.org/project/PySide6/) (Qt GUI)
- [PyMuPDF](https://pypi.org/project/PyMuPDF/) (PDF rendering and editing core)
- [pywin32](https://pypi.org/project/pywin32/) (Word conversion, optional)

## Build

```bash
# Build as onedir
python -m PyInstaller --noconfirm "DO编辑器.spec"

# Compile the installer with Inno Setup (optional; requires Inno Setup 6)
ISCC.exe installer.iss
```

## Project Structure

```
main.py          entry point
main_window.py   main window (multi-tab, toolbar, menus)
document_view.py document view (continuous scrolling, editing logic)
page_view.py     page canvas (rendering, selection, annotation)
backend.py       PDF core logic (render/merge/split/annotate/watermark/Word)
sign_dialog.py   signature canvas, signature library
i18n.py          Chinese/English switching
theme.py         light/dark themes
icons.py         vector icons
```

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

> The MuPDF core engine is AGPL-licensed, so this project is also open-sourced under AGPL-3.0.
> Free for personal and internal use; for closed-source commercial distribution, contact Artifex for a MuPDF commercial license.
