# -*- coding: utf-8 -*-
"""
Tester: leverantörsmallar för fakturatolkning.

Användaren lär tolkaren var värdena står på just den leverantörens
layout (etikett före värde) — mallen vinner över generisk heuristik
och sparas i data/invoice_templates.json.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import scan_import as si


WEIRD_LAYOUT = """\
NORDLYS ENERGI AB
Kundnr: 8811
Er ref hos oss: NL-2026-0771
Utfärdad: 2026-09-01
Betalas senast: 2026-10-01
Pris exkl moms: 900,00
Moms: 225,00
SLUTSUMMA ATT BETALA: 1 125,00 SEK
"""


def test_extract_with_label_kinds():
    text = WEIRD_LAYOUT
    assert si.extract_with_label(text, "Er ref hos oss", "token") \
        == "NL-2026-0771"
    assert si.extract_with_label(text, "SLUTSUMMA ATT BETALA", "amount") \
        == "1125.00"
    assert si.extract_with_label(text, "Utfärdad", "date") == "2026-09-01"
    assert si.extract_with_label(text, "Betalas senast", "date") \
        == "2026-10-01"
    assert si.extract_with_label(text, "Finns inte", "amount") == ""


def test_template_beats_generic_heuristics():
    templates = {
        "Nordlys Energi AB": {"fields": {
            "invoice_number": {"label": "Er ref hos oss"},
            "total_amount": {"label": "SLUTSUMMA ATT BETALA"},
            "date": {"label": "Utfärdad"},
            "due_date": {"label": "Betalas senast"},
        }},
    }
    parsed = si.parse_invoice_text(
        WEIRD_LAYOUT, suppliers=[], templates=templates
    )
    # Mallens etiketter vinner — generiskt hade beloppet kunnat bli
    # ett annat av summorna i dokumentet.
    assert parsed["total_amount"] == 1125.0
    assert parsed["invoice_number"] == "NL-2026-0771"
    assert parsed["due_date"] == "2026-10-01"
    # Leverantören känns igen via mallens namn fast registret är tomt
    assert parsed["supplier"] == "Nordlys Energi AB"
    assert parsed["template"] == "Nordlys Energi AB"
    assert parsed["missing"] == []
    assert set(parsed["template_fields"]) >= {
        "invoice_number", "total_amount", "due_date",
    }


def test_templates_roundtrip_and_corrupt(tmp_path):
    path = tmp_path / "invoice_templates.json"
    data = {"A AB": {"fields": {"total_amount": {"label": "Att betala"}}}}
    assert si.save_templates(path, data) is True
    assert si.load_templates(path) == data
    path.write_text("{trasigt", encoding="utf-8")
    assert si.load_templates(path) == {}
    assert si.find_template(data, "a ab") is not None
    assert si.find_template(data, "Annan AB") is None


def test_infer_label_from_selection_context():
    from ui.scan_import_view import _infer_label

    assert _infer_label("Fakturanr: ") == "Fakturanr"
    assert _infer_label("Er ref hos oss: ") == "Er ref hos oss"
    assert _infer_label("Rad ett\nAtt betala: ") == "Att betala"
    assert _infer_label("") == ""


def test_template_dialog_infers_and_saves(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from PySide6.QtGui import QTextCursor

    from ui.scan_import_view import TemplateDialog

    dlg = TemplateDialog(
        None, WEIRD_LAYOUT, supplier="Nordlys Energi AB", existing=None
    )
    try:
        # Markera beloppet i texten, som användaren gör med musen
        pos = WEIRD_LAYOUT.index("1 125,00")
        cursor = dlg._txt.textCursor()
        cursor.setPosition(pos)
        cursor.setPosition(pos + len("1 125,00"),
                           QTextCursor.MoveMode.KeepAnchor)
        dlg._txt.setTextCursor(cursor)
        dlg._use_selection("total_amount")
        assert dlg._label_edits["total_amount"].text() \
            == "SLUTSUMMA ATT BETALA"
        # Förhandsvisningen visar det tolkade värdet
        assert "1 125" in dlg._previews["total_amount"].text()

        dlg._label_edits["invoice_number"].setText("Er ref hos oss")
        dlg._save()
        assert dlg.result_template is not None
        assert dlg.result_template["supplier"] == "Nordlys Energi AB"
        assert dlg.result_template["fields"]["invoice_number"] \
            == {"label": "Er ref hos oss"}
    finally:
        dlg.close()


def test_scan_view_uses_templates_and_reparses(tmp_path):
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    from ui.scan_import_view import ScanImportView

    templates_file = tmp_path / "invoice_templates.json"
    si.save_templates(templates_file, {
        "Nordlys Energi AB": {"fields": {
            "total_amount": {"label": "SLUTSUMMA ATT BETALA"},
            "invoice_number": {"label": "Er ref hos oss"},
        }},
    })

    class FakeCore:
        def get_suppliers(self):
            return []

        def get_setting(self, key, default=None):
            return default

    view = ScanImportView(app=FakeCore(),
                          templates_path=templates_file)
    try:
        assert "1" in view._btn_templates.text()
        view._txt_paste.setPlainText(WEIRD_LAYOUT)
        view._scan_pasted()
        assert len(view._rows) == 1
        row = view._rows[0]
        assert row["template"] == "Nordlys Energi AB"
        assert row["total_amount"] == 1125.0
        assert row["invoice_number"] == "NL-2026-0771"
        assert view._tbl.item(0, 8).text()  # statuscellen har 🧩
        assert "🧩" in view._tbl.item(0, 8).text()
    finally:
        view.close()
