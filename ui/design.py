# -*- coding: utf-8 -*-
"""
design — gemensamma designtokens och ikonhjälpare för hela appen.

EN källa för: appikonens sökväg/pixmap, rubrikstorlek och de
accentfärger som återkommer i vyerna (marinblått + guld, samma
som appikonen). Vyerna importerar härifrån i stället för att
kopiera sökvägar och storlekar — då ser allt likadant ut överallt.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon, QPixmap

#: Appmappen (ui/ → projektroten).
PROJECT_DIR: Path = Path(__file__).resolve().parent.parent

#: Färger (matchar appikonen).
NAVY: str = "#12284b"
NAVY_DEEP: str = "#0f2140"
GOLD: str = "#d4a017"
GOLD_LIGHT: str = "#f0c24a"

#: Typografi/spacing som delas av vyerna.
HEADER_PT: int = 17          # vyernas huvudrubrik
ICON_HEADER_PX: int = 28     # ikonstorlek bredvid huvudrubriken
MARGIN: int = 16
SPACING: int = 10


def app_icon_path() -> Path:
    """Huvudikonen (PNG, 1024×1024 RGBA)."""
    return PROJECT_DIR / "app_icon.png"


def app_icon_ico_path() -> Path:
    """Windows-ikon med flera storlekar, för genvägar och HWND-ikoner."""
    return PROJECT_DIR / "app_icon.ico"


def load_app_icon() -> QIcon | None:
    """Laddar samma flerupplösta ikon till fönster, dialoger och tray.

    PNG är huvudkällan för Qt:s skalning. ICO och SVG följer med som
    plattforms-/vektorreserv, så alla startvägar använder samma motiv.
    """
    icon = QIcon()
    png = app_icon_path()
    if png.is_file():
        source = QPixmap(str(png))
        if not source.isNull():
            for size in (16, 20, 24, 32, 48, 64, 128, 256):
                icon.addPixmap(
                    source.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
    for name in ("app_icon.ico", "app_icon.svg"):
        path = PROJECT_DIR / name
        if path.is_file():
            icon.addFile(str(path))
    return None if icon.isNull() else icon


def app_icon_pixmap(size: int = ICON_HEADER_PX) -> QPixmap:
    """Ikonen som pixmap i given storlek (tom pixmap om fil saknas)."""
    pix = QPixmap(str(app_icon_path()))
    if pix.isNull():
        return pix
    return pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def header_font(pt: int = HEADER_PT) -> QFont:
    """Fet rubrikfont för vyernas huvudrubriker."""
    return QFont("Segoe UI", pt, QFont.Weight.Bold)
