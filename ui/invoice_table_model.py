# -*- coding: utf-8 -*-
"""Model-based data adapter for the registered-invoices table."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor

try:
    from ui.invoices_helpers import (
        COL_ALIGN, COL_KEYS, COL_LABELS, STATUS_COLORS, fmt_amount,
        make_font,
    )
    from ui.i18n import tr, tr_list, tr_status, tr_type
    from ui.typography import make_tabular_font, scaled_point_size
except ImportError:  # pragma: no cover - standalone imports
    from invoices_helpers import (  # type: ignore[no-redef]
        COL_ALIGN, COL_KEYS, COL_LABELS, STATUS_COLORS, fmt_amount,
        make_font,
    )
    from i18n import tr, tr_list, tr_status, tr_type  # type: ignore[no-redef]
    from typography import (  # type: ignore[no-redef]
        make_tabular_font, scaled_point_size,
    )


SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class InvoiceTableModel(QAbstractTableModel):
    """Rows, cell presentation, export checkboxes, and sort values.

    The invoice collection remains owned by ``InvoicesView``. This model
    holds only the currently visible rows and the per-ID export marks.
    ``QSortFilterProxyModel`` can sort it without changing the underlying
    invoice data or invalidating row selection.
    """

    exportMarkChanged = Signal(str, bool)

    def __init__(
        self,
        *,
        page_counter: Callable[[dict], int] | None = None,
        status_row_bg: dict[str, tuple[str, str]] | None = None,
        dark: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._marked_export_ids: set[str] = set()
        translated_headers = tr_list("invoices.columns")
        self._headers = (
            list(translated_headers)
            if len(translated_headers) == len(COL_KEYS)
            else list(COL_LABELS)
        )
        self._page_counter = page_counter
        self._status_row_bg = dict(status_row_bg or {})
        self._dark = bool(dark)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(COL_KEYS) + 1

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < self.columnCount():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return "☑" if section == 0 else self._headers[section - 1]
        if role == Qt.ItemDataRole.ToolTipRole:
            if section == 0:
                return tr("invoices.export_check_tip")
            full = {
                "Fakturanr": "Fakturanummer",
                "Förfaller": "Förfallodatum",
                "Betaldatum": "Betalningsdatum",
                "Notering": "Anteckning",
            }
            label = self._headers[section - 1]
            return full.get(label, label)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            if section == 0:
                return tr("invoices.export_check_header_accessible")
            return self._headers[section - 1]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (
            0 <= index.row() < len(self._rows)
            and 0 <= index.column() < self.columnCount()
        ):
            return None

        invoice = self._rows[index.row()]
        column = index.column()
        invoice_id = str(invoice.get("id", "") or "")

        if role == Qt.ItemDataRole.UserRole:
            return invoice_id
        if role == Qt.ItemDataRole.AccessibleTextRole:
            if column == 0:
                return tr("invoices.export_check_accessible")
            if COL_KEYS[column - 1] == "status":
                return tr(
                    "invoices.status_accessible",
                    status=tr_status(str(invoice.get("status", "") or "")),
                )
        if role == Qt.ItemDataRole.BackgroundRole:
            pair = self._status_row_bg.get(
                str(invoice.get("status", ""))
            )
            if pair:
                return QColor(pair[0] if self._dark else pair[1])

        if column == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return (
                    Qt.CheckState.Checked
                    if invoice_id in self._marked_export_ids
                    else Qt.CheckState.Unchecked
                )
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignCenter)
            if role == Qt.ItemDataRole.ToolTipRole:
                return tr("invoices.export_check_tip")
            if role == SORT_ROLE:
                # Export-checkboxes are not a meaningful sort key; keep
                # the source order if the header is clicked.
                return ""
            return None

        key = COL_KEYS[column - 1]
        raw = invoice.get(key, "")
        text = self._display_text(invoice, key, raw)

        if role == Qt.ItemDataRole.DisplayRole:
            return text
        if role == Qt.ItemDataRole.ToolTipRole:
            if key == "pages":
                pages = self._page_count(invoice)
                if pages >= 2:
                    return tr("invoices.pages_tooltip", n=pages)
            return text or None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(COL_ALIGN[column - 1]) | int(Qt.AlignmentFlag.AlignVCenter)
        if role == SORT_ROLE:
            return self._sort_value(invoice, key, raw)
        if role == Qt.ItemDataRole.ForegroundRole:
            if key == "status":
                pair = STATUS_COLORS.get(str(raw or ""), ("", ""))
                color = pair[0] if self._dark else pair[1]
                return QColor(color) if color else None
            if key == "invoice_type" and str(raw) == "Kreditfaktura":
                return QColor("#64b5f6" if self._dark else "#1565c0")
            if key == "total_amount" and self._as_float(raw) < 0:
                return QColor("#64b5f6" if self._dark else "#1565c0")
            if key == "pages" and self._page_count(invoice) >= 2:
                return QColor("#d29922" if self._dark else "#9a6700")
        if role == Qt.ItemDataRole.FontRole:
            if key in {
                "invoice_number", "ocr", "date", "due_date",
                "payment_date", "total_amount", "pages",
            }:
                return make_tabular_font(
                    scaled_point_size(12), bold=True
                )
            return make_font(scaled_point_size(12), True)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(  # noqa: N802
        self, index: QModelIndex, value: Any,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            not index.isValid() or index.column() != 0
            or role != Qt.ItemDataRole.CheckStateRole
        ):
            return False
        invoice_id = str(self._rows[index.row()].get("id", "") or "")
        if not invoice_id:
            return False
        checked = value == Qt.CheckState.Checked
        if not checked:
            try:
                checked = int(value) == int(Qt.CheckState.Checked)
            except (TypeError, ValueError):
                checked = False
        already_checked = invoice_id in self._marked_export_ids
        if checked == already_checked:
            return True
        if checked:
            self._marked_export_ids.add(invoice_id)
        else:
            self._marked_export_ids.discard(invoice_id)
        self.dataChanged.emit(
            index, index,
            [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.ToolTipRole],
        )
        self.exportMarkChanged.emit(invoice_id, checked)
        return True

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def set_headers(self, headers: list[str]) -> None:
        if len(headers) == len(COL_KEYS):
            self._headers = list(headers)
            self.headerDataChanged.emit(
                Qt.Orientation.Horizontal, 0, self.columnCount() - 1
            )

    def set_dark(self, dark: bool) -> None:
        dark = bool(dark)
        if self._dark == dark:
            return
        self._dark = dark
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, self.columnCount() - 1),
                [Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole],
            )

    def set_marked_export_ids(self, ids: set[str]) -> None:
        updated = {str(item) for item in ids if str(item)}
        if updated == self._marked_export_ids:
            return
        self._marked_export_ids = updated
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._rows) - 1, 0),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def _page_count(self, invoice: dict) -> int:
        if not callable(self._page_counter):
            return 0
        try:
            return max(0, int(self._page_counter(invoice) or 0))
        except Exception:
            return 0

    def _display_text(self, invoice: dict, key: str, raw: Any) -> str:
        if key == "total_amount":
            return fmt_amount(self._as_float(raw), "").strip()
        if key == "pages":
            pages = self._page_count(invoice)
            return str(pages) if pages else ""
        if key == "invoice_type":
            return tr_type(str(raw) if raw else "Faktura")
        if key == "status":
            return tr_status(str(raw)) if raw else ""
        return str(raw) if raw not in ("", None) else ""

    def _sort_value(self, invoice: dict, key: str, raw: Any) -> Any:
        if key == "total_amount":
            return self._as_float(raw)
        if key == "pages":
            return self._page_count(invoice)
        if key in {"date", "due_date", "payment_date"}:
            return str(raw or "")
        return str(self._display_text(invoice, key, raw) or "").casefold()

    @staticmethod
    def _as_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
