# -*- coding: utf-8 -*-
"""
Tester: nya appikonen + designmodulen.

Ikonen ska finnas i alla format (PNG/ICO/SVG), vara samma motiv
och kunna laddas av både Qt-laddaren och vyernas rubriker.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def test_icon_files_exist_and_are_valid():
    from PIL import Image

    png = PROJECT_DIR / "app_icon.png"
    ico = PROJECT_DIR / "app_icon.ico"
    svg = PROJECT_DIR / "app_icon.svg"
    for f in (png, ico, svg):
        assert f.is_file() and f.stat().st_size > 500, f

    img = Image.open(png)
    assert img.size[0] >= 512 and img.mode == "RGBA"
    assert img.getpixel((2, 2))[3] == 0  # genomskinligt hörn

    ico_img = Image.open(ico)
    sizes = ico_img.info.get("sizes", set())
    assert (256, 256) in sizes and (16, 16) in sizes

    svg_text = svg.read_text(encoding="utf-8")
    assert "#12284b" in svg_text.lower() or "#16305a" in svg_text.lower()
    assert "circle" in svg_text  # guldbadgen


def test_design_module_and_qt_icon_loading():
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui import design

    assert design.app_icon_path().name == "app_icon.png"
    pix = design.app_icon_pixmap(28)
    assert not pix.isNull()
    assert pix.width() == 28
    assert design.HEADER_PT == 17
    assert design.GOLD.startswith("#")

    from ui.main_window import _load_app_icon

    icon = _load_app_icon()
    assert icon is not None and not icon.isNull()
    assert icon.availableSizes()
