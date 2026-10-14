# -*- coding: utf-8 -*-
"""
Tester: automatisk batch-export per leverantör.

Regel A: minst 10 obetalda fakturor hos en leverantör
         → exportera (original bifogade) och sätt Betald.
Regel B: färre än 10 men närmaste förfall inom 5 dagar
         (eller redan förfallet) → exportera + skriv ut + Betald.
Betalda/arkiverade/makulerade räknas aldrig med, och batchen
får tidigaste förfallodatumet som betalningsdatum.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
for _d in (str(PROJECT_DIR), str(PROJECT_DIR / "ui"),
           str(PROJECT_DIR / "plugins")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from ui.auto_batch import export_batches, plan_batches

TODAY = datetime.date(2026, 9, 10)


def _inv(i, supplier="Pilkington", due="2026-10-01",
         status="Obetald", amount=100.0):
    return {"id": f"{supplier}-{i}", "supplier": supplier,
            "invoice_number": f"F-{i}", "total_amount": amount,
            "due_date": due, "status": status}


def test_count_rule_needs_ten_unpaid():
    rows = [_inv(i) for i in range(9)]
    assert plan_batches(rows, TODAY) == []
    rows.append(_inv(9))
    rows.append(_inv(99, status="Betald"))      # räknas inte
    rows.append(_inv(98, status="Arkiverad"))   # räknas inte
    batches = plan_batches(rows, TODAY)
    assert len(batches) == 1
    batch = batches[0]
    assert batch["reason"] == "count"
    assert len(batch["invoices"]) == 10
    assert batch["payment_date"] == "2026-10-01"


def test_due_rule_five_day_window():
    # Förfaller om exakt 5 dagar → med
    rows = [_inv(i, due="2026-09-15") for i in range(3)]
    batches = plan_batches(rows, TODAY)
    assert len(batches) == 1 and batches[0]["reason"] == "due"
    # 6 dagar → inte än
    rows = [_inv(i, due="2026-09-16") for i in range(3)]
    assert plan_batches(rows, TODAY) == []
    # Redan förfallet (förfallodatum igår) → med direkt
    rows = [_inv(i, due="2026-09-09") for i in range(2)]
    assert plan_batches(rows, TODAY)[0]["reason"] == "due"
    # Inga datum alls → ingen förfallo-batch
    rows = [_inv(i, due="") for i in range(4)]
    assert plan_batches(rows, TODAY) == []


def test_batches_per_supplier_sorted_and_earliest_date():
    rows = (
        [_inv(i, "Pilkington", due="2026-09-20") for i in range(10)]
        + [_inv(i, "Direktglas", due="2026-09-12") for i in range(2)]
        + [_inv(7, "Direktglas", due="2026-09-25")]
        + [_inv(0, "", due="2026-09-11")]        # utan leverantör: hoppas
    )
    batches = plan_batches(rows, TODAY)
    assert [b["supplier"] for b in batches] == [
        "Direktglas", "Pilkington",
    ]
    direkt = batches[0]
    assert direkt["reason"] == "due"
    assert direkt["payment_date"] == "2026-09-12"   # tidigaste i batchen
    assert len(direkt["invoices"]) == 3             # alla obetalda följer med


class _FakeExporter:
    def __init__(self, ok=True):
        self.calls = []
        self._ok = ok

    def export_invoice_list(self, invoices, filename="", **kw):
        self.calls.append((invoices, filename, kw))
        if not self._ok:
            return {"success": False, "errors": ["boom"]}
        return {"success": True, "file_path": filename}


class _FakeApp:
    def __init__(self, invoices, ok=True):
        self._invoices = invoices
        self.pdf_exporter = _FakeExporter(ok)

    def get_invoices(self):
        return list(self._invoices)


def test_export_batches_uses_originals_and_earliest_payment_date(tmp_path):
    rows = [_inv(i, due="2026-09-20") for i in range(10)]
    rows[3]["due_date"] = "2026-09-14"
    app = _FakeApp(rows)
    batches = plan_batches(rows, TODAY)
    results = export_batches(
        app, batches,
        path_builder=lambda sups: (tmp_path, "betal.pdf"),
    )
    assert len(results) == 1 and results[0]["success"]
    _invs, _fname, kw = app.pdf_exporter.calls[0]
    assert kw["include_originals"] is True
    assert kw["payment_date"] == "2026-09-14"
    assert kw["ask_payment_date"] is False

    miss = export_batches(
        _FakeApp(rows, ok=False), batches,
        path_builder=lambda sups: (tmp_path, "x.pdf"),
    )
    assert miss[0]["success"] is False
    assert export_batches(_FakeApp([], ok=True), []) == []
