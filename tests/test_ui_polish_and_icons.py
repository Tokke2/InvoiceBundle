# -*- coding: utf-8 -*-
"""Tests for vector icons, mnemonic rendering, toolbar/tabs width, and columns."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (
    str(PROJECT_DIR),
    str(PROJECT_DIR / "ui"),
    str(PROJECT_DIR / "plugins"),
):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_strip_visual_prefix_and_clean_style_mnemonics(monkeypatch):
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QImage, QPainter, QPalette
    from PySide6.QtWidgets import QProxyStyle
    from ui.icons import (
        CleanIconProxyStyle,
        _clean_mnemonic_text,
        strip_visual_prefix,
    )

    _qapp()
    assert strip_visual_prefix("📄  Fakturor") == "Fakturor"
    assert strip_visual_prefix("💖  Donationer…") == "Donationer…"
    assert strip_visual_prefix("Vanlig text") == "Vanlig text"
    assert _clean_mnemonic_text("📄  &Spara") == "&Spara"
    assert _clean_mnemonic_text("Öppna && Spara") == "Öppna && Spara"

    style = CleanIconProxyStyle("Fusion")
    seen: list[tuple[int, str]] = []
    monkeypatch.setattr(
        QProxyStyle,
        "drawItemText",
        lambda _self, _p, _r, flags, _pal, _en, text, _role=QPalette.ColorRole.NoRole: seen.append((flags, text)),
    )

    img = QImage(160, 40, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(img)
    try:
        pal = QPalette()
        rect = QRect(0, 0, 160, 40)
        style.drawItemText(
            painter,
            rect,
            int(Qt.TextFlag.TextShowMnemonic),
            pal,
            True,
            "📄  Test && Co",
        )
        style.drawItemText(
            painter,
            rect,
            int(Qt.AlignmentFlag.AlignLeft.value),
            pal,
            True,
            "📄  Test & Co",
        )
    finally:
        painter.end()

    assert seen[0][1] == "Test && Co"
    assert seen[1][1] == "Test & Co"


def test_vector_icon_renders_normal_and_disabled_states():
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QPushButton
    from ui.icons import bind_icon, refresh_bound_icons, vector_icon
    from ui.main_window import THEMES

    _qapp()
    for theme_name in ("dark", "light"):
        t = THEMES[theme_name]
        icon = vector_icon(
            "export", size=16, color="#ffffff", disabled_color=t["text_disabled"]
        )
        assert not icon.isNull()
        norm = icon.pixmap(16, 16, QIcon.Mode.Normal)
        dis = icon.pixmap(16, 16, QIcon.Mode.Disabled)
        assert not norm.isNull() and not dis.isNull()
        assert norm.toImage() != dis.toImage()

        btn = QPushButton("Export")
        bind_icon(btn, "export", size=16, role="on_accent", theme=t)
        refresh_bound_icons(t)
        assert not btn.icon().isNull()
        assert btn.icon().pixmap(16, 16, QIcon.Mode.Normal).toImage() != (
            btn.icon().pixmap(16, 16, QIcon.Mode.Disabled).toImage()
        )


def test_mainwindow_1280_fits_toolbar_tabs_and_donate_unclipped(tmp_path):
    from PySide6.QtWidgets import QToolButton
    from ui.main_window import MainWindow

    app_qt = _qapp()

    class _Store:
        def on_change(self, _cb):
            pass

        def all(self):
            return []

    class _FakeApp:
        _data_dir = tmp_path
        settings = {
            "theme": "dark",
            "language": "sv",
            "font_size": 13,
            "db_path": str(tmp_path),
            "autostart": False,
        }
        invoices_store = _Store()
        suppliers_store = _Store()
        session_due_date = None
        session_due_date_str = ""

        def get_setting(self, k, d=None):
            return self.settings.get(k, d)

        def set_setting(self, k, v):
            self.settings[k] = v

        def get_invoices(self):
            return []

        def get_suppliers(self):
            return []

        def get_archived_invoices(self):
            return []

        def data_load_summary(self):
            return "Redo"

    mw = MainWindow(_FakeApp())
    try:
        mw.resize(1280, 800)
        mw.show()
        app_qt.processEvents()

        # No leading emoji leftovers on visible tabs
        for i in range(mw.tabs.count()):
            txt = mw.tabs.tabText(i)
            assert txt and txt[0].isalnum(), f"Unexpected tab prefix: {txt!r}"

        # All 9 tabs fit within 1280px
        bar = mw.tabs.tabBar()
        tab_total = sum(bar.tabRect(i).width() for i in range(bar.count()))
        assert tab_total <= 1280, f"Tabs overflow 1280px: {tab_total}"

        # Toolbar fits within 1280px and DonateButton isn't squished
        tb = mw._toolbar
        assert tb.sizeHint().width() <= 1280, (
            f"Toolbar sizeHint {tb.sizeHint().width()} > 1280"
        )
        don = tb.findChild(QToolButton, "DonateButton")
        assert don is not None
        assert don.isVisible()
        assert don.geometry().width() >= don.sizeHint().width()
        assert "Donationer" in don.text()

        # Switching themes updates active theme cleanly
        mw._apply_theme("light", save=False)
        assert mw.current_theme_dict()["name"] == "light"
        mw._apply_theme("dark", save=False)
        assert mw.current_theme_dict()["name"] == "dark"
    finally:
        mw.close()
        mw.deleteLater()
        app_qt.processEvents()


def test_history_and_suppliers_column_widths_avoid_eliding_standard_values():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics
    from ui.history_view import HistoryView
    from ui.suppliers_view import SuppliersView
    from ui.typography import make_tabular_font

    app_qt = _qapp()

    class _App:
        settings = {}

        def get_archived_invoices(self):
            return [
                {
                    "id": "h1",
                    "supplier": "Test AB",
                    "invoice_number": "INV-101",
                    "ocr": "101",
                    "date": "2026-09-01",
                    "due_date": "2026-10-01",
                    "payment_date": "2026-09-29",
                    "total_amount": 6420.00,
                    "currency": "SEK",
                    "status": "Betald",
                    "invoice_type": "Faktura",
                }
            ]

        def get_suppliers(self):
            return [
                {
                    "id": "s1",
                    "name": "Pilkington Floatglas AB",
                    "org_number": "556123-4567",
                    "bg": "512-3456",
                    "pg": "123456-7",
                    "iban": "SE4550000000058398257466",
                    "bic": "ESSESESS",
                    "payment_terms": 30,
                    "ocr_same_as_invoice_number": True,
                }
            ]

    hv = HistoryView(_App())
    sv = SuppliersView(_App())
    try:
        hv.resize(1240, 600)
        sv.resize(1240, 600)
        hv.show()
        sv.show()
        app_qt.processEvents()

        fm = QFontMetrics(make_tabular_font(12, True))
        # Amount column (index 7 in HistoryView) must fit "6 420,00 SEK" cleanly
        amt_w = hv._table.columnWidth(7)
        assert fm.elidedText("6 420,00 SEK", Qt.TextElideMode.ElideRight, amt_w - 18) == "6 420,00 SEK"
        # Typ column (index 0) must fit "Faktura" cleanly
        typ_w = hv._table.columnWidth(0)
        assert fm.elidedText("Faktura", Qt.TextElideMode.ElideRight, typ_w - 18) == "Faktura"

        # Org.nr (col 1), BIC (col 5), and OCR rule (col 7) in SuppliersView
        org_w = sv._table.columnWidth(1)
        ocr_w = sv._table.columnWidth(7)
        assert org_w >= sv._table.sizeHintForColumn(1)
        assert ocr_w >= sv._table.sizeHintForColumn(7)
        assert fm.elidedText("556123-4567", Qt.TextElideMode.ElideRight, org_w - 18) == "556123-4567"
        assert fm.elidedText("= fakturanr", Qt.TextElideMode.ElideRight, ocr_w - 18) == "= fakturanr"
    finally:
        hv.close()
        sv.close()
        hv.deleteLater()
        sv.deleteLater()
        app_qt.processEvents()
