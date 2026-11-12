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
from PySide6.QtWidgets import QApplication

#: Appmappen (ui/ → projektroten).
PROJECT_DIR: Path = Path(__file__).resolve().parent.parent

#: Färger (matchar appikonen).
NAVY: str = "#12284b"
NAVY_DEEP: str = "#0f2140"
GOLD: str = "#d4a017"
GOLD_LIGHT: str = "#f0c24a"

#: Typografi, spacing och fokustillstånd som delas av vyerna.
HEADER_PT: int = 17          # vyernas huvudrubrik
ICON_HEADER_PX: int = 28     # ikonstorlek bredvid huvudrubriken
MARGIN: int = 16
SPACING: int = 10
CONTROL_RADIUS_PX: int = 7
PANEL_RADIUS_PX: int = 10
FOCUS_RING_PX: int = 2
TABLE_ROW_HEIGHT_COMPACT: int = 32
TABLE_ROW_HEIGHT_COMFORTABLE: int = 42
TABLE_CELL_PADDING_COMPACT_PX: int = 4
TABLE_CELL_PADDING_COMFORTABLE_PX: int = 7


def fit_dialog_to_screen(
    dialog,
    preferred_width: int,
    preferred_height: int,
    *,
    minimum_width: int = 360,
    minimum_height: int = 280,
    margin: int = 40,
) -> tuple[int, int]:
    """Clamp a resizable dialog to the available screen while keeping its footer visible."""
    try:
        screen = dialog.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        if available is None:
            return int(preferred_width), int(preferred_height)
        max_width = max(1, available.width() - margin)
        max_height = max(1, available.height() - margin)
        width = min(max_width, max(1, int(preferred_width)))
        height = min(max_height, max(1, int(preferred_height)))
        dialog.setMinimumSize(
            min(width, max(1, int(minimum_width))),
            min(height, max(1, int(minimum_height))),
        )
        dialog.resize(width, height)
        return width, height
    except Exception:
        return int(preferred_width), int(preferred_height)


#: Typsnittskedja per plattform. Första familjen som faktiskt finns
#: installerad används — annars ser appen olika ut på Windows, macOS
#: och Linux (Qt faller annars tillbaka på en slumpmässig standard).
FONT_STACKS: dict[str, tuple[str, ...]] = {
    "windows": ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "Arial"),
    "macos": (
        "SF Pro Text", "SF Pro Display", ".AppleSystemUIFont",
        "Helvetica Neue", "Helvetica", "Arial",
    ),
    "linux": (
        "Inter", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans",
        "Liberation Sans", "Arial",
    ),
}
#: Gemensam reserv om plattformens egna typsnitt saknas (t.ex. minimal
#: container eller server utan skrivbordstypsnitt).
FONT_FALLBACKS: tuple[str, ...] = (
    "Noto Sans", "DejaVu Sans", "Liberation Sans", "Arial", "sans-serif",
)

_FONT_CACHE: dict[str, str] = {}


def current_platform() -> str:
    """'windows' | 'macos' | 'linux' — utan att importera main_window."""
    import platform as _platform

    name = _platform.system().lower()
    if name == "darwin":
        return "macos"
    return "windows" if name == "windows" else "linux"


def installed_font_families() -> set[str]:
    """Familjer Qt faktiskt känner till (tom mängd utan Qt/app).

    QFontDatabase kräver en QGuiApplication. Anropas den innan appen
    finns avbryter Qt processen direkt (Fatal Python error: Aborted),
    vilket inte går att fånga med try/except — därför kontrolleras
    instansen först. Moduler som läser typsnittet vid import får då
    plattformens förstahandsval i stället för att krascha.
    """
    try:
        from PySide6.QtGui import QFontDatabase, QGuiApplication

        if QGuiApplication.instance() is None:
            return set()
        return {str(name) for name in QFontDatabase.families()}
    except Exception:
        return set()


def ui_font_family(platform: str = "") -> str:
    """Första installerade familjen i plattformens typsnittskedja.

    Resultatet cachas: QFontDatabase.families() är billigt men anropas
    från många vyer. Saknas alla kända familjer returneras den första
    reserven, så Qt får en rimlig kedja även på en bar maskin.
    """
    key = platform or current_platform()
    cached = _FONT_CACHE.get(key)
    if cached:
        return cached
    stack = FONT_STACKS.get(key, ()) + FONT_FALLBACKS
    available = installed_font_families()
    if not available:
        # Ingen Qt-app ännu: svara med plattformens förstahandsval men
        # cacha inte, så att det riktiga valet görs när appen finns.
        return stack[0]
    chosen = next(
        (family for family in stack if family in available), stack[0]
    )
    _FONT_CACHE[key] = chosen
    return chosen


def ui_font(size: int = 11, weight: QFont.Weight | None = None) -> QFont:
    """Appens typsnitt i given storlek — samma familj överallt."""
    font = QFont(ui_font_family(), int(size))
    if weight is not None:
        font.setWeight(weight)
    return font


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


def tray_icon_path() -> Path:
    """Monokrom ikon för systemfältet (används på macOS)."""
    return PROJECT_DIR / "app_icon_tray.png"


def tray_icon() -> QIcon | None:
    """Ikon för systemfältet, anpassad efter OS.

    macOS visar menylinjens ikoner som masker — där används den
    monokroma varianten (svart + alfa) så OS:et självt färgar den
    rätt i ljust och mörkt läge. Windows/Linux vill ha den färgade
    appikonen, eftersom deras systemfält inte maskar bilden.
    """
    icon = QIcon()
    if current_platform() == "macos" and tray_icon_path().is_file():
        pix = QPixmap(str(tray_icon_path()))
        if not pix.isNull():
            for size in (16, 18, 22, 32, 44, 64):
                scaled = pix.scaled(
                    size, size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                icon.addPixmap(scaled)
        if not icon.isNull():
            # Maskläge: macOS ritar ikonen i menylinjens färg.
            icon.setIsMask(True)
            return icon
    return load_app_icon()


def logotype_path(dark_background: bool = False) -> Path:
    """Logotypen (SVG, vektor) för ljus eller mörk bakgrund."""
    name = (
        "fakturabunten-logotyp-mork-bakgrund.svg"
        if dark_background else "fakturabunten-logotyp.svg"
    )
    return PROJECT_DIR / "brand" / name


def logotype_pixmap(width: int = 460, dark_background: bool = False) -> QPixmap:
    """Logotypen som pixmap (vektorn ritas i valfri bredd).

    SVG:en renderas med Qt:s SVG-motor; saknas den (eller filen)
    returneras en tom pixmap och anroparen kan falla tillbaka på
    appikonen i stället.
    """
    path = logotype_path(dark_background)
    if not path.is_file():
        return QPixmap()
    try:
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QPixmap()
        size = renderer.defaultSize()
        if size.width() <= 0 or size.height() <= 0:
            return QPixmap()
        height = max(1, round(int(width) * size.height() / size.width()))
        pix = QPixmap(int(width), height)
        pix.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QPainter

        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        return pix
    except Exception:
        return QPixmap()


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
    return ui_font(pt, QFont.Weight.Bold)
