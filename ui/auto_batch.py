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
            # Max `count_threshold` fakturor per exportfil — fler
            # delas i delfiler (tidigaste förfall först) med eget
            # betalningsdatum (tidigaste förfallet) per delfil.
            ordered = sorted(
                rows,
                key=lambda r: (
                    str(r.get("due_date", "") or "9999-99-99"),
                    str(r.get("invoice_number", "") or ""),
                ),
            )
            for start in range(0, len(ordered), count_threshold):
                part = ordered[start:start + count_threshold]
                pdues = [
                    d for d in (
                        _parse_day(r.get("due_date")) for r in part
                    ) if d is not None
                ]
                pearliest = min(pdues) if pdues else None
                batches.append({
                    "supplier": supplier,
                    "invoices": part,
                    "reason": "count",
                    "earliest_due": (
                        pearliest.isoformat() if pearliest else ""
                    ),
                    "payment_date": (
                        pearliest.isoformat() if pearliest
                        else today.isoformat()
                    ),
                })
        elif earliest is not None and (earliest - today).days <= due_days:
            batches.append({
                "supplier": supplier,
                "invoices": rows,
                "reason": "due",
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

    Exporttaket (högst 10 fakturor per exportfil) gäller även
    här, vid sista steget: en batch med fler än 10 fakturor
    delas alltid i delfiler (…-del1avN.pdf, …) innan något
    skrivs, oavsett hur batchen byggdes.

    Returnerar en lista med {batch, success, file_path, error}
    — en post per batch; file_path pekar på första delfilen.
    """
    from ui.invoices_helpers import chunk_export_rows

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
            chunks = chunk_export_rows(list(batch["invoices"]))
            target_dir, filename = path_builder([batch["supplier"]])
            files: list[str] = []
            errors: list[str] = []
            ok = True
            for idx, chunk in enumerate(chunks):
                chunk_name = filename
                if len(chunks) > 1:
                    chunk_name = (
                        f"{Path(filename).stem}"
                        f"-del{idx + 1}av{len(chunks)}.pdf"
                    )
                full_path = Path(target_dir) / chunk_name
                result = exporter.export_invoice_list(
                    chunk,
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
                if result.get("attachments_missing"):
                    log.warning(
                        "AUTOBATCH %s: %s originalfiler saknas på "
                        "disk — kunde inte bifogas i PDF:en",
                        batch["supplier"],
                        result["attachments_missing"],
                    )
                files.append(
                    result.get("file_path", str(full_path))
                )
                if not result.get("success"):
                    ok = False
                    errors.extend(
                        str(e) for e in
                        (result.get("errors") or ["okänt fel"])
                    )
                    break
            results.append({
                "batch": batch,
                "success": ok,
                "file_path": (
                    files[0] if files
                    else str(Path(target_dir) / filename)
                ),
                "error": "" if ok else "; ".join(errors),
            })
            log.info(
                "AUTOBATCH %s: %d fakturor i %d fil(er), %s "
                "(betal datum %s) → %s",
                batch["supplier"], len(batch["invoices"]),
                max(len(files), 0), batch["reason"],
                batch["payment_date"],
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
