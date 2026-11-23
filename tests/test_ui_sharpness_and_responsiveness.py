# -*- coding: utf-8 -*-
"""Verifierar HiDPI-skärpa, rena vektorikoner, responsiva vyer och dialoger."""
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


def test_hidpi_vector_icons_logos_qr_and_qss_indicators():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from ui.design import app_icon_pixmap, logotype_pixmap
    from ui.donate import make_qr_pixmap
    from ui.icons import (
        icon_pixmap,
        qss_indicator_urls,
        strip_visual_prefix,
        vector_icon,
    )

    _qapp()

    # Enclosed alphanumeric prefix (t.ex. 🅿️  PayPal) rensas rent utan tofu
    assert strip_visual_prefix("🅿️  PayPal") == "PayPal"

    # Skarp skalning vid 1.0x / 1.5x / 2.0x DPR
    for dpr in (1.0, 1.5, 2.0):
        pm_ico = icon_pixmap("invoices", "#ffffff", 18, dpr=dpr)
        assert pm_ico.devicePixelRatio() == dpr
        assert pm_ico.width() == int(round(18 * dpr))

        pm_app = app_icon_pixmap(28, dpr=dpr)
        assert not pm_app.isNull()
        assert pm_app.devicePixelRatio() == dpr
        assert pm_app.width() == int(round(28 * dpr))

        pm_logo = logotype_pixmap(440, dark_background=True, dpr=dpr)
        assert not pm_logo.isNull()
        assert pm_logo.devicePixelRatio() == dpr
        assert pm_logo.width() == int(round(440 * dpr))

        pm_qr = make_qr_pixmap("C0721817177;;Stöd;6", size=132, dpr=dpr)
        assert pm_qr is not None
        assert pm_qr.devicePixelRatio() == dpr
        assert pm_qr.width() >= int(round(100 * dpr))

    # _VectorIconEngine levererar skilda lägen (Normal vs Disabled) + alla nya ikoner
    for name in ("chevron_left", "chevron_right", "external"):
        ico = vector_icon(name, color="#ffffff", size=16)
        pm_norm = ico.pixmap(QSize(16, 16), QIcon.Mode.Normal)
        pm_dis = ico.pixmap(QSize(16, 16), QIcon.Mode.Disabled)
        assert not pm_norm.isNull()
        assert pm_norm.toImage() != pm_dis.toImage()

    urls = qss_indicator_urls("#ffffff")
    for key in ("chevron_up", "chevron_down", "chevron_right", "check"):
        assert key in urls and Path(urls[key]).is_file()


def test_mainwindow_responsive_toolbar_settings_and_about_dialog(
    monkeypatch, tmp_path,
):
    from PySide6.QtWidgets import QBoxLayout, QDialog, QMessageBox, QToolButton
    from ui.main_window import MainWindow

    app_qt = _qapp()

    class _Store:
        def __init__(self):
            self._file = tmp_path / "store.json"

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
            "update_auto_check": False,
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
        # 1024x700: kompakt verktygsfält utan overflow och med synlig Donationer-knapp
        mw.resize(1024, 700)
        mw.show()
        app_qt.processEvents()
        tb = mw._toolbar
        assert tb.sizeHint().width() <= 1024
        don = tb.findChild(QToolButton, "DonateButton")
        assert don is not None and don.isVisible()
        assert don.width() >= don.sizeHint().width()
        assert not mw._status_info_lbl.isVisible()

        # 1280x800: fulla etiketter, 2-kolumns Inställningar + synlig statusinfo
        mw.resize(1280, 800)
        app_qt.processEvents()
        assert mw._status_info_lbl.isVisible()
        assert mw._settings_top_row.direction() == QBoxLayout.Direction.LeftToRight
        mw.resize(780, 700)
        app_qt.processEvents()
        assert mw._settings_top_row.direction() == QBoxLayout.Direction.TopToBottom

        # _show_about() får INTE falla tillbaka till QMessageBox.about
        monkeypatch.setattr(
            QMessageBox,
            "about",
            lambda *_a, **_kw: (_ for _ in ()).throw(
                AssertionError("Skulle inte falla tillbaka till QMessageBox.about")
            ),
        )
        seen_titles: list[str] = []

        def _fake_exec(dlg_self):
            seen_titles.append(dlg_self.windowTitle())
            return 0

        monkeypatch.setattr(QDialog, "exec", _fake_exec)
        mw._show_about()
        assert seen_titles
    finally:
        mw.close()
        mw.deleteLater()
        app_qt.processEvents()


def test_dialogs_no_tofu_unclipped_buttons_and_fit_screen(tmp_path):
    from PySide6.QtGui import QFontMetrics
    from ui.donate import DonateDialog
    from ui.invoices_helpers import (
        ExportHistoryDialog,
        ExportHistoryManager,
        InvoiceDialog,
    )
    from ui.main_window import resolve_theme
    from ui.suppliers_view import SupplierDialog

    app_qt = _qapp()

    d_inv = InvoiceDialog(
        None,
        supplier_names=["Test AB"],
        supplier_name="Test AB",
    )
    try:
        assert d_inv.f_sign.itemText(0) == "+"
        assert "\uff0b" not in d_inv.f_sign.itemText(0)
    finally:
        d_inv.close()

    hist_mgr = ExportHistoryManager(tmp_path)
    hist_mgr._data = [
        {
            "timestamp": "2026-10-12 18:10",
            "payment_date": "2026-10-15",
            "invoice_count": 3,
            "credit_count": 1,
            "total_invoices": 12450.0,
            "total_credits": -1200.0,
            "att_betala": 11250.0,
            "suppliers": ["Test AB"],
            "file": "exports/2026-10-12/test.pdf",
            "invoice_ids": [],
        }
    ]
    d_eh = ExportHistoryDialog(None, hist_mgr, resolve_theme("dark"))
    try:
        d_eh.show()
        app_qt.processEvents()
        # Skärmanpassad bredd utan hårdkodat 1060px minimum
        assert d_eh.minimumWidth() < 1060
        assert d_eh._btn_restore.width() >= d_eh._btn_restore.sizeHint().width()
        fm = QFontMetrics(d_eh._table.horizontalHeader().font())
        for col in (0, 1, 2, 3):
            hdr_txt = d_eh._table.horizontalHeaderItem(col).text()
            assert d_eh._table.columnWidth(col) >= fm.horizontalAdvance(hdr_txt) + 20
    finally:
        d_eh.close()

    d_sup = SupplierDialog(None)
    try:
        assert d_sup.minimumWidth() < 580
    finally:
        d_sup.close()

    d_don = DonateDialog(None)
    try:
        pm = d_don._lbl_swish_qr.pixmap()
        assert pm is not None and not pm.isNull()
    finally:
        d_don.close()


def test_views_responsive_layouts_and_log_splitter(tmp_path):
    from PySide6.QtWidgets import QBoxLayout, QSplitter
    from ui.dashboard_view import DashboardView
    from ui.history_view import HistoryView
    from ui.log_view import LogView
    from ui.scan_import_view import ScanImportView
    from ui.suppliers_view import SuppliersView

    app_qt = _qapp()

    class _App:
        _data_dir = tmp_path
        settings = {}

        def get_invoices(self):
            return []

        def get_suppliers(self):
            return []

        def get_archived_invoices(self):
            return []

    core = _App()
    dv = DashboardView(core)
    hv = HistoryView(core)
    sv = SuppliersView(core)
    lv = LogView(core, log_file=tmp_path / "app.log")
    siv = ScanImportView(core, templates_path=tmp_path / "templates.json")
    try:
        # Dashboard 4x1 >= 920 px, 2x2 < 920 px
        dv.show()
        dv.resize(1200, 700)
        app_qt.processEvents()
        assert dv._cards_cols == 4
        dv.resize(800, 700)
        app_qt.processEvents()
        assert dv._cards_cols == 2

        # History filterbar staplas < 820 px
        hv.show()
        hv.resize(1100, 600)
        app_qt.processEvents()
        assert hv._filter_bar.direction() == QBoxLayout.Direction.LeftToRight
        hv.resize(760, 600)
        app_qt.processEvents()
        assert hv._filter_bar.direction() == QBoxLayout.Direction.TopToBottom

        # SuppliersView sökruta håller generös bredd oberoende av knappraden
        sv.resize(1024, 650)
        sv.show()
        app_qt.processEvents()
        assert sv._search.width() >= 700

        # LogView har vertikal QSplitter
        assert isinstance(lv._splitter, QSplitter)

        # ScanImportView: 2-kolumns topp >= 960 px, staplad < 960 px
        siv.show()
        siv.resize(1200, 750)
        app_qt.processEvents()
        assert siv._top_cards_layout.direction() == QBoxLayout.Direction.LeftToRight
        siv.resize(860, 750)
        app_qt.processEvents()
        assert siv._top_cards_layout.direction() == QBoxLayout.Direction.TopToBottom
        assert not siv._lbl_watch_parked.isVisible()
    finally:
        for w in (dv, hv, sv, lv, siv):
            w.close()
            w.deleteLater()
        app_qt.processEvents()
