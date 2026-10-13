from __future__ import annotations

"""
Fakturabunten — Suppliers View
======================================
Fil    : Fakturabunten_/ui/suppliers_view.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Full CRUD-vy för leverantörshantering.

Funktioner
----------
• Lägg till / redigera / ta bort / duplicera leverantör
• Live-sökning med debounce
• Dubblettvarning vid ny leverantör
• Numerisk sortering av betalvillkor-kolumnen
• Tema-anpassning via apply_theme(dict)
• Mörkt tema = vit fet text, ljust tema = mörk fet text
• Knappar och tabbar anpassas alltid efter tema
• Högerklick-meny (markerar raden under muspekaren först)
• Exportera leverantörslista (CSV / JSON)
• Scrollbart med mushjul
• get_supplier_names()  – används av InvoicesView
• prompt_add_supplier() – anropas av InvoicesView
• Samarbetar med: app.py, invoices_view.py, pdf_export.py,
  advanced_logger.py, main_window.py

Plugin hooks
------------
    register(app)            — fas 1
    register_ui(main_window) — fas 2

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLineEdit, QLabel, QTextEdit,
    QFormLayout, QDialog, QDialogButtonBox,
    QMessageBox, QFrame, QSizePolicy, QAbstractItemView,
    QSpinBox, QScrollArea, QMenu, QFileDialog, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QFont, QColor, QCursor, QBrush, QWheelEvent, QPixmap

# Tangentbordsnavigation delas med invoices_helpers (en implementation)
try:
    from ui.invoices_helpers import (
        install_keyboard_navigation,
        fit_table_columns,
        attach_visible_rows,
        ensure_row_height,
        fg_on_row,
        ROLE_ROW_BG,
        ROLE_ROW_FG,
        ROLE_STRIPE,
        ROLE_ROW_BG_ODD,
    )
except ImportError:
    from invoices_helpers import (  # type: ignore[no-redef]
        install_keyboard_navigation,
        fit_table_columns,
        attach_visible_rows,
        ensure_row_height,
        fg_on_row,
        ROLE_ROW_BG,
        ROLE_ROW_FG,
        ROLE_STRIPE,
        ROLE_ROW_BG_ODD,
    )

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

COPYRIGHT_YEAR: int = datetime.date.today().year

log = logging.getLogger("SuppliersView")

#: (etikett, datanyckel, min-bredd, justering)
COLUMNS: list[tuple[str, str, int, Qt.AlignmentFlag]] = [
    ("Namn",     "name",           140, Qt.AlignmentFlag.AlignLeft),
    ("Org.nr",   "org_number",      90, Qt.AlignmentFlag.AlignLeft),
    ("Bankgiro", "bg",              80, Qt.AlignmentFlag.AlignLeft),
    ("Plusgiro", "pg",              70, Qt.AlignmentFlag.AlignLeft),
    ("IBAN",     "iban",           120, Qt.AlignmentFlag.AlignLeft),
    ("BIC",      "bic",             60, Qt.AlignmentFlag.AlignLeft),
    ("Villkor",  "payment_terms",   58, Qt.AlignmentFlag.AlignCenter),
    ("Kontakt",  "contact_person",  90, Qt.AlignmentFlag.AlignLeft),
    ("E-post",   "email",          110, Qt.AlignmentFlag.AlignLeft),
    ("Telefon",  "phone",           80, Qt.AlignmentFlag.AlignLeft),
    ("Adress",   "address",         90, Qt.AlignmentFlag.AlignLeft),
    ("Notering", "note",            70, Qt.AlignmentFlag.AlignLeft),
]

COL_LABELS: list[str] = [c[0] for c in COLUMNS]
COL_KEYS: list[str] = [c[1] for c in COLUMNS]
COL_WIDTHS: list[int] = [c[2] for c in COLUMNS]
COL_ALIGN: list[Qt.AlignmentFlag] = [c[3] for c in COLUMNS]

#: Kolumner som ska sorteras numeriskt i stället för som text.
NUMERIC_KEYS: set[str] = {"payment_terms"}

#: Fält som sökningen omfattar.
SEARCH_FIELDS: tuple[str, ...] = (
    "name", "org_number", "email", "phone", "contact_person", "address",
)

FONT_FAMILY: str = "Segoe UI"

# ═════════════════════════════════════════════════════════════════════
#  UI-HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _font(size: int = 11, bold: bool = False) -> QFont:
    """Typsnittsfabrik — håller alla vyer konsekventa."""
    f = QFont(FONT_FAMILY, size)
    if bold:
        f.setBold(True)
    return f


def _h_line() -> QFrame:
    """Horisontell avskiljare."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


def _make_btn(
    label: str,
    tooltip: str = "",
    accent: bool = False,
    danger: bool = False,
    success: bool = False,
    info: bool = False,
    width: int = 0,
) -> QPushButton:
    """
    Skapar en standardknapp (38 px, fet text, pekhand).

    accent/danger/success/info sätter dynamic properties som
    teman kan känna av; styleSheet sätts av apply_theme().
    """
    btn = QPushButton(label)
    btn.setToolTip(tooltip)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setMinimumHeight(38)
    btn.setFont(_font(11, bold=True))
    btn.setSizePolicy(
        QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
    )
    if accent:
        btn.setProperty("accent", "true")
    if danger:
        btn.setProperty("danger", "true")
    if success:
        btn.setProperty("success", "true")
    if info:
        btn.setProperty("info", "true")
    if width:
        btn.setFixedWidth(width)
    return btn


class _NumericCell(QTableWidgetItem):
    """Tabellcell som sorteras NUMERISKT i stället för som text."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except (TypeError, ValueError):
            return super().__lt__(other)


def _cell(
    text: str,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    bold: bool = True,
    fg: str = "",
    numeric: bool = False,
) -> QTableWidgetItem:
    """Skapar en icke-redigerbar, fet tabellcell med valfri textfärg."""
    item = _NumericCell(str(text)) if numeric else QTableWidgetItem(str(text))
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(
        int(align) | int(Qt.AlignmentFlag.AlignVCenter)
    )
    item.setFont(_font(13, bold=bold))
    if fg:
        item.setForeground(QBrush(QColor(fg)))
    return item


def _le(placeholder: str = "", height: int = 34) -> QLineEdit:
    """Standard-textfält med placeholder."""
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setMinimumHeight(height)
    w.setFont(_font(11))
    return w


# ═════════════════════════════════════════════════════════════════════
#  SUPPLIER DIALOG  (ny / redigera)
# ═════════════════════════════════════════════════════════════════════


class SupplierDialog(QDialog):
    """
    Dialog för att skapa och redigera en leverantör.

    Alla fält från SUPPLIER_SCHEMA finns. Validerar obligatoriska
    fält (namn) innan accept. Scrollbar — fungerar på små skärmar.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        existing: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self._existing = existing or {}
        is_edit = bool(existing)

        self.setWindowTitle(
            "Redigera leverantör" if is_edit else "Ny leverantör"
        )
        self.setMinimumWidth(580)
        self.setMinimumHeight(400)
        self.resize(580, 680)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(20, 20, 20, 16)

        # Scroll — fungerar på små skärmar
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        form = QFormLayout(inner)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setSpacing(10)
        form.setContentsMargins(4, 4, 4, 4)

        # ── Namn + org ─────────────────────────────────────────────────
        self.f_name = _le("Obligatoriskt")
        self.f_name.setFont(_font(13, bold=True))
        self.f_name.setMinimumHeight(40)
        self.f_org = _le("XXXXXXXXXX")

        form.addRow("Namn *:", self.f_name)
        form.addRow("Org.nummer:", self.f_org)
        form.addRow(_h_line())

        # ── Bankuppgifter ──────────────────────────────────────────────
        self.f_bg = _le("XXXX-XXXX")
        self.f_pg = _le("XXXXXXX-X")
        self.f_iban = _le("SEXX XXXX …")
        self.f_bic = _le("XXXXSESS")

        form.addRow("Bankgiro (BG):", self.f_bg)
        form.addRow("Plusgiro (PG):", self.f_pg)
        form.addRow("IBAN:", self.f_iban)
        form.addRow("BIC / SWIFT:", self.f_bic)
        form.addRow(_h_line())

        # ── Betalvillkor ───────────────────────────────────────────────
        self.f_terms = QSpinBox()
        self.f_terms.setRange(0, 365)
        self.f_terms.setSuffix("  dagar")
        self.f_terms.setValue(30)
        self.f_terms.setMinimumHeight(34)
        self.f_terms.setFont(_font(11))
        form.addRow("Betalvillkor:", self.f_terms)

        # Snabbvalsknappar för betalvillkor — färre klick i vardagen
        terms_row = QHBoxLayout()
        terms_row.setSpacing(6)
        for d in (10, 30, 45, 60):
            b = QPushButton(f"{d} d")
            b.setFixedHeight(30)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setToolTip(f"Sätt betalvillkor till {d} dagar")
            b.clicked.connect(
                lambda checked=False, v=d: self.f_terms.setValue(v)
            )
            terms_row.addWidget(b)
        terms_row.addStretch()
        terms_wrap = QWidget()
        terms_wrap.setLayout(terms_row)
        terms_wrap.setStyleSheet("background:transparent;")
        form.addRow("", terms_wrap)

        self.f_favorite = QCheckBox(
            "⭐  Favorit (hamnar överst i fakturavyn)"
        )
        self.f_favorite.setFont(_font(11, bold=True))
        form.addRow("", self.f_favorite)
        form.addRow(_h_line())

        # ── Kontakt ────────────────────────────────────────────────────
        self.f_contact = _le("Förnamn Efternamn")
        self.f_email = _le("namn@foretag.se")
        self.f_phone = _le("+46 70 XXX XX XX")
        self.f_address = _le("Gatuadress, postnr, ort")

        form.addRow("Kontaktperson:", self.f_contact)
        form.addRow("E-post:", self.f_email)
        form.addRow("Telefon:", self.f_phone)
        form.addRow("Adress:", self.f_address)
        form.addRow(_h_line())

        # ── Anteckning ─────────────────────────────────────────────────
        self.f_note = QTextEdit()
        self.f_note.setPlaceholderText("Fritext anteckning …")
        self.f_note.setMaximumHeight(100)
        self.f_note.setFont(_font(11))
        form.addRow("Anteckning:", self.f_note)

        scroll.setWidget(inner)
        root.addWidget(scroll)

        # ── Knappar ────────────────────────────────────────────────────
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = btn_box.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText("💾  Spara" if is_edit else "➕  Lägg till")
        save_btn.setMinimumHeight(40)
        save_btn.setFont(_font(12, bold=True))
        btn_box.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "✖  Avbryt"
        )
        btn_box.accepted.connect(self._validate_and_accept)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

        if is_edit:
            self._populate()

        # Tangentbordsnavigation: logisk Tab-ordning + Enter → nästa
        # fält. Enter i sista enradiga fältet = validera & spara.
        install_keyboard_navigation(
            self,
            [
                self.f_name,
                self.f_org,
                self.f_bg,
                self.f_pg,
                self.f_iban,
                self.f_bic,
                self.f_terms,
                self.f_contact,
                self.f_email,
                self.f_phone,
                self.f_address,
                self.f_favorite,
                self.f_note,
            ],
            on_last=self._validate_and_accept,
        )

        self.f_name.setFocus()

    # ── Data ───────────────────────────────────────────────────────────

    def _populate(self) -> None:
        """Fyller fälten från befintlig leverantör."""
        d = self._existing
        self.f_name.setText(d.get("name", ""))
        self.f_org.setText(d.get("org_number", ""))
        self.f_bg.setText(d.get("bg", ""))
        self.f_pg.setText(d.get("pg", ""))
        self.f_iban.setText(d.get("iban", ""))
        self.f_bic.setText(d.get("bic", ""))
        try:
            self.f_terms.setValue(int(d.get("payment_terms", 30)))
        except (TypeError, ValueError):
            self.f_terms.setValue(30)
        self.f_favorite.setChecked(bool(d.get("favorite", False)))
        self.f_contact.setText(d.get("contact_person", ""))
        self.f_email.setText(d.get("email", ""))
        self.f_phone.setText(d.get("phone", ""))
        self.f_address.setText(d.get("address", ""))
        self.f_note.setPlainText(d.get("note", ""))

    def _validate_and_accept(self) -> None:
        """Validerar obligatoriska fält innan dialogen accepteras."""
        if not self.f_name.text().strip():
            QMessageBox.warning(
                self, "Validering", "Namn är obligatoriskt."
            )
            self.f_name.setFocus()
            return
        self.accept()

    def get_data(self) -> dict:
        """Returnerar formulärets data som supplier-dict."""
        return {
            "name":           self.f_name.text().strip(),
            "org_number":     self.f_org.text().strip(),
            "bg":             self.f_bg.text().strip(),
            "pg":             self.f_pg.text().strip(),
            "iban":           self.f_iban.text().strip(),
            "bic":            self.f_bic.text().strip(),
            "payment_terms":  self.f_terms.value(),
            "favorite":       self.f_favorite.isChecked(),
            "contact_person": self.f_contact.text().strip(),
            "email":          self.f_email.text().strip(),
            "phone":          self.f_phone.text().strip(),
            "address":        self.f_address.text().strip(),
            "note":           self.f_note.toPlainText().strip(),
        }


# ═════════════════════════════════════════════════════════════════════
#  SUPPLIERS VIEW
# ═════════════════════════════════════════════════════════════════════


class SuppliersView(QWidget):
    """
    Huvudvy för leverantörshantering.

    Samarbetar med
    ──────────────
    • app.py              — CRUD-API
    • invoices_view.py    — get_supplier_names, prompt_add_supplier
    • pdf_export.py       — leverantörsdata i PDF
    • advanced_logger.py  — logging via standard logging
    • main_window.py      — theme_changed-signal, statusbar
    """

    supplier_selected = Signal(dict)

    def __init__(self, app: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._all_data: list[dict] = []
        self._current_theme: dict = {}

        # Debounce för live-sökning
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(self._do_refresh)

        self._build_ui()
        self._do_refresh()

        try:
            self._app.suppliers_store.on_change(self._on_data_changed)
        except AttributeError:
            pass

        log.info("SuppliersView initierad")

    # ══════════════════════════════════════════════════════════════════
    #  UI-BYGGNAD
    # ══════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 4)
        root.setSpacing(6)
        self.setMinimumWidth(0)

        # ── Header ─────────────────────────────────────────────────────
        hdr = QLabel("🏢  Leverantörer")
        hdr.setFont(_font(18, bold=True))
        head = QHBoxLayout()
        head.setSpacing(8)
        _icon = Path(__file__).resolve().parent.parent / "app_icon.png"
        if _icon.is_file():
            mark = QLabel()
            mark.setPixmap(
                QPixmap(str(_icon)).scaled(
                    28, 28,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            mark.setStyleSheet("background:transparent;")
            head.addWidget(mark)
        head.addWidget(hdr)
        head.addStretch()
        root.addLayout(head)
        root.addWidget(_h_line())

        # ── Sök + knappar ──────────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "🔍  Sök namn, org.nr, e-post, kontakt …"
        )
        self._search.setMinimumHeight(36)
        self._search.setFont(_font(11))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)

        self._btn_add = _make_btn(
            "➕  Ny leverantör", "Registrera ny leverantör", accent=True
        )
        self._btn_add.clicked.connect(self._add_supplier)

        self._btn_edit = _make_btn(
            "✏️  Redigera", "Redigera vald leverantör"
        )
        self._btn_edit.clicked.connect(self._edit_supplier)
        self._btn_edit.setEnabled(False)

        self._btn_duplicate = _make_btn(
            "📋  Duplicera", "Duplicera vald leverantör"
        )
        self._btn_duplicate.clicked.connect(self._duplicate_supplier)
        self._btn_duplicate.setEnabled(False)

        self._btn_delete = _make_btn(
            "🗑  Ta bort", "Ta bort vald leverantör", danger=True
        )
        self._btn_delete.clicked.connect(self._delete_supplier)
        self._btn_delete.setEnabled(False)

        self._btn_export = _make_btn(
            "📄  Exportera",
            "Exportera leverantörslista till CSV / JSON",
            info=True,
        )
        self._btn_export.clicked.connect(self._export_suppliers)

        self._btn_refresh = _make_btn(
            "🔄", "Uppdatera listan", width=46
        )
        self._btn_refresh.clicked.connect(self._reload_from_disk)

        row1.addWidget(self._search, stretch=1)
        row1.addWidget(self._btn_add)
        row1.addWidget(self._btn_edit)
        row1.addWidget(self._btn_duplicate)
        row1.addWidget(self._btn_delete)
        row1.addWidget(self._btn_export)
        row1.addWidget(self._btn_refresh)
        root.addLayout(row1)

        # ── Räknare ────────────────────────────────────────────────────
        self._lbl_count = QLabel("Leverantörer: 0")
        self._lbl_count.setFont(_font(11, bold=True))
        self._lbl_count.setStyleSheet("background:transparent;")
        root.addWidget(self._lbl_count)

        # ── Tabell ─────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COL_LABELS)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setWordWrap(False)
        self._table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._table.setMinimumWidth(0)
        self._table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._table.setShowGrid(False)
        self._row_delegate = attach_visible_rows(self._table)
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.customContextMenuRequested.connect(
            self._row_context_menu
        )
        self._table.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self._table.doubleClicked.connect(self._edit_supplier)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setStretchLastSection(False)
        hh.setMinimumSectionSize(36)
        hh.setTextElideMode(Qt.TextElideMode.ElideRight)
        full = {"Villkor": "Betalvillkor", "Notering": "Anteckning"}
        for i, label in enumerate(COL_LABELS):
            item = self._table.horizontalHeaderItem(i)
            if item is not None:
                item.setToolTip(full.get(label, label))
        QTimer.singleShot(0, self._fit_columns)

        vh = self._table.verticalHeader()
        vh.setDefaultSectionSize(36)
        vh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        # Mushjul-scroll i tabellen
        self._table.wheelEvent = self._table_wheel  # type: ignore

        root.addWidget(self._table, stretch=1)

    def _fit_columns(self) -> None:
        fit_table_columns(self._table, COL_WIDTHS)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_columns()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_columns)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 200)

        # ── Footer ─────────────────────────────────────────────────────
        root.addWidget(_h_line())
        footer = QLabel(
            f"© {COPYRIGHT_YEAR} Rickard Längkvist"
            f"  —  Fakturabunten"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(_font(9))
        footer.setStyleSheet("background:transparent; color:#718096;")
        root.addWidget(footer)

    def _table_wheel(self, event: QWheelEvent) -> None:
        """Mushjul-scroll i tabellen."""
        sb = self._table.verticalScrollBar()
        sb.setValue(sb.value() - event.angleDelta().y() // 40)

    # ══════════════════════════════════════════════════════════════════
    #  DATA / REFRESH
    # ══════════════════════════════════════════════════════════════════

    def _on_data_changed(self, store_name: str, _: list) -> None:
        """Callback från suppliers_store.on_change."""
        if store_name == "suppliers":
            self._do_refresh()

    def _on_search_changed(self) -> None:
        """Debounce — sökningen körs 250 ms efter sista tangenttrycket."""
        self._search_timer.start()

    def _do_refresh(self) -> None:
        """Hämtar data från app, filtrerar sökningen och ritar tabellen."""
        try:
            self._all_data = self._app.get_suppliers()
        except Exception as exc:
            log.error("SuppliersView refresh: %s", exc)
            self._all_data = []

        query = self._search.text().strip().lower()
        if query:
            filtered = [
                s
                for s in self._all_data
                if any(
                    query in str(s.get(k, "")).lower()
                    for k in SEARCH_FIELDS
                )
            ]
        else:
            filtered = list(self._all_data)

        self._populate_table(filtered)

        n_total = len(self._all_data)
        n_shown = len(filtered)
        where = self._source_label()
        if n_total == 0:
            text = f"Leverantörer: 0  ·  {where}  — filen är tom"
        else:
            text = (
                f"Leverantörer: {n_shown}"
                + (f" av {n_total}" if query and n_shown != n_total else "")
                + f"  ·  {where}"
            )
        self._lbl_count.setText(text)
        self._lbl_count.setToolTip(
            "Appen läser bara data/suppliers.json i appmappen.\n"
            "Finns en kopia i ui/data slås den ihop hit när du trycker Uppdatera.\n"
            "Spara filen i editorn först om du just skrivit i den."
        )

    def _source_label(self) -> str:
        """Relativ sökväg till filen appen faktiskt läser."""
        try:
            path = Path(self._app.suppliers_store.file)
            root = path.parents[1] if path.parent.name == "data" else path.parent
            return path.relative_to(root).as_posix()
        except Exception:
            return "data/suppliers.json"

    def _reload_from_disk(self) -> None:
        """Läser om data/suppliers.json från disk, inklusive kopior."""
        try:
            if hasattr(self._app, "rescan_data"):
                self._app.rescan_data()
        except Exception as exc:
            log.error("rescan_data: %s", exc)
        self._do_refresh()

    def _populate_table(self, data: list[dict]) -> None:
        """Ritar tabellen. Senast ändrad leverantör sist (från app)."""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(data))
        dark = self._is_dark()
        body = "#f7f4ea" if dark else "#1a1d22"
        even = "#173044" if dark else "#f7fbff"
        odd = "#2a5a7a" if dark else "#9bb8dc"
        accent = self._current_theme.get(
            "accent", "#8ec0ff" if dark else "#0b5cab"
        )
        if getattr(self, "_row_delegate", None) is not None:
            self._row_delegate.set_theme(dark=dark, select_bg="#0b5cab")

        for row, supplier in enumerate(data):
            fav = bool(supplier.get("favorite"))
            stripe = "#f0c14a" if fav else accent
            for col, (key, align) in enumerate(
                zip(COL_KEYS, COL_ALIGN)
            ):
                val = supplier.get(key, "")
                txt = str(val) if val != "" else ""
                if col == 0 and fav:
                    txt = f"★ {txt}"
                preferred = accent if col == 0 else ""
                fg = fg_on_row(even, preferred, body, dark)
                item = _cell(
                    txt,
                    align,
                    bold=True,
                    fg=fg,
                    numeric=key in NUMERIC_KEYS,
                )
                item.setData(Qt.ItemDataRole.UserRole, supplier.get("id", ""))
                item.setData(ROLE_ROW_BG, even)
                item.setData(ROLE_ROW_BG_ODD, odd)
                item.setData(ROLE_ROW_FG, fg)
                item.setData(ROLE_STRIPE, stripe if col == 0 else "")
                if txt:
                    item.setToolTip(txt)
                self._table.setItem(row, col, item)

        self._table.setSortingEnabled(True)
        self._table.resizeRowsToContents()
        ensure_row_height(self._table, 40)
        self._update_buttons()

    # ══════════════════════════════════════════════════════════════════
    #  MARKERING
    # ══════════════════════════════════════════════════════════════════

    def _on_selection_changed(self) -> None:
        self._update_buttons()
        s = self._selected_supplier()
        if s:
            self.supplier_selected.emit(s)

    def _update_buttons(self) -> None:
        has = self._selected_id() is not None
        self._btn_edit.setEnabled(has)
        self._btn_duplicate.setEnabled(has)
        self._btn_delete.setEnabled(has)

    def _selected_id(self) -> str | None:
        rows = self._table.selectedItems()
        if not rows:
            return None
        val = rows[0].data(Qt.ItemDataRole.UserRole)
        return val if val else None

    def _selected_supplier(self) -> dict | None:
        sid = self._selected_id()
        if not sid:
            return None
        for s in self._all_data:
            if s.get("id") == sid:
                return s
        return None

    # ══════════════════════════════════════════════════════════════════
    #  CRUD
    # ══════════════════════════════════════════════════════════════════

    def _add_supplier(self) -> None:
        dialog = SupplierDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        if not data["name"]:
            return

        # Dubblettvarning på namn
        existing = [
            s
            for s in self._all_data
            if s.get("name", "").lower() == data["name"].lower()
        ]
        if existing:
            reply = QMessageBox.question(
                self,
                "Möjlig dublett",
                f"'{data['name']}' finns redan.\nLägg till ändå?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            self._app.add_supplier(data)
            log.info("Leverantör tillagd: %s", data["name"])
        except Exception as exc:
            log.error("add_supplier: %s", exc)
            QMessageBox.critical(self, "Fel", f"Kunde inte spara:\n{exc}")
            return

        self._do_refresh()
        self._statusbar(f"✅  Leverantör '{data['name']}' sparad.")

    def _edit_supplier(self) -> None:
        supplier = self._selected_supplier()
        if not supplier:
            return
        dialog = SupplierDialog(parent=self, existing=supplier)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.get_data()
        try:
            self._app.update_supplier(supplier["id"], data)
            log.info("Leverantör uppdaterad: %s", data["name"])
        except Exception as exc:
            log.error("update_supplier: %s", exc)
            QMessageBox.critical(
                self, "Fel", f"Kunde inte uppdatera:\n{exc}"
            )
            return
        self._do_refresh()
        self._statusbar(f"✅  Leverantör '{data['name']}' uppdaterad.")

    def _delete_supplier(self) -> None:
        supplier = self._selected_supplier()
        if not supplier:
            return
        reply = QMessageBox.question(
            self,
            "Ta bort leverantör",
            f"Ta bort '{supplier.get('name', '')}'?\nKan inte ångras.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._app.delete_supplier(supplier["id"])
            log.info("Leverantör borttagen: %s", supplier.get("name", ""))
        except Exception as exc:
            log.error("delete_supplier: %s", exc)
            QMessageBox.critical(self, "Fel", str(exc))
            return
        self._do_refresh()
        self._statusbar(
            f"🗑  Leverantör '{supplier.get('name', '')}' borttagen."
        )

    def _duplicate_supplier(self) -> None:
        supplier = self._selected_supplier()
        if not supplier:
            return
        data = {
            k: v
            for k, v in supplier.items()
            if k not in ("id", "created_at", "updated_at")
        }
        data["name"] = data.get("name", "") + " (kopia)"
        dialog = SupplierDialog(parent=self, existing=data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_data()
            try:
                self._app.add_supplier(new_data)
                log.info("Leverantör duplicerad: %s", new_data["name"])
                self._do_refresh()
                self._statusbar(
                    f"✅  Duplicerad som '{new_data['name']}'."
                )
            except Exception as exc:
                log.error("duplicate_supplier: %s", exc)
                QMessageBox.critical(self, "Fel", str(exc))

    # ══════════════════════════════════════════════════════════════════
    #  EXPORT (CSV / JSON)
    # ══════════════════════════════════════════════════════════════════

    def _export_suppliers(self) -> None:
        """Exporterar leverantörslistan till CSV eller JSON."""
        if not self._all_data:
            QMessageBox.information(
                self, "Export", "Inga leverantörer att exportera."
            )
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        # Alltid i appmappen. Ingen sökväg utanför.
        root = Path(__file__).resolve().parent.parent / "exports"
        day = root / datetime.date.today().isoformat()
        day.mkdir(parents=True, exist_ok=True)
        path = str(day / f"leverantorer_{ts}.csv")

        try:
            p = Path(path)
            if path.endswith(".json"):
                p.write_text(
                    json.dumps(self._all_data, indent=4, ensure_ascii=False),
                    encoding="utf-8",
                )
            else:
                # Semikolonseparerad CSV (svensk Excel-standard) med BOM
                lines = [";".join(COL_LABELS)]
                for s in self._all_data:
                    row = [
                        str(s.get(key, "")).replace(";", ",")
                        for key in COL_KEYS
                    ]
                    lines.append(";".join(row))
                p.write_text("\n".join(lines), encoding="utf-8-sig")

            log.info("Leverantörer exporterade till %s", path)
            self._statusbar(f"📄  Exporterade till {p.name}")
            QMessageBox.information(
                self,
                "Export klar",
                f"✅  {len(self._all_data)} leverantörer exporterade.\n\n"
                f"{path}",
            )
        except Exception as exc:
            log.error("export_suppliers: %s", exc)
            QMessageBox.critical(self, "Export-fel", str(exc))

    # ══════════════════════════════════════════════════════════════════
    #  HÖGERKLICK-MENY
    # ══════════════════════════════════════════════════════════════════

    def _row_context_menu(self, pos) -> None:
        """
        Högerklick i tabellen.

        Markerar först raden UNDER muspekaren (så att menyn alltid
        gäller rätt leverantör, även om en annan rad var markerad).
        """
        item = self._table.itemAt(pos)
        if item is None:
            return
        self._table.selectRow(item.row())
        rid = item.data(Qt.ItemDataRole.UserRole)
        if not rid:
            return

        menu = QMenu(self)
        menu.addAction("✏️  Redigera", self._edit_supplier)
        menu.addAction("📋  Duplicera", self._duplicate_supplier)
        menu.addSeparator()
        menu.addAction("📄  Exportera", self._export_suppliers)
        menu.addSeparator()
        menu.addAction("🗑  Ta bort", self._delete_supplier)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    # ══════════════════════════════════════════════════════════════════
    #  PUBLIKT API  (invoices_view, pdf_export, plugins)
    # ══════════════════════════════════════════════════════════════════

    def get_supplier_names(self) -> list[str]:
        """Sorterad lista av leverantörsnamn (för autocomplete)."""
        return sorted(
            s.get("name", "") for s in self._all_data if s.get("name")
        )

    def get_supplier_by_name(self, name: str) -> dict | None:
        """Hämtar en leverantör baserat på namn (case-insensitive)."""
        target = name.lower()
        for s in self._all_data:
            if s.get("name", "").lower() == target:
                return s
        return None

    def prompt_add_supplier(self, name: str) -> dict | None:
        """
        Anropas av InvoicesView när ett leverantörsnamn är okänt.

        Öppnar dialog förifylld med namnet och returnerar det sparade
        recordet, eller None om användaren avbryter.
        """
        reply = QMessageBox.question(
            self,
            "Okänd leverantör",
            f"Leverantören '{name}' finns inte.\nLägga till nu?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return None

        dialog = SupplierDialog(parent=self, existing={"name": name})
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            try:
                result = self._app.add_supplier(data)
                self._do_refresh()
                log.info("Leverantör auto-tillagd: %s", data["name"])
                return result
            except Exception as exc:
                log.error("prompt_add_supplier: %s", exc)
                QMessageBox.critical(self, "Fel", str(exc))
        return None

    def refresh(self) -> None:
        """Extern refresh-hook (kallas av MainWindow._refresh_all)."""
        self._do_refresh()

    # ══════════════════════════════════════════════════════════════════
    #  TEMA
    # ══════════════════════════════════════════════════════════════════

    def _is_dark(self) -> bool:
        """True om aktuellt tema är mörkt (baserat på bakgrundsfärg)."""
        return self._current_theme.get("bg", "#0d1117") not in (
            "#f5f7fa", "#ffffff", "#f8f9fa", "#f6f8fa",
        )

    def apply_theme(self, theme: dict) -> None:
        """
        Kallas av MainWindow.theme_changed-signalen.

        Mörkt tema = vit fet text.  Ljust tema = mörk fet text.
        Knappar och tabbar anpassas alltid för läsbarhet.
        """
        self._current_theme = theme
        t = theme
        dark = self._is_dark()

        text_strong = t.get("text_strong", "#f0f6fc" if dark else "#1c2128")
        accent      = t.get("accent",      "#58a6ff" if dark else "#0969da")
        accent_hov  = t.get("accent_hover", "#388bfd" if dark else "#0550ae")
        header_bg   = t.get("header_bg",   "#161b22" if dark else "#0969da")
        row_normal  = t.get("row_normal",  "#0d1117" if dark else "#ffffff")
        row_alt     = t.get("row_alt",     "#161b22" if dark else "#f6f8fa")
        border      = t.get("border",      "#30363d" if dark else "#d0d7de")
        input_bg    = t.get("input_bg",    "#0d1117" if dark else "#ffffff")
        input_bdr   = t.get("input_border", "#30363d" if dark else "#d0d7de")
        button_bg   = t.get("button_bg",   "#21262d" if dark else "#6e7781")
        button_text = t.get("button_text", "#f0f6fc" if dark else "#ffffff")
        button_hov  = t.get("button_hover", "#30363d" if dark else "#57606a")
        error       = t.get("error",       "#f85149" if dark else "#cf222e")
        info        = t.get("info",        "#58a6ff" if dark else "#0969da")

        # ── Tabell ─────────────────────────────────────────────────────
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color           : {row_normal};
                color                      : {text_strong};
                font-weight                : 700;
                font-size                  : 12px;
                gridline-color             : {"#8ea4ba" if dark else "#8a7d6c"};
                alternate-background-color : {row_alt};
                selection-background-color : {accent};
                selection-color            : #ffffff;
                border                     : 1px solid {border};
                border-radius              : 6px;
                outline                    : none;
            }}
            QHeaderView::section {{
                background-color : {header_bg};
                color            : #ffffff;
                font-weight      : 700;
                font-size        : 12px;
                padding          : 6px 8px;
                border           : none;
                border-right     : 1px solid {border};
                border-bottom    : 1px solid {border};
            }}
            QHeaderView::section:first {{
                border-radius : 6px 0 0 0;
            }}
            QTableWidget::item {{
                padding : 8px 8px;
                color   : {text_strong};
            }}
            QTableWidget::item:selected {{
                background-color : {"#d6e8ff" if dark else accent};
                color            : {"#102033" if dark else "#ffffff"};
            }}
            QScrollBar:vertical {{
                background    : {row_alt};
                width         : 10px;
                border-radius : 5px;
            }}
            QScrollBar::handle:vertical {{
                background    : {accent};
                border-radius : 5px;
                min-height    : 20px;
            }}
        """)

        # ── Knappar ────────────────────────────────────────────────────
        btn_specs = [
            (self._btn_add,       accent,    accent_hov, "#ffffff"),
            (self._btn_edit,      button_bg, button_hov, button_text),
            (self._btn_duplicate, button_bg, button_hov, button_text),
            (self._btn_delete,    error,     "#da3633",  "#ffffff"),
            (self._btn_export,    info,      accent_hov, "#ffffff"),
            (self._btn_refresh,   button_bg, button_hov, button_text),
        ]
        for btn, bg, hov, fg in btn_specs:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color : {bg};
                    color            : {fg};
                    font-weight      : 700;
                    font-size        : 12px;
                    border-radius    : 7px;
                    border           : none;
                    padding          : 6px 14px;
                    min-height       : 36px;
                }}
                QPushButton:hover   {{ background-color : {hov}; }}
                QPushButton:pressed {{ background-color : {accent};
                                       color : #ffffff; }}
                QPushButton:disabled {{
                    background-color : {border};
                    color            : #666666;
                }}
            """)

        # ── Sökfält ────────────────────────────────────────────────────
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background-color : {input_bg};
                color            : {text_strong};
                border           : 1.5px solid {input_bdr};
                border-radius    : 7px;
                padding          : 4px 10px;
                font-size        : 12px;
                font-weight      : 600;
            }}
            QLineEdit:focus {{
                border-color : {accent};
            }}
        """)

        # ── Labels ─────────────────────────────────────────────────────
        self._lbl_count.setStyleSheet(
            f"color:{text_strong}; font-weight:700; background:transparent;"
        )

        self._do_refresh()

    # ══════════════════════════════════════════════════════════════════
    #  HJÄLPARE
    # ══════════════════════════════════════════════════════════════════

    def _statusbar(self, msg: str, timeout: int = 4000) -> None:
        """Visar ett meddelande i huvudfönstrets statusrad."""
        top = self.window()
        if hasattr(top, "statusBar"):
            top.statusBar().showMessage(msg, timeout)


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN HOOKS
# ═════════════════════════════════════════════════════════════════════


def register(app: Any) -> None:
    """Fas 1: app-nivå-registrering (ingen UI ännu)."""
    log.info("suppliers_view register (fas 1) OK")


def register_ui(main_window: Any) -> None:
    """
    Fas 2: monterar SuppliersView i MainWindow-fliken 'suppliers'.

    OBS: SuppliersView laddas OCKSÅ direkt av
    MainWindow._load_builtin_views() som inbyggd vy. Denna hook är
    säkrad mot dubbelregistrering via isinstance-kontroll.
    """
    try:
        existing = main_window.get_suppliers_view()
        if existing and isinstance(existing, SuppliersView):
            try:
                main_window.theme_changed.connect(existing.apply_theme)
                existing.apply_theme(main_window.current_theme_dict())
            except Exception:
                pass
            log.info(
                "SuppliersView redan laddad — hoppar över dubbelinit"
            )
            return

        app = main_window._app
        view = SuppliersView(app, parent=main_window)
        main_window.replace_tab_content("suppliers", view)
        main_window.theme_changed.connect(view.apply_theme)
        view.apply_theme(main_window.current_theme_dict())
        log.info("SuppliersView registrerad (fas 2) OK")
    except Exception as exc:
        log.error("suppliers_view register_ui: %s", exc, exc_info=True)
