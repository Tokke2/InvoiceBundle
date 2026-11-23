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
* Originalen i bevakade mappar ligger i undermappar efter fakturaår
  från lyckad registrering; exporten flyttar inte originalen vidare.
  Det som flyttats hit är bara registerposten.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.i18n import tr, tr_list
except ImportError:  # fristående körning av filen
    from i18n import tr, tr_list  # type: ignore[no-redef]

try:
    from ui.design import ICON_HEADER_PX, app_icon_pixmap, header_font
except Exception:  # pragma: no cover
    try:
        from design import (  # type: ignore[no-redef]
            ICON_HEADER_PX, app_icon_pixmap, header_font,
        )
    except Exception:
        ICON_HEADER_PX = 28  # type: ignore[no-redef]

        def app_icon_pixmap(size: int = 28):  # type: ignore[no-redef]
            from PySide6.QtGui import QPixmap
            return QPixmap()

        def header_font():  # type: ignore[no-redef]
            from PySide6.QtGui import QFont
            return QFont("Segoe UI", 17, QFont.Weight.Bold)

try:
    from ui.icons import (
        attach_search_icon,
        bind_icon,
        qss_indicator_urls,
        refresh_bound_icons,
    )
except Exception:  # pragma: no cover
    try:
        from icons import (  # type: ignore[no-redef]
            attach_search_icon,
            bind_icon,
            qss_indicator_urls,
            refresh_bound_icons,
        )
    except Exception:
        def bind_icon(target: Any, *_a: Any, **_kw: Any) -> Any:  # type: ignore[no-redef]
            return target

        def attach_search_icon(target: Any, *_a: Any, **_kw: Any) -> Any:  # type: ignore[no-redef]
            return target

        def qss_indicator_urls(*_a: Any, **_kw: Any) -> dict[str, str]:  # type: ignore[no-redef]
            return {}

        def refresh_bound_icons(*_a: Any, **_kw: Any) -> None:  # type: ignore[no-redef]
            pass

try:
    from ui.invoices_helpers import (
        COLUMNS, DATE_COLUMN_KEYS, date_column_width,
        fmt_amount, is_dark_theme, make_font,
    )
    from ui.typography import make_tabular_font, set_item_font
except ImportError:  # pragma: no cover
    from invoices_helpers import (  # type: ignore[no-redef]
        COLUMNS, DATE_COLUMN_KEYS, date_column_width,
        fmt_amount, is_dark_theme, make_font,
    )
    from typography import (  # type: ignore[no-redef]
        make_tabular_font, set_item_font,
    )

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
        self._current_theme: dict = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        pix = app_icon_pixmap(ICON_HEADER_PX)
        if not pix.isNull():
            mark = QLabel()
            mark.setPixmap(pix)
            mark.setStyleSheet("background:transparent;")
            head.addWidget(mark)
        self._lbl_title = QLabel(tr("history.title"))
        self._lbl_title.setFont(header_font())
        self._lbl_title.setWordWrap(True)
        self._lbl_title.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        head.addWidget(self._lbl_title, stretch=1)
        self._lbl_count = QLabel("")
        self._lbl_count.setObjectName("CountChip")
        self._lbl_count.setFont(make_tabular_font(11, bold=True))
        head.addWidget(self._lbl_count)
        root.addLayout(head)

        row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        row.setSpacing(8)
        self._filter_bar = row
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("history.search"))
        self._search.setMinimumHeight(36)
        self._search.setMinimumWidth(220)
        self._search.setClearButtonEnabled(True)
        attach_search_icon(self._search, size=14)
        self._search.textChanged.connect(lambda _t: self.refresh())
        row.addWidget(self._search, stretch=1)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        self._supplier_filter = QComboBox()
        self._supplier_filter.setMinimumHeight(36)
        self._supplier_filter.setMinimumWidth(180)
        self._supplier_filter.addItem(tr("history.all_suppliers"), "")
        self._supplier_filter.currentIndexChanged.connect(
            lambda _i: self.refresh()
        )
        controls_row.addWidget(self._supplier_filter, stretch=1)

        self._btn_folder = QPushButton(tr("history.open_folder"))
        self._btn_folder.setMinimumHeight(36)
        bind_icon(self._btn_folder, "folder", size=15)
        self._btn_folder.clicked.connect(self._open_archive_folder)
        controls_row.addWidget(self._btn_folder)
        row.addLayout(controls_row)
        root.addLayout(row)

        self._table = QTableWidget(0, len(COLUMNS))
        headers = tr_list("invoices.columns")
        self._table.setHorizontalHeaderLabels(
            headers if len(headers) == len(COLUMNS) else [c[0] for c in COLUMNS]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._table.setHorizontalScrollMode(
            QTableWidget.ScrollMode.ScrollPerPixel
        )
        self._apply_column_widths()
        root.addWidget(self._table, stretch=1)

        self._lbl_empty = QLabel(tr("history.empty"))
        self._lbl_empty.setProperty("muted", True)
        self._lbl_empty.setWordWrap(True)
        self._lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_empty.setStyleSheet("padding:16px 20px; background:transparent;")
        root.addWidget(self._lbl_empty)

        self.refresh()
        self.apply_theme(None)

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
                item.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                if key in {
                    "invoice_number", "ocr", "date", "due_date",
                    "payment_date", "total_amount",
                }:
                    set_item_font(
                        item,
                        make_tabular_font(11, bold=(key == "total_amount")),
                    )
                self._table.setItem(row_idx, col_idx, item)

    # ── Tema / språk ───────────────────────────────────────────────

    def apply_theme(self, theme: dict | None = None) -> None:
        """Anpassar Historik-vyn, kontroller, tabell och ikoner till aktivt tema."""
        t = dict(theme or {})
        self._current_theme = t
        dark = is_dark_theme(t) if t else True

        text_strong = t.get("text_strong", "#f4f7fb" if dark else "#0d1218")
        muted = t.get("text_muted", t.get("muted", "#9eb2c9" if dark else "#4f5b69"))
        accent = t.get("accent", "#3d8bfd" if dark else "#0b5cab")
        chip_bg = t.get("tab_selected", accent)
        header_bg = t.get("header_bg", "#162d49" if dark else "#16335b")
        row_normal = t.get("row_normal", "#0f1720" if dark else "#ffffff")
        row_alt = t.get("row_alt", "#162231" if dark else "#eef4fb")
        card_bg = t.get("card_bg", "#131c27" if dark else "#ffffff")
        border = t.get("border", "#263649" if dark else "#d6cec0")
        grid_c = "#243447" if dark else "#e2dbd0"
        input_bg = t.get("input_bg", "#0f1720" if dark else "#ffffff")
        input_bdr = t.get("input_border", "#304358" if dark else "#c9c0b0")
        btn_bg = t.get("button_bg", "#1a2634" if dark else "#ffffff")
        btn_text = t.get("button_text", "#f4f7fb" if dark else "#1c2128")
        btn_hov = t.get("button_hover", "#253447" if dark else "#eef3f9")
        scroll_bg = t.get("scrollbar_bg", "#0c1218" if dark else "#f4f1ea")
        scroll_h = t.get("scrollbar_handle", "#34465a" if dark else "#c7beae")

        self._lbl_title.setStyleSheet(
            f"color:{text_strong}; background:transparent; font-weight:700;"
        )
        self._lbl_count.setStyleSheet(
            f"background-color:{chip_bg}; color:#ffffff;"
            " border-radius:11px; padding:4px 12px; font-weight:700;"
        )
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background-color : {input_bg};
                color            : {text_strong};
                border           : 1.5px solid {input_bdr};
                border-radius    : 8px;
                padding          : 5px 10px;
                font-size        : 13px;
                font-weight      : 600;
            }}
            QLineEdit:focus {{
                border : 2px solid {accent};
            }}
        """)

        qss_urls = qss_indicator_urls(text_strong)
        down_path = qss_urls.get("chevron_down", "")
        down_css = f"image: url({down_path});" if down_path else ""
        self._supplier_filter.setStyleSheet(f"""
            QComboBox {{
                background-color : {input_bg};
                color            : {text_strong};
                border           : 1.5px solid {input_bdr};
                border-radius    : 8px;
                padding          : 5px 28px 5px 10px;
                font-size        : 13px;
                font-weight      : 600;
            }}
            QComboBox:hover {{ border-color: {accent}; }}
            QComboBox:focus {{ border: 2px solid {accent}; }}
            QComboBox::drop-down {{
                border: none; width: 24px; background: transparent;
            }}
            QComboBox::down-arrow {{
                {down_css} width: 12px; height: 12px; margin-right: 8px;
            }}
        """)

        self._btn_folder.setStyleSheet(f"""
            QPushButton {{
                background-color : {btn_bg};
                color            : {btn_text};
                border           : 1px solid {border};
                border-radius    : 8px;
                padding          : 6px 14px;
                font-size        : 13px;
                font-weight      : 600;
            }}
            QPushButton:hover {{
                background-color : {btn_hov};
                border-color     : {accent};
            }}
            QPushButton:focus {{
                border : 2px solid {accent};
            }}
        """)

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color           : {row_normal};
                color                      : {text_strong};
                font-weight                : 600;
                font-size                  : 13px;
                gridline-color             : {grid_c};
                alternate-background-color : {row_alt};
                selection-background-color : {accent};
                selection-color            : #ffffff;
                border                     : 1px solid {border};
                border-radius              : 8px;
                outline                    : none;
            }}
            QTableWidget:focus {{
                border : 2px solid {accent};
            }}
            QHeaderView::section {{
                background-color : {header_bg};
                color            : #ffffff;
                font-weight      : 700;
                font-size        : 12px;
                padding          : 8px 10px;
                border           : none;
                border-right     : 1px solid rgba(255, 255, 255, 0.18);
                border-bottom    : 1px solid {border};
            }}
            QTableWidget::item {{
                padding : 7px 8px;
                color   : {text_strong};
            }}
            QTableWidget::item:selected {{
                background-color : {accent};
                color            : #ffffff;
            }}
            QScrollBar:vertical {{
                background    : {scroll_bg};
                width         : 10px;
                border-radius : 5px;
            }}
            QScrollBar::handle:vertical {{
                background    : {scroll_h};
                border-radius : 5px;
                min-height    : 24px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {accent}; }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{
                background    : {scroll_bg};
                height        : 10px;
                border-radius : 5px;
            }}
            QScrollBar::handle:horizontal {{
                background    : {scroll_h};
                border-radius : 5px;
                min-width     : 24px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {accent}; }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{ width: 0; }}
        """)

        self._lbl_empty.setStyleSheet(
            f"background:{card_bg}; color:{muted};"
            f" border:1px dashed {border}; border-radius:10px;"
            " padding:16px 20px; font-weight:600;"
        )
        attach_search_icon(self._search, size=14, theme=t)
        refresh_bound_icons(t)
        self._table.viewport().update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_filter_bar"):
            self._filter_bar.setDirection(
                QBoxLayout.Direction.TopToBottom
                if 0 < self.width() < 820
                else QBoxLayout.Direction.LeftToRight
            )

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 220)

    def _apply_column_widths(self) -> None:
        from PySide6.QtGui import QFont, QFontMetrics

        header = self._table.horizontalHeader()
        hf = QFont(header.font())
        hf.setBold(True)
        if hf.pointSize() > 0:
            hf.setPointSize(max(12, hf.pointSize()))
        hm = QFontMetrics(hf)
        dw = date_column_width()
        for idx, (default_lbl, key, width, _align) in enumerate(COLUMNS):
            item = self._table.horizontalHeaderItem(idx)
            lbl = item.text() if item is not None else default_lbl
            w = max(width, hm.horizontalAdvance(lbl) + 28)
            if key in DATE_COLUMN_KEYS:
                w = max(w, dw)
            header.resizeSection(idx, w)
        header.setSectionResizeMode(
            len(COLUMNS) - 1, QHeaderView.ResizeMode.Stretch
        )

    def retranslate(self) -> None:
        """Uppdaterar texter efter språkbyte."""
        self._lbl_title.setText(tr("history.title"))
        self._search.setPlaceholderText(tr("history.search"))
        attach_search_icon(
            self._search, size=14,
            theme=getattr(self, "_current_theme", None) or None,
        )
        self._btn_folder.setText(tr("history.open_folder"))
        self._lbl_empty.setText(tr("history.empty"))
        headers = tr_list("invoices.columns")
        self._table.setHorizontalHeaderLabels(
            headers if len(headers) == len(COLUMNS) else [c[0] for c in COLUMNS]
        )
        self._apply_column_widths()
        self.refresh()

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
