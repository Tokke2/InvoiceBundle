from __future__ import annotations

"""
FakturaRäknaren — PDF Export Plugin
=========================================
Fil    : FakturaRäknaren_/plugins/pdf_export.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Kort huvudfil som importerar allt från:
    FakturaRäknaren_/plugins/pdf_export_helpers.py

Plugin hooks
------------
    register(app)            – phase 1: attach exporter + guard till app,
                               kopplar pdf_rounding + tema från settings
    register_ui(main_window) – phase 2: koppla theme_changed + UI-hooks

Samarbetar med
--------------
    • pdf_export_helpers.py – all logik, klasser, konstanter
    • app.py                – CRUD-API, settings, plugin-loader,
                              session_due_date, session_due_date_str
    • invoices_view.py      – anropar export_invoice_list
    • invoices_helpers.py   – delar formatering + round_by_mode
    • main_window.py        – theme_changed signal (4 teman)
    • advanced_logger.py    – loggning

Session-betalningsdatum
-----------------------
    • Läses från app.session_due_date vid export.
    • Skickas som session_due_date= till export_invoice_list().
    • Läses EN gång per session (sätts av main.py).
    • Sparas ALDRIG i JSON.

Avrundning (pdf_rounding)
-------------------------
    • settings-nyckeln "pdf_rounding" (exact/hel/50/100) läses vid
      register() och uppdateras live via settings.on_change().
    • Styr VISAT ATT BETALA i PDF (exakt värde sparas i result).

Teman
-----
    • dark / light / system / auto — auto löses till dark/light per
      klockslag (07–20 = ljust), system via darkdetect-fallback.

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
from pathlib import Path
from typing import Any, Callable

try:
    from plugins.pdf_export_helpers import (
        PDFExporter,
        InvoiceNumberGuard,
        PDF_ROUNDING_MODES,
        fmt_amount,
        to_ascii,
        get_platform,
        now_iso,
        round_by_mode,
        COPYRIGHT_YEAR,
    )
except ImportError:
    from pdf_export_helpers import (  # type: ignore[no-redef]
        PDFExporter,
        InvoiceNumberGuard,
        PDF_ROUNDING_MODES,
        fmt_amount,
        to_ascii,
        get_platform,
        now_iso,
        round_by_mode,
        COPYRIGHT_YEAR,
    )

log = logging.getLogger("FakturaPDF")

#: Projektroten (FakturaRäknaren_/) — för relativa settings-sökvägar.
BASE_DIR: Path = Path(__file__).parent.parent.resolve()


# ═════════════════════════════════════════════════════════════════════
#  HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _resolve_path(p: str | Path) -> Path:
    """Absolut sökväg — relativa sökvägar löses mot projektroten."""
    path = Path(p)
    return path if path.is_absolute() else BASE_DIR / path


def confine_export_dir(p: str | Path) -> Path:
    """
    Exportmapp får bara vara <appmappen>/exports eller en undermapp.
    Allt annat flyttas till exports/ och loggas.
    """
    root = BASE_DIR / "exports"
    root.mkdir(parents=True, exist_ok=True)
    path = _resolve_path(p)
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        resolved.relative_to(BASE_DIR.resolve())
        return resolved
    except (OSError, ValueError):
        log.warning("EXPORT_UTANFÖR: %s → %s", p, root.resolve())
        return root.resolve()


def get_session_due_date(app: Any) -> str:
    """
    Läser session-betalningsdatum från app.session_due_date.

    Returnerar YYYY-MM-DD om satt, annars "".
    Hanterar säkert: app=None, attribut saknas, None-värden.
    """
    if app is None:
        return ""

    # Föredra session_due_date_str (property från app.py)
    str_val = getattr(app, "session_due_date_str", None)
    if str_val and isinstance(str_val, str) and str_val.strip():
        return str_val.strip()

    # Fallback: läs datetime.date direkt
    date_val = getattr(app, "session_due_date", None)
    if date_val is not None:
        try:
            if isinstance(date_val, datetime.date):
                return date_val.isoformat()
            if isinstance(date_val, str) and date_val.strip():
                return date_val.strip()
        except Exception:
            pass

    return ""


# ═════════════════════════════════════════════════════════════════════
#  CONVENIENCE FUNCTION
# ═════════════════════════════════════════════════════════════════════


def quick_export(
    invoices: list[dict],
    data_dir: str | Path = "ui/data",
    export_dir: str | Path = "exports",
    title: str = "Fakturalista",
    company: str = "",
    currency: str = "SEK",
    theme: str = "dark",
    suppliers_list: list[dict] | None = None,
    session_due_date: str = "",
    rounding_mode: str = "exact",
    payment_date: str = "",
    ask_payment_date: bool = True,
) -> dict[str, Any]:
    """
    One-call export med valfri leverantörslista, session-datum och
    avrundning.

    Exempel
    -------
    from plugins.pdf_export import quick_export
    result = quick_export(
        app.get_invoices(),
        title="Januari 2026",
        suppliers_list=app.get_suppliers(),
        session_due_date=app.session_due_date_str,
        rounding_mode=app.get_setting("pdf_rounding", "exact"),
    )
    """
    exporter = PDFExporter(
        export_dir=confine_export_dir(export_dir),
        data_dir=_resolve_path(data_dir),
        company=company,
        currency=currency,
        theme=theme,
        rounding_mode=rounding_mode,
    )
    return exporter.export_invoice_list(
        invoices,
        title=title,
        suppliers_list=suppliers_list,
        session_due_date=session_due_date,
        payment_date=payment_date,
        ask_payment_date=ask_payment_date,
    )


# ═════════════════════════════════════════════════════════════════════
#  PLUGIN HOOKS
# ═════════════════════════════════════════════════════════════════════


def register(app: Any) -> None:
    """
    Phase-1 plugin hook — anropas av app.py PluginLoader.

    Sätter på app
    -------------
    app.pdf_exporter            PDFExporter-instans
    app.invoice_guard           InvoiceNumberGuard-instans
    app.export_pdf(...)         → export_invoice_list (auto session-datum)
    app.export_summary_pdf(..)  → export_summary
    app.export_single_pdf(..)   → export_single
    app.export_batch_pdf(..)    → export_payment_batch
    """
    try:
        data_dir = _resolve_path(app.settings.get("db_path", "ui/data"))
        export_dir = confine_export_dir(
            app.settings.get("export_path", "exports")
        )
        company = app.settings.get("company_name", "")
        org_nr = app.settings.get("org_number", "")
        currency = app.settings.get("currency", "SEK")
        theme = app.settings.get("theme", "dark")
        rounding = app.settings.get("pdf_rounding", "exact")
    except Exception as exc:
        log.warning("[pdf_export] register: settings fallback (%s)", exc)
        data_dir = BASE_DIR / "ui" / "data"
        export_dir = BASE_DIR / "exports"
        company = ""
        org_nr = ""
        currency = "SEK"
        theme = "dark"
        rounding = "exact"

    # Supplier-lookup callback → live-data från app
    get_sup_fn: Callable[[], list[dict]] | None = None
    if hasattr(app, "get_suppliers"):
        get_sup_fn = app.get_suppliers

    pdf = PDFExporter(
        export_dir=export_dir,
        data_dir=data_dir,
        company=company,
        org_number=org_nr,
        currency=currency,
        theme=theme,
        get_suppliers_fn=get_sup_fn,
        rounding_mode=rounding,
    )

    app.pdf_exporter = pdf
    app.invoice_guard = pdf.guard

    # ── Live-uppdatera avrundning + tema vid settings-ändring ─────────
    if hasattr(app, "settings") and hasattr(app.settings, "on_change"):
        def _on_settings_changed(snap: dict) -> None:
            pdf.set_rounding_mode(snap.get("pdf_rounding", "exact"))
            pdf.set_theme(snap.get("theme", "dark"))
        app.settings.on_change(_on_settings_changed)
        log.debug("[pdf_export] settings-watcher kopplad")

    # ── export_pdf: wrapper som automatiskt läser session_due_date ────
    def _export_pdf_with_session_date(
        invoices: list[dict],
        title: str = "Fakturalista",
        suppliers_list: list[dict] | None = None,
        session_due_date: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Wrapper runt export_invoice_list() som automatiskt läser
        app.session_due_date_str om datumet inte skickas explicit.

        Prioritet:
        1. session_due_date (explicit argument)
        2. app.session_due_date_str (satt av main.py EN gång per session)
        3. "" (PDF visar inte datum)
        """
        if not session_due_date:
            session_due_date = get_session_due_date(app)
        if session_due_date:
            log.debug(
                "[pdf_export] export_pdf: session_due_date=%s",
                session_due_date,
            )
        return pdf.export_invoice_list(
            invoices,
            title=title,
            suppliers_list=suppliers_list,
            session_due_date=session_due_date,
            **kwargs,
        )

    app.export_pdf = _export_pdf_with_session_date
    app.export_summary_pdf = pdf.export_summary
    app.export_single_pdf = pdf.export_single
    app.export_batch_pdf = pdf.export_payment_batch

    log.info(
        "[pdf_export] registered on app (theme=%s, rounding=%s, "
        "session_due=%s)",
        theme,
        pdf._rounding,
        get_session_due_date(app) or "ej satt",
    )


def register_ui(main_window: Any) -> None:
    """
    Phase-2 plugin hook — anropas efter att UI är byggt.

    • Kopplar theme_changed så PDF följer aktiva temat (4 teman).
    • Kopplar supplier-lookup callback.
    • Lägger till export-action i InvoicesView om den finns.
    • Loggar session-betalningsdatum vid UI-registrering.
    """
    try:
        app = getattr(main_window, "_app", None)
        if app is None:
            log.warning("[pdf_export] register_ui: main_window._app saknas")
            return

        exporter = getattr(app, "pdf_exporter", None)
        if exporter is None:
            log.warning("[pdf_export] register_ui: app.pdf_exporter saknas")
            return

        # ── Logga session-betalningsdatum vid UI-registrering ──────────
        session_due = get_session_due_date(app)
        if session_due:
            log.info(
                "[pdf_export] Session-betalningsdatum vid UI-init: %s "
                "(visas i PDF-export)",
                session_due,
            )
        else:
            log.debug(
                "[pdf_export] Session-betalningsdatum: ej satt vid UI-init"
            )

        def _on_theme_changed(theme_dict: dict) -> None:
            """Tema-synk: theme_dict["name"] är dark/light/auto/system."""
            exporter.set_theme(theme_dict.get("name", "dark"))
            log.debug(
                "[pdf_export] tema uppdaterat → %s",
                theme_dict.get("name", "dark"),
            )

        try:
            main_window.theme_changed.connect(_on_theme_changed)
        except Exception as exc:
            log.warning("[pdf_export] theme_changed connect: %s", exc)

        if hasattr(app, "get_suppliers"):
            exporter.set_suppliers_fn(app.get_suppliers)

        log.debug("[pdf_export] theme_changed + supplier-signal kopplad")

    except Exception as exc:
        log.warning("[pdf_export] register_ui theme sync: %s", exc)

    # ── UI-hook på InvoicesView ─────────────────────────────────────────
    try:
        inv_view = None
        if hasattr(main_window, "get_invoices_view"):
            inv_view = main_window.get_invoices_view()
        if inv_view and hasattr(inv_view, "_add_export_action"):
            inv_view._add_export_action()
            log.info("[pdf_export] export action added to InvoicesView")
    except Exception as exc:
        log.warning(
            "[pdf_export] register_ui InvoicesView hook: %s", exc
        )

    log.info("[pdf_export] UI registration complete")


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python plugins/pdf_export.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import tempfile
    import uuid

    logging.basicConfig(level=logging.DEBUG)

    print("=" * 65)
    print("  FakturaRäknaren – pdf_export.py självtest")
    print(f"  © {COPYRIGHT_YEAR} Rickard Längkvist")
    print(f"  Platform: {get_platform()}")
    print("=" * 65)

    _suppliers = [
        {
            "id": "s1", "name": "Acme AB",
            "org_number": "556111-2222", "bg": "5555-1234",
            "pg": "", "iban": "SE1234567890", "bic": "SWEDSESS",
            "payment_terms": 30, "contact_person": "Anna Acme",
            "email": "anna@acme.se", "phone": "08-111 222",
            "address": "Storgatan 1, 111 22 Stockholm",
        },
        {
            "id": "s2", "name": "Beta AB",
            "org_number": "556333-4444", "bg": "9999-5678",
            "pg": "123456-7", "iban": "", "bic": "",
            "payment_terms": 20, "contact_person": "Bo Beta",
            "email": "bo@beta.se", "phone": "031-333 444",
            "address": "Lillgatan 5, 411 00 Göteborg",
        },
    ]

    _invoices = [
        {
            "id": str(uuid.uuid4()),
            "invoice_number": "INV-001", "invoice_type": "Faktura",
            "supplier": "Acme AB", "date": "2026-01-10",
            "due_date": "2026-02-10", "payment_date": "",
            "total_amount": 1250.0, "status": "Obetald",
        },
        {
            "id": str(uuid.uuid4()),
            "invoice_number": "INV-002", "invoice_type": "Faktura",
            "supplier": "Beta AB", "date": "2026-01-15",
            "due_date": "2026-02-15", "payment_date": "",
            "total_amount": 5000.0, "status": "Obetald",
        },
        {
            "id": str(uuid.uuid4()),
            "invoice_number": "KRE-001", "invoice_type": "Kreditfaktura",
            "supplier": "Acme AB", "date": "2026-01-20",
            "due_date": "2026-02-20", "payment_date": "",
            "total_amount": -500.0, "status": "Obetald",
        },
    ]

    _test_session_due = "2026-02-28"
    print(f"\n  Session-betalningsdatum (test): {_test_session_due}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        for theme in ("dark", "light"):
            print(f"\n{'─' * 55}\n  Tema: {theme}\n{'─' * 55}")

            exporter = PDFExporter(
                export_dir=tmp_path / f"exports_{theme}",
                data_dir=tmp_path / f"data_{theme}",
                company="Test Foretag AB",
                org_number="556000-1234",
                currency="SEK",
                theme=theme,
                get_suppliers_fn=lambda: _suppliers,
                rounding_mode="100",
            )

            # [1] Export med leverantörsuppgifter + session-datum
            print("\n  [1] Export med leverantorsinfo + session-datum")
            r = exporter.export_invoice_list(
                _invoices,
                title="Test med leverantorsinfo",
                session_due_date=_test_session_due,
                payment_date=_test_session_due,
                ask_payment_date=False,
            )
            assert r["success"], r["errors"]
            assert r["net_total"] == 5750.0
            assert r["net_total_display"] == 5800.0  # avrundning 100
            print(f"      net={r['net_total']}  display={r['net_total_display']}")

            if not exporter._has_rl:
                content = Path(r["file_path"]).read_text(encoding="utf-8")
                assert "Acme AB" in content
                assert "ATT BETALA" in content
                assert _test_session_due in content
                assert "5 800,00 SEK" in content
                print("      OK: supplier + ATT BETALA + session + avrundning")

            # [2] Export utan session-datum
            print("\n  [2] Export utan session-datum")
            r_no = exporter.export_invoice_list(
                _invoices, title="Test utan session-datum",
                session_due_date="", force_export=True,
                ask_payment_date=False,
            )
            assert r_no["success"] and r_no["session_due_date"] == ""
            print("      OK")

            # [3] Dubblettskydd
            print("\n  [3] Dubblettskydd")
            r2 = exporter.export_invoice_list(
                _invoices, title="Dup-test",
                session_due_date=_test_session_due,
                payment_date=_test_session_due,
                ask_payment_date=False,
            )
            assert r2["skipped_count"] == 3
            print(f"      blocked: {r2['skipped_count']}  OK")

            # [4] Force export
            print("\n  [4] Force export")
            r3 = exporter.export_invoice_list(
                _invoices, title="Force-test", force_export=True,
                session_due_date=_test_session_due,
                payment_date=_test_session_due,
                ask_payment_date=False,
            )
            assert r3["success"] and r3["exported_count"] == 3
            print("      OK")

            # [5] Sammanställning
            print("\n  [5] Sammanstallning")
            rs = exporter.export_summary(
                _invoices, title="Sammanstallning Test",
                session_due_date=_test_session_due,
            )
            assert rs["success"] and rs["net_total_display"] == 5800.0
            print("      OK")

            # [6] quick_export med rounding
            print("\n  [6] quick_export med session-datum + avrundning")
            rq = quick_export(
                _invoices,
                data_dir=tmp_path / f"data_q_{theme}",
                export_dir=tmp_path / "exports2",
                title="Quick Export Test",
                company="Test AB",
                theme=theme,
                suppliers_list=_suppliers,
                session_due_date=_test_session_due,
                rounding_mode="50",
                payment_date=_test_session_due,
                ask_payment_date=False,
            )
            assert rq["success"] and rq["net_total_display"] == 5750.0
            print("      OK")

            # [7] Statistik
            print("\n  [7] Export-statistik")
            st = exporter.get_export_stats()
            assert st["rounding_mode"] == "100"
            print(f"      rounding_mode={st['rounding_mode']}  OK")

            # [8] Tema-test inkl auto
            print("\n  [8] Tema-test (dark/light/auto)")
            exporter.set_theme("light")
            assert exporter._is_dark() is False
            exporter.set_theme("auto")
            h = datetime.datetime.now().hour
            assert exporter._is_dark() is not (7 <= h < 20)
            exporter.set_theme(theme)
            print("      OK")

    print("\n  ✅  självtest klart.")
