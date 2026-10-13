# -*- coding: utf-8 -*-
"""
Regressionstester: leverantörsfliken, språk (sv/en) och donation.

Bakgrund: leverantörsfliken var död i produktion eftersom
suppliers_view importerade attach_visible_rows m.fl. från
invoices_helpers — funktioner som aldrig fanns där. ImportError →
MainWindow visade en tyst platshållare. De här testerna ser till
att det aldrig händer igen.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui")):
    if _d not in sys.path:
        sys.path.insert(0, _d)


def _qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _FakeSuppliersStore:
    def __init__(self, rows):
        self._rows = rows
        self.file = PROJECT_DIR / "data" / "suppliers.json"

    def on_change(self, _cb):
        pass


class FakeApp:
    """Minimal stand-in för FakturaApp (bara det vyerna använder)."""

    def __init__(self, suppliers=None):
        self._suppliers = list(suppliers or [])
        self.suppliers_store = _FakeSuppliersStore(self._suppliers)

    def get_suppliers(self):
        return list(self._suppliers)

    def add_supplier(self, data):
        row = {"id": f"id-{len(self._suppliers) + 1}", **data}
        self._suppliers.append(row)
        return row

    def update_supplier(self, record_id, data):
        for row in self._suppliers:
            if row.get("id") == record_id:
                row.update(data)
                return row
        return None

    def delete_supplier(self, record_id):
        self._suppliers = [
            r for r in self._suppliers if r.get("id") != record_id
        ]
        return True


def test_suppliers_view_imports_and_builds():
    """Importen får aldrig krascha igen (regression: attach_visible_rows)."""
    _qapp()
    from ui.suppliers_view import SuppliersView

    view = SuppliersView(FakeApp([{"id": "1", "name": "Test AB"}]))
    assert view._table.rowCount() == 1
    assert view._table.item(0, 0).text() == "Test AB"
    assert view._empty_label.isHidden()


def test_suppliers_view_empty_state_and_search():
    _qapp()
    from ui.suppliers_view import SuppliersView

    view = SuppliersView(FakeApp())
    assert view._table.rowCount() == 0
    # Tom-läget ska förklara sig (inte en död vit tabell)
    assert not view._empty_label.isHidden()
    view._app.add_supplier({"name": "Sök Mig AB"})
    view.refresh()
    assert view._table.rowCount() == 1
    assert view._empty_label.isHidden()
    view._search.setText("finns-inte")
    view._do_refresh()
    assert view._table.rowCount() == 0
    assert not view._empty_label.isHidden()


def test_row_delegate_helpers_exist():
    _qapp()
    from PySide6.QtWidgets import QTableWidget

    from ui.invoices_helpers import (
        ROLE_ROW_BG,
        attach_visible_rows,
        ensure_row_height,
        fg_on_row,
        is_dark_theme,
    )

    table = QTableWidget(2, 1)
    delegate = attach_visible_rows(table)
    assert delegate is not None
    delegate.set_theme(dark=True, select_bg="#0b5cab")
    ensure_row_height(table, 40)
    assert table.rowHeight(0) >= 40
    assert isinstance(ROLE_ROW_BG, int)
    # Accentfärg med för låg kontrast byts mot fallback
    assert fg_on_row("#ffffff", "#eeeeee", "#111111", False) == "#111111"
    assert fg_on_row("#000000", "#58a6ff", "#ffffff", True) == "#58a6ff"
    # Mörk/ljus-detektion: temanamn vinner, annars luminans
    assert is_dark_theme({"name": "light", "bg": "#0c1218"}) is False
    assert is_dark_theme({"bg": "#f4f1ea"}) is False   # nuvarande ljustema!
    assert is_dark_theme({"bg": "#0c1218"}) is True


def test_i18n_swedish_and_english():
    from ui import i18n

    i18n.set_language("sv")
    assert i18n.tr("tab.suppliers") == "🏢  Leverantörer"
    assert i18n.tr("suppliers.count", n=3) == "Leverantörer: 3"
    i18n.set_language("en")
    assert i18n.tr("tab.suppliers") == "🏢  Suppliers"
    assert i18n.tr("suppliers.count", n=3) == "Suppliers: 3"
    assert i18n.tr_list("supplier.columns")[0] == "Name"
    # Okänd nyckel faller tillbaka synligt men kraschar inte
    assert i18n.tr("saknas.helt") == "saknas.helt"
    i18n.set_language("sv")
    assert i18n.normalize_language("en-US") == "en"
    assert i18n.normalize_language("s") == "sv"


def test_language_setting_is_validated():
    import app as appmod

    assert appmod.DEFAULT_SETTINGS["language"] == "sv"
    clean, repairs = appmod.validate_settings({"language": "klingon"})
    assert clean["language"] == "sv"
    assert repairs
    clean, _ = appmod.validate_settings({"language": "en"})
    assert clean["language"] == "en"


def test_donate_dialog_both_languages():
    _qapp()
    from ui import i18n
    from ui.donate import (
        DONATE_KOFI_URL,
        DONATE_PAYPAL_URL,
        DonateDialog,
        open_donate_dialog,
    )

    assert DONATE_PAYPAL_URL == "https://paypal.me/Rickard3dPrint"
    assert DONATE_KOFI_URL == "https://ko-fi.com/tokke2"
    for lang, needle in (("sv", "Stöd"), ("en", "Support")):
        i18n.set_language(lang)
        dlg = DonateDialog()
        assert needle in dlg.windowTitle()
        dlg.close()
    i18n.set_language("sv")
    # open_donate_dialog kör exec() — testas bara att Qt-vägen finns
    assert callable(open_donate_dialog)


def test_suppliers_view_retranslate():
    _qapp()
    from ui import i18n
    from ui.suppliers_view import SuppliersView

    i18n.set_language("sv")
    view = SuppliersView(FakeApp([{"id": "1", "name": "Test AB"}]))
    i18n.set_language("en")
    view.retranslate()
    assert view._hdr_label.text() == "🏢  Suppliers"
    assert view._table.horizontalHeaderItem(0).text() == "Name"
    i18n.set_language("sv")
    view.retranslate()
    assert view._hdr_label.text() == "🏢  Leverantörer"
