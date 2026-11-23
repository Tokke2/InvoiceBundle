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
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QGuiApplication,
    QIcon,
    QIconEngine,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QLayout, QLayoutItem, QWidget

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


class FlowLayout(QLayout):
    """Responsiv radbrytande layout så knappar och filter aldrig klipps."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        spacing: int = 6,
        margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(*margins)

    def __del__(self) -> None:
        while self.count():
            self.takeAt(0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, max(1, width), 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        spacing = max(0, self.spacing())

        for item in self._items:
            widget = item.widget()
            if widget is not None and widget.isHidden():
                continue
            sz = item.sizeHint()
            next_x = x + sz.width() + spacing
            if next_x - spacing > effective.right() and line_height > 0:
                x = effective.x()
                y += line_height + spacing
                next_x = x + sz.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), sz))
            x = next_x
            line_height = max(line_height, sz.height())

        return y + line_height - rect.y() + m.bottom()


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
MONO_FONT_STACK: tuple[str, ...] = (
    "JetBrains Mono", "Cascadia Mono", "Consolas", "SF Mono",
    "DejaVu Sans Mono", "Liberation Mono", "monospace",
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


def ui_font_css_stack(platform: str = "") -> str:
    """CSS-typsnittskedja med vald plattformsfamilj först."""
    primary = ui_font_family(platform)
    stack = [primary]
    for fam in FONT_STACKS.get(platform or current_platform(), ()) + FONT_FALLBACKS:
        if fam not in stack:
            stack.append(fam)
    quoted = [
        f'"{fam}"' if (" " in fam or fam.startswith(".")) else fam
        for fam in stack
    ]
    return ",".join(quoted)


def mono_font_family() -> str:
    """Bästa tillgängliga monospaced-familj för loggar/tracebacks."""
    available = installed_font_families()
    if not available:
        return MONO_FONT_STACK[0]
    return next(
        (fam for fam in MONO_FONT_STACK if fam in available),
        MONO_FONT_STACK[-1],
    )


def effective_dpr(dpr: float | None = None, widget: Optional[QWidget] = None) -> float:
    """Returnerar aktiv skärms DPI-skalfaktor (>= 1.0) för skarp grafik."""
    if dpr is not None:
        try:
            return max(1.0, float(dpr))
        except (TypeError, ValueError):
            return 1.0
    try:
        if widget is not None:
            scr = widget.screen()
            if scr is not None:
                return max(1.0, float(scr.devicePixelRatio()))
    except Exception:
        pass
    try:
        inst = QGuiApplication.instance()
        if inst is not None:
            scr = inst.primaryScreen()
            if scr is not None:
                return max(1.0, float(scr.devicePixelRatio()))
    except Exception:
        pass
    return 1.0


def ui_font(size: int = 11, weight: QFont.Weight | None = None) -> QFont:
    """Appens typsnitt i given storlek — samma familj överallt, skarp hinting."""
    font = QFont(ui_font_family(), int(size))
    if weight is not None:
        font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def app_icon_path() -> Path:
    """Huvudikonen (PNG, 1024×1024 RGBA)."""
    return PROJECT_DIR / "app_icon.png"


def app_icon_svg_path() -> Path:
    """Huvudikonen i vektorformat (SVG)."""
    return PROJECT_DIR / "app_icon.svg"


def app_icon_ico_path() -> Path:
    """Windows-ikon med flera storlekar, för genvägar och HWND-ikoner."""
    return PROJECT_DIR / "app_icon.ico"


def _render_app_svg_pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    svg_path = app_icon_svg_path()
    if not svg_path.is_file():
        return QPixmap()
    try:
        from PySide6.QtSvg import QSvgRenderer

        renderer = QSvgRenderer(str(svg_path))
        if not renderer.isValid():
            return QPixmap()
        scale = max(1.0, float(dpr))
        px = max(1, int(round(max(1, int(size)) * scale)))
        pix = QPixmap(px, px)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(0, 0, px, px))
        painter.end()
        if scale > 1.0:
            pix.setDevicePixelRatio(scale)
        return pix
    except Exception:
        return QPixmap()


class _AppIconEngine(QIconEngine):
    """Vektorskarp QIconEngine för appikonen (SVG först, PNG-reserv)."""

    _SIZES: tuple[int, ...] = (16, 20, 24, 32, 48, 64, 128, 256)

    def paint(  # noqa: N802
        self,
        painter: QPainter,
        rect: QRect,
        mode: QIcon.Mode,
        state: QIcon.State,
    ) -> None:
        if rect.isEmpty():
            return
        svg_path = app_icon_svg_path()
        if svg_path.is_file():
            try:
                from PySide6.QtSvg import QSvgRenderer

                renderer = QSvgRenderer(str(svg_path))
                if renderer.isValid():
                    painter.save()
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                    painter.setRenderHint(
                        QPainter.RenderHint.SmoothPixmapTransform, True
                    )
                    side = float(min(rect.width(), rect.height()))
                    target = QRectF(
                        rect.x() + (rect.width() - side) / 2.0,
                        rect.y() + (rect.height() - side) / 2.0,
                        side,
                        side,
                    )
                    renderer.render(painter, target)
                    painter.restore()
                    return
            except Exception:
                pass
        side = max(1, min(rect.width(), rect.height()))
        dpr = 1.0
        try:
            dev = painter.device()
            if dev is not None and hasattr(dev, "devicePixelRatioF"):
                dpr = max(1.0, float(dev.devicePixelRatioF()))
        except Exception:
            pass
        pm = app_icon_pixmap(side, dpr=dpr)
        if not pm.isNull():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(rect, pm)
            painter.restore()

    def pixmap(  # noqa: N802
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State
    ) -> QPixmap:
        return self.scaledPixmap(size, mode, state, effective_dpr())

    def scaledPixmap(  # noqa: N802
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float
    ) -> QPixmap:
        side = max(1, min(int(size.width()) or 32, int(size.height()) or 32))
        return app_icon_pixmap(side, dpr=max(1.0, float(scale)))

    def availableSizes(  # noqa: N802
        self,
        mode: QIcon.Mode = QIcon.Mode.Normal,
        state: QIcon.State = QIcon.State.Off,
    ) -> list[QSize]:
        return [QSize(s, s) for s in self._SIZES]

    def clone(self) -> "_AppIconEngine":
        return _AppIconEngine()


def load_app_icon() -> QIcon | None:
    """Laddar samma knivskarpa vektor-/flerupplösta ikon till fönster, dialoger och tray."""
    if app_icon_svg_path().is_file():
        icon = QIcon(_AppIconEngine())
        if not icon.isNull():
            return icon
    icon = QIcon()
    png = app_icon_path()
    if png.is_file():
        source = QPixmap(str(png))
        if not source.isNull():
            for size in (16, 20, 24, 32, 48, 64, 128, 256):
                for scale in (1, 2):
                    px = size * scale
                    pm = source.scaled(
                        px,
                        px,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    if scale > 1:
                        pm.setDevicePixelRatio(float(scale))
                    icon.addPixmap(pm)
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


def logotype_pixmap(
    width: int = 460,
    dark_background: bool = False,
    dpr: float | None = None,
) -> QPixmap:
    """Logotypen som skarp DPR-medveten vektor-pixmap i valfri bredd."""
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
        scale = effective_dpr(dpr)
        logical_w = max(1, int(width))
        logical_h = max(1, round(logical_w * size.height() / size.width()))
        pw = max(1, int(round(logical_w * scale)))
        ph = max(1, int(round(logical_h * scale)))
        pix = QPixmap(pw, ph)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(0, 0, pw, ph))
        painter.end()
        if scale > 1.0:
            pix.setDevicePixelRatio(scale)
        return pix
    except Exception:
        return QPixmap()


def app_icon_pixmap(
    size: int = ICON_HEADER_PX,
    dpr: float | None = None,
) -> QPixmap:
    """Ikonen som skarp DPR-medveten vektor-pixmap (PNG-reserv om SVG saknas)."""
    scale = effective_dpr(dpr)
    logical = max(1, int(size))
    svg_pix = _render_app_svg_pixmap(logical, dpr=scale)
    if not svg_pix.isNull():
        return svg_pix
    pix = QPixmap(str(app_icon_path()))
    if pix.isNull():
        return pix
    px = max(1, int(round(logical * scale)))
    scaled = pix.scaled(
        px, px,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    if scale > 1.0:
        scaled.setDevicePixelRatio(scale)
    return scaled


def header_font(pt: int = HEADER_PT) -> QFont:
    """Fet rubrikfont för vyernas huvudrubriker."""
    return ui_font(pt, QFont.Weight.Bold)
