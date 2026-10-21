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
    QDialog, QListWidget, QPlainTextEdit,
)
from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QColor, QFont, QPixmap, QPainter, QPen

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(350, 420)
        self._pixmap: QPixmap | None = None
        self._page = 0
        self._regions: dict[str, tuple[int, tuple]] = {}
        self._active = ""
        self._drag_a: tuple[float, float] | None = None
        self._drag_b: tuple[float, float] | None = None

    def set_page(self, pixmap: QPixmap | None, page: int) -> None:
        self._pixmap = pixmap
        self._page = page
        self._drag_a = self._drag_b = None
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
        return QRectF(
            area.center().x() - size.width() / 2,
            area.center().y() - size.height() / 2,
            float(size.width()), float(size.height()),
        )

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
        if not self._active:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        frac = self._fraction(event.position())
        if frac is not None:
            self._drag_a = self._drag_b = frac
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_a is None:
            return
        frac = self._fraction(event.position())
        if frac is not None:
            self._drag_b = frac
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
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
        left.addLayout(nav)
        self._view = _RegionImageView()
        self._view.region_drawn.connect(self._on_region_drawn)
        left.addWidget(self._view, stretch=1)
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
    def _goto_page(self, page: int) -> None:
        self._page = min(max(page, 0), max(self._page_count - 1, 0))
        self._reload_page()

    def _reload_page(self) -> None:
        pixmap = self._pixmaps.get(self._page)
        if pixmap is None and self._path is not None:
            si = _scan_module()
            data = si.render_page_image(self._path, self._page)
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
    """Lista sparade mallar; radering sker via callback direkt."""

    def __init__(
        self, parent: QWidget | None, templates: dict,
        on_delete: Any,
    ) -> None:
        super().__init__(parent)
        self._templates = templates
        self._on_delete = on_delete
        self.setWindowTitle(tr("tmpl.manager_title"))
        self.setMinimumSize(520, 360)
        root = QVBoxLayout(self)
        self._list = QListWidget()
        root.addWidget(self._list, stretch=1)
        row = QHBoxLayout()
        btn_del = QPushButton(tr("tmpl.delete"))
        btn_del.clicked.connect(self._delete_selected)
        row.addWidget(btn_del)
        row.addStretch()
        btn_close = QPushButton(f"✖  {tr('common.cancel')}")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        root.addLayout(row)
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
        # Använd mallen direkt på nytt som ligger i mappen
        if self._watch is not None:
            try:
                self._watch.scan_folder(entry)
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
        for parked in list(self._watch.parked):
            parsed = dict(parked.get("parsed", {}))
            parsed["file"] = parked.get("file", "")
            parsed["_path"] = parked.get("path", "")
            parsed["method"] = parked.get("method", "")
            parsed["_text"] = parked.get("text", "")
            parsed = self._apply_template_to_row(
                parsed, str(parked.get("text", "") or "")
            )
            parsed["status"] = self._compute_status(
                parsed, bool(parked.get("text"))
            )
            self._rows.append(parsed)
            self._watch.remove_parked(parked.get("hash", ""))
        self._refresh_table()

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

    def _open_template_dialog(self) -> None:
        """Skapa/redigera mall för markerad rad + tolka om raden."""
        idxs = self._selected_rows()
        if not idxs:
            self._lbl_status.setText(tr("scan.select_row"))
            return
        si = _scan_module()
        row = self._rows[idxs[0]]
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
        self._refresh_table()
        self._lbl_status.setText(
            tr("tmpl.saved", supplier=supplier)
        )
        log.info(
            "SCAN_TEMPLATE: mall sparad för %s, fält=%s",
            supplier, list(dlg.result_template["fields"]),
        )

    def _open_templates_manager(self) -> None:
        templates = self._get_templates()

        def _delete(name: str) -> None:
            templates.pop(name, None)
            self._save_templates_file()

        dlg = TemplatesManagerDialog(self, templates, _delete)
        dlg.exec()

    def _suppliers(self) -> list[dict]:
        try:
            return self._app.get_suppliers() if self._app else []
        except Exception:
            return []

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
        log.info(
            "SCAN_IMPORT (inklistrad): belopp=%s fakturanr=%s",
            parsed["total_amount"], parsed["invoice_number"] or "-",
        )
        self._lbl_status.setText("Inklistrad text tolkad")

    # ══════════════════════════════════════════════════════════════════
    #  TABELL
    # ══════════════════════════════════════════════════════════════════

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
                    if self._ocr_check_bad(row):
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
        # Dålig kontrollsiffra syns direkt i listan — fångas här
        # i stället för först vid betalning hos banken.
        if ScanImportView._ocr_check_bad(row):
            text += "  ·  " + tr("scan.ocr_warn")
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

    def _remove_row(self) -> None:
        for i in reversed(self._selected_rows()):
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

        ready = [i for i in idxs if not self._rows[i]["missing"]]
        not_ready = [i for i in idxs if self._rows[i]["missing"]]
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


#: importeras sent för att undvika cirkulär import vid modulladdning
try:
    from PySide6.QtWidgets import QDialog

    QDialogAccepted = QDialog.DialogCode.Accepted
except Exception:  # pragma: no cover
    QDialogAccepted = 1
