# -*- coding: utf-8 -*-
"""
HistoryView — egen Historik-flik för exporterade/betalda fakturor.

Betalda/exporterade fakturor bor INTE längre i huvudfilen
invoices.json: varje leverantör har en egen fil i data/betalda/
(<leverantör>.json), skriven av SupplierArchiveStore i app.py.

* Fakturor-fliken visar bara huvudregistret (det som ännu inte
  exporterats) — Historik visar arkivet, läsbart och sökbart.
* Vid import/skanning söks BÅDA registren igenom (motorns all()),
  så en redan betald faktura känns igen som dubblett och
  registreras aldrig en gång till.
* Originalen ligger kvar där de alltid legat (t.ex. i den
  bevakade mappen) — det som flyttats hit är bara registerposten.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.i18n import tr
except ImportError:  # fristående körning av filen
    from i18n import tr  # type: ignore[no-redef]

try:
    from ui.invoices_helpers import COLUMNS, fmt_amount, make_font
except ImportError:  # pragma: no cover
    from invoices_helpers import COLUMNS, fmt_amount, make_font  # type: ignore[no-redef]

log = logging.getLogger("HistoryView")

_SEARCH_FIELDS = (
    "supplier", "invoice_number", "ocr", "reference", "note", "status",
)


def filter_history(
    records: list[dict], query: str = "", supplier: str = ""
) -> list[dict]:
    """Filtrerar arkivposter (fritext + leverantör). Ren funktion
    — testbar utan Qt."""
    q = str(query or "").strip().lower()
    sup = str(supplier or "").strip().lower()
    out: list[dict] = []
    for r in records or []:
        if sup and str(r.get("supplier", "")).strip().lower() != sup:
            continue
        if q and not any(
            q in str(r.get(k, "")).lower() for k in _SEARCH_FIELDS
        ):
            continue
        out.append(r)
    return out


def paid_total(records: list[dict]) -> float:
    """Nettosumma av arkivposter (fakturor +, krediter −)."""
    total = 0.0
    for r in records or []:
        try:
            total += float(r.get("total_amount", 0) or 0)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


class HistoryView(QWidget):
    """Tabell över betalda/exporterade fakturor (data/betalda/)."""

    def __init__(self, app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._app = app
        self._records: list[dict] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        lbl_title = QLabel(tr("history.title"))
        lbl_title.setFont(make_font(15, bold=True))
        root.addWidget(lbl_title)

        row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("history.search"))
        self._search.setMinimumHeight(36)
        self._search.textChanged.connect(lambda _t: self.refresh())
        row.addWidget(self._search, stretch=1)

        self._supplier_filter = QComboBox()
        self._supplier_filter.setMinimumHeight(36)
        self._supplier_filter.addItem(tr("history.all_suppliers"), "")
        self._supplier_filter.currentIndexChanged.connect(
            lambda _i: self.refresh()
        )
        row.addWidget(self._supplier_filter)

        self._btn_folder = QPushButton(tr("history.open_folder"))
        self._btn_folder.setMinimumHeight(36)
        self._btn_folder.clicked.connect(self._open_archive_folder)
        row.addWidget(self._btn_folder)
        root.addLayout(row)

        self._lbl_count = QLabel("")
        root.addWidget(self._lbl_count)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(
            [c[0] for c in COLUMNS]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        header = self._table.horizontalHeader()
        for idx, (_label, _key, width, _align) in enumerate(COLUMNS):
            header.resizeSection(idx, width)
        header.setSectionResizeMode(
            len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self._table, stretch=1)

        self._lbl_empty = QLabel(tr("history.empty"))
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._lbl_empty)

        self.refresh()

    # ── Data ───────────────────────────────────────────────────────

    def _fetch(self) -> list[dict]:
        try:
            if self._app is not None and hasattr(
                self._app, "get_archived_invoices"
            ):
                return list(self._app.get_archived_invoices() or [])
        except Exception as exc:
            log.warning("history fetch: %s", exc)
        return []

    def refresh(self) -> None:
        """Läser om arkivet och ritar tabellen (anropas av
        huvudfönstrets refresh + vid filterändring)."""
        self._records = self._fetch()
        self._sync_supplier_filter()
        supplier = str(self._supplier_filter.currentData() or "")
        rows = filter_history(
            self._records,
            query=self._search.text(),
            supplier=supplier,
        )
        self._populate(rows)
        self._lbl_count.setText(
            tr(
                "history.count",
                shown=len(rows),
                total=len(self._records),
                sum=fmt_amount(paid_total(rows)),
            )
        )
        self._lbl_empty.setVisible(not self._records)

    def _sync_supplier_filter(self) -> None:
        current = str(self._supplier_filter.currentData() or "")
        names = sorted(
            {
                str(r.get("supplier", "")).strip()
                for r in self._records
                if str(r.get("supplier", "")).strip()
            }
        )
        self._supplier_filter.blockSignals(True)
        self._supplier_filter.clear()
        self._supplier_filter.addItem(tr("history.all_suppliers"), "")
        for name in names:
            self._supplier_filter.addItem(name, name)
        idx = self._supplier_filter.findData(current)
        self._supplier_filter.setCurrentIndex(max(idx, 0))
        self._supplier_filter.blockSignals(False)

    def _populate(self, rows: list[dict]) -> None:
        self._table.setRowCount(len(rows))
        for row_idx, rec in enumerate(rows):
            for col_idx, (_label, key, _width, align) in enumerate(
                COLUMNS
            ):
                value = rec.get(key, "")
                if key == "total_amount":
                    try:
                        text = fmt_amount(float(value or 0))
                    except (TypeError, ValueError):
                        text = str(value or "")
                else:
                    text = str(value or "")
                item = QTableWidgetItem(text)
                item.setTextAlignment(align)
                if key == "total_amount":
                    item.setFont(make_font(11, bold=True))
                self._table.setItem(row_idx, col_idx, item)

    # ── Arkivmapp ──────────────────────────────────────────────────

    def _archive_dir(self):
        try:
            from app import DATA_DIR

            return DATA_DIR / "betalda"
        except Exception:
            from pathlib import Path

            return Path("data") / "betalda"

    def _open_archive_folder(self) -> None:
        folder = self._archive_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            from ui.invoices_helpers import open_folder

            open_folder(str(folder))
        except Exception as exc:
            log.warning("history open folder: %s", exc)
