from __future__ import annotations

"""
Fakturabunten — Import-vy för skannade fakturor
======================================================
Fil    : Fakturabunten_/ui/scan_import_view.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Import-fliken: läser in skannade fakturor (PDF/bild), visar vad som
tolkades och låter användaren bekräfta/rätta INNAN fakturan skapas.

Kärnan i appen är oförändrad — ange fakturor, räkna ihop ATT BETALA.
Den här vyn är bara en snabbväg in till samma registrering.

Flöde
─────
    1. Dra in filer / välj filer / klistra in text
    2. "Läs in och tolka"  → visar tabell med kandidater
    3. Markera rad → "Skapa faktura" → fakturan registreras
       (belopp läggs till ATT BETALA precis som vid manuell inmatning)

Allt loggas som SCAN_IMPORT / SCAN_CREATE i logs/app.log.

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
import re
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QGroupBox, QTextEdit, QMessageBox, QFileDialog, QFrame,
    QLineEdit, QCheckBox, QApplication, QInputDialog,
    QDialog, QListWidget, QPlainTextEdit, QComboBox, QMenu,
    QGridLayout, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QRectF, QSizeF, QSize
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QIcon, QImage, QPixmap,
    QPainter, QPen,
)

try:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
except Exception:  # pragma: no cover - skrivarstöd saknas
    QPrintDialog = QPrinter = None  # type: ignore[assignment]

try:
    from ui.design import ICON_HEADER_PX, app_icon_pixmap
except Exception:  # pragma: no cover - fristående körning
    try:
        from design import ICON_HEADER_PX, app_icon_pixmap  # type: ignore[no-redef]
    except Exception:
        ICON_HEADER_PX = 28  # type: ignore[no-redef]

        def app_icon_pixmap(size: int = 28):  # type: ignore[no-redef]
            from PySide6.QtGui import QPixmap as _QP
            return _QP()

log = logging.getLogger("ScanImportView")

try:
    from ui.i18n import tr, tr_list, tr_missing
except Exception:  # pragma: no cover
    try:
        from i18n import tr, tr_list, tr_missing  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_fmt: object) -> str:  # type: ignore[no-redef]
            return key

        def tr_list(key: str) -> list:  # type: ignore[no-redef]
            return []

        def tr_missing(fields: list) -> str:  # type: ignore[no-redef]
            return ", ".join(map(str, fields))

COPYRIGHT_YEAR: int = datetime.date.today().year

#: Kolumner i tolkningstabellen: (rubrik, nyckel, bredd, justering)
COLUMNS: list[tuple[str, str, int, Any]] = [
    ("Fil",            "file",           170, Qt.AlignmentFlag.AlignLeft),
    ("Leverantör",     "supplier",       140, Qt.AlignmentFlag.AlignLeft),
    ("Fakturanr",      "invoice_number", 100, Qt.AlignmentFlag.AlignLeft),
    ("Datum",          "date",            90, Qt.AlignmentFlag.AlignLeft),
    ("Förfaller",      "due_date",        90, Qt.AlignmentFlag.AlignLeft),
    ("OCR",            "ocr",            110, Qt.AlignmentFlag.AlignLeft),
    ("Belopp",         "total_amount",   100, Qt.AlignmentFlag.AlignRight),
    ("Metod",          "method",         120, Qt.AlignmentFlag.AlignLeft),
    ("Status",         "status",         110, Qt.AlignmentFlag.AlignLeft),
]


#: Radfärger för matchningssäkerhet i importtabellen:
#: (mörkt tema, ljust tema). OSÄKER matchning = röd rad, SÄKER
#: matchning = grön rad — samma röda/gröna princip och palett
#: som Fakturor-flikens radfärger (Förfallen/Betald). Rader utan
#: någon matchning alls (okänt format) lämnas neutrala — de får
#: i stället mall-dialogen direkt.
ROW_BG_MATCH_UNCERTAIN = ("#3b1113", "#fdecea")
ROW_BG_MATCH_SECURE = ("#0f2e17", "#e8f5e9")


def _supplier_monogram(name: str) -> str:
    """Logotyp-monom för leverantörsvalet: första bokstäverna ur
    namnets två första ord ("Martin G Anderson" → "MG")."""
    words = [
        w for w in re.split(r"[\s\-/]+", str(name or ""))
        if w and any(c.isalpha() for c in w)
    ]
    if not words:
        return "?"
    initials = "".join(w[0] for w in words[:2])
    return initials.upper()


#: Palett för leverantörernas logotyp-rutor (samma namn ger
#: alltid samma färg, så leverantören känns igen visuellt).
_SUPPLIER_TILE_COLORS: tuple[str, ...] = (
    "#1565c0", "#6a1b9a", "#00838f", "#2e7d32", "#ad1457",
    "#4e342e", "#37474f", "#283593", "#00695c", "#bf360c",
)


def _supplier_tile_pixmap(name: str, size: int = 44) -> QPixmap:
    """Ritar leverantörens logotyp-ruta: färgad rundad platta med
    monogrammet — igenkänning på en blick i matchningsdialogen."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        idx = sum(ord(c) for c in str(name or "")) % len(
            _SUPPLIER_TILE_COLORS
        )
        painter.setBrush(QColor(_SUPPLIER_TILE_COLORS[idx]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(
            1, 1, size - 2, size - 2, 9, 9
        )
        painter.setPen(QColor("#ffffff"))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * 0.36))
        painter.setFont(font)
        painter.drawText(
            pixmap.rect(), Qt.AlignmentFlag.AlignCenter,
            _supplier_monogram(name),
        )
    finally:
        painter.end()
    return pixmap


def _fmt_amount(value: float) -> str:
    """45546.0 → '45 546,00' (svenskt format)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    kr = int(v)
    frac = int(round((v - kr) * 100))
    return f"{kr:,}".replace(",", " ") + f",{frac:02d}"


def _parse_amount(text: str) -> float:
    """Tolerant parsning av '45 546,00' / '45546.50' → float."""
    t = (text or "").replace(" ", "").replace("\u00a0", "")
    t = t.replace("kr", "").replace("SEK", "").replace(",", ".")
    try:
        return abs(float(t))
    except ValueError:
        return 0.0


def _scan_module():
    """Laddar plugins/scan_import.py (samma sökvägstrick som vyn)."""
    import sys

    plugins_dir = str(Path(__file__).resolve().parent.parent / "plugins")
    if plugins_dir not in sys.path:
        sys.path.insert(0, plugins_dir)
    import scan_import as si

    return si


def print_invoice_document(path: Any, printer: Any) -> int:
    """Skriver ut en fakturafils alla sidor på vald skrivare.

    Sidorna renderas som bilder (samma rendering som
    malldialogen använder) och RITAS mot sidans utskriftsyta
    med bibehållna proportioner, centrerat — bilden skalas
    aldrig upp till skrivarens fulla enhetsupplösning (en
    1200-dpi-skrivare skulle annars få en gigantisk bild och
    utskriften kan hänga sig eller komma ut tom). Returnerar
    antalet utskrivna sidor — 0 om filen inte kan visas.
    """
    if printer is None:
        return 0
    si = _scan_module()
    pages = si.page_image_count(path)
    if pages <= 0:
        return 0
    painter = QPainter(printer)
    printed = 0
    try:
        if not painter.isActive():
            return 0
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, True
        )
        rect = QRectF(
            printer.pageLayout().paintRectPixels(printer.resolution())
        )
        for idx in range(pages):
            data = si.render_page_image(path, idx, dpi=200)
            if not data:
                continue
            img = QImage.fromData(data)
            if img.isNull():
                continue
            if printed and not printer.newPage():
                break
            size = QSizeF(img.size()).scaled(
                rect.size(), Qt.AspectRatioMode.KeepAspectRatio
            )
            target = QRectF(
                rect.x() + (rect.width() - size.width()) / 2,
                rect.y() + (rect.height() - size.height()) / 2,
                size.width(), size.height(),
            )
            painter.drawImage(target, img)
            printed += 1
    finally:
        painter.end()
    return printed


#: Fält i malldialogen (ordning = visning).
_TEMPLATE_FIELDS = (
    "invoice_number", "total_amount", "date", "due_date", "ocr",
)


def _infer_label(text_before: str) -> str:
    """
    Härleder etiketten före en markering: sista textbiten på raden,
    max 5 ord / 40 tecken, utan avslutande kolon.
    """
    line = (text_before or "").rsplit("\n", 1)[-1]
    cand = re.split(r"\s{2,}", line)[-1].strip()
    cand = cand.strip(":# \t").strip()
    words = cand.split()
    cand = " ".join(words[-5:])[:40].rstrip(":# ").strip()
    return cand


#: Fältfärger i bildmarkeringsdialogen.
_FIELD_COLORS = {
    "invoice_number": "#2563eb",
    "date": "#059669",
    "due_date": "#d97706",
    "total_amount": "#dc2626",
    "ocr": "#7c3aed",
}


class _RegionImageView(QWidget):
    """Fakturabild där användaren drar rutor runt värden.

    En sida i taget; rutorna hanteras som andelar (0–1) av
    sidans bredd/höjd och ritas i fältens färger. Signalen
    region_drawn(fält, sidindex, (x0, y0, x1, y1)) avges när
    en ruta är färdigritad.
    """

    region_drawn = Signal(str, int, tuple)
    zoom_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(350, 420)
        self._pixmap: QPixmap | None = None
        self._page = 0
        self._regions: dict[str, tuple[int, tuple]] = {}
        self._active = ""
        self._drag_a: tuple[float, float] | None = None
        self._drag_b: tuple[float, float] | None = None
        # Zoom: 1.0 = hela sidan anpassad; _focus = bildandelen
        # i vycentret. Panorera med höger musknapp.
        self._zoom = 1.0
        self._focus: tuple[float, float] = (0.5, 0.5)
        self._pan_last = None

    def set_page(self, pixmap: QPixmap | None, page: int) -> None:
        self._pixmap = pixmap
        self._page = page
        self._drag_a = self._drag_b = None
        self._pan_last = None
        self._zoom = 1.0
        self._focus = (0.5, 0.5)
        self.zoom_changed.emit(self._zoom)
        self.update()

    def set_regions(self, regions: dict) -> None:
        self._regions = dict(regions or {})
        self.update()

    def set_active(self, field: str) -> None:
        self._active = field or ""
        self.update()

    # ── Koordinater ───────────────────────────────────────────
    def _img_rect(self) -> QRectF | None:
        if self._pixmap is None or self._pixmap.isNull():
            return None
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        size = self._pixmap.size().scaled(
            area.size().toSize(), Qt.AspectRatioMode.KeepAspectRatio
        )
        w = float(size.width()) * self._zoom
        h = float(size.height()) * self._zoom
        center = area.center()
        if w <= area.width():
            left = center.x() - w / 2
        else:
            left = min(
                max(center.x() - self._focus[0] * w,
                    area.right() - w),
                area.left(),
            )
        if h <= area.height():
            top = center.y() - h / 2
        else:
            top = min(
                max(center.y() - self._focus[1] * h,
                    area.bottom() - h),
                area.top(),
            )
        return QRectF(left, top, w, h)

    # ── Zoom / panorering ────────────────────────────────────
    def set_zoom(self, zoom: float) -> None:
        self._zoom = min(max(float(zoom), 1.0), 8.0)
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.3)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.3)

    def zoom_fit(self) -> None:
        self._focus = (0.5, 0.5)
        self.set_zoom(1.0)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt-namn)
        if self._pixmap is None or self._pixmap.isNull():
            return
        delta = event.angleDelta().y()
        if not delta:
            return
        frac = self._fraction(event.position())
        if frac is not None:
            self._focus = frac  # zooma mot pekaren
        self.set_zoom(self._zoom * (1.25 if delta > 0 else 1 / 1.25))
        event.accept()

    def _fraction(self, pos) -> tuple[float, float] | None:
        rect = self._img_rect()
        if rect is None:
            return None
        x = min(max(pos.x(), rect.left()), rect.right())
        y = min(max(pos.y(), rect.top()), rect.bottom())
        return (
            (x - rect.left()) / rect.width(),
            (y - rect.top()) / rect.height(),
        )

    def _rect_px(self, frac: tuple) -> QRectF:
        img = self._img_rect()
        x0, y0, x1, y1 = frac
        return QRectF(
            img.left() + x0 * img.width(),
            img.top() + y0 * img.height(),
            (x1 - x0) * img.width(),
            (y1 - y0) * img.height(),
        )

    @staticmethod
    def _norm(
        a: tuple[float, float], b: tuple[float, float]
    ) -> tuple[float, float, float, float]:
        return (
            min(a[0], b[0]), min(a[1], b[1]),
            max(a[0], b[0]), max(a[1], b[1]),
        )

    # ── Rita ──────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt-namn)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#dde2e8"))
        img = self._img_rect()
        if img is None:
            painter.setPen(QColor("#5b6470"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                tr("tmpl.no_image"),
            )
            return
        painter.fillRect(img, QColor("white"))
        painter.drawPixmap(img.toRect(), self._pixmap)
        painter.setPen(QPen(QColor("#8a939e"), 1))
        painter.drawRect(img)
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        for field, (page, frac) in self._regions.items():
            if page != self._page:
                continue
            color = QColor(_FIELD_COLORS.get(field, "#333333"))
            rubrik = self._rect_px(frac)
            fill = QColor(color)
            fill.setAlpha(45)
            painter.fillRect(rubrik, fill)
            painter.setPen(QPen(color, 2.5))
            painter.drawRect(rubrik)
            label = tr(f"tmpl.field_{field}")
            painter.setFont(font)
            tw = painter.fontMetrics().horizontalAdvance(label) + 8
            tag = QRectF(
                rubrik.left(), max(img.top(), rubrik.top() - 16),
                float(tw), 16.0,
            )
            painter.fillRect(tag, color)
            painter.setPen(QColor("white"))
            painter.drawText(
                tag, Qt.AlignmentFlag.AlignCenter, label
            )
        if self._drag_a and self._drag_b and self._active:
            color = QColor(_FIELD_COLORS.get(self._active, "#333333"))
            rubrik = self._rect_px(
                self._norm(self._drag_a, self._drag_b)
            )
            painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine))
            painter.drawRect(rubrik)

    # ── Mus ───────────────────────────────────────────────────
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._pan_last = event.position()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        if not self._active:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        frac = self._fraction(event.position())
        if frac is not None:
            self._drag_a = self._drag_b = frac
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_last is not None:
            pos = event.position()
            rect = self._img_rect()
            if rect is not None:
                dx = (pos.x() - self._pan_last.x()) / max(
                    rect.width(), 1.0)
                dy = (pos.y() - self._pan_last.y()) / max(
                    rect.height(), 1.0)
                self._focus = (
                    min(max(self._focus[0] - dx, 0.0), 1.0),
                    min(max(self._focus[1] - dy, 0.0), 1.0),
                )
            self._pan_last = pos
            self.update()
            return
        if self._drag_a is None:
            return
        frac = self._fraction(event.position())
        if frac is not None:
            self._drag_b = frac
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.RightButton
            and self._pan_last is not None
        ):
            self._pan_last = None
            self.unsetCursor()
            return
        if self._drag_a is None or self._drag_b is None:
            return
        rect = self._norm(self._drag_a, self._drag_b)
        self._drag_a = self._drag_b = None
        if rect[2] - rect[0] > 0.004 and rect[3] - rect[1] > 0.003:
            self.region_drawn.emit(self._active, self._page, rect)
        self.update()


class TemplateDialog(QDialog):
    """
    Skapa/redigera en leverantörsmall mot fakturans BILD.

    Flöde: välj ett fält → dra en ruta runt värdet på bilden →
    värdet i rutan visas direkt (samma läsning som skanningen
    använder: textlager i rutan, annars OCR). Rutorna sparas
    som andelar av sidan + sidnummer:

        {"supplier": namn,
         "fields": {fält: {"region": [x0, y0, x1, y1], "page": n}}}

    Gamla etikettfält i en befintlig mall bevaras oförändrade
    för fält som inte markeras om på bilden.
    """

    def __init__(
        self,
        parent: QWidget | None,
        text: str = "",
        supplier: str = "",
        existing: dict | None = None,
        path: Any = None,
    ) -> None:
        super().__init__(parent)
        self._text = text or ""
        self._path = Path(path) if path else None
        self.result_template: dict | None = None
        si = _scan_module()
        self._page_count = (
            si.page_image_count(self._path) if self._path else 0
        )
        self._page = 0
        self._pixmaps: dict[int, QPixmap] = {}
        self._existing_fields: dict = dict(
            (existing or {}).get("fields", {}) or {}
        )
        self._regions: dict[str, tuple[int, tuple]] = {}
        for field, spec in self._existing_fields.items():
            if not isinstance(spec, dict):
                continue
            region = spec.get("region")
            if (
                isinstance(region, (list, tuple))
                and len(region) == 4
            ):
                try:
                    page = int(spec.get("page", 0) or 0)
                except (TypeError, ValueError):
                    page = 0
                try:
                    self._regions[field] = (
                        page,
                        tuple(float(v) for v in region),
                    )
                except (TypeError, ValueError):
                    continue
        self._active = ""

        self.setWindowTitle(tr("tmpl.title", supplier=supplier or "…"))
        self.setMinimumSize(980, 640)
        root = QVBoxLayout(self)
        root.setSpacing(8)

        row_sup = QHBoxLayout()
        row_sup.addWidget(QLabel(tr("tmpl.supplier")))
        self._supplier_edit = QLineEdit(supplier)
        row_sup.addWidget(self._supplier_edit, stretch=1)
        root.addLayout(row_sup)

        intro = QLabel(tr("tmpl.intro_image"))
        intro.setWordWrap(True)
        root.addWidget(intro)

        middle = QHBoxLayout()
        middle.setSpacing(10)

        left = QVBoxLayout()
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀")
        self._btn_prev.clicked.connect(
            lambda: self._goto_page(self._page - 1)
        )
        nav.addWidget(self._btn_prev)
        self._lbl_page = QLabel()
        self._lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav.addWidget(self._lbl_page, stretch=1)
        self._btn_next = QPushButton("▶")
        self._btn_next.clicked.connect(
            lambda: self._goto_page(self._page + 1)
        )
        nav.addWidget(self._btn_next)
        nav.addSpacing(12)
        self._btn_zoom_out = QPushButton("−")
        self._btn_zoom_out.setToolTip(tr("tmpl.zoom_out"))
        self._btn_zoom_out.setMaximumWidth(34)
        nav.addWidget(self._btn_zoom_out)
        self._lbl_zoom = QLabel("100 %")
        self._lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_zoom.setMinimumWidth(46)
        nav.addWidget(self._lbl_zoom)
        self._btn_zoom_in = QPushButton("+")
        self._btn_zoom_in.setToolTip(tr("tmpl.zoom_in"))
        self._btn_zoom_in.setMaximumWidth(34)
        nav.addWidget(self._btn_zoom_in)
        self._btn_zoom_fit = QPushButton(tr("tmpl.zoom_fit"))
        nav.addWidget(self._btn_zoom_fit)
        left.addLayout(nav)
        self._view = _RegionImageView()
        self._view.region_drawn.connect(self._on_region_drawn)
        self._btn_zoom_out.clicked.connect(self._view.zoom_out)
        self._btn_zoom_in.clicked.connect(self._view.zoom_in)
        self._btn_zoom_fit.clicked.connect(self._view.zoom_fit)
        self._view.zoom_changed.connect(self._on_zoom_changed)
        left.addWidget(self._view, stretch=1)
        lbl_zoom_hint = QLabel(tr("tmpl.zoom_hint"))
        lbl_zoom_hint.setWordWrap(True)
        left.addWidget(lbl_zoom_hint)
        middle.addLayout(left, stretch=3)

        right = QVBoxLayout()
        right.addWidget(QLabel(tr("tmpl.fields_header")))
        self._previews: dict[str, QLabel] = {}
        self._mark_buttons: dict[str, QPushButton] = {}
        for field in _TEMPLATE_FIELDS:
            row = QHBoxLayout()
            chip = QLabel("■")
            chip.setStyleSheet(
                f"color:{_FIELD_COLORS.get(field, '#333')};"
                "font-size:15px;background:transparent;"
            )
            row.addWidget(chip)
            texts = QVBoxLayout()
            name_lbl = QLabel(tr(f"tmpl.field_{field}"))
            name_lbl.setStyleSheet(
                "font-weight:bold;background:transparent;"
            )
            texts.addWidget(name_lbl)
            prev = QLabel()
            prev.setMinimumWidth(120)
            texts.addWidget(prev)
            row.addLayout(texts, stretch=1)
            btn = QPushButton(tr("tmpl.mark"))
            btn.clicked.connect(
                lambda _c=False, f=field: self._set_active(f)
            )
            row.addWidget(btn)
            right.addLayout(row)
            self._previews[field] = prev
            self._mark_buttons[field] = btn
        right.addStretch(1)
        middle.addLayout(right, stretch=2)
        root.addLayout(middle, stretch=1)

        self._lbl_hint = QLabel()
        self._lbl_hint.setWordWrap(True)
        root.addWidget(self._lbl_hint)

        row_btn = QHBoxLayout()
        btn_clear = QPushButton(tr("tmpl.clear_marks"))
        btn_clear.clicked.connect(self._clear_marks)
        row_btn.addWidget(btn_clear)
        btn_test = QPushButton(tr("tmpl.test"))
        btn_test.clicked.connect(self._test_all)
        row_btn.addWidget(btn_test)
        row_btn.addStretch()
        btn_cancel = QPushButton(f"✖  {tr('common.cancel')}")
        btn_cancel.clicked.connect(self.reject)
        row_btn.addWidget(btn_cancel)
        btn_save = QPushButton(tr("tmpl.save"))
        btn_save.setProperty("success", True)
        btn_save.clicked.connect(self._save)
        row_btn.addWidget(btn_save)
        root.addLayout(row_btn)

        self._view.set_regions(self._regions)
        self._reload_page()
        self._set_active(
            next(
                (f for f in _TEMPLATE_FIELDS if f not in self._regions),
                _TEMPLATE_FIELDS[0],
            )
        )
        self._test_all()

    # ── Sidor ─────────────────────────────────────────────────
    def _on_zoom_changed(self, zoom: float) -> None:
        self._lbl_zoom.setText(f"{int(round(zoom * 100))} %")

    def _goto_page(self, page: int) -> None:
        self._page = min(max(page, 0), max(self._page_count - 1, 0))
        self._reload_page()

    def _reload_page(self) -> None:
        pixmap = self._pixmaps.get(self._page)
        if pixmap is None and self._path is not None:
            si = _scan_module()
            data = si.render_page_image(
                self._path, self._page, dpi=200
            )
            pixmap = QPixmap()
            if data:
                pixmap.loadFromData(data)
            self._pixmaps[self._page] = pixmap
        self._view.set_page(pixmap, self._page)
        self._lbl_page.setText(
            tr(
                "tmpl.page", n=self._page + 1,
                total=max(self._page_count, 1),
            )
        )
        self._btn_prev.setEnabled(self._page > 0)
        self._btn_next.setEnabled(self._page + 1 < self._page_count)

    # ── Markering ─────────────────────────────────────────────
    def _set_active(self, field: str) -> None:
        self._active = field
        self._view.set_active(field)
        for f, btn in self._mark_buttons.items():
            btn.setText(
                tr("tmpl.marked") if f in self._regions
                else tr("tmpl.mark")
            )
            btn.setStyleSheet(
                "font-weight:bold;" if f == field else ""
            )

    def _on_region_drawn(
        self, field: str, page: int, rect: tuple
    ) -> None:
        self._regions[field] = (page, tuple(rect))
        self._view.set_regions(self._regions)
        self._preview_field(field)
        nxt = next(
            (f for f in _TEMPLATE_FIELDS if f not in self._regions),
            field,
        )
        self._set_active(nxt)

    def _clear_marks(self) -> None:
        self._regions = {}
        self._view.set_regions(self._regions)
        self._set_active(_TEMPLATE_FIELDS[0])
        self._test_all()

    # ── Förhandsvisning / spara ───────────────────────────────
    def _rules(self) -> dict:
        rules: dict[str, dict] = {}
        for field in _TEMPLATE_FIELDS:
            if field in self._regions:
                page, rect = self._regions[field]
                rules[field] = {
                    "region": [round(float(v), 4) for v in rect],
                    "page": page,
                }
            else:
                spec = self._existing_fields.get(field)
                if (
                    isinstance(spec, dict)
                    and str(spec.get("label", "")).strip()
                ):
                    rules[field] = {
                        "label": str(spec["label"]).strip()
                    }
        return rules

    def _preview_field(self, field: str) -> None:
        si = _scan_module()
        if field in self._regions:
            page, rect = self._regions[field]
            template = {
                "fields": {
                    field: {"region": list(rect), "page": page}
                }
            }
            found = si.template_values_from_regions(
                template,
                si.extract_region_texts(self._path, template),
            )
            self._set_preview(field, found.get(field), page)
            return
        spec = self._existing_fields.get(field)
        if isinstance(spec, dict) and spec.get("label"):
            found = si.apply_template(
                self._text, {"fields": {field: spec}}
            )
            self._set_preview(field, found.get(field))
            return
        self._set_preview(field, None)

    def _test_all(self) -> None:
        for field in _TEMPLATE_FIELDS:
            self._preview_field(field)

    def _set_preview(
        self, field: str, value: Any, page: int | None = None
    ) -> None:
        lbl = self._previews[field]
        if value in (None, "", 0, 0.0):
            lbl.setText(tr("tmpl.not_found"))
            lbl.setStyleSheet(
                "color:#d29922;background:transparent;"
            )
        else:
            shown = (
                _fmt_amount(float(value))
                if field == "total_amount"
                else str(value)
            )
            text = tr("tmpl.found", value=shown)
            if page:
                text += " · " + tr("tmpl.page_note", n=page + 1)
            lbl.setText(text)
            lbl.setStyleSheet(
                "color:#3fb950;background:transparent;"
            )

    def _save(self) -> None:
        supplier = self._supplier_edit.text().strip()
        if not supplier:
            self._lbl_hint.setText(tr("tmpl.need_supplier"))
            self._supplier_edit.setFocus()
            return
        rules = self._rules()
        if not rules:
            self._lbl_hint.setText(tr("tmpl.need_field"))
            return
        self.result_template = {
            "supplier": supplier, "fields": rules
        }
        self.accept()


class TemplatesManagerDialog(QDialog):
    """Lista sparade mallar; radera/redigera/skapa via callbacks."""

    def __init__(
        self, parent: QWidget | None, templates: dict,
        on_delete: Any, on_edit: Any = None, on_create: Any = None,
    ) -> None:
        super().__init__(parent)
        self._templates = templates
        self._on_delete = on_delete
        self._on_edit = on_edit
        self._on_create = on_create
        self.setWindowTitle(tr("tmpl.manager_title"))
        self.setMinimumSize(520, 360)
        root = QVBoxLayout(self)
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(
            lambda _item: self._edit_selected()
        )
        root.addWidget(self._list, stretch=1)
        row = QHBoxLayout()
        if on_create is not None:
            btn_new = QPushButton(tr("tmpl.new"))
            btn_new.clicked.connect(self._create_new)
            row.addWidget(btn_new)
        if on_edit is not None:
            btn_edit = QPushButton(tr("tmpl.edit"))
            btn_edit.clicked.connect(self._edit_selected)
            row.addWidget(btn_edit)
        btn_del = QPushButton(tr("tmpl.delete"))
        btn_del.clicked.connect(self._delete_selected)
        row.addWidget(btn_del)
        row.addStretch()
        btn_close = QPushButton(f"✖  {tr('common.cancel')}")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        root.addLayout(row)
        self._refresh_list()

    def _selected_name(self) -> str:
        row = self._list.currentRow()
        names = sorted(self._templates)
        if row < 0 or row >= len(names):
            return ""
        return names[row]

    def _edit_selected(self) -> None:
        if self._on_edit is None:
            return
        name = self._selected_name()
        if not name:
            return
        self._on_edit(name)
        self._refresh_list()

    def _create_new(self) -> None:
        if self._on_create is None:
            return
        self._on_create()
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        if not self._templates:
            self._list.addItem(tr("tmpl.manager_empty"))
            return
        for name in sorted(self._templates):
            fields = (self._templates[name] or {}).get("fields", {})
            self._list.addItem(tr(
                "tmpl.manager_entry", supplier=name,
                n=len(fields), fields=", ".join(fields.keys()),
            ))

    def _delete_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0 or not self._templates:
            return
        names = sorted(self._templates)
        if row >= len(names):
            return
        self._on_delete(names[row])
        self._refresh_list()


class ScanImportView(QWidget):
    """
    Import-vy för skannade fakturor.

    Integritet: läser bara filer användaren själv väljer, skickar
    aldrig något över nätet, sparar inget förrän användaren klickar
    "Skapa faktura".
    """

    def __init__(
        self, app: Any = None, parent: QWidget | None = None,
        templates_path: Path | None = None,
    ):
        super().__init__(parent)
        self._app = app
        self._rows: list[dict] = []       # tolkade rader
        self._paths: list[Path] = []      # valda filer
        self._dark = True
        self._templates_path = (
            Path(templates_path) if templates_path else None
        )
        self._templates_cache: dict | None = None
        self._learning_cache: dict | None = None
        self._watch = None
        self._build_ui()
        self._init_watch()
        self._log_status()

    # ══════════════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        hdr = QLabel(tr("scan.title"))
        self._hdr_label = hdr
        hdr.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        head = QHBoxLayout()
        head.setSpacing(8)
        _pix = app_icon_pixmap(ICON_HEADER_PX)
        if not _pix.isNull():
            mark = QLabel()
            mark.setPixmap(_pix)
            mark.setStyleSheet("background:transparent;")
            head.addWidget(mark)
        head.addWidget(hdr)
        head.addStretch()
        root.addLayout(head)

        info = QLabel(tr("scan.info"))
        self._info_label = info
        info.setWordWrap(True)
        info.setStyleSheet("color:#8b949e;background:transparent;")
        root.addWidget(info)
        root.addWidget(self._hline())

        # ── 1. Välj filer ─────────────────────────────────────────────
        box_files = QGroupBox(tr("scan.step1"))
        self._box_files = box_files
        bf = QVBoxLayout(box_files)
        bf.setSpacing(8)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        btn_pick = QPushButton(tr("scan.pick"))
        self._btn_pick = btn_pick
        btn_pick.clicked.connect(self._pick_files)
        btn_clear = QPushButton(tr("scan.clear"))
        self._btn_clear = btn_clear
        btn_clear.clicked.connect(self._clear_paths)
        self._lbl_files = QLabel(tr("scan.no_files"))
        self._lbl_files.setStyleSheet("color:#8b949e;background:transparent;")
        row1.addWidget(btn_pick)
        row1.addWidget(btn_clear)
        row1.addWidget(self._lbl_files, stretch=1)
        bf.addLayout(row1)

        self._txt_paths = QTextEdit()
        self._txt_paths.setReadOnly(True)
        self._txt_paths.setMaximumHeight(70)
        self._txt_paths.setPlaceholderText(
            "Valda filer visas här (du kan också klistra in sökvägar, "
            "en per rad)"
        )
        bf.addWidget(self._txt_paths)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        btn_scan = QPushButton(tr("scan.scan"))
        self._btn_scan = btn_scan
        btn_scan.setProperty("accent", True)
        btn_scan.setMinimumHeight(42)
        btn_scan.clicked.connect(self._scan_files)
        # ── Bevakade mappar: auto-import från leverantörsmappar ──
        box_watch = QGroupBox(tr("watch.title"))
        self._box_watch = box_watch
        bw = QVBoxLayout()
        bw.setContentsMargins(10, 8, 10, 8)
        lbl_winfo = QLabel(tr("watch.info"))
        self._lbl_watch_info = lbl_winfo
        lbl_winfo.setWordWrap(True)
        lbl_winfo.setStyleSheet("color:#5a6b80;")
        bw.addWidget(lbl_winfo)
        self._lst_watch = QListWidget()
        self._lst_watch.setMaximumHeight(96)
        bw.addWidget(self._lst_watch)
        wr = QHBoxLayout()
        self._btn_add_folder = QPushButton(tr("watch.add_folder"))
        self._btn_add_folder.clicked.connect(self._add_watch_folder)
        self._btn_remove_folder = QPushButton(tr("watch.remove_folder"))
        self._btn_remove_folder.clicked.connect(self._remove_watch_folder)
        self._chk_auto_watch = QCheckBox(tr("watch.auto_create"))
        self._chk_auto_watch.setChecked(True)
        self._chk_auto_watch.stateChanged.connect(self._toggle_watch_auto)
        wr.addWidget(self._btn_add_folder)
        wr.addWidget(self._btn_remove_folder)
        wr.addWidget(self._chk_auto_watch)
        wr.addStretch(1)
        bw.addLayout(wr)
        wr2 = QHBoxLayout()
        self._lbl_watch_parked = QLabel()
        self._btn_review_parked = QPushButton(tr("watch.review"))
        self._btn_review_parked.clicked.connect(self._review_parked)
        wr2.addWidget(self._lbl_watch_parked)
        wr2.addWidget(self._btn_review_parked)
        self._btn_teach_folder = QPushButton(tr("watch.learn"))
        self._btn_teach_folder.clicked.connect(
            self._teach_from_folder_clicked
        )
        wr2.addWidget(self._btn_teach_folder)
        self._btn_scan_watch = QPushButton(tr("watch.scan_now"))
        self._btn_scan_watch.clicked.connect(self._scan_watch_now)
        wr2.addWidget(self._btn_scan_watch)
        self._btn_control_scan = QPushButton(tr("watch.control_scan"))
        self._btn_control_scan.clicked.connect(self._control_scan_now)
        wr2.addWidget(self._btn_control_scan)
        wr2.addStretch(1)
        bw.addLayout(wr2)
        box_watch.setLayout(bw)
        root.addWidget(box_watch)

        self._lbl_status = QLabel(tr("scan.ready"))
        self._lbl_status.setStyleSheet("color:#8b949e;background:transparent;")
        row2.addWidget(btn_scan)
        row2.addWidget(self._lbl_status, stretch=1)
        bf.addLayout(row2)
        root.addWidget(box_files)

        # ── 2. Klistra in text (manuell fallback) ─────────────────────
        box_txt = QGroupBox(tr("scan.step2"))
        self._box_txt = box_txt
        bt = QVBoxLayout(box_txt)
        bt.setSpacing(6)
        self._txt_paste = QTextEdit()
        self._txt_paste.setPlaceholderText(
            "Klistra in texten från fakturan här om OCR inte är "
            "installerat eller misslyckas.\n\n"
            "Exempel:\nFakturanr: 2026-144\nFakturadatum: 2026-08-17\n"
            "Förfallodatum: 2026-09-16\nAtt betala: 45 546,00"
        )
        self._txt_paste.setMaximumHeight(110)
        bt.addWidget(self._txt_paste)

        rowt = QHBoxLayout()
        rowt.setSpacing(8)
        btn_parse = QPushButton(tr("scan.parse"))
        self._btn_parse = btn_parse
        btn_parse.clicked.connect(self._scan_pasted)
        self._chk_auto = QCheckBox(tr("scan.auto_open"))
        self._chk_auto.setChecked(False)
        rowt.addWidget(btn_parse)
        rowt.addWidget(self._chk_auto)
        rowt.addStretch(1)
        bt.addLayout(rowt)
        root.addWidget(box_txt)

        # ── 3. Tolkade rader ──────────────────────────────────────────
        box_res = QGroupBox(tr("scan.step3"))
        self._box_res = box_res
        br = QVBoxLayout(box_res)
        br.setSpacing(8)

        self._tbl = QTableWidget(0, len(COLUMNS))
        _scan_headers = tr_list("scan.columns")
        self._tbl.setHorizontalHeaderLabels(
            _scan_headers
            if len(_scan_headers) == len(COLUMNS)
            else [c[0] for c in COLUMNS]
        )
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setAlternatingRowColors(True)
        self._tbl.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._tbl.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._tbl.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._tbl.setWordWrap(False)
        self._tbl.doubleClicked.connect(self._open_row_dialog)
        self._tbl.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._tbl.customContextMenuRequested.connect(
            self._table_context_menu
        )
        hh = self._tbl.horizontalHeader()
        for i, (_lbl, _key, width, _al) in enumerate(COLUMNS):
            self._tbl.setColumnWidth(i, width)
            hh.setSectionResizeMode(
                i, QHeaderView.ResizeMode.Interactive
            )
        hh.setStretchLastSection(True)
        self._tbl.setMinimumHeight(220)
        br.addWidget(self._tbl, stretch=1)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        btn_create = QPushButton(tr("scan.create"))
        self._btn_create = btn_create
        btn_create.setProperty("success", True)
        btn_create.setMinimumHeight(42)
        btn_create.clicked.connect(self._create_invoices)
        btn_open_dlg = QPushButton(tr("scan.open_dialog"))
        self._btn_open_dlg = btn_open_dlg
        btn_open_dlg.clicked.connect(self._open_row_dialog)
        btn_print = QPushButton(tr("scan.print"))
        self._btn_print = btn_print
        btn_print.clicked.connect(self._print_row)
        btn_open_orig = QPushButton(tr("scan.open_original"))
        self._btn_open_orig = btn_open_orig
        btn_open_orig.clicked.connect(self._open_original_row)
        btn_del = QPushButton(tr("scan.remove_row"))
        self._btn_del = btn_del
        btn_del.clicked.connect(self._remove_row)
        self._btn_template = QPushButton(tr("scan.template_btn"))
        self._btn_template.clicked.connect(self._open_template_dialog)
        self._btn_templates = QPushButton()
        self._btn_templates.clicked.connect(self._open_templates_manager)
        self._lbl_sum = QLabel()
        self._lbl_sum.setStyleSheet(
            "background:transparent;font-weight:700;"
        )
        row3.addWidget(btn_create)
        row3.addWidget(btn_open_dlg)
        row3.addWidget(btn_print)
        row3.addWidget(btn_open_orig)
        row3.addWidget(btn_del)
        row3.addWidget(self._btn_template)
        row3.addWidget(self._btn_templates)
        row3.addWidget(self._lbl_sum, stretch=1)
        self._refresh_templates_btn()
        br.addLayout(row3)
        root.addWidget(box_res, stretch=1)

        # ── Logg-utdrag ───────────────────────────────────────────────
        self._lbl_log = QLabel()
        self._lbl_log.setStyleSheet(
            "color:#8b949e;background:transparent;font-size:11px;"
        )
        self._lbl_log.setWordWrap(True)
        root.addWidget(self._lbl_log)

        footer = QLabel(
            f"© {COPYRIGHT_YEAR} Rickard Längkvist  —  "
            f"Fakturabunten  ·  allt körs lokalt"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color:#8b949e;background:transparent;")
        root.addWidget(footer)

    def retranslate(self) -> None:
        """Uppdaterar vyns texter efter språkbyte (utan omstart)."""
        self._hdr_label.setText(tr("scan.title"))
        self._info_label.setText(tr("scan.info"))
        self._box_files.setTitle(tr("scan.step1"))
        self._box_txt.setTitle(tr("scan.step2"))
        self._box_res.setTitle(tr("scan.step3"))
        self._btn_pick.setText(tr("scan.pick"))
        self._btn_clear.setText(tr("scan.clear"))
        if not self._paths:
            self._lbl_files.setText(tr("scan.no_files"))
        self._btn_scan.setText(tr("scan.scan"))
        self._btn_parse.setText(tr("scan.parse"))
        self._chk_auto.setText(tr("scan.auto_open"))
        self._btn_create.setText(tr("scan.create"))
        self._btn_open_dlg.setText(tr("scan.open_dialog"))
        self._btn_print.setText(tr("scan.print"))
        self._btn_open_orig.setText(tr("scan.open_original"))
        self._btn_del.setText(tr("scan.remove_row"))
        self._btn_template.setText(tr("scan.template_btn"))
        self._refresh_templates_btn()
        _scan_headers = tr_list("scan.columns")
        if len(_scan_headers) == len(COLUMNS):
            self._tbl.setHorizontalHeaderLabels(_scan_headers)
        if hasattr(self, "_box_watch"):
            self._box_watch.setTitle(tr("watch.title"))
            self._lbl_watch_info.setText(tr("watch.info"))
            self._btn_add_folder.setText(tr("watch.add_folder"))
            self._btn_remove_folder.setText(tr("watch.remove_folder"))
            self._chk_auto_watch.setText(tr("watch.auto_create"))
            self._btn_review_parked.setText(tr("watch.review"))
            self._btn_teach_folder.setText(tr("watch.learn"))
            self._btn_control_scan.setText(tr("watch.control_scan"))
            self._refresh_watch_ui()
        self._refresh_table()

    @staticmethod
    def _hline() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet("color:#30363d;")
        return f

    # ══════════════════════════════════════════════════════════════════
    #  STATUS / LOGG
    # ══════════════════════════════════════════════════════════════════

    # ── Bevakade mappar (auto-import) ───────────────────────────────
    def _init_watch(self) -> None:
        """Startar mappbevakningen; får aldrig krascha vyn."""
        try:
            from ui.watch_folders import WatchManager
            cfg = self._templates_file().parent / "watch_folders.json"
            self._watch = WatchManager(
                cfg,
                app=self._app,
                templates_provider=self._get_templates,
                parent=self,
            )
            # Parkerade filer samlas och meddelas i EN dialog
            # per skanningsomgång — otolkbara fakturor ska
            # aldrig försvinna tyst i parkeringen.
            self._parked_notify: list[dict] = []
            self._parked_timer = QTimer(self)
            self._parked_timer.setSingleShot(True)
            self._parked_timer.timeout.connect(self._show_parked_dialog)
            self._watch.invoice_ready.connect(self._on_watch_invoice)
            self._watch.file_parked.connect(self._on_watch_parked)
            self._watch.changed.connect(self._refresh_watch_ui)
            self._chk_auto_watch.setChecked(self._watch.auto_create)
            self._refresh_watch_ui()
            # Osäkra parkeringar hör hemma i Import-tabellen —
            # lägg in dem direkt (även från tidigare körningar).
            QTimer.singleShot(0, self._collect_uncertain_parked)
        except Exception as exc:
            log.warning("WatchManager start: %s", exc)

    def _on_watch_parked(self, info: dict) -> None:
        """Ny parkerad fil från bevakningen — samla till en
        gemensam informationsdialog (startar om nedräkningen
        så en skanningsrunda ger exakt en dialog)."""
        self._refresh_watch_ui()
        if not hasattr(self, "_parked_notify"):
            return
        self._parked_notify.append(dict(info or {}))
        self._parked_timer.start(2500)

    def _show_parked_dialog(self) -> None:
        """Dialog: de här filerna kunde inte tolkas.

        Visar filnamn + orsak på svenska och vägen vidare
        (Granska i tabellen). Tömmer kön så samma filer
        aldrig larmar igen.
        """
        infos = getattr(self, "_parked_notify", [])
        self._parked_notify = []
        if not infos:
            return
        from ui.watch_folders import _park_reason_sv
        lines = []
        for info in infos[:8]:
            name = info.get("file") or Path(
                str(info.get("path", ""))
            ).name
            lines.append(
                f"• {name} — {_park_reason_sv(info.get('reason', ''))}"
            )
        if len(infos) > 8:
            lines.append(
                tr("watch.parked_dialog_more", n=len(infos) - 8)
            )
        QMessageBox.warning(
            self, tr("watch.parked_dialog_title"),
            tr(
                "watch.parked_dialog",
                n=len(infos), files="\n".join(lines),
            ),
        )
        # Osäkra matchningar läggs DIREKT i Import-tabellen som
        # röda rader och frågas om där — användaren avgör dem i
        # tabellen (välj leverantör via logotyp/dropdown), och
        # avbryts frågan blir raden kvar i sikte i tabellen i
        # stället för att bara ligga gömd i parkeringen. Appen
        # gissar aldrig och parkerar aldrig tyst.
        added = self._add_parked_rows_to_table(infos)
        for row in added:
            if row.get("match_uncertain") and self._ask_user_for_match(row):
                self._unpark_row(row)
        if added:
            self._refresh_table()
            self._lbl_status.setText(
                tr("scan.parked_added_table", n=len(added))
            )
        # Parkeringar som inte kunde läggas i tabellen (t.ex.
        # saknad tolkning) frågas det om på den äldre vägen.
        added_paths = {str(r.get("_path", "")) for r in added}
        leftover = [
            i for i in infos
            if str(i.get("path", "")) not in added_paths
            and isinstance(i.get("parsed"), dict)
            and i["parsed"].get("match_uncertain")
        ]
        if leftover:
            self._ask_uncertain_parked(leftover)
        # Varje okänt format ska erbjudas en mall direkt i
        # appen — användaren ska inte behöva leta fram rätt
        # knapp själv. En fråga per leverantör och runda.
        self._offer_create_templates_for_parked(infos)

    def _offer_create_templates_for_parked(
        self, infos: list[dict]
    ) -> None:
        """Frågar (en gång per leverantör) om en mall ska skapas
        för parkerade filer vars format inte kändes igen.

        Vid Ja öppnas matchningsdialogen med just den parkerade
        fakturans bild; när mallen sparats skannas mappen om så
        filerna prövas — och registreras — av sig själva.
        """
        try:
            from ui.watch_folders import _norm_path_key
        except Exception:
            return
        watch = getattr(self, "_watch", None)
        if watch is None:
            return
        folders = [
            f for f in (getattr(watch, "folders", []) or [])
            if isinstance(f, dict)
        ]
        if not folders:
            return
        seen: set[str] = set()
        for info in infos:
            reason = str(info.get("reason", "") or "")
            if not (
                reason == "no-template"
                or reason.startswith("missing")
            ):
                continue
            file_path = str(info.get("path", "") or "")
            if not file_path:
                continue
            fkey = _norm_path_key(file_path)
            entry = None
            for f in folders:
                root = _norm_path_key(str(f.get("path", "")))
                if root and (
                    fkey == root or fkey.startswith(root + "/")
                ):
                    entry = f
                    break
            if entry is None:
                continue
            supplier = str(entry.get("supplier", "") or "").strip()
            if not supplier:
                parsed = info.get("parsed") or {}
                supplier = str(
                    parsed.get("supplier", "") or ""
                ).strip()
            dedupe = (supplier or file_path).lower()
            if dedupe in seen:
                continue
            seen.add(dedupe)
            name = info.get("file") or Path(file_path).name
            answer = QMessageBox.question(
                self,
                tr("watch.learn_title"),
                tr(
                    "watch.parked_learn_offer",
                    file=name,
                    supplier=supplier or "okänd leverantör",
                ),
            )
            if answer != QMessageBox.StandardButton.Yes:
                continue
            teach_entry = dict(entry)
            if supplier:
                teach_entry["supplier"] = supplier
            self._teach_from_folder(
                teach_entry, example=Path(file_path), force=True
            )

    def _refresh_watch_ui(self) -> None:
        if not hasattr(self, "_lst_watch"):
            return
        watch = self._watch
        self._lst_watch.clear()
        if not watch or not watch.folders:
            self._lst_watch.addItem(tr("watch.no_folders"))
        else:
            for f in watch.folders:
                sup = f.get("supplier") or tr("watch.folder_no_supplier")
                self._lst_watch.addItem(
                    tr("watch.folder_entry", supplier=sup,
                       path=f.get("path", ""))
                )
        n = len(watch.parked) if watch else 0
        self._lbl_watch_parked.setText(
            tr("watch.parked", n=n) if n else ""
        )
        self._btn_review_parked.setEnabled(bool(n))

    def _add_watch_folder(self) -> None:
        if not self._watch:
            return
        from ui.watch_folders import WatchFolderDialog
        names = sorted(
            {s.get("name", "") for s in self._suppliers()
             if s.get("name")}
        )
        dlg = WatchFolderDialog(self, names)
        if dlg.exec() and dlg.result_data:
            self._watch.set_folders(
                list(self._watch.folders) + [dlg.result_data]
            )
            self._maybe_offer_teach(dlg.result_data)

    def _remove_watch_folder(self) -> None:
        if not self._watch:
            return
        row = self._lst_watch.currentRow()
        folders = list(self._watch.folders)
        if 0 <= row < len(folders):
            del folders[row]
            self._watch.set_folders(folders)

    def _scan_watch_now(self) -> None:
        """Manuell skanning av alla bevakade mappar (knapp).

        Samma skanning som annars sker vid start, mappändring
        och var 30:e sekund — men på begäran, med återkoppling
        i statusraden. Detaljer per fil hamnar i loggen
        (SCAN_WATCH)."""
        if not self._watch:
            return
        if not self._watch.folders:
            self._lbl_status.setText(tr("watch.scan_none"))
            return
        self._watch.scan_all()
        self._refresh_watch_ui()
        stats = self._watch.last_scan_stats
        self._lbl_status.setText(
            tr(
                "watch.scan_done",
                imported=stats.get("imported", 0),
                duplicate=stats.get("duplicate", 0),
                parked=stats.get("parked", 0),
                already=stats.get("already", 0),
            )
        )
        log.info(
            "SCAN_WATCH: manuell skanning klar — %s",
            stats,
        )

    def _control_scan_now(self) -> None:
        """Kontrollskanning (knapp): läs om ÄVEN redan inlästa
        fakturor och jämför mot registret.

        Vanlig skanning hoppar över bearbetade filer; kontrollen
        tolkar dem på nytt med dagens mallar och rapporterar
        avvikelser (statusraden + loggen), utan att ändra
        något registrerat — rättning sker per faktura i
        Fakturor-fliken via högerklick → Skanna om faktura."""
        if not self._watch:
            return
        if not self._watch.folders:
            self._lbl_status.setText(tr("watch.scan_none"))
            return
        self._watch.scan_all(force=True)
        self._refresh_watch_ui()
        stats = self._watch.last_scan_stats
        self._lbl_status.setText(
            tr(
                "watch.control_done",
                imported=stats.get("imported", 0),
                duplicate=stats.get("duplicate", 0),
                parked=stats.get("parked", 0),
                already=stats.get("already", 0),
                changed=stats.get("changed", 0),
            )
        )
        log.info(
            "SCAN_WATCH: manuell kontrollskanning klar — %s, "
            "avvikelser=%s",
            stats, self._watch.last_control_diffs,
        )

    def _toggle_watch_auto(self, state) -> None:
        if self._watch:
            self._watch.set_auto_create(bool(state))

    def _maybe_year_sort(self, row: dict, path: str) -> str:
        """Årssortera ett original vars faktura just registrerats
        ur granskningen — samma årsmapp (<år>/ under den bevakade
        mappen) som auto-registreringar får. Parkerade rörs inte;
        sker bara när fakturan faktiskt registreras och datumet
        är läsbart. Aldrig ett fel som stoppar registreringen."""
        try:
            from pathlib import Path as _P

            from invoices_helpers import (
                invoice_year, read_watch_folders, sort_into_year_folder,
            )

            year = invoice_year(row.get("date", ""))
            if not year:
                return path
            cfg = _P(self._templates_file()).parent / "watch_folders.json"
            for entry in read_watch_folders(cfg):
                moved = sort_into_year_folder(
                    str(path), str(entry.get("path", "")), year
                )
                if moved != str(path):
                    return moved
        except Exception:
            pass
        return path

    def _on_watch_invoice(self, row: dict, path: str) -> None:
        """Ny komplett faktura från bevakad mapp → registrera direkt.

        Originalfilen lämnas kvar i den bevakade mappen; fakturans
        attachment-fält i JSON pekar på den där (ingen kopia i
        data/attachments/). Flyttas filen före export varnar
        exporten att originalet saknas.
        """
        data = self._invoice_data_from_row(row, attachment=str(path))
        if self._save_invoice(
            data, source=row.get("file", ""), silent=True
        ):
            self._lbl_status.setText(
                tr("watch.imported", file=row.get("file", ""))
            )
        elif self._watch is not None and row.get("_hash"):
            # Registreringen misslyckades — filen får inte bli kvar
            # som bearbetad/importerad utan faktura i registret.
            # Markera om den så nästa skanning prövar igen, och
            # säg det högt i stället för att tappa den tyst.
            self._watch.unprocess(str(row["_hash"]))
            log.error(
                "SCAN_WATCH: registrering av %s misslyckades — "
                "filen prövas igen vid nästa skanning",
                row.get("file", ""),
            )
            self._lbl_status.setText(
                tr("watch.register_failed", file=row.get("file", ""))
            )

    def _selected_watch_entry(self) -> dict | None:
        """Markerad bevakad mapp (finns bara en används den)."""
        if not self._watch:
            return None
        folders = list(self._watch.folders)
        if not folders:
            return None
        row = self._lst_watch.currentRow()
        if 0 <= row < len(folders):
            return folders[row]
        if len(folders) == 1:
            return folders[0]
        return None

    def _teach_from_folder_clicked(self) -> None:
        entry = self._selected_watch_entry()
        if entry is None:
            self._lbl_status.setText(tr("watch.learn_need_folder"))
            return
        self._teach_from_folder(entry)

    def _maybe_offer_teach(self, entry: dict) -> None:
        """Efter mapp-tillägg: erbjud att lära appen leverantören.

        Bara om mappen har en leverantör, innehåller minst en
        fakturafil och det inte redan finns en mall för den —
        aldrig tjat, aldrig gissning.
        """
        supplier = str(entry.get("supplier", "") or "").strip()
        if not supplier:
            return
        try:
            from ui.watch_folders import supported_invoice_files
            if not supported_invoice_files(entry.get("path", "")):
                return
            si = _scan_module()
            if si.find_template(self._get_templates(), supplier):
                return  # mallen finns redan
            if si.has_builtin_format(supplier):
                return  # inbyggt verifierat format — inget att lära
        except Exception as exc:
            log.warning("teach offer: %s", exc)
            return
        answer = QMessageBox.question(
            self,
            tr("watch.learn_title"),
            tr("watch.learn_offer", supplier=supplier),
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._teach_from_folder(entry)

    def _verification_rows(
        self, supplier: str, template: dict, files: list
    ) -> list[dict]:
        """Kör mallen på väntande filer och sammanfattar exakt
        vad den läser ur varje — underlaget för användarens
        säkerhetskontroll. Registrerar ingenting."""
        si = _scan_module()
        rows: list[dict] = []
        for fpath in list(files)[:8]:
            fp = Path(fpath)
            try:
                text, _method = si.extract_text(fp)
            except Exception as exc:
                log.warning("verify extract %s: %s", fp, exc)
                text = ""
            try:
                parsed = si.parse_invoice_file(
                    fp, text or "", self._suppliers(),
                    templates={supplier: template},
                )
            except Exception as exc:
                log.warning("verify parse %s: %s", fp, exc)
                continue
            rows.append({
                "file": fp.name, "path": str(fp),
                "invoice_number": parsed.get("invoice_number", ""),
                "total_amount": parsed.get("total_amount", 0),
                "date": parsed.get("date", ""),
                "due_date": parsed.get("due_date", ""),
                "missing": list(parsed.get("missing", []) or []),
            })
        return rows

    def _verify_template(
        self, supplier: str, template: dict, files: list
    ) -> str:
        """Automatisk säkerhetskontroll av en nyss sparad mall.

        Visar per faktura exakt vad mallen läser och låter
        användaren bekräfta ("bekrafta"), gå tillbaka och
        justera markeringarna ("justera") eller stänga
        ("senare"). Känns mallen inte igen på någon faktura
        sägs det rakt ut högst upp.
        """
        rows = self._verification_rows(supplier, template, files)
        ok = sum(1 for r in rows if not r["missing"])
        lines = [tr("tmpl.verify_intro", supplier=supplier), ""]
        if rows and ok == 0:
            lines.append(tr("tmpl.verify_none"))
            lines.append("")
        lines.append(
            tr("tmpl.verify_counts", ok=ok, n=len(rows))
        )
        for r in rows:
            if r["missing"]:
                lines.append(tr(
                    "tmpl.verify_missing", file=r["file"],
                    missing=", ".join(r["missing"]),
                ))
            else:
                lines.append(tr(
                    "tmpl.verify_line", file=r["file"],
                    nr=r["invoice_number"] or "—",
                    amount=_fmt_amount(float(r["total_amount"] or 0)),
                    date=r["date"] or "—",
                    due=r["due_date"] or "—",
                ))
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("tmpl.verify_title"))
        box.setText("\n".join(lines))
        btn_ok = box.addButton(
            tr("tmpl.verify_ok"), QMessageBox.ButtonRole.AcceptRole
        )
        btn_adjust = box.addButton(
            tr("tmpl.verify_adjust"),
            QMessageBox.ButtonRole.ActionRole,
        )
        box.addButton(
            tr("tmpl.verify_later"),
            QMessageBox.ButtonRole.RejectRole,
        )
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_ok:
            return "bekrafta"
        if clicked is btn_adjust:
            return "justera"
        return "senare"

    def _teach_from_folder(
        self, entry: dict, example: Any = None, force: bool = False
    ) -> bool:
        """Lär appen läsa mappens fakturor från en exempel-PDF.

        Appen skannar en av filerna i mappen; användaren matchar
        manuellt vad som är fakturanummer/belopp/förfallo i
        TemplateDialog ("visa vad som hör till vad"). Mallen
        sparas i data/invoice_templates.json under leverantören
        och används direkt av mappbevakningen.
        """
        supplier0 = str(entry.get("supplier", "") or "").strip()
        if supplier0 and not force:
            _si0 = _scan_module()
            if _si0.has_builtin_format(supplier0):
                # Inbyggt verifierat format (matchat mot riktiga
                # exempelfakturor i förväg) — ingen inlärning,
                # ingen dialog. Meddela bara och låt bevakningen
                # sköta resten.
                self._lbl_status.setText(
                    tr("watch.learn_builtin", supplier=supplier0)
                )
                return False
        from ui.watch_folders import supported_invoice_files
        files = supported_invoice_files(entry.get("path", ""))
        if not files and not example:
            self._lbl_status.setText(tr("watch.learn_no_files"))
            return False
        chosen = Path(example) if example else files[0]
        if not example and len(files) > 1:
            names = [f.name for f in files]
            name, ok = QInputDialog.getItem(
                self,
                tr("watch.learn_title"),
                tr("watch.learn_pick"),
                names, 0, False,
            )
            if not ok:
                return False
            chosen = files[names.index(name)]
        si = _scan_module()
        if si.page_image_count(chosen) <= 0:
            self._lbl_status.setText(
                tr("watch.learn_no_image", file=chosen.name)
            )
            return False
        supplier = str(entry.get("supplier", "") or "")
        templates = self._get_templates()
        existing = (
            si.find_template(templates, supplier) if supplier else None
        )
        dlg = TemplateDialog(
            self, "", supplier=supplier, existing=existing,
            path=chosen,
        )
        if not dlg.exec() or not dlg.result_template:
            return False
        name = dlg.result_template["supplier"]
        templates[name] = {"fields": dlg.result_template["fields"]}
        self._save_templates_file()
        log.info(
            "SCAN_TEMPLATE: mall inlärd från mapp %s → %s",
            entry.get("path", ""), name,
        )

        # Säkerhetskontroll: appen visar automatiskt hur den
        # nya mallen läser mapparnas väntande fakturor och ber
        # användaren kontrollera värdena. Justera → tillbaka
        # till markeringen med mallen ifylld, kontrollera igen.
        action = self._verify_template(
            name, templates[name],
            self._pending_verification_files(name, chosen),
        )
        justera_path = Path(chosen)
        while action == "justera":
            dlg2 = TemplateDialog(
                self, "", supplier=name,
                existing=templates.get(name), path=justera_path,
            )
            if not dlg2.exec() or not dlg2.result_template:
                break
            name = dlg2.result_template["supplier"]
            templates[name] = {
                "fields": dlg2.result_template["fields"]
            }
            self._save_templates_file()
            action = self._verify_template(
                name, templates[name],
                self._pending_verification_files(name, chosen),
            )

        # Minne: mallen ligger i invoice_templates.json och
        # används av både bevakning och manuell import på alla
        # kommande fakturor — det sägs rakt ut i statusraden.
        self._lbl_status.setText(tr("tmpl.remembered", supplier=name))
        # Den nya mallen prövas direkt på mappens parkerade
        # fakturor: de läses om NU ifall de kan använda samma
        # mall. (Vanliga skanningar läser aldrig om parkerade
        # tolkningsfiler — de ligger still tills en mall sparas.)
        if self._watch is not None:
            try:
                self._watch.reprocess_parked(entry)
            except Exception as exc:
                log.warning("teach rescan: %s", exc)
        return True

    def _pending_verification_files(
        self, supplier: str, first: Any = None
    ) -> list[Path]:
        """Exempelfilen + leverantörens parkerade filer (max 8)
        — det säkerhetskontrollen ska pröva mallen mot."""
        files: list[Path] = []
        seen: set[str] = set()

        def _add(fp: Any) -> None:
            key = str(fp or "")
            if key and key not in seen:
                seen.add(key)
                files.append(Path(key))

        if first:
            _add(first)
        watch = getattr(self, "_watch", None)
        if watch is not None:
            try:
                from ui.watch_folders import _norm_path_key
                folders = [
                    f for f in (watch.folders or [])
                    if isinstance(f, dict)
                    and str(f.get("supplier", "")).strip().lower()
                    == supplier.strip().lower()
                ]
                roots = [
                    _norm_path_key(str(f.get("path", "")))
                    for f in folders
                ]
                for parked in list(watch.parked or []):
                    ppath = str(parked.get("path", "") or "")
                    if not ppath:
                        continue
                    key = _norm_path_key(ppath)
                    psup = str(
                        (parked.get("parsed") or {}).get(
                            "supplier", ""
                        ) or ""
                    ).strip().lower()
                    if (
                        psup == supplier.strip().lower()
                        or any(
                            r and key.startswith(r + "/")
                            for r in roots
                        )
                    ):
                        _add(ppath)
            except Exception as exc:
                log.warning("verify files: %s", exc)
        return files[:8]

    @staticmethod
    def _match_candidate_names(row: dict) -> list[str]:
        """Kandidatnamn ur en matchbedömning (strängar eller dicts)."""
        raw = row.get("match_candidates") or []
        if not isinstance(raw, (list, tuple)):
            raw = [raw]
        names: list[str] = []
        seen: set[str] = set()
        for cand in raw:
            if isinstance(cand, dict):
                name = str(
                    cand.get("name")
                    or cand.get("supplier")
                    or cand.get("template")
                    or ""
                ).strip()
            else:
                name = str(cand or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
        return names

    @staticmethod
    def _recalc_missing(row: dict) -> None:
        try:
            amount_ok = float(row.get("total_amount") or 0) > 0
        except (TypeError, ValueError):
            amount_ok = False
        row["missing"] = [
            label for ok, label in (
                (amount_ok, "belopp"),
                (bool(row.get("invoice_number")), "fakturanummer"),
                (bool(row.get("supplier")), "leverantör"),
            ) if not ok
        ]

    def _add_supplier_logo_picker(self, layout, options, combo) -> None:
        """Klickbara logotyprutor för leverantörsvalet.

        Varje alternativ får en färgad logotyp-ruta med sitt
        monogram bredvid namnet — användaren väljer leverantör via
        logotypen på en blick i stället för att läsa en lång lista.
        Rutorna och dropdownen hålls i sync åt båda hållen. Fler
        alternativ än en handfull rullas i en egen yta så dialogen
        aldrig växer iväg.
        """
        if len(options) < 2:
            return
        layout.addWidget(QLabel(tr("scan.match_pick_logo")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(190)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setSpacing(6)
        buttons: list[QPushButton] = []

        def _sync(idx: int) -> None:
            for j, btn in enumerate(buttons):
                btn.setChecked(j == idx)

        def _pick(idx: int) -> None:
            combo.setCurrentIndex(idx)
            _sync(idx)

        for i, name in enumerate(options):
            btn = QPushButton(str(name))
            btn.setCheckable(True)
            btn.setMinimumHeight(48)
            btn.setIcon(QIcon(_supplier_tile_pixmap(str(name))))
            btn.setIconSize(QSize(36, 36))
            btn.setToolTip(str(name))
            btn.clicked.connect(
                lambda _checked=False, idx=i: _pick(idx)
            )
            grid.addWidget(btn, i // 3, i % 3)
            buttons.append(btn)
        scroll.setWidget(holder)
        layout.addWidget(scroll)
        combo.currentIndexChanged.connect(_sync)
        _sync(combo.currentIndex())

    def _add_multipage_amount_field(self, layout, row: dict):
        """Flersidig faktura: notis + redigerbart att betala-fält.

        Delsumman på en tidig sida är precis felet användaren
        råkat ut för (857,25 i stället för 13 480 på sida 3) —
        därför får hen se och vid behov rätta SLUTSUMMAN direkt
        i bekräftelsen, inte bara välja leverantör blint.
        Returnerar QLineEdit för flersidiga rader, annars None.
        """
        pages = self._row_pages(row)
        if pages < 2:
            return None
        note = QLabel(tr("scan.match_multipage_note", n=pages))
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(QLabel(tr("scan.match_amount_label")))
        edit = QLineEdit()
        try:
            edit.setText(_fmt_amount(float(row.get("total_amount") or 0)))
        except (TypeError, ValueError):
            edit.setText(str(row.get("total_amount", "") or ""))
        layout.addWidget(edit)
        return edit

    @staticmethod
    def _amount_override(edit) -> float | None:
        """Användarens rättade belopp ur bekräftelsefältet."""
        if edit is None:
            return None
        value = _parse_amount(edit.text())
        return value if value > 0 else None

    def _ask_user_for_match(self, row: dict) -> bool:
        """Frågar användaren vilken leverantör/mall som gäller.

        Anropas vid VARJE osäker matchning — appen gissar aldrig
        och parkerar aldrig tyst. Returnerar True först när
        användaren själv valt ett alternativ; vid Avbryt förblir
        raden osäker och kan inte registreras automatiskt.
        """
        if not row.get("match_uncertain"):
            return True
        kind = str(row.get("match_kind") or "supplier").strip()
        candidates = self._match_candidate_names(row)
        if kind == "template":
            options = candidates or sorted(
                str(name) for name in self._get_templates().keys()
            )
        else:
            options = candidates or [
                str(s.get("name", "")).strip()
                for s in self._suppliers()
                if str(s.get("name", "")).strip()
            ]
        # Mappens kopplade leverantör är en egen kandidat när
        # bevakningen pekat ut den men tolkningen var osäker.
        folder_candidate = str(
            row.get("folder_supplier_candidate", "") or ""
        ).strip()
        if folder_candidate and folder_candidate.lower() not in {
            name.lower() for name in options
        }:
            options.append(folder_candidate)
        if not options:
            QMessageBox.information(
                self, tr("scan.match_ask_title"),
                tr("scan.match_no_options"),
            )
            return False

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("scan.match_ask_title"))
        layout = QVBoxLayout(dlg)
        try:
            amount_text = _fmt_amount(float(row.get("total_amount") or 0))
        except (TypeError, ValueError):
            amount_text = str(row.get("total_amount", "") or "—")
        intro = QLabel(tr(
            "scan.match_ask_body",
            file=str(row.get("file", "") or "—"),
            nr=str(row.get("invoice_number", "") or "—"),
            amount=amount_text,
        ))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        reason = str(row.get("match_reason", "") or "").strip()
        reason_key = {
            "weak": "scan.match_reason_weak",
            "ambiguous": "scan.match_reason_ambiguous",
            "competing": "scan.match_reason_competing",
            "template_ambiguous": "scan.match_reason_template",
            "region_ambiguous": "scan.match_reason_template",
            "builtin_ambiguous": "scan.match_reason_template",
        }.get(reason, "scan.match_reason_generic")
        reason_lbl = QLabel(tr(reason_key))
        reason_lbl.setWordWrap(True)
        layout.addWidget(reason_lbl)
        layout.addWidget(QLabel(tr(
            "scan.match_ask_template_label"
            if kind == "template" else "scan.match_ask_supplier_label"
        )))
        combo = QComboBox(dlg)
        combo.addItems(options)
        combo.setCurrentIndex(-1)
        combo.setPlaceholderText(tr("scan.match_ask_placeholder"))
        layout.addWidget(combo)
        self._add_supplier_logo_picker(layout, options, combo)
        amount_edit = self._add_multipage_amount_field(layout, row)
        buttons = QHBoxLayout()
        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.clicked.connect(dlg.reject)
        btn_use = QPushButton(tr("scan.match_use"))
        btn_use.setDefault(True)

        def _accept() -> None:
            if combo.currentIndex() >= 0:
                dlg.accept()

        btn_use.clicked.connect(_accept)
        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_use)
        layout.addLayout(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            log.info(
                "SCAN_IMPORT: användaren avbröt matchningsfrågan "
                "för %s — inget valdes",
                row.get("file", ""),
            )
            return False
        chosen = combo.currentText().strip()
        if not chosen:
            return False
        self._apply_manual_match(
            row, chosen, kind=kind, candidates=candidates,
            amount=self._amount_override(amount_edit),
        )
        return True

    def _apply_manual_match(
        self, row: dict, chosen: str,
        kind: str = "", candidates: list | None = None,
        amount: float | None = None,
    ) -> str:
        """Tillämpar användarens eget leverantörsval på en rad.

        Delas av osäkerhetsfrågan och högerklickets manuella
        matchning: leverantören sätts, dess mall (om en sådan
        finns) läses in i radens fält och osäkerhetsflaggorna
        rensas — raden är därefter användarens eget val, aldrig
        en gissning, och kan registreras via Skapa fakturor.
        Ett rättat belopp ur bekräftelsen vinner alltid över det
        avlästa. Efteråt lär sig appen av valet (se
        _learn_from_match); inlärningsnotisen returneras för
        statustexten.
        """
        candidates = list(candidates or [])
        text = str(row.get("_text", "") or "")
        row["supplier"] = chosen
        self._apply_template_to_row(row, text)
        if amount is not None and amount > 0:
            # Användarens bekräftade slutsumma vinner alltid över
            # den avlästa (som kan vara en delsumma på sida 1).
            row["total_amount"] = float(amount)
        if kind == "template" or chosen in self._get_templates():
            if chosen in self._get_templates():
                row["template"] = chosen
            row["template_match"] = {
                "status": "matched", "template": chosen,
                "candidates": candidates, "uncertain": False,
                "reason": "user_choice",
            }
        row["supplier_match"] = {
            "status": "matched", "supplier": chosen,
            "candidates": candidates, "uncertain": False,
            "reason": "user_choice",
        }
        for key in (
            "match_uncertain", "match_candidates",
            "match_reason", "match_kind",
        ):
            row.pop(key, None)
        self._recalc_missing(row)
        row["status"] = self._compute_status(
            row, bool(text or row.get("_path"))
        )
        log.info(
            "SCAN_IMPORT: användaren matchade %s mot %s manuellt",
            row.get("file", ""), chosen,
        )
        return self._learn_from_match(row, chosen)

    def _learn_from_match(self, row: dict, chosen: str) -> str:
        """Appen lär sig av användarens matchning — varje gång.

        Två saker lärs, båda ur användarens eget bekräftade val
        (aldrig ur appens automatiska träffar):

        1. Inlärningsminnet räknar bekräftelsen. Flersidiga
           bekräftelser för samma leverantör bygger mot att den
           leverantörens flersidiga fakturor till slut får
           passera utan fråga — men bara med avstämning mot
           texten (tolkarens flersidighetsvakt avgör).
        2. Saknar leverantören både mall och inbyggt format
           härleds en mall ur de just bekräftade värdena: bara
           etiketter som läser tillbaka EXAKT dem sparas, och
           övriga rader i listan läses genast om mot mallen.

        Inlärningen får aldrig fälla matchningen — fel loggas
        och tystas. Returnerar en kort notis för statusraden.
        """
        try:
            si = _scan_module()
            pages = self._row_pages(row)
            learning = self._get_match_learning()
            entry = si.record_match_confirmation(
                learning, chosen, multipage=pages >= 2
            )
            notes: list[str] = []
            if pages >= 2:
                notes.append(tr(
                    "scan.learning_progress",
                    supplier=chosen,
                    n=int(entry.get("multipage_confirmed", 0) or 0),
                ))
            templates = self._get_templates()
            if not si.find_template(templates, chosen) \
                    and not si.has_builtin_format(chosen):
                tmpl = si.derive_template_from_confirmation(
                    str(row.get("_text", "") or ""),
                    str(row.get("invoice_number", "") or ""),
                    row.get("total_amount"),
                )
                if tmpl:
                    templates[chosen] = tmpl
                    self._save_templates_file()
                    entry["template_learned"] = True
                    self._reread_rows_with_template(
                        chosen, tmpl, exclude=row
                    )
                    notes.append(tr(
                        "scan.learned_template", supplier=chosen
                    ))
            self._save_match_learning()
            return " ".join(notes)
        except Exception as exc:
            log.warning("learn from match: %s", exc)
            return ""

    def _manual_match_row(self) -> None:
        """Högerklick: matcha markerad rad mot en leverantör själv.

        När den automatiska matchningen misslyckats (ingen eller
        osäker träff) ska användaren inte vara låst till att lära
        in en helt ny mall — här väljer man helt enkelt vilken
        leverantör i registret fakturan tillhör. Leverantörens
        mall, om en sådan finns, läses direkt in i radens fält;
        finns ingen mall behåller raden sina avlästa värden och
        får bara leverantören satt. Raden markeras som användarens
        eget val (grön, aldrig som en automatgissning).
        """
        idxs = self._selected_rows()
        if not idxs:
            self._lbl_status.setText(tr("scan.select_row"))
            return
        row = self._rows[idxs[0]]
        options: list[str] = []
        seen: set[str] = set()

        def _add(name: str) -> None:
            name = str(name or "").strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                options.append(name)

        # Osäkerhetens kandidater först (sannolikast rätt), sedan
        # mappens leverantör, hela registret och mallnamnen.
        for name in self._match_candidate_names(row):
            _add(name)
        _add(str(row.get("folder_supplier_candidate", "") or ""))
        for supplier in self._suppliers():
            _add(str(supplier.get("name", "") or ""))
        for name in self._get_templates().keys():
            _add(str(name))
        if not options:
            QMessageBox.information(
                self, tr("scan.manual_match_title"),
                tr("scan.manual_no_suppliers"),
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("scan.manual_match_title"))
        layout = QVBoxLayout(dlg)
        try:
            amount_text = _fmt_amount(float(row.get("total_amount") or 0))
        except (TypeError, ValueError):
            amount_text = str(row.get("total_amount", "") or "—")
        intro = QLabel(tr(
            "scan.manual_match_body",
            file=str(row.get("file", "") or "—"),
            nr=str(row.get("invoice_number", "") or "—"),
            amount=amount_text,
        ))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(QLabel(tr("scan.match_ask_supplier_label")))
        combo = QComboBox(dlg)
        combo.addItems(options)
        current = str(row.get("supplier", "") or "").strip()
        idx = next(
            (i for i, name in enumerate(options)
             if name.lower() == current.lower()),
            -1,
        )
        combo.setCurrentIndex(idx)
        combo.setPlaceholderText(tr("scan.match_ask_placeholder"))
        layout.addWidget(combo)
        self._add_supplier_logo_picker(layout, options, combo)
        amount_edit = self._add_multipage_amount_field(layout, row)
        buttons = QHBoxLayout()
        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.clicked.connect(dlg.reject)
        btn_use = QPushButton(tr("scan.match_use"))
        btn_use.setDefault(True)

        def _accept() -> None:
            if combo.currentIndex() >= 0:
                dlg.accept()

        btn_use.clicked.connect(_accept)
        buttons.addStretch()
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_use)
        layout.addLayout(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = combo.currentText().strip()
        if not chosen:
            return
        note = self._apply_manual_match(
            row, chosen, candidates=options,
            amount=self._amount_override(amount_edit),
        )
        self._refresh_table()
        status = tr(
            "scan.manual_matched",
            file=str(row.get("file", "") or "—"),
            supplier=chosen,
        )
        if note:
            status += "  ·  " + note
        self._lbl_status.setText(status)

    def _ask_uncertain_rows(self, rows: list[dict]) -> int:
        """Frågar om varje osäker rad; returnerar antal lösta."""
        resolved = 0
        for row in list(rows or []):
            if isinstance(row, dict) and row.get("match_uncertain"):
                if self._ask_user_for_match(row):
                    resolved += 1
        if resolved:
            self._refresh_table()
        return resolved

    def _parked_entry_for(self, info: dict) -> dict | None:
        """Parkerade posten som hör till ett parkeringsevent."""
        watch = getattr(self, "_watch", None)
        if watch is not None:
            for entry in list(getattr(watch, "parked", []) or []):
                if info.get("hash") and str(entry.get("hash", "")) \
                        == str(info.get("hash", "")):
                    return entry
                if str(entry.get("path", "")) \
                        == str(info.get("path", "")):
                    return entry
        if isinstance(info, dict) and info.get("parsed"):
            return info
        return None

    def _add_parked_rows_to_table(
        self, infos: list[dict]
    ) -> list[dict]:
        """Lägger OSÄKRA parkerade fakturor direkt i Import-tabellen.

        Alla fakturor vars matchning är osäker (leverantör/mall/
        flersidor) ska ligga i Import-tabellen — inte bara gömda
        i bevakningens parkering. Raderna kommer dit röda
        (osäkra) och stannar tills användaren matchat dem, skapat
        fakturor av dem eller tagit bort dem; samma fil läggs
        aldrig in två gånger. Returnerar de NYA raderna.
        """
        added: list[dict] = []
        for info in infos or []:
            if not isinstance(info, dict):
                continue
            source = self._parked_entry_for(info)
            if not isinstance(source, dict):
                continue
            parsed = dict(source.get("parsed", {}) or {})
            if not parsed.get("match_uncertain"):
                continue
            digest = str(
                source.get("hash", "") or info.get("hash", "") or ""
            )
            path = str(
                source.get("path", "") or info.get("path", "") or ""
            )
            if any(
                (digest and str(r.get("_parked_hash", "")) == digest)
                or (path and str(r.get("_path", "")) == path)
                for r in self._rows
            ):
                continue
            text = str(source.get("text", "") or "")
            parsed["file"] = source.get("file", "") or Path(path).name
            parsed["_path"] = path
            parsed["method"] = source.get("method", "")
            parsed["_text"] = text
            if digest:
                parsed["_parked_hash"] = digest
            parsed = self._apply_template_to_row(parsed, text)
            try:
                si = _scan_module()
                if "math_check" not in parsed:
                    parsed["math_check"] = si.invoice_math_check(
                        text, float(parsed.get("total_amount") or 0)
                    )
                if "date_check" not in parsed:
                    parsed["date_check"] = si.invoice_date_check(
                        parsed.get("date", ""),
                        parsed.get("due_date", ""),
                    )
            except Exception:
                pass
            parsed["status"] = self._compute_status(
                parsed, bool(text)
            )
            self._rows.append(parsed)
            added.append(parsed)
        if added:
            self._refresh_table()
            log.info(
                "SCAN_IMPORT: %d osäkra parkerade fakturor lades "
                "direkt i Import-tabellen för manuell matchning",
                len(added),
            )
        return added

    def _unpark_row(self, row: dict) -> None:
        """Tar bort radens parkerade post när raden avgjorts i
        tabellen (matchad, skapad eller borttagen) — parkeringen
        ska aldrig berätta en gammal historia om en fil som
        användaren redan hanterat här."""
        watch = getattr(self, "_watch", None)
        digest = str(row.get("_parked_hash", "") or "")
        if watch is None or not digest:
            return
        try:
            watch.remove_parked(digest)
            self._refresh_watch_ui()
        except Exception as exc:
            log.debug("unpark row: %s", exc)

    def _collect_uncertain_parked(self) -> None:
        """Vid start: osäkra parkeringar från tidigare körningar
        läggs i Import-tabellen direkt (utan dialogregn — de
        väntar där som röda rader tills användaren matchar dem)."""
        try:
            watch = getattr(self, "_watch", None)
            if watch is None:
                return
            self._add_parked_rows_to_table(list(watch.parked))
        except Exception as exc:
            log.debug("collect uncertain parked: %s", exc)

    def _ask_uncertain_parked(self, infos: list[dict]) -> None:
        """Frågar direkt om parkerade filer med osäker matchning.

        Ett bekräftat val flyttar filen till granskningstabellen
        med vald leverantör/mall; Avbryt lämnar den parkerad —
        den registreras aldrig automatiskt på en gissning.
        """
        watch = getattr(self, "_watch", None)
        if watch is None:
            return
        moved = False
        for info in infos or []:
            reason = str(info.get("reason", "") or "")
            parsed_info = info.get("parsed") or {}
            if reason != "uncertain-supplier" and not (
                isinstance(parsed_info, dict)
                and parsed_info.get("match_uncertain")
            ):
                continue
            parked = None
            for entry in list(getattr(watch, "parked", []) or []):
                if str(entry.get("hash", "")) == str(info.get("hash", "")) \
                        and info.get("hash"):
                    parked = entry
                    break
                if str(entry.get("path", "")) == str(info.get("path", "")):
                    parked = entry
                    break
            source = parked if isinstance(parked, dict) else info
            parsed = dict(source.get("parsed", {}) or {})
            parsed["file"] = source.get("file", "")
            parsed["_path"] = source.get("path", "")
            parsed["method"] = source.get("method", "")
            parsed["_text"] = source.get("text", "")
            if not self._ask_user_for_match(parsed):
                continue
            parsed["status"] = self._compute_status(
                parsed, bool(source.get("text"))
            )
            self._rows.append(parsed)
            if parked is not None:
                watch.remove_parked(parked.get("hash", ""))
            moved = True
        if moved:
            self._refresh_table()
            self._refresh_watch_ui()

    def _apply_template_to_row(self, parsed: dict, text: str) -> dict:
        """Applicerar leverantörsmallen på en (parkerad) rad.

        Mallen kan ha lärts in EFTER att filen parkerades — då ska
        granskningen visa mallens värden (och mallmarkören), inte
        den gamla heuristik-tolkningen från parkeringstillfället.
        """
        supplier = str(parsed.get("supplier", "") or "")
        if not supplier or not text:
            return parsed
        try:
            si = _scan_module()
            tmpl = si.find_template(self._get_templates(), supplier)
            if not tmpl:
                builtin = si.builtin_template_for(text)
                tmpl = builtin[1] if builtin else None
            if not tmpl:
                return parsed
            found = si.apply_template(text, tmpl)
        except Exception as exc:
            log.warning("apply template on parked: %s", exc)
            return parsed
        for field, value in found.items():
            if value not in (None, "", 0, 0.0):
                parsed[field] = value
        if found:
            parsed["template"] = supplier
            try:
                amount_ok = (
                    float(parsed.get("total_amount") or 0) > 0
                )
            except (TypeError, ValueError):
                amount_ok = False
            parsed["missing"] = [
                label for ok, label in (
                    (amount_ok, "belopp"),
                    (bool(parsed.get("invoice_number")),
                     "fakturanummer"),
                    (bool(parsed.get("supplier")), "leverantör"),
                ) if not ok
            ]
        return parsed

    def _review_parked(self) -> None:
        """Flyttar parkerade filer till granskningstabellen.

        Filer som parkerades före inlärningen tolkas om med den
        mall som eventuellt finns nu (se _apply_template_to_row).
        """
        if not self._watch:
            return
        start = len(self._rows)
        for parked in list(self._watch.parked):
            digest = str(parked.get("hash", "") or "")
            if digest and any(
                str(r.get("_parked_hash", "")) == digest
                for r in self._rows
            ):
                # Redan i Import-tabellen (osäker parkering som
                # lades dit automatiskt) — lägg aldrig in samma
                # faktura två gånger.
                continue
            parsed = dict(parked.get("parsed", {}))
            parsed["file"] = parked.get("file", "")
            parsed["_path"] = parked.get("path", "")
            parsed["method"] = parked.get("method", "")
            parsed["_text"] = parked.get("text", "")
            parsed = self._apply_template_to_row(
                parsed, str(parked.get("text", "") or "")
            )
            # Äldre parkeringar saknar räkne-/datumkontrollerna
            # (de kom i en senare version) — räkna fram dem nu
            # så även de får sina kontrollflaggor i listan.
            try:
                si = _scan_module()
                if "math_check" not in parsed:
                    parsed["math_check"] = si.invoice_math_check(
                        str(parked.get("text", "") or ""),
                        float(parsed.get("total_amount") or 0),
                    )
                if "date_check" not in parsed:
                    parsed["date_check"] = si.invoice_date_check(
                        parsed.get("date", ""),
                        parsed.get("due_date", ""),
                    )
            except Exception:
                pass
            parsed["status"] = self._compute_status(
                parsed, bool(parked.get("text"))
            )
            self._rows.append(parsed)
            self._watch.remove_parked(parked.get("hash", ""))
        self._refresh_table()
        # Osäkra matchningar som följt med till tabellen avgörs
        # av användaren här — aldrig av en gissning i bakgrunden.
        self._ask_uncertain_rows(self._rows[start:])
        self._offer_template_repairs(self._rows[start:])

    def _offer_template_repairs(self, rows: list[dict]) -> None:
        """Malldriftsassistenten för nyligen granskade parkeringar.

        Har leverantören bytt formulering på sina fakturor läser
        den sparade mallen inte längre alla fält. Då föreslår
        appen — utifrån fakturornas egen text — nya etiketter.
        Användaren bekräftar alltid; först därefter uppdateras
        mallen, sparas och prövas på raderna igen.
        """
        if not rows:
            return
        try:
            si = _scan_module()
            templates = self._get_templates()
        except Exception as exc:
            log.warning("malldrift: %s", exc)
            return
        if not templates:
            return

        import copy

        field_names = {
            "invoice_number": "Fakturanr",
            "total_amount": "Att betala",
            "date": "Fakturadatum",
            "due_date": "Förfallodatum",
            "ocr": "OCR",
        }
        by_supplier: dict[str, list[dict]] = {}
        for row in rows:
            supplier = str(row.get("supplier", "") or "").strip()
            if supplier:
                by_supplier.setdefault(supplier, []).append(row)

        for supplier, supplier_rows in by_supplier.items():
            try:
                template = si.find_template(templates, supplier)
                if not template:
                    continue
                template_name = supplier
                if template_name not in templates:
                    template_name = next(
                        (
                            name
                            for name, tmpl in templates.items()
                            if tmpl is template
                        ),
                        supplier,
                    )

                # Samla förslag per fält; vid flera parkerade
                # fakturor vinner den vanligaste nya etiketten.
                candidates: dict[str, dict[str, dict[str, Any]]] = {}
                for row in supplier_rows:
                    text = str(row.get("_text", "") or "")
                    if not text:
                        continue
                    for suggestion in si.suggest_template_repairs(
                        text, template
                    ):
                        field = str(suggestion.get("field", "") or "")
                        label = str(suggestion.get("new_label", "") or "")
                        if not field or not label:
                            continue
                        per_label = candidates.setdefault(field, {})
                        record = per_label.get(label)
                        if record is None:
                            per_label[label] = {
                                "suggestion": suggestion,
                                "count": 1,
                            }
                        else:
                            record["count"] += 1
                if not candidates:
                    continue

                chosen: list[dict[str, Any]] = []
                ordered_fields = [
                    field for field in _TEMPLATE_FIELDS
                    if field in candidates
                ] + [
                    field for field in candidates
                    if field not in _TEMPLATE_FIELDS
                ]
                for field in ordered_fields:
                    record = max(
                        candidates[field].values(),
                        key=lambda item: item["count"],
                    )
                    chosen.append(dict(record["suggestion"]))
                if not chosen:
                    continue

                lines: list[str] = []
                for suggestion in chosen:
                    value = suggestion.get("value", "")
                    if suggestion.get("field") == "total_amount":
                        value_text = _fmt_amount(value) or str(value)
                    else:
                        value_text = str(value)
                    evidence = f"= {value_text}"
                    if suggestion.get("below"):
                        evidence += ", på raden under rubriken"
                    lines.append(
                        "• {}: {} → {} ({})".format(
                            field_names.get(
                                suggestion["field"],
                                suggestion["field"],
                            ),
                            suggestion.get("old_label") or "—",
                            suggestion["new_label"],
                            evidence,
                        )
                    )
                answer = QMessageBox.question(
                    self,
                    tr("tmpl.repair_title"),
                    tr(
                        "tmpl.repair_body",
                        supplier=template_name,
                        changes="\n".join(lines),
                    ),
                )
                if answer != QMessageBox.StandardButton.Yes:
                    continue

                new_template = copy.deepcopy(template)
                fields = new_template.setdefault("fields", {})
                if not isinstance(fields, dict):
                    fields = {}
                    new_template["fields"] = fields
                for suggestion in chosen:
                    spec = fields.get(suggestion["field"])
                    if not isinstance(spec, dict):
                        spec = {}
                        fields[suggestion["field"]] = spec
                    if spec.get("region"):
                        continue
                    spec["label"] = suggestion["new_label"]
                    if suggestion.get("below"):
                        spec["below"] = True
                    else:
                        spec.pop("below", None)
                templates[template_name] = new_template
                self._save_templates_file()
                count = self._reread_rows_with_template(
                    template_name, new_template
                )
                self._lbl_status.setText(
                    tr(
                        "tmpl.repaired",
                        supplier=template_name,
                        n=count,
                    )
                )
                if not count:
                    self._refresh_table()
                log.info(
                    "SCAN_TEMPLATE: malldrift reparerad för %s: %s",
                    template_name,
                    ", ".join(
                        "{}→{}".format(
                            suggestion["field"],
                            suggestion["new_label"],
                        )
                        for suggestion in chosen
                    ),
                )
            except Exception as exc:
                log.warning(
                    "malldrift för %s: %s", supplier, exc
                )

    def _log_status(self) -> None:
        """Visar vilka textkällor som är tillgängliga på maskinen."""
        try:
            import sys

            sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
            import scan_import as si

            stöd = []
            if si.HAS_PYPDF:
                stöd.append("pypdf")
            if si.HAS_FITZ:
                stöd.append("PyMuPDF")
            if si.HAS_TESS:
                stöd.append("Tesseract OCR")
            txt = (
                "Textkällor: " + ", ".join(stöd)
                if stöd
                else "Ingen PDF/OCR-modul hittad — klistra in fakturatexten "
                     "i ruta 2 (fungerar alltid)"
            )
            self._lbl_log.setText(txt)
        except Exception as exc:
            log.warning("status: %s", exc)

    # ══════════════════════════════════════════════════════════════════
    #  FILVAL
    # ══════════════════════════════════════════════════════════════════

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Välj skannade fakturor",
            "",
            "Fakturor (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp);;"
            "Alla filer (*)",
        )
        if files:
            self._set_paths([Path(f) for f in files])

    def _set_paths(self, paths: list[Path]) -> None:
        self._paths = [p for p in paths if p.exists()]
        self._txt_paths.setPlainText(
            "\n".join(str(p) for p in self._paths)
        )
        n = len(self._paths)
        self._lbl_files.setText(
            f"{n} fil(er) valda" if n else "Inga filer valda"
        )

    def _clear_paths(self) -> None:
        self._paths = []
        self._txt_paths.clear()
        self._lbl_files.setText("Inga filer valda")

    # ══════════════════════════════════════════════════════════════════
    #  TOLKNING
    # ══════════════════════════════════════════════════════════════════

    # ── Leverantörsmallar ─────────────────────────────────────────────

    def _templates_file(self) -> Path:
        if self._templates_path is not None:
            return self._templates_path
        raw = ""
        try:
            if self._app is not None and hasattr(self._app, "settings"):
                raw = str(self._app.settings.get("db_path", "data"))
            elif self._app is not None and hasattr(
                self._app, "get_setting"
            ):
                raw = str(self._app.get_setting("db_path", "data"))
        except Exception:
            raw = ""
        data_dir = Path(raw or "data")
        if not data_dir.is_absolute():
            data_dir = (
                Path(__file__).resolve().parent.parent / data_dir
            )
        return data_dir / "invoice_templates.json"

    def _learning_file(self) -> Path:
        """Inlärningsminnet bor bredvid mallfilen."""
        return self._templates_file().parent / "match_memory.json"

    def _get_match_learning(self) -> dict:
        if self._learning_cache is None:
            self._learning_cache = _scan_module().load_match_learning(
                self._learning_file()
            )
        return self._learning_cache

    def _save_match_learning(self) -> None:
        _scan_module().save_match_learning(
            self._learning_file(), self._get_match_learning()
        )

    def _row_pages(self, row: dict) -> int:
        """Radens sidantal (tolkningens värde, annars filen)."""
        try:
            pages = int(row.get("pages") or 0)
        except (TypeError, ValueError):
            pages = 0
        if pages:
            return pages
        try:
            return _scan_module().page_image_count(
                str(row.get("_path", "") or "")
            )
        except Exception:
            return 0

    def _get_templates(self) -> dict:
        if self._templates_cache is None:
            si = _scan_module()
            self._templates_cache = si.load_templates(
                self._templates_file()
            )
        return self._templates_cache

    def _save_templates_file(self) -> None:
        si = _scan_module()
        si.save_templates(
            self._templates_file(), self._get_templates()
        )
        self._refresh_templates_btn()

    def _refresh_templates_btn(self) -> None:
        try:
            n = len(self._get_templates())
        except Exception:
            n = 0
        self._btn_templates.setText(tr("scan.templates_btn", n=n))

    @staticmethod
    def _compute_status(parsed: dict, has_text: bool) -> str:
        status = (
            "redo" if not parsed.get("missing")
            else "saknas: " + ", ".join(parsed["missing"])
        )
        if not has_text:
            status = "ingen text hittad"
        return status

    def _reread_rows_with_template(
        self, supplier: str, template: dict, exclude: Any = None
    ) -> int:
        """Läser om de ANDRA tolkade raderna med en nyss sparad mall.

        Efter att användaren granskat EN faktura och sparat mallen
        prövas den direkt på resten av listan: rader som mallen
        faktiskt läser (fakturanummer eller belopp hittas) får
        mallens värden + status omräknad. Rader mallen inte läser
        rörs inte. Returnerar antalet omlästa rader.
        """
        si = _scan_module()
        count = 0
        for other in self._rows:
            if exclude is not None and other is exclude:
                continue
            text = str(other.get("_text", "") or "")
            path = str(other.get("_path", "") or "")
            if not text and not path:
                continue
            try:
                found = si.template_values(
                    path or None, text, template
                )
            except Exception as exc:
                log.warning("reread row: %s", exc)
                continue
            if not found:
                continue
            if not found.get("invoice_number") \
                    and not found.get("total_amount"):
                continue  # mallen gör inte anspråk på dokumentet
            for field, value in found.items():
                other[field] = value
            other["supplier"] = supplier
            other["template"] = supplier
            miss: list[str] = []
            try:
                amount_ok = float(other.get("total_amount") or 0) > 0
            except (TypeError, ValueError):
                amount_ok = False
            if not amount_ok:
                miss.append("belopp")
            if not other.get("invoice_number"):
                miss.append("fakturanummer")
            other["missing"] = miss
            other["status"] = (
                "redo" if not miss
                else "saknas: " + ", ".join(miss)
            )
            count += 1
        if count:
            self._refresh_table()
            log.info(
                "SCAN_TEMPLATE: %d andra rader lästes om med "
                "mallen för %s", count, supplier,
            )
        return count

    def _open_template_dialog(self, row: dict | None = None) -> None:
        """Skapa/redigera mall för markerad rad + tolka om raden."""
        if row is None:
            idxs = self._selected_rows()
            if not idxs:
                self._lbl_status.setText(tr("scan.select_row"))
                return
            row = self._rows[idxs[0]]
        si = _scan_module()
        text = str(row.get("_text", "") or "")
        path = str(row.get("_path", "") or "")
        if si.page_image_count(path) <= 0:
            self._lbl_status.setText(tr("tmpl.need_image"))
            return
        templates = self._get_templates()
        existing = si.find_template(
            templates, str(row.get("supplier", "") or "")
        )
        dlg = TemplateDialog(
            self, text,
            supplier=str(row.get("supplier", "") or ""),
            existing=existing,
            path=path or None,
        )
        if not dlg.exec() or not dlg.result_template:
            return
        supplier = dlg.result_template["supplier"]
        templates[supplier] = {"fields": dlg.result_template["fields"]}
        self._save_templates_file()

        # Den just sparade mallen appliceras ALLTID på den här raden
        # (även om leverantörsnamnet inte står ordagrant i texten).
        found = si.template_values(
            path or None, text, templates[supplier]
        )
        if found:
            for field, value in found.items():
                row[field] = value
            row["supplier"] = supplier
            row["template"] = supplier
            miss = []
            if not float(row.get("total_amount") or 0) > 0:
                miss.append("belopp")
            if not row.get("invoice_number"):
                miss.append("fakturanummer")
            row["missing"] = miss
            row["status"] = (
                "redo" if not miss
                else "saknas: " + ", ".join(miss)
            )
        else:
            reparsed = si.parse_invoice_text(
                text, self._suppliers(), templates=templates
            )
            for key in ("supplier", "invoice_number", "date",
                        "due_date", "ocr", "total_amount", "missing"):
                row[key] = reparsed.get(key, row.get(key))
            row["template"] = reparsed.get("template", "")
            row["status"] = self._compute_status(reparsed, bool(text))
        # De andra tolkade raderna läses om med samma mall —
        # kan de använda den fylls deras fält i direkt.
        n_others = self._reread_rows_with_template(
            supplier, templates[supplier], exclude=row
        )
        self._refresh_table()
        status = tr("tmpl.saved", supplier=supplier)
        if n_others:
            status += " " + tr("tmpl.reread_others", n=n_others)
        self._lbl_status.setText(status)
        log.info(
            "SCAN_TEMPLATE: mall sparad för %s, fält=%s",
            supplier, list(dlg.result_template["fields"]),
        )

    def _example_row_for_template(self, name: str) -> dict | None:
        """Tolkad rad vars fil kan visa mallens fakturabild."""
        for row in self._rows:
            if str(row.get("_path", "") or "") and (
                str(row.get("template", "") or "") == name
                or str(row.get("supplier", "") or "") == name
            ):
                return row
        return None

    def _manager_edit_template(self, name: str) -> None:
        """Redigera en sparad mall mot dess exempelfaktura."""
        templates = self._get_templates()
        existing = templates.get(name)
        if existing is None:
            return
        si = _scan_module()
        example = self._example_row_for_template(name)
        path = (
            str(example.get("_path", "") or "") if example else ""
        )
        text = str(example.get("_text", "") or "") if example else ""
        if path and si.page_image_count(path) <= 0:
            path = ""
        dlg = TemplateDialog(
            self, text, supplier=name, existing=existing,
            path=path or None,
        )
        if not dlg.exec() or not dlg.result_template:
            return
        supplier = dlg.result_template["supplier"]
        if supplier != name:
            templates.pop(name, None)
        templates[supplier] = {"fields": dlg.result_template["fields"]}
        self._save_templates_file()
        self._lbl_status.setText(tr("tmpl.saved", supplier=supplier))
        log.info("SCAN_TEMPLATE: mall redigerad för %s", supplier)

    def _manager_create_template(self) -> None:
        """Skapa en NY mall från en tolkad faktura i listan."""
        si = _scan_module()
        example = None
        idxs = self._selected_rows()
        if idxs and str(self._rows[idxs[0]].get("_path", "") or ""):
            example = self._rows[idxs[0]]
        if example is None:
            example = next(
                (
                    r for r in self._rows
                    if str(r.get("_path", "") or "")
                ),
                None,
            )
        if example is None or si.page_image_count(
            str(example.get("_path", "") or "")
        ) <= 0:
            QMessageBox.information(
                self, tr("tmpl.manager_title"),
                tr("tmpl.manager_need_example"),
            )
            return
        self._open_template_dialog(row=example)

    def _open_templates_manager(self) -> None:
        templates = self._get_templates()

        def _delete(name: str) -> None:
            templates.pop(name, None)
            self._save_templates_file()

        dlg = TemplatesManagerDialog(
            self, templates, _delete,
            on_edit=self._manager_edit_template,
            on_create=self._manager_create_template,
        )
        dlg.exec()
        self._refresh_templates_btn()

    def _suppliers(self) -> list[dict]:
        try:
            return self._app.get_suppliers() if self._app else []
        except Exception:
            return []

    def _open_template_for_unmatched(self, rows: list[dict]) -> None:
        """Öppnar mallskapandet för rader utan matchande mall.

        En importerad faktura som varken träffar en inlärd mall
        eller ett inbyggt format ska inte bara bli liggande: appen
        öppnar malldialogen för den direkt, så användaren kan
        markera fälten på bilden och lära appen formatet. Sparas
        mallen läses övriga rader om automatiskt (och kan då få
        sin mall) — avbryter användaren stannar vi, i stället för
        att öppna dialog efter dialog.
        """
        si = _scan_module()
        for row in list(rows or []):
            if not isinstance(row, dict):
                continue
            if row.get("template") or row.get("match_uncertain"):
                continue
            path = str(row.get("_path", "") or "")
            if not path or si.page_image_count(path) <= 0:
                continue
            log.info(
                "SCAN_IMPORT: %s kunde inte matchas mot någon "
                "mall — öppnar mallskapandet",
                row.get("file", ""),
            )
            self._open_template_dialog(row=row)
            if not row.get("template"):
                break

    def _scan_files(self) -> None:
        """Läser och tolkar valda filer."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
        import scan_import as si

        # Tolerera inklistrade sökvägar i textrutan
        if self._txt_paths.toPlainText().strip():
            pasted = [
                Path(line.strip())
                for line in self._txt_paths.toPlainText().splitlines()
                if line.strip()
            ]
            if pasted:
                self._paths = [p for p in pasted if p.exists()] or self._paths

        if not self._paths:
            QMessageBox.information(
                self, "Import",
                "Välj en eller flera filer först (ruta 1).",
            )
            return

        suppliers = self._suppliers()
        new_rows: list[dict] = []
        for path in self._paths:
            try:
                text, method = si.extract_text(path)
            except Exception as exc:
                log.error("extract %s: %s", path.name, exc)
                text, method = "", "fel"
            parsed = si.parse_invoice_file(
                path, text, suppliers,
                templates=self._get_templates(),
            )
            parsed["file"] = path.name
            parsed["_path"] = str(path)
            parsed["method"] = method
            parsed["_text"] = (text or "")[:30_000]
            status = (
                "redo" if not parsed["missing"]
                else "saknas: " + ", ".join(parsed["missing"])
            )
            if not text:
                status = "ingen text hittad"
            parsed["status"] = status
            new_rows.append(parsed)
            log.info(
                "SCAN_IMPORT: %s → metod=%s belopp=%s fakturanr=%s status=%s",
                path.name, method, parsed["total_amount"],
                parsed["invoice_number"] or "-", status,
            )

        self._rows.extend(new_rows)
        self._refresh_table()
        # Vid minsta osäkerhet om leverantör/mall: fråga
        # användaren direkt i stället för att gissa.
        self._ask_uncertain_rows(new_rows)
        # Kunde fakturan inte matchas mot någon mall alls öppnas
        # mallskapandet direkt för den — användaren ska inte
        # behöva leta fram rätt knapp själv.
        self._open_template_for_unmatched(new_rows)
        ok = sum(1 for r in new_rows if not r["missing"])
        self._lbl_status.setText(
            f"{len(new_rows)} fil(er) tolkade — {ok} kompletta, "
            f"{len(new_rows) - ok} behöver kompletteras"
        )

    def _scan_pasted(self) -> None:
        """Tolkar inklistrad fakturatext (fallback utan OCR)."""
        import sys

        sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))
        import scan_import as si

        text = self._txt_paste.toPlainText().strip()
        if not text:
            QMessageBox.information(
                self, "Import", "Klistra in fakturatext i ruta 2 först."
            )
            return

        parsed = si.parse_invoice_text(
            text, self._suppliers(),
            templates=self._get_templates(),
        )
        parsed["file"] = "(inklistrad text)"
        parsed["_path"] = ""
        parsed["method"] = "manuell text"
        parsed["_text"] = text[:30_000]
        parsed["status"] = (
            "redo" if not parsed["missing"]
            else "saknas: " + ", ".join(parsed["missing"])
        )
        self._rows.append(parsed)
        self._refresh_table()
        self._ask_uncertain_rows([parsed])
        log.info(
            "SCAN_IMPORT (inklistrad): belopp=%s fakturanr=%s",
            parsed["total_amount"], parsed["invoice_number"] or "-",
        )
        self._lbl_status.setText("Inklistrad text tolkad")

    # ══════════════════════════════════════════════════════════════════
    #  TABELL
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _row_match_state(row: dict) -> str:
        """Radens matchningssäkerhet: "uncertain" / "secure" / "".

        Osäker leverantörs-/mallmatchning (appen har frågat eller
        ska fråga användaren) → "uncertain" (röd rad). En rad med
        säkert identifierad leverantör eller mall → "secure"
        (grön rad). Ingen träff alls (okänt format, tom rad)
        → "" — neutral rad, ingen färg gissas fram.
        """
        if not isinstance(row, dict):
            return ""
        if row.get("match_uncertain"):
            return "uncertain"
        if str(row.get("supplier", "") or "").strip() or str(
            row.get("template", "") or ""
        ).strip():
            return "secure"
        return ""

    def _refresh_table(self) -> None:
        self._tbl.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            for c, (_lbl, key, _w, align) in enumerate(COLUMNS):
                if key == "total_amount":
                    text = _fmt_amount(row.get(key, 0.0))
                elif key == "status":
                    text = self._display_status(row)
                else:
                    text = str(row.get(key, "") or "")
                item = QTableWidgetItem(text)
                item.setTextAlignment(
                    align | Qt.AlignmentFlag.AlignVCenter
                )
                if key == "status":
                    if self._ocr_check_bad(row) \
                            or self._check_warnings(row):
                        item.setForeground(QColor("#ef6c00"))
                    elif row.get("missing") or text == tr("scan.no_text"):
                        item.setForeground(
                            QApplication.palette().mid()
                        )
                    else:
                        item.setForeground(
                            QApplication.palette().link()
                        )
                self._tbl.setItem(r, c, item)
            # Hela raden färgas efter matchningssäkerhet:
            # OSÄKER matchning = röd rad, SÄKER = grön rad.
            # Rader utan någon träff alls lämnas neutrala.
            _state = self._row_match_state(row)
            if _state:
                _pair = (
                    ROW_BG_MATCH_UNCERTAIN if _state == "uncertain"
                    else ROW_BG_MATCH_SECURE
                )
                _bg = QColor(_pair[0] if self._dark else _pair[1])
                _tip = (
                    tr("scan.match_uncertain_status")
                    if _state == "uncertain"
                    else tr("scan.match_secure_tip")
                )
                for _c in range(len(COLUMNS)):
                    _cell = self._tbl.item(r, _c)
                    if _cell is not None:
                        _cell.setBackground(_bg)
                        _cell.setToolTip(_tip)
        self._update_sum()
        self._tbl.resizeRowsToContents()
        self._tbl.resizeRowsToContents()

    @staticmethod
    def _ocr_check_bad(row: dict) -> bool:
        """True om radens OCR-nummer har fel kontrollsiffra (Luhn)."""
        try:
            from ui.invoices_helpers import ocr_luhn_status
        except Exception:
            try:
                from invoices_helpers import ocr_luhn_status
            except Exception:
                return False
        try:
            return ocr_luhn_status(row.get("ocr", "")) == "bad_check"
        except Exception:
            return False

    @staticmethod
    def _check_warnings(row: dict) -> list[str]:
        """Kontrollvarningar (räkning/datum) för statuscellen.

        Tolkningen bifogar math_check/date_check på varje rad;
        avvikelserna visas — värdena ändras aldrig av dem.
        """
        warns: list[str] = []
        mc = row.get("math_check") or {}
        if isinstance(mc, dict) and mc.get("status") == "mismatch":
            warns.append(tr("scan.math_warn"))
        dc = row.get("date_check") or {}
        keys = {
            "due_before_date": "scan.date_due_before",
            "term_long": "scan.date_term_long",
            "date_future": "scan.date_future",
        }
        if isinstance(dc, dict):
            for prob in dc.get("problems") or []:
                key = keys.get(str(prob))
                if key:
                    warns.append(tr(key))
        return warns

    @staticmethod
    def _display_status(row: dict) -> str:
        """Statuscell på aktuellt språk (internt värde är svenska)."""
        raw = str(row.get("status", "") or "")
        if raw == "redo" and row.get("template"):
            text = tr("scan.template_used")
        elif raw == "redo":
            text = tr("scan.ready")
        elif raw.startswith("saknas:"):
            text = tr(
                "scan.missing",
                fields=tr_missing(list(row.get("missing") or [])),
            )
        elif raw == "ingen text hittad":
            text = tr("scan.no_text")
        else:
            text = raw
        if row.get("match_uncertain"):
            text += "  ·  " + tr("scan.match_uncertain_status")
        # Flersidiga fakturor syns direkt: totalen står ofta på
        # sista sidan, så 2+ sidor är viktig granskningsinfo.
        try:
            _pages = _scan_module().page_image_count(
                str(row.get("_path", "") or "")
            )
        except Exception:
            _pages = 0
        if _pages >= 2:
            text += "  ·  " + tr("scan.pages_status", n=_pages)
        # Dålig kontrollsiffra syns direkt i listan — fångas här
        # i stället för först vid betalning hos banken.
        if ScanImportView._ocr_check_bad(row):
            text += "  ·  " + tr("scan.ocr_warn")
        # Räkne-/datumavvikelser likaså: hellre en flagga i
        # listan än ett felbelopp i summan.
        warns = ScanImportView._check_warnings(row)
        if warns:
            text += "  ·  " + " · ".join(warns)
        return text

    def _update_sum(self) -> None:
        total = sum(float(r.get("total_amount", 0.0)) for r in self._rows)
        self._lbl_sum.setText(
            tr("scan.sum", n=len(self._rows), amount=_fmt_amount(total))
        )

    def _selected_rows(self) -> list[int]:
        idxs = sorted({i.row() for i in self._tbl.selectedIndexes()})
        if not idxs and self._tbl.currentRow() >= 0:
            idxs = [self._tbl.currentRow()]
        return [i for i in idxs if 0 <= i < len(self._rows)]

    def _table_context_menu(self, pos) -> None:
        """Högerklick i granskningstabellen: öppna originalet m.m."""
        item = self._tbl.itemAt(pos)
        if item is not None and item.row() >= 0:
            self._tbl.selectRow(item.row())
        menu = QMenu(self)
        menu.addAction(tr("scan.open_original"), self._open_original_row)
        menu.addAction(tr("scan.print"), self._print_row)
        menu.addAction(tr("scan.manual_match"), self._manual_match_row)
        menu.addAction(tr("scan.template_btn"), self._open_template_dialog)
        menu.addSeparator()
        menu.addAction(tr("scan.remove_row"), self._remove_row)
        menu.exec(self._tbl.viewport().mapToGlobal(pos))

    def _open_original_row(self) -> None:
        """Öppnar markerad rads originalfaktura i systemets visare.

        Samma original som Skriv ut använder — för parkerade
        filer är det filen i den bevakade mappen, orörd. Finns
        filen inte kvar (eller ingen visare svarar) sägs det i
        statusraden i stället för att något gissas fram.
        """
        idxs = self._selected_rows()
        if not idxs:
            self._lbl_status.setText(tr("scan.select_row"))
            return
        row = self._rows[idxs[0]]
        path = str(row.get("_path", "") or "")
        name = str(row.get("file", "") or "") or Path(path).name
        if not path or not Path(path).exists():
            self._lbl_status.setText(
                tr("scan.open_missing", file=name)
            )
            return
        try:
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:
            log.warning("open original: %s", exc)
            ok = False
        if ok:
            self._lbl_status.setText(tr("scan.opened", file=name))
            log.info("SCAN_OPEN: %s öppnad i systemets visare", name)
        else:
            self._lbl_status.setText(
                tr("scan.open_failed", file=name)
            )

    def _print_row(self) -> None:
        """Skriver ut markerad rads originalfaktura.

        Raderna i granskningen bär originalets sökväg — för
        parkerade filer ur bevakade mappar är det filen i den
        bevakade mappen, orörd. Alla sidor skrivs ut via
        systemets skrivardialog; finns filen inte kvar sägs
        det i statusraden i stället för att gissa.
        """
        idxs = self._selected_rows()
        if not idxs:
            self._lbl_status.setText(tr("scan.select_row"))
            return
        row = self._rows[idxs[0]]
        path = str(row.get("_path", "") or "")
        name = str(row.get("file", "") or "") or Path(path).name
        if not path or not Path(path).exists():
            self._lbl_status.setText(
                tr("scan.print_missing", file=name)
            )
            return
        if QPrinter is None or QPrintDialog is None:
            self._lbl_status.setText(
                tr(
                    "scan.print_failed",
                    error="skrivarstödet (QtPrintSupport) saknas",
                )
            )
            return
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            dlg = QPrintDialog(printer, self)
            if not dlg.exec():
                return
            n = print_invoice_document(path, printer)
            if n:
                self._lbl_status.setText(
                    tr("scan.printed", file=name, n=n)
                )
                log.info(
                    "SCAN_PRINT: %s utskriven (%d sida/sidor)",
                    name, n,
                )
            else:
                self._lbl_status.setText(
                    tr(
                        "scan.print_failed",
                        error="inga sidor kunde renderas",
                    )
                )
        except Exception as exc:
            log.warning("print row: %s", exc)
            self._lbl_status.setText(
                tr("scan.print_failed", error=str(exc))
            )

    def _remove_row(self) -> None:
        for i in reversed(self._selected_rows()):
            # En parkerad fil användaren tar bort ur tabellen är
            # avgjord — lämna ingen zombiepost i parkeringen.
            self._unpark_row(self._rows[i])
            self._rows.pop(i)
        self._refresh_table()

    # ══════════════════════════════════════════════════════════════════
    #  RÄTTA I FAKTURADIALOGEN
    # ══════════════════════════════════════════════════════════════════

    def _open_row_dialog(self, *_args: Any) -> None:
        """
        Öppnar den vanliga fakturadialogen förifylld med tolkade
        värden — användaren rättar och godkänner; fakturan registreras
        av dialogen (samma väg som manuell registrering).
        """
        idxs = self._selected_rows()
        if not idxs:
            QMessageBox.information(self, "Import", "Markera en rad först.")
            return
        row = self._rows[idxs[0]]
        try:
            from ui.invoices_helpers import InvoiceDialog

            sup_names = [s.get("name", "") for s in self._suppliers()]
            dlg = InvoiceDialog(
                parent=self,
                supplier_name=row.get("supplier", "") or "",
                supplier_names=sup_names,
                app_core=self._app,
            )
            if row.get("total_amount"):
                dlg.f_total.setValue(float(row["total_amount"]))
            if row.get("invoice_number"):
                dlg.f_inv_nr.setText(str(row["invoice_number"]))
            if row.get("ocr"):
                dlg.f_ocr.setText(str(row["ocr"]))
            if row.get("date"):
                from PySide6.QtCore import QDate

                qd = QDate.fromString(str(row["date"]), "yyyy-MM-dd")
                if qd.isValid():
                    dlg.f_date.setDate(qd)
            if row.get("due_date"):
                from PySide6.QtCore import QDate

                qd = QDate.fromString(str(row["due_date"]), "yyyy-MM-dd")
                if qd.isValid():
                    dlg.f_due_date.setDate(qd)

            if dlg.exec() == QDialogAccepted:
                data = dlg.get_data()
                if row.get("_path"):
                    moved = self._maybe_year_sort(
                        row, str(row["_path"])
                    )
                    if moved != str(row["_path"]):
                        data["attachment"] = moved
                self._save_invoice(data, source=row.get("file", ""))
                self._rows.pop(idxs[0])
                self._refresh_table()
        except Exception as exc:
            log.error("SCAN_OPEN_DIALOG: %s", exc, exc_info=True)
            QMessageBox.warning(
                self, "Import", f"Kunde inte öppna dialogen:\n{exc}"
            )

    # ══════════════════════════════════════════════════════════════════
    #  SKAPA FAKTUROR
    # ══════════════════════════════════════════════════════════════════

    def _registry_invoices(self) -> list[dict]:
        """Hela registret (även arkiverade/betalda) för
        dubblettkollen — en exporterad faktura är fortfarande
        en dubblett. Tyst [] om kärnan inte kan svara."""
        app = self._app
        if app is None:
            return []
        try:
            if hasattr(app, "get_invoices"):
                return list(app.get_invoices() or [])
            invoices = getattr(app, "invoices", None)
            if invoices is not None and hasattr(invoices, "all"):
                return list(invoices.all() or [])
        except Exception as exc:
            log.debug("registry invoices for dup check: %s", exc)
        return []

    def _possible_duplicates_for_rows(
        self, idxs: list[int]
    ) -> list[tuple[int, dict]]:
        """[(radindex, träff)] för möjliga dubbletter bland de
        valda raderna — mot registret OCH mot varandra (samma
        faktura två gånger i samma inläsning). Bara varning:
        här registreras eller tas ingenting bort."""
        try:
            try:
                from ui.invoices_helpers import find_possible_duplicate
            except Exception:
                from invoices_helpers import (  # type: ignore
                    find_possible_duplicate,
                )
        except Exception:
            return []
        registry = self._registry_invoices()
        hits: list[tuple[int, dict]] = []
        earlier: list[dict] = []
        for i in idxs:
            row = self._rows[i]
            hit = find_possible_duplicate(registry, row)
            if hit is None:
                hit = find_possible_duplicate(earlier, row)
            if hit is not None:
                hits.append((i, hit))
            earlier.append(row)
        return hits

    def _create_invoices(self) -> None:
        """Registrerar markerade rader som fakturor (belopp → summan)."""
        idxs = self._selected_rows()
        if not idxs:
            QMessageBox.information(self, "Import", "Markera rader först.")
            return

        # En rad med osäker leverantörs-/mallmatchning får aldrig
        # registreras på en gissning — fråga först, och avbryter
        # användaren registreras den inte alls.
        unresolved: set[int] = set()
        for i in idxs:
            if self._rows[i].get("match_uncertain"):
                if not self._ask_user_for_match(self._rows[i]):
                    unresolved.add(i)
        if unresolved:
            self._refresh_table()
            QMessageBox.warning(
                self, tr("scan.match_ask_title"),
                tr(
                    "scan.match_unresolved",
                    files="\n".join(
                        f"• {self._rows[i].get('file', '')}"
                        for i in sorted(unresolved)
                    ),
                ),
            )

        ready = [
            i for i in idxs
            if i not in unresolved and not self._rows[i]["missing"]
        ]
        not_ready = [
            i for i in idxs
            if i not in unresolved and self._rows[i]["missing"]
        ]
        if not_ready:
            QMessageBox.warning(
                self, "Import",
                "Dessa rader saknar obligatoriska uppgifter och kan inte "
                "registreras direkt:\n\n"
                + "\n".join(
                    f"• {self._rows[i]['file']}: "
                    f"{', '.join(self._rows[i]['missing'])}"
                    for i in not_ready
                )
                + "\n\nAnvänd 'Öppna i fakturadialogen' för att komplettera.",
            )
        if not ready:
            return

        # Möjliga dubbletter: varna FÖRE registrering och låt
        # användaren avgöra. Nej = raderna lämnas kvar orörda;
        # inget tas någonsin bort automatiskt.
        skip_idxs: set[int] = set()
        dup_hits = self._possible_duplicates_for_rows(ready)
        if dup_hits:
            lines = []
            for i, hit in dup_hits:
                inv = hit.get("invoice", {}) or {}
                lines.append(tr(
                    "scan.possible_dup_line",
                    file=self._rows[i].get("file", ""),
                    nr=self._rows[i].get("invoice_number", "") or "—",
                    supplier=inv.get("supplier", "") or "—",
                    existing=inv.get("invoice_number", "") or "—",
                    reason=hit.get("reason", ""),
                ))
            answer = QMessageBox.question(
                self, tr("scan.possible_dup_title"),
                tr("scan.possible_dup_body", lines="\n".join(lines)),
            )
            if answer != QMessageBox.StandardButton.Yes:
                skip_idxs = {i for i, _hit in dup_hits}
                self._lbl_status.setText(tr(
                    "scan.possible_dup_skipped", n=len(skip_idxs)
                ))

        created = 0
        for i in sorted(ready, reverse=True):
            if i in skip_idxs:
                continue
            row = self._rows[i]
            if not self._supplier_exists(row.get("supplier", "")):
                QMessageBox.warning(
                    self, "Import",
                    f"Leverantören '{row.get('supplier') or '(okänd)'}' "
                    f"finns inte i registret.\n\n"
                    f"Skapa leverantören först, eller använd "
                    f"'Öppna i fakturadialogen'.",
                )
                continue
            if row.get("_path"):
                row["_path"] = self._maybe_year_sort(
                    row, str(row.get("_path", ""))
                )
            data = self._invoice_data_from_row(row)
            if self._save_invoice(data, source=row.get("file", "")):
                created += 1
                # Registrerad = avgjord: den parkerade posten
                # (om raden kom från parkeringen) tas bort.
                self._unpark_row(row)
                self._rows.pop(i)

        self._refresh_table()
        if created:
            self._lbl_status.setText(f"{created} faktura(or) registrerade")
            QMessageBox.information(
                self, "Import",
                f"✅  {created} faktura{'r' if created != 1 else ''} "
                f"registrerade och inräknade i ATT BETALA.",
            )

    def _invoice_data_from_row(
        self, row: dict, attachment: str | None = None
    ) -> dict:
        """Rad → fakturadata (samma fält som manuell registrering)."""
        return {
            "supplier": str(row.get("supplier", "")),
            "invoice_number": str(row.get("invoice_number", "")),
            "ocr": str(row.get("ocr", "")),
            "date": str(row.get("date", ""))
            or datetime.date.today().isoformat(),
            "due_date": str(row.get("due_date", "")),
            "payment_date": "",
            "total_amount": round(
                float(row.get("total_amount", 0.0)), 2
            ),
            "vat_amount": 0.0,
            "amount_ex_vat": round(
                float(row.get("total_amount", 0.0)), 2
            ),
            "vat_percent": 0,
            "currency": "SEK",
            "status": "Obetald",
            "category": "",
            "reference": "",
            "note": f"Importerad från {row.get('file', '')}"
                    f" ({row.get('method', '')})",
            "attachment": (
                row.get("_path", "") if attachment is None else attachment
            ),
        }

    def _supplier_exists(self, name: str) -> bool:
        target = str(name or "").strip().lower()
        if not target:
            return False
        return any(
            str(s.get("name", "")).strip().lower() == target
            for s in self._suppliers()
        )

    def _save_invoice(
        self, data: dict, source: str = "", silent: bool = False
    ) -> bool:
        """Sparar via app-kärnan (samma väg som manuell registrering).

        silent=True (auto-import): inga dialoger — bara logg.
        """
        try:
            if self._app is None:
                if not silent:
                    QMessageBox.warning(
                        self, "Import", "App-kärnan saknas."
                    )
                return False
            rec = self._app.add_invoice(data)
            log.info(
                "SCAN_CREATE: faktura skapad från %s → id=%s nummer=%s "
                "belopp=%s",
                source or "(dialog)",
                rec.get("id", "?"),
                rec.get("invoice_number", "?"),
                rec.get("total_amount"),
            )
            return True
        except Exception as exc:
            log.error("SCAN_CREATE misslyckades: %s", exc, exc_info=True)
            if not silent:
                QMessageBox.warning(
                    self, "Import", f"Kunde inte spara fakturan:\n{exc}"
                )
            return False

    # ══════════════════════════════════════════════════════════════════
    #  TEMA
    # ══════════════════════════════════════════════════════════════════

    def apply_theme(self, theme: dict) -> None:
        """Anpassar små detaljer efter aktivt tema."""
        try:
            bg = str(theme.get("bg", "#0d1117")).lower()
            self._dark = bg not in (
                "#ffffff", "#f6f8fa", "#eaeef2", "#f5f7fa",
            )
        except Exception:
            pass
        # Radfärgerna (röd osäker / grön säker) följer temat —
        # rita om tabellen så färgerna byter mörkt/ljust direkt.
        try:
            if hasattr(self, "_tbl"):
                self._refresh_table()
        except Exception:
            pass


#: importeras sent för att undvika cirkulär import vid modulladdning
try:
    from PySide6.QtWidgets import QDialog

    QDialogAccepted = QDialog.DialogCode.Accepted
except Exception:  # pragma: no cover
    QDialogAccepted = 1
