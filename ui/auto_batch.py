# -*- coding: utf-8 -*-
"""
auto_batch.py — automatisk batch-export per leverantör.

Regler (användarens arbetsflöde):
  A) En leverantör har minst 10 obetalda fakturor
     → exportera dem till betal-PDF (original bifogade) och
       sätt dem som Betald.
  B) Färre än 10, men närmaste förfallodatum är högst 5 dagar bort
     (eller redan passerat)
     → exportera + SKRIV UT (ihop med originalen) och sätt Betald.

Utan "Betald"-steget i B skulle samma lilla batch exporteras om
vid varje programstart — därför sätts båda reglerna som betalda
efter lyckad export. Betalningsdatum på exporten = tidigaste
förfallodatumet i batchen (samma princip som Slå ihop-funktionen).

Aktiveras med inställningen auto_batch (standard AV). Planeringen
(plan_batches) är en ren funktion; exporten körs i bakgrundstråd
och statusändringarna appliceras av anroparen på huvudtråden.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

try:
    from ui.i18n import tr
except Exception:  # pragma: no cover
    def tr(key: str, **_f: object) -> str:  # type: ignore[no-redef]
        return key

log = logging.getLogger("AutoBatch")

#: Trösklar enligt specifikationen.
BATCH_COUNT = 10
DUE_DAYS = 5

#: Statusar som INTE räknas som obetalda (samma som Fakturor-fliken).
NON_UNPAID_STATUSES: tuple[str, ...] = ("Betald", "Makulerad", "Arkiverad")


def _parse_day(raw: Any) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None


def plan_batches(
    invoices: list[dict],
    today: datetime.date,
    count_threshold: int = BATCH_COUNT,
    due_days: int = DUE_DAYS,
) -> list[dict]:
    """
    Grupperar obetalda fakturor per leverantör och väljer ut de
    batcher som ska exporteras enligt regel A eller B.

    Returnerar [{supplier, invoices, reason: 'count'|'due',
                 earliest_due, payment_date}, ...] sorterat på
    leverantörsnamn. Fakturor utan leverantör hoppas över.
    """
    groups: dict[str, list[dict]] = {}
    for inv in invoices or []:
        if str(inv.get("status", "")) in NON_UNPAID_STATUSES:
            continue
        supplier = str(inv.get("supplier", "")).strip()
        if not supplier:
            continue
        groups.setdefault(supplier, []).append(inv)

    batches: list[dict] = []
    for supplier in sorted(groups):
        rows = groups[supplier]
        dues = [
            d for d in (_parse_day(r.get("due_date")) for r in rows)
            if d is not None
        ]
        earliest = min(dues) if dues else None
        if len(rows) >= count_threshold:
            reason = "count"
        elif earliest is not None and (earliest - today).days <= due_days:
            reason = "due"
        else:
            continue
        batches.append({
            "supplier": supplier,
            "invoices": rows,
            "reason": reason,
            "earliest_due": earliest.isoformat() if earliest else "",
            "payment_date": (
                earliest.isoformat() if earliest
                else today.isoformat()
            ),
        })
    return batches


def export_batches(
    app: Any,
    batches: list[dict],
    path_builder: Callable | None = None,
) -> list[dict]:
    """
    Exporterar varje batch till betal-PDF med original bifogade.
    Rör INTE statusar — det gör anroparen efter lyckad export.

    Returnerar en lista med {batch, success, file_path, error}.
    """
    results: list[dict] = []
    exporter = getattr(app, "pdf_exporter", None)
    if exporter is None:
        log.warning("AUTOBATCH: pdf_exporter saknas — hoppar över")
        return results
    if path_builder is None:
        from ui.invoices_helpers import build_export_path

        path_builder = build_export_path

    for batch in batches:
        try:
            target_dir, filename = path_builder([batch["supplier"]])
            full_path = Path(target_dir) / filename
            result = exporter.export_invoice_list(
                batch["invoices"],
                filename=str(full_path),
                title=tr("auto_batch.pdf_title",
                         supplier=batch["supplier"]),
                check_duplicates=False,
                mark_exported=True,
                force_export=True,
                payment_date=batch["payment_date"],
                ask_payment_date=False,
                include_originals=True,
            )
            ok = bool(result.get("success"))
            results.append({
                "batch": batch,
                "success": ok,
                "file_path": result.get("file_path", str(full_path)),
                "error": "" if ok else str(
                    result.get("errors", ["okänt fel"])
                ),
            })
            log.info(
                "AUTOBATCH %s: %d fakturor, %s (betal datum %s) → %s",
                batch["supplier"], len(batch["invoices"]),
                batch["reason"], batch["payment_date"],
                "OK" if ok else "MISSLYCKADES",
            )
        except Exception as exc:
            log.error(
                "AUTOBATCH %s misslyckades: %s",
                batch["supplier"], exc, exc_info=True,
            )
            results.append({
                "batch": batch, "success": False,
                "file_path": "", "error": str(exc),
            })
    return results


class AutoBatchWorker(QThread):
    """Kör planering + export utanför UI-tråden."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, app: Any, parent=None) -> None:
        super().__init__(parent)
        self._app = app

    def run(self) -> None:  # noqa: D401
        try:
            try:
                invoices = list(self._app.get_invoices())
            except Exception:
                invoices = []
            batches = plan_batches(invoices, datetime.date.today())
            self.done.emit(export_batches(self._app, batches))
        except Exception as exc:
            log.warning("AUTOBATCH worker: %s", exc)
            self.failed.emit(str(exc))
