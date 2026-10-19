from __future__ import annotations

"""
FakturaRäknaren — Invoices Helpers
========================================
Fil    : FakturaRäknaren_/ui/invoices_helpers.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Hjälpmodul för invoices_view.py.

Innehåller
----------
• Plattformshjälpare (öppna filer, mappar — Win/Linux/macOS)
• Typsnittsfabrik (svenska tecken åäöÅÄÖ)
• UI-widget-fabrik (knappar, celler, inputs)
• Beloppsformaterare (svenskt format)
• Exportmapps-builder (exports/<Leverantör>/<YYYY-MM-DD>/)
• ExportHistoryManager (JSON-historik med atomisk skrivning)
• ExportHistoryDialog (tabell, återställning, tema, betalningsdatum)
• InvoiceDialog (registrering / redigering av faktura/kredit)
• Konstanter (statusar, kolumner, färger, valutor)

Betalningsdatum per export
--------------------------
• InvoiceDialog._apply_session_due_date() läser session_due_date från
  app_core som default-förfallodatum (sätts EN gång per session i main.py).
• Innan varje export visas ask_export_payment_date() (från
  pdf_export_helpers.py) som frågar om betalningsdatum JUST FÖR DENNA
  EXPORT.
• Betalningsdatumet nollställs automatiskt efter exporten.
• Nästa export → frågar igen.

Samarbetar med
--------------
• ui/invoices_view.py            – huvudvy som importerar allt härifrån
• app.py                         – FakturaApp (CRUD-API, settings,
                                   session_due_date, session_due_date_str)
• plugins/pdf_export.py          – PDF-export
• plugins/pdf_export_helpers.py  – ask_export_payment_date()
• main.py / ui/main_window.py    – MainWindow, tema-signal

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import json
import logging
import math
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLineEdit,
    QLabel,
    QTextEdit,
    QComboBox,
    QFormLayout,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QFrame,
    QSizePolicy,
    QAbstractItemView,
    QDoubleSpinBox,
    QDateEdit,
    QScrollArea,
    QGroupBox,
    QCompleter,
    QApplication,
    QStyledItemDelegate,
)
from PySide6.QtCore import Qt, QTimer, QDate, Signal, QUrl, QObject, QEvent
from PySide6.QtGui import (
    QFont, QColor, QCursor, QBrush, QDesktopServices, QWheelEvent,
    QPalette,
)

log = logging.getLogger("InvoicesHelpers")

try:
    from ui.i18n import tr, tr_status
except Exception:  # pragma: no cover - fristående körning
    try:
        from i18n import tr, tr_status  # type: ignore[no-redef]
    except Exception:
        def tr(key: str, **_f: object) -> str:  # type: ignore[no-redef]
            return key

        def tr_status(v: str) -> str:  # type: ignore[no-redef]
            return str(v)

COPYRIGHT_YEAR: int = datetime.date.today().year

# ═════════════════════════════════════════════════════════════════════
#  PLATTFORM
# ═════════════════════════════════════════════════════════════════════


def get_platform() -> str:
    """Returnerar 'windows' | 'linux' | 'macos'."""
    p = platform.system().lower()
    if p == "darwin":
        return "macos"
    return "windows" if p == "windows" else "linux"


CURRENT_PLATFORM: str = get_platform()

BASE_DIR: Path = Path(__file__).parent.parent.resolve()

# ═════════════════════════════════════════════════════════════════════
#  ÖPPNA FIL / MAPP  (multi-OS)
# ═════════════════════════════════════════════════════════════════════


def open_file(path: str | Path) -> None:
    """Öppnar en fil med OS:ets standardprogram. Multi-OS."""
    p = Path(path)
    if not p.exists():
        log.warning("open_file: filen hittades inte: %s", p)
        return
    try:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
    except Exception:
        try:
            if CURRENT_PLATFORM == "windows":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif CURRENT_PLATFORM == "macos":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:
            log.error("open_file fallback-fel: %s", exc)


def print_file(path: str | Path) -> bool:
    """Skriver ut en fil via OS:ets standardväg. True om det gick iväg.

    Windows: print-verbet (standardprogrammets utskrift),
    macOS/Linux: lpr/lp. Kastar aldrig — utskrift är ett tillägg,
    aldrig ett krav för att exporten ska räknas som lyckad.
    """
    p = Path(path)
    if not p.exists():
        log.warning("print_file: filen hittades inte: %s", p)
        return False
    try:
        if CURRENT_PLATFORM == "windows":
            os.startfile(str(p), "print")  # type: ignore[attr-defined]
        elif CURRENT_PLATFORM == "macos":
            subprocess.Popen(["lpr", str(p)])
        else:
            subprocess.Popen(["lp", str(p)])
        return True
    except Exception as exc:
        log.warning("print_file %s: %s", p, exc)
        return False


def open_folder(path: str | Path) -> None:
    """Öppnar en mapp i OS:ets filhanterare. Skapar aldrig utanför appmappen."""
    p = Path(path)
    try:
        probe = p.resolve() if p.exists() else (BASE_DIR / p) if not p.is_absolute() else p
        probe.resolve().relative_to(BASE_DIR.resolve())
    except (OSError, ValueError):
        log.warning("Öppnar inte mapp utanför appmappen: %s", p)
        p = BASE_DIR / "exports"
    p.mkdir(parents=True, exist_ok=True)
    try:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
    except Exception:
        try:
            if CURRENT_PLATFORM == "windows":
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif CURRENT_PLATFORM == "macos":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as exc:
            log.error("open_folder fallback-fel: %s", exc)


# ═════════════════════════════════════════════════════════════════════
#  TYPSSNITTSFABRIK — stöder svenska tecken (åäöÅÄÖ) på alla plattformar
# ═════════════════════════════════════════════════════════════════════

FONT_FALLBACKS: tuple[str, ...] = (
    "Segoe UI",
    "SF Pro Display",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    "Helvetica Neue",
    "Arial",
    "sans-serif",
)


def make_font(size: int = 12, bold: bool = False) -> QFont:
    """Skapar QFont med fallback-kedja för svenska tecken."""
    for family in FONT_FALLBACKS:
        f = QFont(family, size)
        if f.exactMatch() or family == "sans-serif":
            f.setBold(bold)
            return f
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    return f


# ═════════════════════════════════════════════════════════════════════
#  FORMATERING
# ═════════════════════════════════════════════════════════════════════


def fmt_amount(value: float, currency: str = "SEK") -> str:
    """
    Svenskt beloppsformat: 12 345,67 SEK
    Negativt: −12 345,67 SEK
    """
    prefix = "−" if value < 0 else ""
    s = f"{abs(value):,.2f}".replace(",", "\u2009").replace(".", ",")
    suffix = f" {currency}" if currency else ""
    return f"{prefix}{s}{suffix}"


def combine_invoices(rows: list[dict]) -> dict:
    """
    Slår ihop markerade fakturor till en sammanfattning.

    Returnerar summor (fakturor +, krediter −, netto) samt det
    TIDIGASTE förfallodatumet bland rader som har ett giltigt datum —
    tanken: betalar man allt i ett svep gör man det senast när den
    första fakturan förfaller. Ogiltiga/saknade datum räknas i
    ``missing_due`` men stoppar aldrig sammanslagningen.
    """
    import datetime as _dt

    total_invoices = 0.0
    total_credits = 0.0
    earliest: _dt.date | None = None
    earliest_row: dict | None = None
    missing_due = 0
    suppliers: set[str] = set()

    for row in rows or []:
        val = _to_float(row.get("total_amount"))
        if val >= 0:
            total_invoices += val
        else:
            total_credits += val
        sup = str(row.get("supplier", "")).strip()
        if sup:
            suppliers.add(sup)
        raw_due = str(row.get("due_date", "") or "").strip()[:10]
        parsed: _dt.date | None = None
        if raw_due:
            try:
                parsed = _dt.date.fromisoformat(raw_due)
            except ValueError:
                parsed = None
        if parsed is None:
            missing_due += 1
        elif earliest is None or parsed < earliest:
            earliest = parsed
            earliest_row = row

    return {
        "count": len(rows or []),
        "n_invoices": sum(
            1 for r in rows or [] if _to_float(r.get("total_amount")) >= 0
        ),
        "n_credits": sum(
            1 for r in rows or [] if _to_float(r.get("total_amount")) < 0
        ),
        "total_invoices": round(total_invoices, 2),
        "total_credits": round(total_credits, 2),
        "net": round(total_invoices + total_credits, 2),
        "earliest_due": earliest.isoformat() if earliest else "",
        "earliest_invoice": earliest_row,
        "missing_due": missing_due,
        "suppliers": sorted(suppliers),
    }


#: Statusar som INTE ska betalas (samma regel som vyerna).
_PAID_LIKE_STATUSES: tuple[str, ...] = ("Betald", "Makulerad", "Arkiverad")


def ocr_luhn_status(ocr: Any) -> str:
    """
    Kontrollerar OCR-numrets kontrollsiffra (Luhn/mod-10).

    Returnerar:
      "empty"          – inget ifyllt
      "invalid_format" – inte bara siffror (t.ex. en referens) → ingen
                         kontroll möjlig, ingen varning visas
      "ok"             – kontrollsiffran stämmer
      "bad_check"      – siffror, men kontrollsiffran stämmer INTE
                         (troligen en felskriven siffra)
    """
    text = str(ocr or "").replace(" ", "").strip()
    if not text:
        return "empty"
    if not text.isdigit() or len(text) < 2:
        return "invalid_format"
    total = 0
    for idx, ch in enumerate(reversed(text)):
        d = ord(ch) - 48
        if idx % 2 == 1:  # varannan siffra (från höger) dubblas
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return "ok" if total % 10 == 0 else "bad_check"


def find_invoice_duplicate(
    invoices: list[dict],
    invoice_number: str,
    supplier: str,
    exclude_id: str = "",
) -> dict | None:
    """
    Returnerar befintlig faktura med samma nummer+leverantör
    (skiftläges- och mellanslags-okänsligt), annars None.
    *exclude_id* används vid redigering så fakturan inte
    matchar sig själv.
    """
    nr = str(invoice_number or "").strip().casefold()
    sup = str(supplier or "").strip().casefold()
    if not nr or not sup:
        return None
    for inv in invoices:
        if exclude_id and str(inv.get("id", "")) == str(exclude_id):
            continue
        if (
            str(inv.get("invoice_number", "")).strip().casefold() == nr
            and str(inv.get("supplier", "")).strip().casefold() == sup
        ):
            return inv
    return None


def payment_info_text(invoice: dict, supplier: dict | None) -> str:
    """
    Betalinfo för en faktura som färdig text till urklipp —
    exakt det som knappas in i internetbanken.
    """
    sup = supplier or {}
    lines = [tr("payinfo.title")]
    name = str(invoice.get("supplier", "") or sup.get("name", "")).strip()
    if name:
        lines.append(f"{tr('payinfo.supplier')}: {name}")
    for key, label_key in (
        ("bg", "payinfo.bankgiro"),
        ("pg", "payinfo.plusgiro"),
        ("iban", "payinfo.iban"),
    ):
        val = str(sup.get(key, "") or "").strip()
        if val:
            lines.append(f"{tr(label_key)}: {val}")
    nr = str(invoice.get("invoice_number", "") or "").strip()
    if nr:
        lines.append(f"{tr('payinfo.invoice_number')}: {nr}")
    ocr = str(invoice.get("ocr", "") or "").strip()
    ref = str(invoice.get("reference", "") or "").strip()
    if ocr:
        lines.append(f"{tr('payinfo.ocr')}: {ocr}")
    elif ref:
        lines.append(f"{tr('payinfo.reference')}: {ref}")
    due = str(invoice.get("due_date", "") or "").strip()
    if due:
        lines.append(f"{tr('payinfo.due')}: {due[:10]}")
    amount = _to_float(invoice.get("total_amount"))
    lines.append(f"{tr('payinfo.amount')}: {fmt_amount(amount)}")
    return "\n".join(lines)


#: Snabbfilterlägen för förfallofönster i Fakturor-vyn.
DUE_WINDOW_MODES: tuple[str, ...] = ("overdue", "today", "week")


def due_window_filter(
    rows: list[dict],
    mode: str,
    today: datetime.date,
) -> list[dict]:
    """
    Snabbfilter på förfallodatum (bara obetalda rader):

      "overdue" – förfallna (datum passerat eller status Förfallen)
      "today"   – förfaller idag eller i morgon
      "week"    – förfaller inom 7 dagar (idag inräknad)

    Rader utan giltigt förfallodatum faller bort i alla lägen.
    """
    if mode not in DUE_WINDOW_MODES:
        return list(rows)
    out: list[dict] = []
    for r in rows:
        if str(r.get("status", "")) in _PAID_LIKE_STATUSES:
            continue
        try:
            due = datetime.date.fromisoformat(
                str(r.get("due_date", "") or "")[:10]
            )
        except ValueError:
            continue
        if mode == "overdue":
            if due < today or str(r.get("status", "")) == "Förfallen":
                out.append(r)
        elif mode == "today":
            if today <= due <= today + datetime.timedelta(days=1):
                out.append(r)
        else:  # week
            if today <= due <= today + datetime.timedelta(days=7):
                out.append(r)
    return out


def att_betala_summary(invoices: list[dict]) -> dict:
    """
    Kärnsiffran: vad ska betalas just nu.

    {"total": nettosumma obetalda (krediter avdragna), "count": antal}
    Samma regel som Dashboard och Fakturor: Betald/Makulerad/
    Arkiverad räknas inte.
    """
    total = 0.0
    count = 0
    for inv in invoices:
        if str(inv.get("status", "")) in _PAID_LIKE_STATUSES:
            continue
        total += _to_float(inv.get("total_amount"))
        count += 1
    return {"total": round(total, 2), "count": count}


def due_within(
    invoices: list[dict],
    today: datetime.date,
    horizon_days: int = 1,
) -> list[dict]:
    """
    Obetalda fakturor som förfaller senast idag + *horizon_days*
    (förfallna ingår), sorterade på förfallodatum. Krediter tas
    med — de dras av i summeringen.
    """
    limit = today + datetime.timedelta(days=horizon_days)
    hits: list[tuple[str, dict]] = []
    for inv in invoices:
        if str(inv.get("status", "")) in _PAID_LIKE_STATUSES:
            continue
        raw = str(inv.get("due_date", "") or "")[:10]
        try:
            due = datetime.date.fromisoformat(raw)
        except ValueError:
            continue
        if due <= limit:
            hits.append((raw, inv))
    hits.sort(key=lambda t: t[0])
    return [inv for _raw, inv in hits]


def _to_float(value: Any, default: float = 0.0) -> float:
    """Säker float-konvertering."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_amount_text(text: str) -> float:
    """
    Parsar formaterat svenskt belopp ("45 546,00" / "−12 345,67").

    Returnerar nan vid okänd text (faller då tillbaka på textsortering).
    """
    t = (
        text.replace("\u2009", "")
        .replace(" ", "")
        .replace(",", ".")
        .replace("−", "-")
    )
    try:
        return float(t)
    except ValueError:
        return float("nan")


def format_amount_edit(value: Any) -> str:
    """
    Formatterar ett belopp för AmountLineEdit — svenskt format:

        45546        → "45 546,00"
        1234.5       → "1 234,50"
        0 / ogiltigt → ""  (tomt fält, placeholder visas)

    Mellanslag som tusentalsavgränsare, komma som decimaltecken,
    alltid 2 decimaler (öre). Tecken ignoreras (＋/− hanteras av
    teckenväljaren i fakturadialogen).
    """
    v = _to_float(value, default=float("nan"))
    if v != v:                       # NaN
        return ""
    v = abs(v)
    if v <= 0:
        return ""
    ore = int(round(v * 100))
    kr = ore // 100
    frac = ore % 100
    kr_s = f"{kr:,}".replace(",", " ")
    return f"{kr_s},{frac:02d}"


def parse_amount_edit(text: Any) -> float:
    """
    Parsar text från AmountLineEdit till ett POSITIVT belopp.

    • Mellanslag / tunna mellanslag ignoreras (tusentalsavgränsare).
    • Punkt och komma fungerar som decimaltecken.
    • Minus ignoreras (tecknet ägs av ＋/−-väljaren).
    • Tom / ogiltig text → 0.0.
    """
    t = str(text or "")
    t = (
        t.replace("\u2009", "")
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace("−", "")
        .replace("-", "")
    )
    t = t.replace(",", ".")
    if t.count(".") > 1:             # flera decimaltecken → ogiltigt
        return 0.0
    try:
        v = float(t)
    except ValueError:
        return 0.0
    if v != v:                       # NaN
        return 0.0
    return abs(v)


# ═════════════════════════════════════════════════════════════════════
#  EXPORTMAPP
# ═════════════════════════════════════════════════════════════════════


def safe_dirname(name: str) -> str:
    """Rensar otillåtna filsystemstecken men behåller åäöÅÄÖ."""
    keep = set(
        "abcdefghijklmnopqrstuvwxyzåäö"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ"
        "0123456789_- "
    )
    cleaned = "".join(c if c in keep else "_" for c in name)
    return cleaned.strip().rstrip(".")


def get_export_base() -> Path:
    """
    exports/ under app-roten. Aldrig en sökväg utanför appmappen.
    En symlänk som pekar ut följs inte.
    """
    p = BASE_DIR / "exports"
    try:
        if p.is_symlink():
            target = p.resolve()
            target.relative_to(BASE_DIR.resolve())
        p.mkdir(parents=True, exist_ok=True)
        resolved = p.resolve()
        resolved.relative_to(BASE_DIR.resolve())
        return resolved
    except (OSError, ValueError):
        log.warning(
            "EXPORT_UTANFÖR: exports pekar utanför appmappen → data/exports"
        )
        alt = BASE_DIR / "data" / "exports"
        alt.mkdir(parents=True, exist_ok=True)
        return alt


def build_export_path(suppliers: list[str]) -> tuple[Path, str]:
    """
    Bygger exportmapp och filnamn, alltid inuti appmappen:

        exports/<Leverantör>/<YYYY-MM-DD>/fakturalista_HHMMSS.pdf

    Flera leverantörer → Blandade_leverantörer.
    Returnerar (mapp, filnamn).
    """
    base = get_export_base()
    now = datetime.datetime.now()

    if len(suppliers) == 1:
        sup_dir = safe_dirname(suppliers[0]) or "Okänd"
    elif len(suppliers) > 1:
        sup_dir = "Blandade_leverantörer"
    else:
        sup_dir = "Okänd"

    date_dir = now.strftime("%Y-%m-%d")
    target = base / sup_dir / date_dir
    target.mkdir(parents=True, exist_ok=True)

    filename = f"fakturalista_{now.strftime('%H%M%S')}.pdf"
    return target, filename


#: Max antal fakturarader i EN exportfil (betal-PDF). Fler rader
#: → flera filer (…-del1avN.pdf, …-del2avN.pdf, …). Varje faktura
#: är alltid en egen rad i PDF:en — taket gäller per fil, det
#: betyder aldrig att fakturor slås ihop till en gemensam rad.
MAX_PER_EXPORT_FILE = 10


def chunk_export_rows(
    rows: list[dict], size: int = MAX_PER_EXPORT_FILE
) -> list[list[dict]]:
    """
    Delar exportrader i filer om högst `size` stycken, i samma
    ordning som betal-PDF:en sorterar (leverantör → förfallodatum
    → fakturanummer). Uppdelningen blir därmed förutsägbar och
    samma leverantörs rader hålls ihop så långt taket tillåter.
    """
    def _key(r: dict) -> tuple[str, str, str]:
        return (
            str(r.get("supplier", "") or "").strip().lower(),
            str(r.get("due_date", "") or ""),
            str(r.get("invoice_number", "") or ""),
        )

    ordered = sorted(rows or [], key=_key)
    if size < 1:
        size = MAX_PER_EXPORT_FILE
    return [
        ordered[i:i + size] for i in range(0, len(ordered), size)
    ]


def read_watch_folders(config_file) -> list[dict]:
    """folders-listan ur watch_folders.json ([] vid alla fel)."""
    try:
        cfg = json.loads(
            Path(config_file).read_text(encoding="utf-8")
        )
        folders = cfg.get("folders", [])
        return [f for f in folders if isinstance(f, dict)]
    except Exception:
        return []


def archive_original_file(
    attachment: str, watched_folders: list[dict], year: int
) -> str:
    """
    Flyttar en exporterad fakturas original från den bevakade
    mappen till <mapp>/Arkiv/<år>/ och returnerar nya sökvägen.

    Bara filer som ligger DIREKT i en bevakad mapp flyttas;
    allt annat (annan plats, saknad fil, fel under vägen) lämnas
    orört och den gamla sökvägen returneras oförändrad. Funktionen
    kastar aldrig undantag — exporten får inte fallera på en
    arkivflytt.
    """
    old = str(attachment or "")
    try:
        src = Path(old.strip())
        if not old.strip() or not src.is_file():
            return old
        root = None
        for entry in watched_folders or []:
            pth = str(entry.get("path", "") or "").strip()
            if not pth:
                continue
            try:
                parent = src.resolve().parent
                top = Path(pth).resolve()
                # Direkt i mappen ELLER i dess årsmapp (<år>/) —
                # årssorterade original arkiveras likadant.
                if parent == top or parent.parent == top:
                    root = Path(pth)
                    break
            except Exception:
                continue
        if root is None:
            return old
        if parent.parent == root.resolve() \
                and parent.name == "Arkiv":
            return old  # redan arkiverad
        target_dir = root / "Arkiv" / str(year)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        if target.exists():
            if target.resolve() == src.resolve():
                return str(src)
            stem, suffix = src.stem, src.suffix
            n = 2
            while target.exists():
                target = target_dir / f"{stem}_{n}{suffix}"
                n += 1
        shutil.move(str(src), str(target))
        return str(target)
    except Exception:
        return old


# ═════════════════════════════════════════════════════════════════════
#  SESSION-BETALNINGSDATUM
# ═════════════════════════════════════════════════════════════════════


def get_session_due_date_str(app_core: Any) -> str:
    """
    Hämtar session-betalningsdatum från app_core som YYYY-MM-DD-sträng.

    Prioritet:
        1. app_core.session_due_date_str  (property från app.py)
        2. app_core.session_due_date      (datetime.date direkt)
        3. ""                             (ej satt)

    Returnerar "" om app_core är None eller datumet ej är satt.
    Används av InvoiceDialog som default-förfallodatum.
    """
    if app_core is None:
        return ""

    str_val = getattr(app_core, "session_due_date_str", None)
    if str_val and isinstance(str_val, str) and str_val.strip():
        return str_val.strip()

    date_val = getattr(app_core, "session_due_date", None)
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
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

INVOICE_STATUSES: list[str] = [
    "Obetald",
    "Planerad",
    "Betalfil skapad",
    "Betald",
    "Förfallen",
    "Makulerad",
    "Arkiverad",
]

#: Statusar som döljs i standardvyn och inte är exporterbara.
HIDDEN_STATUSES: frozenset[str] = frozenset({"Arkiverad", "Makulerad"})

#: (dark_fg, light_fg) per status.
STATUS_COLORS: dict[str, tuple[str, str]] = {
    "Obetald":         ("#ffb74d", "#e65100"),
    "Planerad":        ("#64b5f6", "#1565c0"),
    "Betalfil skapad": ("#ce93d8", "#6a1b9a"),
    "Betald":          ("#81c784", "#2e7d32"),
    "Förfallen":       ("#ef9a9a", "#b71c1c"),
    "Makulerad":       ("#bdbdbd", "#424242"),
    "Arkiverad":       ("#4dd0e1", "#00838f"),
}

#: (etikett, datanyckel, min-bredd, justering)
COLUMNS: list[tuple[str, str, int, Qt.AlignmentFlag]] = [
    ("Typ",        "invoice_type",    64, Qt.AlignmentFlag.AlignCenter),
    ("Leverantör", "supplier",       150, Qt.AlignmentFlag.AlignLeft),
    ("Fakturanr",  "invoice_number", 110, Qt.AlignmentFlag.AlignLeft),
    ("OCR",        "ocr",             90, Qt.AlignmentFlag.AlignLeft),
    ("Datum",      "date",            88, Qt.AlignmentFlag.AlignCenter),
    ("Förfaller",  "due_date",        88, Qt.AlignmentFlag.AlignCenter),
    ("Betaldatum", "payment_date",    88, Qt.AlignmentFlag.AlignCenter),
    ("Belopp",     "total_amount",   100, Qt.AlignmentFlag.AlignRight),
    ("Valuta",     "currency",        52, Qt.AlignmentFlag.AlignCenter),
    ("Status",     "status",          88, Qt.AlignmentFlag.AlignCenter),
    ("Kategori",   "category",        72, Qt.AlignmentFlag.AlignLeft),
    ("Referens",   "reference",       72, Qt.AlignmentFlag.AlignLeft),
    ("Notering",   "note",            80, Qt.AlignmentFlag.AlignLeft),
]

COL_LABELS: list[str] = [c[0] for c in COLUMNS]
COL_KEYS: list[str] = [c[1] for c in COLUMNS]
COL_WIDTHS: list[int] = [c[2] for c in COLUMNS]
COL_ALIGN: list[Qt.AlignmentFlag] = [c[3] for c in COLUMNS]

CURRENCIES: list[str] = [
    "SEK", "EUR", "USD", "NOK", "DKK", "GBP", "CHF",
]

HIST_COLUMNS: list[tuple[str, int]] = [
    ("Datum",          150),
    ("Antal fakturor",  90),
    ("Antal krediter",  90),
    ("Fakturor (+)",   135),
    ("Krediter (−)",   135),
    ("Att betala",     140),
    ("Leverantörer",   200),
    ("Fil",            280),
]

EXPORT_HISTORY_FILE: str = "export_history.json"

#: Tomt/saknat datum i QDateEdit visas som detta (specialValueText).
NO_DATE_TEXT: str = "(ej angivet)"

#: "Tomt" datum i QDateEdit — värdet vid minimum visas som NO_DATE_TEXT.
EMPTY_DATE = QDate(1900, 1, 1)

#: Avrundningslägen för ATT BETALA i PDF-exporten.
PDF_ROUNDING_MODES: tuple[str, ...] = ("exact", "hel", "50", "100")


def round_by_mode(value: float, mode: str = "exact") -> float:
    """
    Avrundar ett belopp enligt läge:

    • ``exact`` : 2 decimaler (oförändrat)
    • ``hel``   : hel krona (50 öre+ upp)
    • ``50``    : jämnt 50 kr
    • ``100``   : jämnt 100 kr

    Tecken behålls (krediter förblir negativa).
    Används av GUI + PDF via settings-nyckeln ``pdf_rounding``.
    """
    if mode not in PDF_ROUNDING_MODES or mode == "exact":
        return round(value, 2)
    sign = -1.0 if value < 0 else 1.0
    v = abs(value)
    if mode == "hel":
        v = math.floor(v + 0.5)
    elif mode == "50":
        v = math.floor(v / 50.0 + 0.5) * 50.0
    else:  # "100"
        v = math.floor(v / 100.0 + 0.5) * 100.0
    return round(sign * v, 2)


# ═════════════════════════════════════════════════════════════════════
#  UI-WIDGET-FABRIKER
# ═════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════
#  TANGENTBORDSNAVIGATION — logisk Tab-ordning + Enter → nästa fält
# ═════════════════════════════════════════════════════════════════════


class _EnterNextFilter(QObject):
    """
    Eventfilter: Enter hoppar till nästa fält i stället för att
    aktivera default-knappen mitt i ifyllandet.

    • Flerradiga fält (QTextEdit) hoppas över — Enter där = ny rad.
    • Enter i SISTA enradiga fältet = spara/validera (on_last).
    """

    def __init__(
        self, order: list[QWidget], on_last: Callable | None = None
    ) -> None:
        super().__init__()
        self._order = order
        self._nav = [w for w in order if not isinstance(w, QTextEdit)]
        self._on_last = on_last

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        ):
            w = QApplication.focusWidget()
            if w is not None and w in self._nav:
                idx = self._nav.index(w)
                if idx + 1 < len(self._nav):
                    self._nav[idx + 1].setFocus()
                    return True
                if self._on_last is not None:
                    self._on_last()
                    return True
        return False


def install_keyboard_navigation(
    dialog: QDialog,
    order: list[QWidget],
    on_last: Callable | None = None,
) -> None:
    """
    Logisk Tab-ordning + Enter → nästa fält i en dialog.

    • Kedjar fälten med setTabOrder i given ordning.
    • Enter hoppar till nästa ENRADIGA fält (QTextEdit hoppas över).
    • Enter i sista enradiga fältet = spara/validera (on_last).
    • Referensen till filtret sparas på dialogen så att den inte
      skrotas av garbage collectorn.
    """
    for a, b in zip(order, order[1:]):
        dialog.setTabOrder(a, b)
    filt = _EnterNextFilter(order, on_last)
    for w in order:
        w.installEventFilter(filt)
    dialog._enter_next_filter = filt  # noqa: SLF001 – medvetet


def fit_table_columns(table: QTableWidget, weights: list[int]) -> None:
    """
    Fördelar kolumnerna så de fyller tabellens synliga bredd.

    Ingen horisontell scroll så länge fönstret är normalt brett.
    Vikterna är de gamla fasta bredderna — de styr proportionerna.
    """
    if not weights or table.columnCount() == 0:
        return
    available = table.viewport().width()
    if available < 80:
        return
    n = min(len(weights), table.columnCount())
    parts = [max(1, int(weights[i])) for i in range(n)]
    total = sum(parts) or 1
    min_px = 36
    widths = [max(min_px, available * part // total) for part in parts]
    overflow = sum(widths) - available
    if overflow > 0:
        order = sorted(
            range(n), key=lambda i: widths[i] - min_px, reverse=True
        )
        for i in order:
            if overflow <= 0:
                break
            spare = widths[i] - min_px
            cut = min(spare, overflow)
            widths[i] -= cut
            overflow -= cut
    elif overflow < 0:
        widths[0] -= overflow
    header = table.horizontalHeader()
    header.blockSignals(True)
    header.setStretchLastSection(False)
    for i, width in enumerate(widths):
        table.setColumnWidth(i, width)
    header.blockSignals(False)


def h_line() -> QFrame:
    """Horisontell avdelare."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFrameShadow(QFrame.Shadow.Sunken)
    return f


# ═════════════════════════════════════════════════════════════════════
#  RAD-DELEGATE  (synliga rader i tabeller — används av suppliers_view)
#
#  BAKGRUND: suppliers_view.py importerade attach_visible_rows(),
#  ensure_row_height(), fg_on_row() och ROLE_*-konstanterna härifrån,
#  men funktionerna fanns aldrig i filen → ImportError vid import →
#  HELA leverantörsfliken dog tyst (MainWindow visade bara en död
#  platshållare). Här är den saknade implementationen.
# ═════════════════════════════════════════════════════════════════════

#: Item-data-roller för radmålning (över UserRole så de aldrig
#: krockar med post-id:t som vyerna lagrar i UserRole).
ROLE_ROW_BG: int = int(Qt.ItemDataRole.UserRole) + 11      # jämn rad
ROLE_ROW_BG_ODD: int = int(Qt.ItemDataRole.UserRole) + 12  # udda rad
ROLE_ROW_FG: int = int(Qt.ItemDataRole.UserRole) + 13      # textfärg
ROLE_STRIPE: int = int(Qt.ItemDataRole.UserRole) + 14      # vänsterkant


def _luminance(color: str) -> float:
    """Relativ luminans (0–1) för '#rrggbb'. 0.5 vid ogiltig färg."""
    try:
        h = str(color).lstrip("#")
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

        def ch(v: float) -> float:
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

        return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
    except Exception:
        return 0.5


def _contrast(a: str, b: str) -> float:
    """WCAG-kontrastförhållande (1–21) mellan två hexfärger."""
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def is_dark_theme(theme: dict | None) -> bool:
    """
    True om temat är mörkt.

    Använder temats ``name`` ("dark"/"light") när det finns och
    faller tillbaka på bakgrundens luminans. (Den gamla listan över
    ljusa hexvärden kände inte igen nuvarande ljustema #f4f1ea,
    så vyerna trodde att ljust läge var mörkt och målade fel.)
    """
    if not theme:
        return True
    name = str(theme.get("name", "")).lower()
    if name in ("dark", "light"):
        return name == "dark"
    return _luminance(str(theme.get("bg", "#0c1218"))) < 0.5


def fg_on_row(
    row_bg: str, preferred: str, fallback: str, dark: bool,
) -> str:
    """
    Väljer läsbar textfärg för en tabellrad.

    ``preferred`` (t.ex. accentfärg i första kolumnen) används bara
    om den håller minst 3:1 kontrast mot radbakgrunden — annars
    ``fallback``. ``dark`` behålls i signaturen för anropens skull.
    """
    if preferred and _contrast(row_bg, preferred) >= 3.0:
        return preferred
    return fallback


def ensure_row_height(table: QTableWidget, min_px: int = 40) -> None:
    """Ser till att ingen rad är lägre än ``min_px`` pixlar."""
    for row in range(table.rowCount()):
        if table.rowHeight(row) < min_px:
            table.setRowHeight(row, min_px)


class VisibleRowsDelegate(QStyledItemDelegate):
    """
    Målar tabellrader från ROLE_*-data på varje item:

    • jämn/udda radbakgrund (ROLE_ROW_BG / ROLE_ROW_BG_ODD)
    • textfärg (ROLE_ROW_FG), vit på markerad rad
    • färgrand i vänsterkanten på kolumn 0 (ROLE_STRIPE) —
      guld för favoriter, accentfärg annars
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = True
        self._select_bg = "#0b5cab"

    def set_theme(self, *, dark: bool, select_bg: str) -> None:
        self._dark = bool(dark)
        if select_bg:
            self._select_bg = select_bg

    def paint(self, painter, option, index) -> None:  # noqa: N802
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

        selected = bool(option.state & QStyle.State.State_Selected)
        row_bg = index.data(
            ROLE_ROW_BG_ODD if index.row() % 2 else ROLE_ROW_BG
        )
        stripe = index.data(ROLE_STRIPE) if index.column() == 0 else None

        painter.save()
        if selected:
            painter.fillRect(option.rect, QColor(self._select_bg))
        elif row_bg:
            painter.fillRect(option.rect, QColor(str(row_bg)))
        if stripe:
            r = option.rect
            painter.fillRect(r.x(), r.y(), 4, r.height(), QColor(str(stripe)))
        painter.restore()

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.backgroundBrush = QBrush(Qt.GlobalColor.transparent)
        fg = "#ffffff" if selected else index.data(ROLE_ROW_FG)
        if fg:
            opt.palette.setColor(
                QPalette.ColorRole.Text, QColor(str(fg))
            )
            opt.palette.setColor(
                QPalette.ColorRole.HighlightedText, QColor("#ffffff")
            )
        widget = option.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget
        )


def attach_visible_rows(table: QTableWidget) -> VisibleRowsDelegate:
    """
    Kopplar VisibleRowsDelegate till tabellen och returnerar den
    (så vyn kan anropa ``delegate.set_theme(...)`` vid temabyte).
    """
    delegate = VisibleRowsDelegate(table)
    table.setItemDelegate(delegate)
    return delegate


def make_btn(
    label: str,
    tooltip: str = "",
    accent: bool = False,
    danger: bool = False,
    success: bool = False,
    info: bool = False,
    width: int = 0,
) -> QPushButton:
    """
    Skapar en QPushButton med enhetlig stil.

    accent/danger/success/info sätter dynamic properties ("true")
    som stylesheet-teman kan känna av.
    """
    btn = QPushButton(label)
    btn.setToolTip(tooltip)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    btn.setMinimumHeight(32)
    btn.setFont(make_font(12, bold=True))
    btn.setSizePolicy(
        QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
    )
    if width:
        btn.setFixedWidth(width)
    if accent:
        btn.setProperty("accent", "true")
    if danger:
        btn.setProperty("danger", "true")
    if success:
        btn.setProperty("success", "true")
    if info:
        btn.setProperty("info", "true")
    return btn


class _NumericCell(QTableWidgetItem):
    """Tabellcell som sorteras NUMERISKT (svenskt beloppsformat)."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        a = _parse_amount_text(self.text())
        b = _parse_amount_text(other.text())
        if a == a and b == b:  # båda är tal (inte nan)
            return a < b
        return super().__lt__(other)


def make_cell(
    text: str,
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft,
    bold: bool = True,
    fg: str = "",
    numeric: bool = False,
) -> QTableWidgetItem:
    """
    Skapar en QTableWidgetItem med enhetlig stil.

    numeric=True → cellen sorteras numeriskt (för beloppskolumner).
    """
    if numeric:
        item = _NumericCell(str(text))
    else:
        item = QTableWidgetItem(str(text))
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    item.setTextAlignment(
        int(align) | int(Qt.AlignmentFlag.AlignVCenter)
    )
    item.setFont(make_font(12, bold=bold))
    if fg:
        item.setForeground(QBrush(QColor(fg)))
    return item


def make_line_edit(placeholder: str = "", height: int = 36) -> QLineEdit:
    """Skapar en QLineEdit med enhetlig stil."""
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setMinimumHeight(height)
    w.setFont(make_font(12))
    return w


def make_date_edit(
    today: bool = False, offset_days: int = 0
) -> QDateEdit:
    """
    Skapar ett datumfält med STOR kalender-popup (yyyy-MM-dd):
    måndag först, veckonummer, helger röda, idag markerat (date_picker).

    Standardvärde: idag (+ offset_days dagar om angivet).
    """
    try:
        from ui.date_picker import NiceDateEdit
    except ImportError:
        from date_picker import NiceDateEdit  # type: ignore[no-redef]
    w = NiceDateEdit()
    w.setMinimumHeight(36)
    w.setFont(make_font(12))
    d = QDate.currentDate()
    if offset_days:
        d = d.addDays(offset_days)
    w.setDate(d)
    return w


def make_spin(
    min_v: float = 0.0,
    max_v: float = 99_999_999.0,
    decs: int = 2,
) -> QDoubleSpinBox:
    """Skapar en QDoubleSpinBox med gruppseparator."""
    w = QDoubleSpinBox()
    w.setDecimals(decs)
    w.setMinimum(min_v)
    w.setMaximum(max_v)
    w.setGroupSeparatorShown(True)
    w.setMinimumHeight(36)
    w.setFont(make_font(12))
    return w


class AmountLineEdit(QLineEdit):
    """
    Bättre beloppfält — ersätter QDoubleSpinBox för belopp.

    Egenskaper
    ──────────
    • Helsvenskt format: mellanslag som tusentalsavgränsare och
      komma som decimaltecken ("45 546,00").
    • Skriv med punkt OCH kommas — båda fungerar.
    • HELMARKERAT tills du skriver något: vid fokus eller klick i
      fältet markeras hela beloppet, så det är bara att börja skriva.
      ("kr" ligger som etikett UTANFÖR fältet — kan aldrig markeras.)
    • Minustecken i fältet (t.ex. "-7853") känns av automatiskt:
      tecknet stripas och sign_requested(-1) skickas så att dialogen
      växlar till − (kreditfaktura). "+" växlar tillbaka till +.
    • Enter hoppar till nästa fält (dialogens tangentbordsnav).
    • Formatteras automatiskt när fokus lämnar fältet.
    • value()/setValue(float) → drop-in-API för dialogens kod.
    """

    #: Emitteras när användaren skriver ett tecken i fältet:
    #: -1 vid "-"/"−" (kredit), +1 vid "+".
    sign_requested = Signal(int)

    def __init__(
        self, placeholder: str = "0,00", parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        #: True = helmarkering behålls tills användaren skriver något.
        self._armed = True
        self.editingFinished.connect(self._format_on_finish)
        # Alla användarändringar (inkl. inklistring) avaktiverar
        # det armade läget + känns av inledande minustecken.
        self.textEdited.connect(self._on_edited)

    # ── Publik API (kompatibel med QDoubleSpinBox) ─────────────────

    def setValue(self, value: float) -> None:
        """Sätter beloppet formaterat ("45 546,00") och armarar om."""
        self.setText(format_amount_edit(value))
        self._armed = True

    def value(self) -> float:
        """Aktuellt belopp som float (alltid ≥ 0; 0 vid tom/ogiltig)."""
        return parse_amount_edit(self.text())

    def setSuffix(self, *_args: Any) -> None:
        """Kompatibilitets-no-op — enheten visas utanför fältet."""

    def setSpecialValueText(self, *_args: Any) -> None:
        """Kompatibilitets-no-op (tomt värde visas som tomt fält)."""

    def selectAllArm(self) -> None:
        """Markerar allt och återaktiverar det armade läget."""
        self._armed = True
        self.selectAll()

    # ── Markering: alltid helmarkerat tills man skriver något ───────

    def focusInEvent(self, event: Any) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._armed = True
        # singleShot: markera EFTER att Qt gjort sin fokus-hantering
        QTimer.singleShot(0, self.selectAll)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        # I armat läge: ett vänsterklick placerar INTE markören
        # (det skulle avmarkera) — behåll helmarkeringen.
        if self._armed and event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            self.selectAll()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802
        """
        Känner av inledande tecken:

        • "-" / "−" → sign_requested(-1) — tecknet skrivs INTE i
          fältet (beloppet är alltid positivt; ＋/− äger tecknet).
        • "+"       → sign_requested(+1).

        Övriga tangenter (siffror, backsteg, pilar …) går vidare som
        vanligt — första skrivna tecknet ersätter helmarkeringen.
        """
        t = event.text()
        if t in ("-", "−"):
            self.sign_requested.emit(-1)
            event.accept()
            return
        if t == "+":
            self.sign_requested.emit(+1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_edited(self, text: str) -> None:
        """
        Användaren skrev/klistrade: avaktivera helmarkeringen och
        hantera inledande minustecken (t.ex. klistrad "-7853").
        """
        self._armed = False
        if text[:1] in ("-", "−", "+"):
            sign = -1 if text[0] in ("-", "−") else 1
            self.sign_requested.emit(sign)
            self.setText(text.lstrip("+-−"))

    # ── Formattering ───────────────────────────────────────────────

    def _format_on_finish(self) -> None:
        """Formatterar om beloppet när fokus lämnar fältet/Enter."""
        v = self.value()
        if v > 0:
            self.setText(format_amount_edit(v))
        elif not self.text().strip():
            self.setText("")


def _btn_stylesheet(
    bg: str, hover: str, fg: str, accent: str, border: str
) -> str:
    """Genererar knapp-stylesheet."""
    return f"""
        QPushButton {{
            background-color : {bg};
            color            : {fg};
            font-weight      : 700;
            font-size        : 12px;
            border-radius    : 7px;
            border           : 1px solid {border};
            padding          : 7px 16px;
            min-height       : 38px;
        }}
        QPushButton:hover {{
            background-color : {hover};
            border-color     : {accent};
        }}
        QPushButton:pressed {{
            background-color : {accent};
            color            : #ffffff;
        }}
        QPushButton:disabled {{
            background-color : {border};
            color            : #666666;
            border-color     : {border};
        }}
    """


# ═════════════════════════════════════════════════════════════════════
#  EXPORT HISTORY MANAGER
# ═════════════════════════════════════════════════════════════════════


class ExportHistoryManager:
    """
    Sparar historik över alla exporter i JSON (atomisk skrivning).

    Stöder: spara, lista, hämta, ta bort (för återställning).
    Sparar även betalningsdatum per export (payment_date).
    """

    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / EXPORT_HISTORY_FILE
        self._data: list[dict] = []
        self._load()

    # ── Intern I/O ─────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                    self._data = raw if isinstance(raw, list) else []
        except Exception as exc:
            log.error("ExportHistory load-fel: %s", exc)
            self._data = []

    def _save(self) -> None:
        """Atomisk skrivning: .tmp → rename."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=4, ensure_ascii=False)
            tmp.replace(self._path)
        except Exception as exc:
            log.error("ExportHistory save-fel: %s", exc)

    # ── Publik API ─────────────────────────────────────────────────────

    def record_export(
        self,
        invoices: list[dict],
        file_path: str,
        total_inv: float,
        total_cred: float,
        att_betala: float,
        suppliers: list[str],
        payment_date: str = "",
    ) -> dict:
        """
        Spara en ny export i historiken.

        payment_date: betalningsdatum angivet vid exporten (YYYY-MM-DD).
        Nollställs automatiskt — frågas igen vid nästa export.
        """
        entry = {
            "export_date": datetime.datetime.now().isoformat(
                timespec="seconds"
            ),
            "file_path": str(file_path),
            "suppliers": list(suppliers),
            "payment_date": payment_date,   # betalningsdatum per export
            "invoice_count": sum(
                1
                for i in invoices
                if _to_float(i.get("total_amount")) >= 0
            ),
            "credit_count": sum(
                1
                for i in invoices
                if _to_float(i.get("total_amount")) < 0
            ),
            "total_count": len(invoices),
            "total_invoices": round(total_inv, 2),
            "total_credits": round(total_cred, 2),
            "att_betala": round(att_betala, 2),
            "invoices": [
                {
                    "id":             i.get("id", ""),
                    "invoice_number": i.get("invoice_number", ""),
                    "supplier":       i.get("supplier", ""),
                    "invoice_type":   i.get("invoice_type", "Faktura"),
                    "total_amount":   _to_float(i.get("total_amount")),
                    "date":           i.get("date", ""),
                    "due_date":       i.get("due_date", ""),
                    "payment_date":   i.get("payment_date", ""),
                    "status":         i.get("status", ""),
                }
                for i in invoices
            ],
        }
        self._data.append(entry)
        self._save()
        log.info(
            "Export registrerad: %d fakturor, att betala %s, "
            "betaldatum=%s, fil=%s",
            len(invoices),
            fmt_amount(att_betala),
            payment_date or "ej angivet",
            file_path,
        )
        return entry

    def all_exports(self) -> list[dict]:
        """Alla exporter, senaste först."""
        return list(reversed(self._data))

    def count(self) -> int:
        return len(self._data)

    def get_export(self, display_index: int) -> dict | None:
        """Hämta export via visningsindex (senaste = 0)."""
        try:
            return self.all_exports()[display_index]
        except IndexError:
            return None

    def remove_export(self, display_index: int) -> dict | None:
        """Tar bort en export baserat på visningsindex (senaste = 0)."""
        real_index = len(self._data) - 1 - display_index
        if 0 <= real_index < len(self._data):
            removed = self._data.pop(real_index)
            self._save()
            log.info(
                "Export borttagen: %s (%d fakturor, betaldatum=%s)",
                removed.get("export_date", "?"),
                removed.get("total_count", 0),
                removed.get("payment_date", "ej angivet"),
            )
            return removed
        return None

    def get_invoice_ids(self, display_index: int) -> list[str]:
        """Hämtar alla faktura-ID:n från en specifik export."""
        exp = self.get_export(display_index)
        if not exp:
            return []
        return [
            inv.get("id", "")
            for inv in exp.get("invoices", [])
            if inv.get("id")
        ]


# ═════════════════════════════════════════════════════════════════════
#  EXPORT HISTORY DIALOG
# ═════════════════════════════════════════════════════════════════════


class ExportHistoryDialog(QDialog):
    """
    Visar alla tidigare exporter i en tabell.

    • Dubbelklicka rad  → öppna PDF-filen.
    • ↩️ Återställ      → fakturorna tillbaka till Obetald, exporten tas bort.
    • 📂 Öppna exportmapp.
    • Mushjul-scroll i tabellen.
    • Komplett tema-anpassning (dark/light/auto/system).
    • Visar betalningsdatum per export.
    """

    export_restored = Signal(list)  # list[str] = invoice-ID:n

    #: Tabellkolumner inkl Betaldatum.
    _HIST_COLS: list[tuple[str, int]] = [
        ("Datum",          150),
        ("Betaldatum",     120),   # betalningsdatum per export
        ("Antal fakturor",  90),
        ("Antal krediter",  90),
        ("Fakturor (+)",   130),
        ("Krediter (−)",   130),
        ("Att betala",     135),
        ("Leverantörer",   190),
        ("Fil",            260),
    ]

    def __init__(
        self,
        parent: QWidget | None,
        history: ExportHistoryManager,
        theme: dict,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("📚  Exporthistorik")
        self.setMinimumSize(1060, 580)
        self.setSizeGripEnabled(True)
        self._history = history
        self._theme = theme

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(18, 14, 18, 14)

        # ── Header ────────────────────────────────────────────────────
        hdr = QLabel("📚  Exporthistorik – alla genomförda exporter")
        hdr.setFont(make_font(16, True))
        root.addWidget(hdr)

        self._info_lbl = QLabel(
            f"Totalt {history.count()} export(er). "
            f"Dubbelklicka för att öppna PDF-filen."
        )
        self._info_lbl.setFont(make_font(11))
        self._info_lbl.setStyleSheet("color:#888;background:transparent;")
        root.addWidget(self._info_lbl)
        root.addWidget(h_line())

        # ── Tabell ─────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(len(self._HIST_COLS))
        self._table.setHorizontalHeaderLabels(
            [c[0] for c in self._HIST_COLS]
        )
        self._table.setSortingEnabled(False)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setMinimumSectionSize(70)
        self._table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.itemSelectionChanged.connect(self._on_selection)

        for i, (_, w) in enumerate(self._HIST_COLS):
            self._table.setColumnWidth(i, w)

        # Mushjul-scroll direkt på tabellen
        self._table.wheelEvent = self._table_wheel  # type: ignore

        self._populate_table()
        root.addWidget(self._table, stretch=1)

        # ── Knappar ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._btn_restore = make_btn(
            "↩️  Återställ export",
            "Återställ fakturorna till Obetald och ta bort exporten.\n"
            "Du kan sedan lägga till fler fakturor och exportera igen.",
            danger=True,
        )
        self._btn_restore.clicked.connect(self._restore_export)
        self._btn_restore.setEnabled(False)

        self._btn_open = make_btn(
            "📂  Öppna exportmapp",
            "Öppna exports/-mappen i filhanteraren",
        )
        self._btn_open.clicked.connect(
            lambda: open_folder(get_export_base())
        )

        self._btn_close = make_btn("✖  Stäng")
        self._btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self._btn_restore)
        btn_row.addWidget(self._btn_open)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_close)
        root.addLayout(btn_row)

        # ── Footer ─────────────────────────────────────────────────────
        self._footer = QLabel(
            f"© {COPYRIGHT_YEAR} Rickard Längkvist"
            f" — FakturaRäknaren"
        )
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setFont(make_font(9))
        self._footer.setStyleSheet("color:#888;background:transparent;")
        root.addWidget(self._footer)

        # Applicera tema
        self._apply_dialog_theme()

    # ── Hjälpare ─────────────────────────────────────────────────────────

    def _table_wheel(self, event: QWheelEvent) -> None:
        """Mushjul-scroll i tabellen."""
        sb = self._table.verticalScrollBar()
        sb.setValue(sb.value() - (event.angleDelta().y() // 40))
        event.accept()

    def _is_dark(self) -> bool:
        bg = self._theme.get("bg", "#0d1117")
        return bg.lower() not in (
            "#ffffff", "#f5f7fa", "#f8f9fa", "#f6f8fa", "#eaeef2",
        )

    def _apply_dialog_theme(self) -> None:
        """Applicerar komplett tema på dialogen."""
        t = self._theme
        if not t:
            return
        dark = self._is_dark()

        bg         = t.get("bg",          "#0d1117" if dark else "#ffffff")
        text       = t.get("text_strong", "#f0f6fc" if dark else "#1c2128")
        muted      = t.get("text",        "#c9d1d9" if dark else "#24292f")
        border     = t.get("border",      "#30363d" if dark else "#d0d7de")
        header_bg  = t.get("header_bg",   "#1f6feb" if dark else "#0969da")
        row_normal = t.get("row_normal",  "#0d1117" if dark else "#ffffff")
        row_alt    = t.get("row_alt",     "#161b22" if dark else "#f6f8fa")
        accent     = t.get("accent",      "#58a6ff" if dark else "#0969da")
        scroll_h   = t.get(
            "scrollbar_handle", "#30363d" if dark else "#d0d7de"
        )
        error_c    = t.get("error",       "#f85149" if dark else "#cf222e")
        btn_bg     = t.get("button_bg",   "#21262d" if dark else "#6e7781")
        btn_hov    = t.get(
            "button_hover", "#30363d" if dark else "#57606a"
        )
        btn_text   = t.get(
            "button_text", "#f0f6fc" if dark else "#ffffff"
        )

        self.setStyleSheet(
            f"QDialog{{background-color:{bg};color:{text};}}"
            f"QLabel{{color:{text};background:transparent;}}"
        )

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color           : {row_normal};
                color                      : {text};
                font-weight                : 700;
                font-size                  : 12px;
                gridline-color             : {border};
                alternate-background-color : {row_alt};
                selection-background-color : {accent};
                selection-color            : #ffffff;
                border                     : 1px solid {border};
                border-radius              : 6px;
                outline                    : none;
            }}
            QHeaderView::section {{
                background-color : {header_bg};
                color            : #ffffff;
                font-weight      : 800;
                font-size        : 12px;
                padding          : 7px 8px;
                border           : none;
                border-right     : 1px solid {border};
                border-bottom    : 1px solid {border};
            }}
            QTableWidget::item {{ padding: 5px 8px; }}
            QTableWidget::item:selected {{
                background-color : {accent};
                color            : #ffffff;
            }}
            QScrollBar:vertical {{
                background    : {row_alt};
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
        """)

        self._btn_restore.setStyleSheet(
            _btn_stylesheet(
                error_c, "#da3633", "#ffffff", accent, border
            )
        )
        self._btn_open.setStyleSheet(
            _btn_stylesheet(btn_bg, btn_hov, btn_text, accent, border)
        )
        self._btn_close.setStyleSheet(
            _btn_stylesheet(btn_bg, btn_hov, btn_text, accent, border)
        )

        muted_ss = f"color:{muted};background:transparent;"
        self._info_lbl.setStyleSheet(muted_ss)
        self._footer.setStyleSheet(muted_ss)

    # ── Populate ─────────────────────────────────────────────────────────

    def _populate_table(self) -> None:
        """Fyller tabellen med alla exporter inkl betalningsdatum."""
        exports = self._history.all_exports()
        self._table.setRowCount(len(exports))

        for row, exp in enumerate(exports):
            sups = ", ".join(exp.get("suppliers", []))
            att = exp.get("att_betala", exp.get("netto", 0))
            payment_date = exp.get("payment_date", "") or "—"

            vals: list[tuple[str, Qt.AlignmentFlag, str, bool]] = [
                (exp.get("export_date", "")[:19],
                 Qt.AlignmentFlag.AlignCenter, "", False),
                (payment_date,
                 Qt.AlignmentFlag.AlignCenter,
                 "#4caf50" if payment_date != "—" else "#888888",
                 payment_date != "—"),
                (str(exp.get("invoice_count", 0)),
                 Qt.AlignmentFlag.AlignCenter, "", False),
                (str(exp.get("credit_count", 0)),
                 Qt.AlignmentFlag.AlignCenter, "", False),
                (fmt_amount(exp.get("total_invoices", 0), ""),
                 Qt.AlignmentFlag.AlignRight, "#4caf50", True),
                (fmt_amount(exp.get("total_credits", 0), ""),
                 Qt.AlignmentFlag.AlignRight, "#2196f3", True),
                (fmt_amount(att, ""),
                 Qt.AlignmentFlag.AlignRight,
                 "#f85149" if att < 0 else "#3fb950",
                 True),
                (sups[:55], Qt.AlignmentFlag.AlignLeft, "", False),
            ]

            for col, (text_v, align, fg, bold) in enumerate(vals):
                self._table.setItem(
                    row, col,
                    make_cell(text_v, align, bold=bold, fg=fg),
                )

            # Fil-kolumn (sista) — sökvägen sparas i UserRole
            fp = Path(exp.get("file_path", ""))
            item_file = make_cell(fp.name, Qt.AlignmentFlag.AlignLeft)
            item_file.setData(Qt.ItemDataRole.UserRole, str(fp))
            self._table.setItem(row, len(vals), item_file)

        self._table.resizeRowsToContents()

    # ── Slots ───────────────────────────────────────────────────────────

    def _on_selection(self) -> None:
        self._btn_restore.setEnabled(
            len(self._table.selectedItems()) > 0
        )

    def _on_double_click(self, index) -> None:
        """Dubbelklick → öppna PDF-filen."""
        row = index.row()
        item = self._table.item(row, len(self._HIST_COLS) - 1)
        if item:
            path = item.data(Qt.ItemDataRole.UserRole)
            if path:
                open_file(path)

    def _restore_export(self) -> None:
        """
        Återställ en export:
        1. Bekräfta med användaren
        2. Hämta faktura-ID:n
        3. Ta bort exporten från historiken
        4. Emit signal → InvoicesView sätter dem till Obetald
        """
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        row = rows[0].row()
        exp = self._history.get_export(row)
        if not exp:
            return

        att = exp.get("att_betala", exp.get("netto", 0))
        n = exp.get("total_count", 0)
        datum = exp.get("export_date", "?")[:19]
        payment_date = exp.get("payment_date", "") or "ej angivet"

        reply = QMessageBox.question(
            self,
            "↩️  Återställ export",
            f"Återställ exporten från {datum}?\n\n"
            f"  Antal fakturor:   {n}\n"
            f"  Att betala:       {fmt_amount(att)}\n"
            f"  Betalningsdatum:  {payment_date}\n\n"
            f"Alla {n} fakturor ändras tillbaka till 'Obetald'\n"
            f"så du kan lägga till fler och göra en ny export.\n\n"
            f"Exporten tas bort från historiken.\n"
            f"PDF-filen på disk påverkas inte.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        invoice_ids = self._history.get_invoice_ids(row)
        self._history.remove_export(row)
        if invoice_ids:
            self.export_restored.emit(invoice_ids)

        self._populate_table()
        self._info_lbl.setText(
            f"Totalt {self._history.count()} export(er). "
            f"Dubbelklicka för att öppna PDF-filen."
        )
        QMessageBox.information(
            self,
            "✅  Export återställd",
            f"{len(invoice_ids)} fakturor har återställts till "
            f"'Obetald'.\n\n"
            f"Du kan nu lägga till fler fakturor och\n"
            f"exportera på nytt.",
        )


# ═════════════════════════════════════════════════════════════════════
#  INVOICE DIALOG
# ═════════════════════════════════════════════════════════════════════


class SupplierDefaults:
    """
    SMART IFYLLNING — kommer ihåg senast använda OCR, referens och
    kategori per leverantör (sparas i supplier_defaults.json).

    När samma leverantör väljs igen förfylls fälten automatiskt,
    så att upprepade registreringar går på sekunder.
    """

    FILE: str = "supplier_defaults.json"

    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / self.FILE
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
        except Exception as exc:
            log.error("SupplierDefaults load-fel: %s", exc)

    def get(self, supplier: str) -> dict:
        d = self._data.get(str(supplier or "").strip().lower(), {})
        return d if isinstance(d, dict) else {}

    def remember(
        self, supplier: str, ocr: str, ref: str, category: str
    ) -> None:
        """Uppdaterar minnet för leverantören (tomma värden hoppas över)."""
        key = str(supplier or "").strip().lower()
        if not key:
            return
        entry = self._data.setdefault(key, {})
        changed = False
        for field, value in (
            ("ocr", ocr), ("ref", ref), ("category", category),
        ):
            value = str(value or "").strip()
            if value and entry.get(field) != value:
                entry[field] = value
                changed = True
        if changed:
            self._save()
            log.info("SMART_IFYLLNING: minne uppdaterat för '%s'", key)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except Exception as exc:
            log.error("SupplierDefaults save-fel: %s", exc)


class InvoiceDialog(QDialog):
    """
    Registrering / redigering av faktura eller kreditfaktura.

    Primärt  : fakturanummer + belopp (+/−).
    Sekundärt: betalningsdatum, OCR, kategori m.m.
    Leverantör förvald via persistent dropdown i InvoicesView.

    Belopp
    ──────
    ＋ = Faktura        (läggs till ATT BETALA)
    −  = Kreditfaktura  (dras av från ATT BETALA)
    Belopp anges i AmountLineEdit — ett textfält i svenskt format
    (mellanslag som tusentalsavgränsare, komma som decimaltecken).
    Fältet är ALLTID helmarkerat tills man skriver något: vid fokus
    eller klick markeras hela beloppet, så det är bara att börja
    skriva. Punkt och komma fungerar båda som decimaltecken.

    Förfallodatum (f_due_date)
    ──────────────────────────
    • Default: session_due_date från app_core (sätts EN gång per session
      i main.py via _set_session_due_date()).
    • Om session_due_date ej är satt → idag + 30 dagar.
    • Användaren kan ändra datumet per faktura i dialogen.

    Betalningsdatum (f_payment_date)
    ────────────────────────────────
    • PER FAKTURA — INTE relaterat till session_due_date.
    • Export-betalningsdatum frågas separat av
      ask_export_payment_date() och nollställs efter exporten.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        existing: dict | None = None,
        supplier_name: str = "",
        supplier_names: list[str] | None = None,
        default_currency: str = "SEK",
        app_core: Any = None,
    ) -> None:
        super().__init__(parent)
        self._existing = existing or {}
        self._supplier_name = supplier_name
        self._supplier_names = supplier_names or []
        self._default_currency = default_currency
        self._app_core = app_core
        self._is_edit = bool(existing)

        # SMART IFYLLNING: leverantörsminne + leverantörspost
        data_dir = None
        try:
            data_dir = Path(app_core.invoices_store._file.parent)
        except Exception:
            data_dir = None
        self._defaults = SupplierDefaults(data_dir) if data_dir else None
        self._supplier_rec: dict | None = None

        self.setWindowTitle(
            tr("invdialog.title_edit")
            if self._is_edit
            else tr("invdialog.title_new")
        )
        self.setMinimumWidth(580)
        self.setMinimumHeight(540)
        self.setSizeGripEnabled(True)

        self._build_dialog_ui()

        if self._is_edit:
            self._populate()
        else:
            # Ny faktura → session_due_date som default-förfallodatum
            self._apply_session_due_date()
            # SMART IFYLLNING: OCR/referens/kategori + förfallodatum
            # från leverantörens betalvillkor (om inget session-datum)
            self._apply_smart_defaults()

        self._refresh_supplier_info()
        self._on_sign_changed(self.f_sign.currentIndex())

    # ══════════════════════════════════════════════════════════════════
    #  SMART IFYLLNING
    # ══════════════════════════════════════════════════════════════════

    def _lookup_supplier(self, name: str) -> dict | None:
        """Hämtar leverantörsposten från app_core baserat på namn."""
        if self._app_core is None or not name:
            return None
        try:
            target = str(name).strip().lower()
            for sup in self._app_core.get_suppliers():
                if str(sup.get("name", "")).strip().lower() == target:
                    return sup
        except Exception as exc:
            log.debug("lookup_supplier: %s", exc)
        return None

    def _apply_smart_defaults(self) -> None:
        """
        Förfyller OCR / referens / kategori från leverantörsminnet och
        sätter förfallodatum = fakturadatum + betalvillkor (endast om
        inget session-förfallodatum redan har applicerats).
        """
        if self._is_edit or self._app_core is None:
            return
        sup = self._lookup_supplier(self._supplier_name)
        self._supplier_rec = sup
        if sup is None:
            return

        if self._defaults is not None:
            mem = self._defaults.get(self._supplier_name)
            if mem.get("ocr") and not self.f_ocr.text():
                self.f_ocr.setText(str(mem["ocr"]))
            if mem.get("ref") and not self.f_ref.text():
                self.f_ref.setText(str(mem["ref"]))
            if mem.get("category") and not self.f_category.text():
                self.f_category.setText(str(mem["category"]))

        # Förfallodatum från betalvillkor när session-datum saknas
        if not getattr(self._app_core, "has_session_due_date", False):
            try:
                terms = int(sup.get("payment_terms") or 30)
            except (TypeError, ValueError):
                terms = 30
            self.f_due_date.setDate(self.f_date.date().addDays(terms))
            log.info(
                "SMART IFYLLNING: förfallodatum = fakturadatum + "
                "%d dagar (betalvillkor)", terms,
            )

    def _refresh_supplier_info(self) -> None:
        """Visar org.nr / bankgiro / betalvillkor under leverantören."""
        lbl = getattr(self, "_lbl_sup_info", None)
        if lbl is None:
            return
        name = self._get_supplier()
        sup = self._lookup_supplier(name) if name else None
        self._supplier_rec = sup
        if not sup:
            lbl.setVisible(False)
            return
        parts: list[str] = []
        for lab, key in (
            (tr("invdialog.orgnr"), "org_number"),
            (tr("invdialog.bankgiro"), "bg"),
            (tr("invdialog.plusgiro"), "pg"), ("IBAN", "iban"),
        ):
            val = str(sup.get(key, "") or "").strip()
            if val:
                parts.append(f"{lab}: {val}")
        try:
            terms = int(sup.get("payment_terms") or 0)
        except (TypeError, ValueError):
            terms = 0
        if terms:
            parts.append(tr("invdialog.terms", n=terms))
        if parts:
            lbl.setText("  ·  ".join(parts))
            lbl.setVisible(True)
        else:
            lbl.setVisible(False)

    # ── Session-betalningsdatum ──────────────────────────────────────────

    def _apply_session_due_date(self) -> None:
        """
        Sätter f_due_date till session_due_date om det är satt.

        Regler:
        • session_due_date sätts EN gång per programstart (main.py).
        • Gäller alla nya fakturor under sessionen.
        • Användaren kan ändra per faktura i dialogen.
        • Datumet sparas INTE i JSON — nollställs vid omstart.
        • Om session_due_date ej är satt → idag + 30 dagar.
        """
        due_str = get_session_due_date_str(self._app_core)
        if due_str:
            qd = QDate.fromString(due_str, "yyyy-MM-dd")
            if qd.isValid():
                self.f_due_date.setDate(qd)
                log.debug(
                    "InvoiceDialog: session_due_date → f_due_date = %s",
                    due_str,
                )
                return
        # Fallback: idag + 30 dagar
        self.f_due_date.setDate(QDate.currentDate().addDays(30))

    # ── UI-byggnad ───────────────────────────────────────────────────────

    def _build_dialog_ui(self) -> None:
        """Bygger hela dialog-layouten."""
        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(22, 18, 22, 16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setSpacing(14)
        v.setContentsMargins(0, 0, 0, 0)

        # ── Leverantör ─────────────────────────────────────────────────
        sup_box = QGroupBox(tr("invdialog.supplier"))
        sup_box.setFont(make_font(11, True))
        sup_outer = QVBoxLayout(sup_box)
        sup_outer.setContentsMargins(12, 8, 12, 8)
        sup_outer.setSpacing(4)
        sup_layout = QHBoxLayout()
        sup_layout.setSpacing(10)
        sup_outer.addLayout(sup_layout)

        self._lbl_supplier = QLabel(
            self._supplier_name or tr("invdialog.none_chosen")
        )
        self._lbl_supplier.setFont(make_font(15, True))
        self._lbl_supplier.setStyleSheet(
            "color:#4299e1;background:transparent;"
        )
        sup_layout.addWidget(self._lbl_supplier)

        # SMART IFYLLNING: org.nr / bankgiro / betalvillkor under namnet
        self._lbl_sup_info = QLabel()
        self._lbl_sup_info.setFont(make_font(9))
        self._lbl_sup_info.setStyleSheet(
            "color:#8b949e;background:transparent;"
        )
        self._lbl_sup_info.setWordWrap(True)
        self._lbl_sup_info.setVisible(False)
        sup_outer.addWidget(self._lbl_sup_info)

        if self._is_edit:
            # Redigering: leverantören kan bytas via kombobox
            self._combo_supplier = QComboBox()
            self._combo_supplier.setEditable(True)
            self._combo_supplier.setMinimumHeight(36)
            self._combo_supplier.setFont(make_font(12))
            self._combo_supplier.addItems(self._supplier_names)
            self._combo_supplier.setCurrentText(
                self._existing.get("supplier", self._supplier_name)
            )
            completer = QCompleter(self._supplier_names, self)
            completer.setCaseSensitivity(
                Qt.CaseSensitivity.CaseInsensitive
            )
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self._combo_supplier.setCompleter(completer)
            self._combo_supplier.currentTextChanged.connect(
                lambda _t: self._refresh_supplier_info()
            )
            sup_layout.addWidget(self._combo_supplier, stretch=1)
            self._combo_supplier.currentTextChanged.connect(
                lambda *_: self._refresh_dup_warning()
            )
            self._lbl_supplier.setVisible(False)
        else:
            self._combo_supplier = None

        v.addWidget(sup_box)

        # ── Session-banner (nya fakturor) ──────────────────────────────
        due_str = get_session_due_date_str(self._app_core)
        if due_str and not self._is_edit:
            self._session_due_banner = QLabel(
                tr("invdialog.session_banner", date=due_str)
            )
            self._session_due_banner.setFont(make_font(10, True))
            self._session_due_banner.setStyleSheet(
                "background:#1565c0;color:#ffffff;"
                "border-radius:5px;padding:5px 10px;"
            )
            self._session_due_banner.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            v.addWidget(self._session_due_banner)
        else:
            self._session_due_banner = None

        # ── Primära fält ───────────────────────────────────────────────
        prim_box = QGroupBox(tr("invdialog.primary"))
        prim_box.setFont(make_font(11, True))
        pf = QFormLayout(prim_box)
        pf.setSpacing(12)
        pf.setContentsMargins(14, 10, 14, 10)
        pf.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        # Fakturanummer
        self.f_inv_nr = make_line_edit("ex. 2025-001 / INV-001")
        self.f_inv_nr.setFont(make_font(14, True))
        self.f_inv_nr.setMinimumHeight(44)
        pf.addRow(tr("invdialog.invoice_number"), self.f_inv_nr)

        # Teckenväljare ＋/−
        self.f_sign = QComboBox()
        self.f_sign.setMinimumHeight(44)
        self.f_sign.setFixedWidth(95)
        self.f_sign.setFont(make_font(20, True))
        self.f_sign.addItem("＋", +1)
        self.f_sign.addItem("−", -1)
        self.f_sign.setToolTip(tr("invdialog.sign_tip"))
        self.f_sign.currentIndexChanged.connect(self._on_sign_changed)

        # Belopp — AmountLineEdit: bättre textfält, svenskt format,
        # ALLTID helmarkerat tills man skriver något.
        self.f_total = AmountLineEdit(placeholder="0,00")
        self.f_total.setFont(make_font(14, True))
        self.f_total.setMinimumHeight(44)
        self.f_total.setToolTip(
            "Belopp i kronor.\n"
            "Fältet är helmarkerat — det är bara att skriva.\n\n"
            "KREDIT: tryck -  (ensam tangent) FÖRST, slå sen beloppet.\n"
            "Minustecknet hamnar aldrig i fältet — väljaren byter till −\n"
            "direkt.  + växlar tillbaka till faktura.\n\n"
            "Enter hoppar till nästa fält."
        )
        # "-7853" i fältet → automatiskt − (kredit); "+" → +
        self.f_total.sign_requested.connect(
            lambda s: self.f_sign.setCurrentIndex(0 if s > 0 else 1)
        )

        # "kr"-etikett efter beloppsfältet (suffix utanför texten)
        kr_label = QLabel("kr")
        kr_label.setFont(make_font(14, True))
        kr_label.setStyleSheet("background:transparent;")

        amount_widget = QWidget()
        amount_widget.setStyleSheet("background:transparent;")
        amount_layout = QHBoxLayout(amount_widget)
        amount_layout.setContentsMargins(0, 0, 0, 0)
        amount_layout.setSpacing(10)
        amount_layout.addWidget(self.f_sign)
        amount_layout.addWidget(self.f_total, stretch=1)
        amount_layout.addWidget(kr_label)
        pf.addRow(tr("invdialog.amount"), amount_widget)

        # Typ-indikator (FAKTURA / KREDITFAKTURA)
        self._lbl_type = QLabel()
        self._lbl_type.setFont(make_font(11, True))
        self._lbl_type.setStyleSheet("background:transparent;")
        pf.addRow("", self._lbl_type)

        v.addWidget(prim_box)

        # ── Sekundära fält ─────────────────────────────────────────────
        sec_box = QGroupBox(tr("invdialog.other"))
        sec_box.setFont(make_font(11))
        # EJ checkable: Qt inaktiverar annars alla fält i rutan när den
        # är okryssad (standard vid ny faktura). Fälten ska ALLTID vara
        # ifyllbara — "(valfritt)" i rubriken räcker som signal.
        sf = QFormLayout(sec_box)
        sf.setSpacing(10)
        sf.setContentsMargins(14, 10, 14, 10)
        sf.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.f_ocr = make_line_edit("OCR-nummer")
        self.f_ref = make_line_edit(tr("invdialog.ref_ph"))
        self.f_category = make_line_edit(tr("invdialog.category_ph"))
        self.f_date = make_date_edit(today=True)
        # Förfallodatum: default sätts av _apply_session_due_date()
        self.f_due_date = make_date_edit(offset_days=30)

        # Betalningsdatum PER FAKTURA (ej per export-batch).
        # Tomt värde visas som "(ej angivet)" via specialValueText.
        self.f_payment_date = make_date_edit()
        self.f_payment_date.setMinimumDate(EMPTY_DATE)
        self.f_payment_date.setDate(EMPTY_DATE)
        self.f_payment_date.setSpecialValueText(tr("invdialog.no_date"))

        self.f_currency = QComboBox()
        self.f_currency.setMinimumHeight(34)
        self.f_currency.setFont(make_font(12))
        self.f_currency.addItems(CURRENCIES)
        self.f_currency.setCurrentText(self._default_currency)

        self.f_status = QComboBox()
        self.f_status.setMinimumHeight(34)
        self.f_status.setFont(make_font(12))
        # Visning på aktuellt språk — kanonisk (svensk) status i data
        for _st in INVOICE_STATUSES:
            self.f_status.addItem(tr_status(_st), _st)

        self.f_note = QTextEdit()
        self.f_note.setPlaceholderText(tr("invdialog.note_ph"))
        self.f_note.setMaximumHeight(80)
        self.f_note.setFont(make_font(12))

        sf.addRow(tr("invdialog.ocr"), self.f_ocr)
        sf.addRow(tr("invdialog.reference"), self.f_ref)
        sf.addRow(tr("invdialog.category"), self.f_category)
        sf.addRow(h_line())
        sf.addRow(tr("invdialog.invoice_date"), self.f_date)
        sf.addRow(tr("invdialog.due_date"), self.f_due_date)
        sf.addRow(tr("invdialog.payment_date"), self.f_payment_date)
        sf.addRow(h_line())
        sf.addRow(tr("invdialog.currency"), self.f_currency)
        sf.addRow(tr("invdialog.status"), self.f_status)
        sf.addRow(h_line())
        sf.addRow(tr("invdialog.note"), self.f_note)

        v.addWidget(sec_box)
        v.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # ── OCR-varning ────────────────────────────────────────────────
        self._warn_ocr = QLabel(tr("invdialog.ocr_warning"))
        self._warn_ocr.setStyleSheet(
            "color:#ff9800;font-weight:700;background:transparent;"
        )
        self._warn_ocr.setVisible(False)
        root.addWidget(self._warn_ocr)

        self._warn_ocr_check = QLabel(tr("invdialog.ocr_check_warning"))
        self._warn_ocr_check.setStyleSheet(
            "color:#ff9800;font-weight:700;background:transparent;"
        )
        self._warn_ocr_check.setVisible(False)
        root.addWidget(self._warn_ocr_check)

        self._warn_dup = QLabel("")
        self._warn_dup.setStyleSheet(
            "color:#ff9800;font-weight:700;background:transparent;"
        )
        self._warn_dup.setVisible(False)
        root.addWidget(self._warn_dup)

        self.f_ocr.textChanged.connect(
            lambda *_: self._refresh_ocr_warnings()
        )
        self.f_inv_nr.textChanged.connect(
            lambda *_: self._refresh_dup_warning()
        )

        # ── Dialog-knappar ─────────────────────────────────────────────
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = bb.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText(
            tr("invdialog.save_changes")
            if self._is_edit
            else tr("invdialog.register")
        )
        save_btn.setMinimumHeight(44)
        save_btn.setFont(make_font(13, True))
        cancel_btn = bb.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText(f"✖  {tr('common.cancel')}")
        cancel_btn.setMinimumHeight(40)
        cancel_btn.setFont(make_font(12))
        bb.accepted.connect(self._validate_and_accept)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)

        # Tangentbordsnavigation: logisk Tab-ordning + Enter → nästa
        # fält. Enter i sista enradiga fältet = validera & spara.
        # (Anteckningsfältet är flerradigt: Enter där = ny rad.)
        install_keyboard_navigation(
            self,
            [
                self.f_inv_nr,
                self.f_sign,
                self.f_total,
                self.f_ocr,
                self.f_ref,
                self.f_category,
                self.f_date,
                self.f_due_date,
                self.f_payment_date,
                self.f_currency,
                self.f_status,
                self.f_note,
            ],
            on_last=self._validate_and_accept,
        )

    # ── Live-varningar: OCR-kontrollsiffra + dubblett ────────────────

    def _refresh_ocr_warnings(self) -> None:
        """Visar OCR-varningar medan man skriver (saknas/kontrollsiffra)."""
        text = self.f_ocr.text().strip()
        self._warn_ocr.setVisible(not text)
        self._warn_ocr_check.setVisible(
            ocr_luhn_status(text) == "bad_check"
        )

    def _refresh_dup_warning(self) -> None:
        """Varnar direkt om fakturanumret redan finns för leverantören."""
        lbl = getattr(self, "_warn_dup", None)
        if lbl is None:
            return
        nr = self.f_inv_nr.text().strip()
        try:
            supplier = self._get_supplier()
        except Exception:
            supplier = ""
        dup = None
        if nr and supplier and self._app_core is not None:
            try:
                dup = find_invoice_duplicate(
                    list(self._app_core.get_invoices()),
                    nr,
                    supplier,
                    exclude_id=str(self._existing.get("id", "")),
                )
            except Exception as exc:
                log.debug("_refresh_dup_warning: %s", exc)
        if dup:
            lbl.setText(
                tr("invdialog.dup_warning", nr=nr, supplier=supplier)
            )
            lbl.setVisible(True)
        else:
            lbl.setVisible(False)

    # ── Teckenindikator ──────────────────────────────────────────────────

    def _on_sign_changed(self, _: int = 0) -> None:
        """Uppdaterar typ-indikatorn (FAKTURA / KREDITFAKTURA)."""
        if self.f_sign.currentData() == -1:
            self._lbl_type.setText(tr("invdialog.type_credit"))
            self._lbl_type.setStyleSheet(
                "color:#2196f3;font-weight:700;background:transparent;"
            )
        else:
            self._lbl_type.setText(tr("invdialog.type_invoice"))
            self._lbl_type.setStyleSheet(
                "color:#4caf50;font-weight:700;background:transparent;"
            )

    # ── Populate (redigeringsläge) ───────────────────────────────────────

    def _populate(self) -> None:
        """Fyller formuläret med befintlig fakturadata."""
        d = self._existing

        self.f_inv_nr.setText(d.get("invoice_number", ""))
        self.f_ocr.setText(d.get("ocr", ""))
        self.f_ref.setText(d.get("reference", ""))
        self.f_category.setText(d.get("category", ""))

        for widget, key in [
            (self.f_date, "date"),
            (self.f_due_date, "due_date"),
        ]:
            raw = d.get(key, "")
            if raw:
                qd = QDate.fromString(raw, "yyyy-MM-dd")
                if qd.isValid():
                    widget.setDate(qd)

        pd_raw = d.get("payment_date", "")
        if pd_raw:
            qd = QDate.fromString(pd_raw, "yyyy-MM-dd")
            if qd.isValid():
                self.f_payment_date.setDate(qd)

        total = _to_float(d.get("total_amount"))
        if total < 0:
            self.f_sign.setCurrentIndex(1)
            self.f_total.setValue(abs(total))
        else:
            self.f_sign.setCurrentIndex(0)
            self.f_total.setValue(total)

        idx = self.f_currency.findText(
            d.get("currency", self._default_currency)
        )
        if idx >= 0:
            self.f_currency.setCurrentIndex(idx)

        idx = self.f_status.findData(d.get("status", "Obetald"))
        if idx >= 0:
            self.f_status.setCurrentIndex(idx)

        self.f_note.setPlainText(d.get("note", ""))

    # ── Validering ───────────────────────────────────────────────────────

    def _validate_and_accept(self) -> None:
        """Validerar obligatoriska fält innan dialogen accepteras."""
        supplier = self._get_supplier()
        if not supplier:
            QMessageBox.warning(self, "Validering", "Leverantör saknas.")
            return

        inv_nr = self.f_inv_nr.text().strip()
        if not inv_nr:
            QMessageBox.warning(
                self,
                "Validering",
                "Fakturanummer krävs.\n\nAnge ett unikt fakturanummer.",
            )
            self.f_inv_nr.setFocus()
            return

        if self.f_total.value() <= 0:
            QMessageBox.warning(
                self,
                tr("invdialog.validation"),
                tr("invdialog.amount_required"),
            )
            self.f_total.setFocus()
            return

        # OCR-kontrollsiffra (Luhn) – varna, men blockera inte helt
        ocr_text = self.f_ocr.text().strip()
        if ocr_luhn_status(ocr_text) == "bad_check":
            reply = QMessageBox.question(
                self,
                tr("invdialog.ocr_check_title"),
                tr("invdialog.ocr_check_body", ocr=ocr_text),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                self.f_ocr.setFocus()
                self.f_ocr.selectAll()
                return

        # Förfallodatum passerat + Obetald → erbjud statusändring
        if (
            self.f_due_date.date() < QDate.currentDate()
            and (self.f_status.currentData() or "Obetald") == "Obetald"
        ):
            reply = QMessageBox.question(
                self,
                tr("invdialog.overdue_title"),
                tr("invdialog.overdue_body"),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                idx = self.f_status.findData("Förfallen")
                if idx >= 0:
                    self.f_status.setCurrentIndex(idx)

        # SMART IFYLLNING: kom ihåg OCR/referens/kategori för
        # leverantören till nästa registrering.
        if self._defaults is not None:
            self._defaults.remember(
                self._get_supplier(),
                self.f_ocr.text(),
                self.f_ref.text(),
                self.f_category.text(),
            )

        self.accept()

    def _get_supplier(self) -> str:
        """Aktuell leverantör (kombobox vid redigering, annars förvald)."""
        if self._combo_supplier is not None:
            return self._combo_supplier.currentText().strip()
        return self._supplier_name.strip()

    # ── Resultat ─────────────────────────────────────────────────────────

    def get_data(self) -> dict:
        """
        Returnerar fakturadata som dict.

        Redo att skickas till app.add_invoice() / app.update_invoice().
        Ingen momsberäkning — belopp sparas exakt som användaren anger.
        """
        sign = self.f_sign.currentData()
        total = round(self.f_total.value() * sign, 2)

        pd = self.f_payment_date.date()
        payment_date = (
            pd.toString("yyyy-MM-dd")
            if pd.isValid() and pd.year() > 2000
            else ""
        )

        return {
            "invoice_type": "Kreditfaktura" if sign == -1 else "Faktura",
            "supplier": self._get_supplier(),
            "invoice_number": self.f_inv_nr.text().strip(),
            "ocr": self.f_ocr.text().strip(),
            "reference": self.f_ref.text().strip(),
            "category": self.f_category.text().strip(),
            "date": self.f_date.date().toString("yyyy-MM-dd"),
            "due_date": self.f_due_date.date().toString("yyyy-MM-dd"),
            "payment_date": payment_date,
            "total_amount": total,
            "vat_amount": 0.0,
            "amount_ex_vat": total,
            "vat_percent": 0,
            "currency": self.f_currency.currentText(),
            "status": self.f_status.currentData() or "Obetald",
            "note": self.f_note.toPlainText().strip(),
        }


def invoice_year(date_str) -> str:
    """
    Året ur ett datumfält ("2023-06-16" → "2023"); "" om det
    inte ser ut som ett rimligt datum. Året blir mappnamnet när
    en registrerad faktura sorteras i bevakade mappen
    (/pilkington/2023/…), så det måste vara ett äkta fyrsiffrigt
    år — aldrig en gissning.
    """
    import re as _re

    m = _re.match(r"^(?:19|20)\d{2}", str(date_str or "").strip())
    return str(date_str).strip()[:4] if m else ""


def sort_into_year_folder(
    attachment: str, watch_folder: str, year: str
) -> str:
    """
    Flyttar ett registrerat original in i årsmappen
    <bevakad mapp>/<år>/ och returnerar nya sökvägen.

    Bara filer DIREKT i den bevakade mappen flyttas (parkerade
    och allt annat lämnas orört — sorteringsvalet gäller bara
    registrerade fakturor). Redan sorterade filer (samma mål)
    returneras oförändrade. Funktionen kastar aldrig undantag
    och ger tillbaka den gamla sökvägen vid varje fel — precis
    som archive_original_file.
    """
    old = str(attachment or "")
    try:
        if not year:
            return old
        src = Path(old.strip())
        if not old.strip() or not src.is_file():
            return old
        root = Path(str(watch_folder or "").strip())
        if not root.is_dir():
            return old
        if src.resolve().parent != root.resolve():
            return old
        target_dir = root / str(year)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        if target.exists():
            if target.resolve() == src.resolve():
                return str(src)
            stem, suffix = src.stem, src.suffix
            n = 2
            while target.exists():
                target = target_dir / f"{stem}_{n}{suffix}"
                n += 1
        shutil.move(str(src), str(target))
        return str(target)
    except Exception:
        return old
