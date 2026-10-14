# -*- coding: utf-8 -*-
"""
DashboardView — startsidan med nyckeltal (ersätter platshållaren).

Fyra kort (Att betala / Förfallet / Förfaller inom 7 dagar /
Leverantörer) + listan "Förfaller snart" med de obetalda fakturor
som ligger närmast i tiden. Samma statusregler som Fakturor-fliken
(Betald/Makulerad/Arkiverad räknas inte som obetalt) och samma
beloppsformat, så siffrorna alltid stämmer mellan flikarna.

Designen använder ui/design.py (marinblått + guld, som appikonen).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from ui.i18n import tr
except Exception:  # pragma: no cover
    try:
        from i18n import tr  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_f: object) -> str:  # type: ignore[no-redef]
            return key

try:
    from ui.design import GOLD, NAVY, app_icon_pixmap, header_font
except Exception:  # pragma: no cover
    GOLD = "#d4a017"  # type: ignore[no-redef]
    NAVY = "#12284b"  # type: ignore[no-redef]

    def app_icon_pixmap(size: int = 28):  # type: ignore[no-redef]
        from PySide6.QtGui import QPixmap
        return QPixmap()

    def header_font():  # type: ignore[no-redef]
        from PySide6.QtGui import QFont
        return QFont("Segoe UI", 17, QFont.Weight.Bold)

try:
    from ui.invoices_helpers import fmt_amount
except Exception:  # pragma: no cover
    try:
        from invoices_helpers import fmt_amount  # type: ignore[no-redef]
    except Exception:
        def fmt_amount(value: float, currency: str = "SEK") -> str:  # type: ignore[no-redef]
            return f"{value:,.2f} {currency}"

log = logging.getLogger("DashboardView")

#: Samma regler som i Fakturor-fliken.
NON_UNPAID_STATUSES: tuple[str, ...] = ("Betald", "Makulerad", "Arkiverad")


def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _parse_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def summarize(invoices: list[dict], today: date) -> dict[str, Any]:
    """Nyckeltal + kommande förfall (ren funktion — testbar)."""
    unpaid = [
        inv for inv in invoices
        if str(inv.get("status", "")) not in NON_UNPAID_STATUSES
    ]
    to_pay = sum(_to_float(inv.get("total_amount")) for inv in unpaid)

    overdue: list[dict] = []
    upcoming: list[dict] = []
    week = today + timedelta(days=7)
    for inv in unpaid:
        due = _parse_day(inv.get("due_date"))
        if due is None:
            continue
        entry = {**inv, "_due": due}
        if str(inv.get("status", "")) == "Förfallen" or due < today:
            overdue.append(entry)
        elif due <= week:
            upcoming.append(entry)
    upcoming.sort(key=lambda e: e["_due"])
    overdue.sort(key=lambda e: e["_due"])
    return {
        "to_pay": to_pay,
        "unpaid_count": len(unpaid),
        "overdue": overdue,
        "overdue_sum": sum(
            _to_float(i.get("total_amount")) for i in overdue
        ),
        "upcoming": upcoming,
        "upcoming_7d_sum": sum(
            _to_float(i.get("total_amount")) for i in upcoming
        ),
    }


class _StatCard(QWidget):
    """Ett nyckeltalskort med stor summa och liten förklaring."""

    def __init__(self, accent: str) -> None:
        super().__init__()
        self.setStyleSheet(
            f"background:{NAVY}; border:1px solid {accent};"
            " border-radius:10px;"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(2)
        self._title = QLabel()
        self._title.setStyleSheet(
            "color:#c9d4e6; background:transparent; font-size:12px;"
            " font-weight:700;"
        )
        self._value = QLabel("–")
        self._value.setStyleSheet(
            f"color:{GOLD}; background:transparent; font-size:22px;"
            " font-weight:800;"
        )
        self._sub = QLabel()
        self._sub.setStyleSheet(
            "color:#8ea4ba; background:transparent; font-size:11px;"
        )
        lay.addWidget(self._title)
        lay.addWidget(self._value)
        lay.addWidget(self._sub)

    def set(self, title: str, value: str, sub: str) -> None:
        self._title.setText(title)
        self._value.setText(value)
        self._sub.setText(sub)


class DashboardView(QWidget):
    """Startflik: nyckeltal + förfaller snart."""

    def __init__(self, app: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._build_ui()
        self.refresh()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        self._lbl_title = QLabel()
        self._lbl_title.setFont(header_font())
        head = QHBoxLayout()
        pix = app_icon_pixmap(28)
        if not pix.isNull():
            mark = QLabel()
            mark.setPixmap(pix)
            mark.setStyleSheet("background:transparent;")
            head.addWidget(mark)
        head.addWidget(self._lbl_title)
        head.addStretch()
        self._btn_open_invoices = QPushButton()
        self._btn_open_invoices.clicked.connect(self._goto_invoices)
        head.addWidget(self._btn_open_invoices)
        root.addLayout(head)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self._card_pay = _StatCard(GOLD)
        self._card_overdue = _StatCard("#e5534b")
        self._card_week = _StatCard("#58a6ff")
        self._card_suppliers = _StatCard("#3fb950")
        for card in (self._card_pay, self._card_overdue,
                     self._card_week, self._card_suppliers):
            cards.addWidget(card, stretch=1)
        root.addLayout(cards)

        self._lbl_upcoming = QLabel()
        self._lbl_upcoming.setFont(header_font())
        root.addWidget(self._lbl_upcoming)

        self._table = QTableWidget(0, 4)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 110)
        self._table.setColumnWidth(2, 120)
        self._table.setColumnWidth(3, 130)
        self._table.doubleClicked.connect(
            lambda _i: self._goto_invoices()
        )
        root.addWidget(self._table, stretch=1)

        self._lbl_hint = QLabel()
        self._lbl_hint.setStyleSheet(
            "color:#8b949e;background:transparent;"
        )
        root.addWidget(self._lbl_hint)
        self.retranslate()

    # ── Data ──────────────────────────────────────────────────────────

    def _invoices(self) -> list[dict]:
        try:
            return list(self._app.get_invoices())
        except Exception:
            return []

    def _suppliers(self) -> list[dict]:
        try:
            return list(self._app.get_suppliers())
        except Exception:
            return []

    def refresh(self) -> None:
        """Räknar om nyckeltalen (anropas av huvudfönstret)."""
        invoices = self._invoices()
        stats = summarize(invoices, date.today())
        suffix = tr("dashboard.currency")
        self._card_pay.set(
            tr("dashboard.to_pay"),
            fmt_amount(stats["to_pay"], suffix),
            tr("dashboard.to_pay_sub", n=stats["unpaid_count"]),
        )
        self._card_overdue.set(
            tr("dashboard.overdue"),
            fmt_amount(stats["overdue_sum"], suffix),
            tr("dashboard.overdue_sub", n=len(stats["overdue"])),
        )
        self._card_week.set(
            tr("dashboard.due_week"),
            fmt_amount(stats["upcoming_7d_sum"], suffix),
            tr("dashboard.due_week_sub", n=len(stats["upcoming"])),
        )
        self._card_suppliers.set(
            tr("dashboard.suppliers"),
            str(len(self._suppliers())),
            tr("dashboard.suppliers_sub", n=len(invoices)),
        )

        rows = (stats["overdue"] + stats["upcoming"])[:12]
        self._table.setRowCount(len(rows))
        for r, inv in enumerate(rows):
            values = [
                str(inv.get("due_date", ""))[:10],
                str(inv.get("supplier", "")),
                str(inv.get("invoice_number", "")),
                fmt_amount(_to_float(inv.get("total_amount")), suffix),
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                if c == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(r, c, item)
        self._lbl_hint.setText(
            tr("dashboard.hint") if rows else tr("dashboard.all_clear")
        )

    def _goto_invoices(self) -> None:
        """Hoppar till Fakturor-fliken via huvudfönstrets API."""
        widget: QWidget | None = self
        while widget is not None:
            goto = getattr(widget, "_goto_tab", None)
            if callable(goto):
                try:
                    from ui.i18n import tr as _tr
                    goto("invoices", _tr("tab.invoices"))
                except Exception as exc:
                    log.debug("DashboardView._goto_invoices: %s", exc)
                return
            widget = widget.parentWidget()

    # ── Tema / språk ──────────────────────────────────────────────────

    def apply_theme(self, theme: dict | None = None) -> None:
        self.refresh()

    def retranslate(self) -> None:
        self._lbl_title.setText(tr("dashboard.title"))
        self._lbl_upcoming.setText(tr("dashboard.upcoming"))
        self._btn_open_invoices.setText(tr("dashboard.open_invoices"))
        self._table.setHorizontalHeaderLabels([
            tr("dashboard.col_due"), tr("dashboard.col_supplier"),
            tr("dashboard.col_invoice"), tr("dashboard.col_amount"),
        ])
        self.refresh()
