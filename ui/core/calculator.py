from __future__ import annotations

"""
FakturaRäknaren — Calculator / Business Logic
===================================================
Fil    : FakturaRäknaren_/ui/core/calculator.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Ren Python-motor för beräkning, filtrering, validering och rapporter.
Inga UI-beroenden — säker att importera från vilken modul/plugin som helst.

VIKTIG PRINCIP
--------------
• Användaren anger pris INKLUSIVE moms som standard.
• Moms bryts ut ur totalbelopp via split_vat().
• Ex moms-belopp härleds från total + momssats.
• Negativa belopp tillåts (kreditfakturor).
• invoice_type stöds: "Faktura" / "Kredit" / "Kreditfaktura".
• Momsvalidering borttagen — moms är inte obligatoriskt i
  registreringsflödet (KNOWN_VAT_RATES behålls endast för rapporter).
• "Arkiverad" är en giltig status (fakturor arkiveras efter export).
• payment_date är sökbart.
• Senast ändrad/tillagd post sorteras ALLTID SIST (längst bak) (MUST-023).

Samarbetar med
--------------
• app.py               – InvoiceEngine, dashboard_data
• invoices_view.py     – beloppsberäkning i dialog
• invoices_helpers.py  – filterpipeline, dialog
• pdf_export.py        – summering i PDF-export
• search.py            – sökmotor (light-version finns även här)
• storage.py           – samma datastruktur

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
import platform
import re
from typing import Any

log = logging.getLogger("FakturaCalc")

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

COPYRIGHT_YEAR: int = datetime.date.today().year

DATE_FMT: str = "%Y-%m-%d"

#: "Arkiverad" MÅSTE finnas — fakturor arkiveras efter PDF-export.
VALID_STATUSES: frozenset[str] = frozenset({
    "Obetald",
    "Planerad",
    "Betalfil skapad",
    "Betald",
    "Förfallen",
    "Makulerad",
    "Arkiverad",
})

VALID_INVOICE_TYPES: frozenset[str] = frozenset({
    "Faktura",
    "Kredit",
    "Kreditfaktura",
})

#: Enbart för referens/rapporter — valideras inte längre.
KNOWN_VAT_RATES: tuple[int, ...] = (0, 6, 12, 25)

#: Standard: inmatat pris = inklusive moms.
DEFAULT_PRICE_IS_INCLUSIVE: bool = True

#: Statusar som INTE räknas som obetalda/förfallna.
NON_UNPAID_STATUSES: frozenset[str] = frozenset({
    "Betald", "Makulerad", "Arkiverad",
})

# ═════════════════════════════════════════════════════════════════════
#  PLATTFORM
# ═════════════════════════════════════════════════════════════════════


def get_platform() -> str:
    """Returnerar normaliserat OS: windows / linux / macos."""
    p = platform.system().lower()
    if p == "darwin":
        return "macos"
    if p == "windows":
        return "windows"
    return "linux"


# ═════════════════════════════════════════════════════════════════════
#  INTERNA HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def _parse_date(value: Any) -> datetime.date | None:
    """Parsar YYYY-MM-DD, datetime eller date. None vid fel."""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return datetime.datetime.strptime(value, DATE_FMT).date()
        except ValueError:
            return None
    return None


def _to_float(value: Any, default: float = 0.0) -> float:
    """Säker float-konvertering."""
    try:
        if value is None or value == "" or value is False:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _today() -> datetime.date:
    return datetime.date.today()


def _is_unpaid_status(inv: dict) -> bool:
    """True om fakturan inte är Betald/Makulerad/Arkiverad."""
    return inv.get("status") not in NON_UNPAID_STATUSES


def is_credit(inv: dict) -> bool:
    """
    Avgör om en faktura är en kreditfaktura.

    Matchar: invoice_type in (kredit, kreditfaktura) ELLER
    total_amount < 0.
    """
    itype = str(inv.get("invoice_type", "")).strip().lower()
    if itype in ("kredit", "kreditfaktura"):
        return True
    return _to_float(inv.get("total_amount", 0)) < 0


# ═════════════════════════════════════════════════════════════════════
#  SORTERING — SENAST ÄNDRAD SIST  (MUST-023, synk med search/storage)
# ═════════════════════════════════════════════════════════════════════


def _timestamp_sort_key(inv: dict) -> str:
    """
    Sorteringsnyckel: updated_at → created_at → "".

    • Primärt        : updated_at (senast ändrad)
    • Fallback       : created_at (skapad)
    • Sista fallback : "" (sorteras först = äldst)

    Används för att alltid sortera senast ändrad/tillagd post SIST.
    """
    ts = str(inv.get("updated_at", "")).strip()
    if not ts:
        ts = str(inv.get("created_at", "")).strip()
    return ts


def _sort_newest_last(
    invoices: list[dict], limit: int = 0
) -> list[dict]:
    """
    Sorterar fakturor med senast ändrad SIST (längst bak).

    Äldst → nyast (stigande ordning på updated_at/created_at).
    limit > 0 → returnerar bara de N senaste (fortfarande sorterade
    äldst → nyast så att sista posten är nyast).
    """
    sorted_list = sorted(invoices, key=_timestamp_sort_key)
    if limit > 0:
        return sorted_list[-limit:]
    return sorted_list


def _sort_newest_first(
    invoices: list[dict], limit: int = 0
) -> list[dict]:
    """
    Sorterar fakturor med senast ändrad FÖRST (omvänd ordning).

    Används för recent_invoices i dashboard (senaste överst).
    Den primära "senast sist"-sorteringen görs via _sort_newest_last().
    """
    sorted_list = sorted(
        invoices, key=_timestamp_sort_key, reverse=True
    )
    if limit > 0:
        return sorted_list[:limit]
    return sorted_list


def _typed_sort_value(value: Any) -> tuple[int, float, int, str]:
    """
    Typsäker sorteringsnyckel: tal → datum → text.

    Förhindrar TypeError vid blandade typer i samma kolumn.
    """
    try:
        return (0, float(value), 0, "")
    except (TypeError, ValueError):
        pass
    parsed = _parse_date(value)
    if parsed is not None:
        return (1, 0.0, parsed.toordinal(), "")
    return (2, 0.0, 0, str(value or "").lower())


# ═════════════════════════════════════════════════════════════════════
#  BELOPPSNORMALISERING
# ═════════════════════════════════════════════════════════════════════


def _resolve_invoice_amounts(inv: dict) -> dict[str, float]:
    """
    Normaliserar en faktura-dict till kanoniska beloppsfält:

        amount_ex_vat, vat_percent, vat_amount, total_amount

    Regler
    ──────
    1. Finns total_amount (eller legacy 'amount') → betraktas som
       inkl moms.
    2. Finns endast amount_ex_vat → härled total + moms (bakåtkompat).
    3. Negativa belopp tillåts (krediter).
    4. vat_percent är 0 om det saknas.
    """
    vat_pct = _to_float(inv.get("vat_percent", 0), 0.0)
    total_raw = inv.get("total_amount", inv.get("amount", None))
    total_amount = _to_float(total_raw, 0.0)
    amount_ex = _to_float(inv.get("amount_ex_vat", 0), 0.0)
    vat_amount = _to_float(inv.get("vat_amount", 0), 0.0)

    # ── Fall 1: total finns (normalflöde) ──────────────────────────────
    if total_amount != 0:
        if vat_pct != 0:
            derived_ex, derived_vat = split_vat(total_amount, vat_pct)
        else:
            derived_ex = total_amount
            derived_vat = 0.0
        if amount_ex != 0:
            derived_ex = round(amount_ex, 2)
            derived_vat = (
                round(vat_amount, 2)
                if vat_amount != 0
                else round(total_amount - derived_ex, 2)
            )
        return {
            "amount_ex_vat": round(derived_ex, 2),
            "vat_percent":   round(vat_pct, 2),
            "vat_amount":    round(derived_vat, 2),
            "total_amount":  round(total_amount, 2),
        }

    # ── Fall 2: endast amount_ex_vat → bakåtkompatibilitet ────────────
    if amount_ex != 0:
        if vat_pct != 0:
            vat_amount = calculate_vat(
                abs(amount_ex), vat_pct, price_is_inclusive=False
            )
            if amount_ex < 0:
                vat_amount = -vat_amount
            total_amount = round(amount_ex + vat_amount, 2)
        else:
            vat_amount = 0.0
            total_amount = amount_ex
        return {
            "amount_ex_vat": round(amount_ex, 2),
            "vat_percent":   round(vat_pct, 2),
            "vat_amount":    round(vat_amount, 2),
            "total_amount":  round(total_amount, 2),
        }

    # ── Fall 3: tomt ───────────────────────────────────────────────────
    return {
        "amount_ex_vat": 0.0,
        "vat_percent":   round(vat_pct, 2),
        "vat_amount":    0.0,
        "total_amount":  0.0,
    }


def _amount(inv: dict, key: str = "total_amount") -> float:
    """Hämtar ett normaliserat beloppsfält från en faktura."""
    resolved = _resolve_invoice_amounts(inv)
    return _to_float(resolved.get(key, 0.0), 0.0)


# ═════════════════════════════════════════════════════════════════════
#  MOMSBERÄKNINGAR
# ═════════════════════════════════════════════════════════════════════


def calculate_vat(
    amount: float,
    vat_percent: float,
    price_is_inclusive: bool = DEFAULT_PRICE_IS_INCLUSIVE,
) -> float:
    """
    Beräknar momsbeloppet.

    amount             : absolutbelopp (≥ 0)
    vat_percent        : momssats (≥ 0)
    price_is_inclusive : True → amount är inkl moms (standard)

    Exempel
    ───────
    >>> calculate_vat(1250, 25)         # inkl → 250.0
    250.0
    >>> calculate_vat(1000, 25, False)  # exkl → 250.0
    250.0
    """
    if amount < 0 or vat_percent < 0:
        raise ValueError("amount and vat_percent must be ≥ 0")
    if vat_percent == 0:
        return 0.0
    if price_is_inclusive:
        return round(
            amount * vat_percent / (100.0 + vat_percent), 2
        )
    return round(amount * (vat_percent / 100.0), 2)


def total_with_vat(
    amount: float,
    vat_percent: float,
    price_is_inclusive: bool = DEFAULT_PRICE_IS_INCLUSIVE,
) -> float:
    """
    Returnerar total inklusive moms.
    Är amount redan inkl → returneras som den är.
    Är amount exkl → moms adderas.
    """
    if amount < 0 or vat_percent < 0:
        raise ValueError("amount and vat_percent must be ≥ 0")
    if price_is_inclusive:
        return round(amount, 2)
    return round(
        amount + calculate_vat(amount, vat_percent, False), 2
    )


def split_vat(
    total_incl: float, vat_percent: float
) -> tuple[float, float]:
    """
    Delar ett inkl-moms-belopp i (ex_vat, vat_amount).

    Stöder negativa belopp (krediter):
        split_vat(-500, 25) → (-400.0, -100.0)
    """
    if vat_percent < 0:
        raise ValueError("vat_percent must be ≥ 0")
    if vat_percent == 0:
        return round(total_incl, 2), 0.0

    sign = -1.0 if total_incl < 0 else 1.0
    abs_total = abs(total_incl)
    divisor = 1.0 + vat_percent / 100.0
    abs_ex = round(abs_total / divisor, 2)
    abs_vat = round(abs_total - abs_ex, 2)
    return round(sign * abs_ex, 2), round(sign * abs_vat, 2)


def compute_invoice_amounts(
    amount: float,
    vat_percent: float,
    price_is_inclusive: bool = DEFAULT_PRICE_IS_INCLUSIVE,
) -> dict[str, float]:
    """
    Normaliserar ett belopp + momssats till alla fyra kanoniska fält.
    Stöder negativa belopp (krediter).
    Standard: amount = total inkl moms.
    """
    if price_is_inclusive:
        total_amount = round(amount, 2)
        amount_ex, vat_amt = split_vat(total_amount, vat_percent)
    else:
        amount_ex = round(amount, 2)
        abs_vat = calculate_vat(
            abs(amount_ex), vat_percent, False
        )
        vat_amt = round(
            abs_vat if amount_ex >= 0 else -abs_vat, 2
        )
        total_amount = round(amount_ex + vat_amt, 2)

    return {
        "amount_ex_vat": round(amount_ex, 2),
        "vat_percent":   round(vat_percent, 2),
        "vat_amount":    round(vat_amt, 2),
        "total_amount":  round(total_amount, 2),
    }


def normalize_invoice_amounts(inv: dict) -> dict[str, Any]:
    """Returnerar en kopia av fakturan med normaliserade beloppsfält."""
    copy = dict(inv)
    copy.update(_resolve_invoice_amounts(inv))
    return copy


# ═════════════════════════════════════════════════════════════════════
#  GRUNDSUMMOR
# ═════════════════════════════════════════════════════════════════════


def total_invoices(invoices: list[dict]) -> float:
    """Summa total_amount (inkl moms) över alla fakturor."""
    return round(
        sum(_amount(inv, "total_amount") for inv in invoices), 2
    )


def total_by_status(invoices: list[dict], status: str) -> float:
    """Summa total_amount för en specifik status."""
    return round(
        sum(
            _amount(inv, "total_amount")
            for inv in invoices
            if inv.get("status") == status
        ),
        2,
    )


def total_vat(invoices: list[dict]) -> float:
    """Summa moms över alla fakturor."""
    return round(
        sum(_amount(inv, "vat_amount") for inv in invoices), 2
    )


def total_ex_vat(invoices: list[dict]) -> float:
    """Summa ex moms över alla fakturor."""
    return round(
        sum(_amount(inv, "amount_ex_vat") for inv in invoices), 2
    )


def total_unpaid(invoices: list[dict]) -> float:
    """
    Summa obetalda fakturor.
    Exkluderar: Betald, Makulerad, Arkiverad.
    """
    return round(
        sum(
            _amount(inv, "total_amount")
            for inv in invoices
            if _is_unpaid_status(inv)
        ),
        2,
    )


def total_overdue(invoices: list[dict]) -> float:
    """Summa förfallna fakturor."""
    return round(
        sum(
            _amount(inv, "total_amount")
            for inv in overdue_invoices(invoices)
        ),
        2,
    )


def total_credits(invoices: list[dict]) -> float:
    """Summa av alla kreditfakturor (negativa belopp)."""
    return round(
        sum(
            _amount(inv, "total_amount")
            for inv in invoices
            if is_credit(inv)
        ),
        2,
    )


def total_regular(invoices: list[dict]) -> float:
    """Summa av alla vanliga (icke-kredit) fakturor."""
    return round(
        sum(
            _amount(inv, "total_amount")
            for inv in invoices
            if not is_credit(inv)
        ),
        2,
    )


def net_total(invoices: list[dict]) -> float:
    """Fakturor + krediter = netto (ATT BETALA)."""
    return round(
        total_regular(invoices) + total_credits(invoices), 2
    )


def count_by_status(invoices: list[dict]) -> dict[str, int]:
    """Antal fakturor grupperade på status."""
    result: dict[str, int] = {}
    for inv in invoices:
        status = inv.get("status", "Okänd")
        result[status] = result.get(status, 0) + 1
    return result


def count_by_type(invoices: list[dict]) -> dict[str, int]:
    """Antal fakturor grupperade på invoice_type."""
    result: dict[str, int] = {}
    for inv in invoices:
        itype = (
            str(inv.get("invoice_type", "Faktura")).strip()
            or "Faktura"
        )
        result[itype] = result.get(itype, 0) + 1
    return result


# ═════════════════════════════════════════════════════════════════════
#  FILTERHJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def filter_by_status(
    invoices: list[dict], status: str
) -> list[dict]:
    return [inv for inv in invoices if inv.get("status") == status]


def filter_by_supplier(
    invoices: list[dict], supplier: str
) -> list[dict]:
    s = supplier.lower().strip()
    return [
        inv for inv in invoices
        if str(inv.get("supplier", "")).lower().strip() == s
    ]


def filter_by_type(
    invoices: list[dict], invoice_type: str
) -> list[dict]:
    """Filtrerar på invoice_type (case-insensitive)."""
    t = invoice_type.lower().strip()
    return [
        inv for inv in invoices
        if str(inv.get("invoice_type", "Faktura")).lower().strip() == t
    ]


def filter_by_due_date(
    invoices: list[dict],
    before_date: str | datetime.date,
) -> list[dict]:
    """Fakturor med förfallodatum ≤ before_date."""
    limit = _parse_date(before_date)
    if limit is None:
        log.warning(
            "filter_by_due_date: ogiltigt datum '%s' — returnerar alla",
            before_date,
        )
        return list(invoices)
    result = []
    for inv in invoices:
        due = _parse_date(inv.get("due_date"))
        if due and due <= limit:
            result.append(inv)
    return result


def filter_by_date_range(
    invoices: list[dict],
    start_date: str | datetime.date,
    end_date: str | datetime.date,
    date_key: str = "date",
) -> list[dict]:
    """Fakturor inom datumintervall (båda gränser inklusive)."""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    if start is None or end is None:
        return list(invoices)
    result = []
    for inv in invoices:
        d = _parse_date(inv.get(date_key))
        if d and start <= d <= end:
            result.append(inv)
    return result


def filter_by_category(
    invoices: list[dict], category: str
) -> list[dict]:
    c = category.lower().strip()
    return [
        inv for inv in invoices
        if str(inv.get("category", "")).lower().strip() == c
    ]


def filter_by_amount_range(
    invoices: list[dict],
    min_amount: float = float("-inf"),
    max_amount: float = float("inf"),
) -> list[dict]:
    """Filtrerar på total_amount (stöder negativa krediter)."""
    return [
        inv for inv in invoices
        if min_amount <= _amount(inv, "total_amount") <= max_amount
    ]


def overdue_invoices(invoices: list[dict]) -> list[dict]:
    """
    Fakturor med passerat förfallodatum som inte är
    Betald, Makulerad eller Arkiverad.
    Sorterade: senast ändrad längst bak.
    """
    today = _today()
    result = []
    for inv in invoices:
        if not _is_unpaid_status(inv):
            continue
        due = _parse_date(inv.get("due_date"))
        if due and due < today:
            result.append(inv)
    return _sort_newest_last(result)


def due_today(invoices: list[dict]) -> list[dict]:
    """Fakturor som förfaller idag. Senast ändrad längst bak."""
    today = _today()
    result = []
    for inv in invoices:
        if not _is_unpaid_status(inv):
            continue
        due = _parse_date(inv.get("due_date"))
        if due == today:
            result.append(inv)
    return _sort_newest_last(result)


def due_within_days(
    invoices: list[dict], days: int
) -> list[dict]:
    """Fakturor som förfaller inom N dagar. Senast ändrad längst bak."""
    today = _today()
    end = today + datetime.timedelta(days=days)
    result = []
    for inv in invoices:
        if not _is_unpaid_status(inv):
            continue
        due = _parse_date(inv.get("due_date"))
        if due and today <= due <= end:
            result.append(inv)
    return _sort_newest_last(result)


def due_this_week(invoices: list[dict]) -> list[dict]:
    """Fakturor som förfaller inom 7 dagar."""
    return due_within_days(invoices, 7)


def due_this_month(invoices: list[dict]) -> list[dict]:
    """Fakturor som förfaller denna månad. Senast ändrad längst bak."""
    today = _today()
    if today.month == 12:
        month_end = today.replace(
            year=today.year + 1, month=1, day=1
        )
    else:
        month_end = today.replace(month=today.month + 1, day=1)
    result = []
    for inv in invoices:
        if not _is_unpaid_status(inv):
            continue
        due = _parse_date(inv.get("due_date"))
        if due and today <= due < month_end:
            result.append(inv)
    return _sort_newest_last(result)


# ═════════════════════════════════════════════════════════════════════
#  SORTERING
# ═════════════════════════════════════════════════════════════════════


def sort_invoices(
    invoices: list[dict],
    key: str,
    reverse: bool = False,
) -> list[dict]:
    """
    Sorterar fakturor säkert på str / float / datum-fält.

    Blandade typer (tal + text) kraschar inte.
    Sekundär nyckel: updated_at (stigande) → senast ändrad post
    hamnar längst bak vid lika värden.
    """
    amount_keys = {"total_amount", "amount_ex_vat", "vat_amount"}

    def _sort_key(inv: dict) -> tuple:
        if key in amount_keys:
            primary: tuple[int, float, int, str] = (
                0, _amount(inv, key), 0, ""
            )
        else:
            primary = _typed_sort_value(inv.get(key, ""))
        return (primary, _timestamp_sort_key(inv))

    return sorted(invoices, key=_sort_key, reverse=reverse)


# ═════════════════════════════════════════════════════════════════════
#  GRUPPERING / SAMMANSTÄLLNINGAR
# ═════════════════════════════════════════════════════════════════════


def group_by(
    invoices: list[dict], key: str
) -> dict[str, list[dict]]:
    """
    Grupperar fakturor efter valfritt fält.
    Inom varje grupp: senast ändrad längst bak.
    """
    result: dict[str, list[dict]] = {}
    for inv in invoices:
        group = str(inv.get(key, "Okänd"))
        result.setdefault(group, []).append(inv)
    for group_key in result:
        result[group_key] = _sort_newest_last(result[group_key])
    return result


def summary_by_supplier(
    invoices: list[dict],
) -> dict[str, dict]:
    """Sammanställning per leverantör (inkl krediter och netto)."""
    result: dict[str, dict] = {}
    for inv in invoices:
        supplier = (
            str(inv.get("supplier", "Okänd")).strip() or "Okänd"
        )
        if supplier not in result:
            result[supplier] = {
                "count":        0,
                "total_amount": 0.0,
                "total_vat":    0.0,
                "total_ex_vat": 0.0,
                "unpaid":       0.0,
                "credits":      0.0,
                "net":          0.0,
            }
        row = result[supplier]
        amt = _amount(inv, "total_amount")
        row["count"] += 1
        row["total_amount"] = round(row["total_amount"] + amt, 2)
        row["total_vat"] = round(
            row["total_vat"] + _amount(inv, "vat_amount"), 2
        )
        row["total_ex_vat"] = round(
            row["total_ex_vat"] + _amount(inv, "amount_ex_vat"), 2
        )
        if _is_unpaid_status(inv):
            row["unpaid"] = round(row["unpaid"] + amt, 2)
        if is_credit(inv):
            row["credits"] = round(row["credits"] + amt, 2)
        row["net"] = round(row["total_amount"], 2)
    return result


def summary_by_month(
    invoices: list[dict],
) -> dict[str, dict]:
    """Sammanställning per månad (YYYY-MM), sorterad på period."""
    result: dict[str, dict] = {}
    for inv in invoices:
        month = str(inv.get("date", ""))[:7]
        if not month or len(month) < 7:
            month = "Okänd"
        if month not in result:
            result[month] = {
                "count":        0,
                "total_amount": 0.0,
                "total_vat":    0.0,
                "total_ex_vat": 0.0,
                "credits":      0.0,
                "net":          0.0,
            }
        row = result[month]
        amt = _amount(inv, "total_amount")
        row["count"] += 1
        row["total_amount"] = round(row["total_amount"] + amt, 2)
        row["total_vat"] = round(
            row["total_vat"] + _amount(inv, "vat_amount"), 2
        )
        row["total_ex_vat"] = round(
            row["total_ex_vat"] + _amount(inv, "amount_ex_vat"), 2
        )
        if is_credit(inv):
            row["credits"] = round(row["credits"] + amt, 2)
        row["net"] = round(row["total_amount"], 2)
    return dict(sorted(result.items()))


def summary_by_category(
    invoices: list[dict],
) -> dict[str, dict]:
    """Sammanställning per kategori."""
    result: dict[str, dict] = {}
    for inv in invoices:
        category = (
            str(inv.get("category", "")).strip() or "Okategoriserad"
        )
        if category not in result:
            result[category] = {
                "count":        0,
                "total_amount": 0.0,
                "total_vat":    0.0,
                "total_ex_vat": 0.0,
            }
        row = result[category]
        row["count"] += 1
        row["total_amount"] = round(
            row["total_amount"] + _amount(inv, "total_amount"), 2
        )
        row["total_vat"] = round(
            row["total_vat"] + _amount(inv, "vat_amount"), 2
        )
        row["total_ex_vat"] = round(
            row["total_ex_vat"] + _amount(inv, "amount_ex_vat"), 2
        )
    return result


# ═════════════════════════════════════════════════════════════════════
#  DASHBOARD-NYCKELTAL
# ═════════════════════════════════════════════════════════════════════


def dashboard_summary(invoices: list[dict]) -> dict[str, Any]:
    """
    Komplett dashboard-sammanställning (används av app.py →
    dashboard_data()). Inkluderar ATT BETALA (net_total) för
    fakturor + krediter. Arkiverade räknas inte som obetalda.

    Sortering: alla listor med senast ändrad längst bak.
    """
    overdue = overdue_invoices(invoices)
    paid = filter_by_status(invoices, "Betald")
    recent = _sort_newest_last(invoices, limit=10)

    return {
        # ── Summor ─────────────────────────────────────────────────────
        "total":          total_invoices(invoices),
        "total_ex_vat":   total_ex_vat(invoices),
        "total_vat":      total_vat(invoices),
        "total_regular":  total_regular(invoices),
        "total_credits":  total_credits(invoices),
        "net_total":      net_total(invoices),
        "unpaid":         total_unpaid(invoices),
        "paid":           total_invoices(paid),
        "overdue_total":  total_invoices(overdue),
        "planned":        total_by_status(invoices, "Planerad"),
        # ── Antal ──────────────────────────────────────────────────────
        "count":          len(invoices),
        "count_unpaid":   sum(
            1 for inv in invoices if _is_unpaid_status(inv)
        ),
        "count_overdue":  len(overdue),
        "count_paid":     len(paid),
        "count_by_status": count_by_status(invoices),
        "count_by_type":  count_by_type(invoices),
        # ── Listor (senast ändrad SIST) ────────────────────────────────
        "due_today":       due_today(invoices),
        "due_this_week":   due_this_week(invoices),
        "due_this_month":  due_this_month(invoices),
        "overdue_invoices": overdue,
        "recent_invoices": recent,
        # ── Sammanställningar ──────────────────────────────────────────
        "by_supplier":  summary_by_supplier(invoices),
        "by_month":     summary_by_month(invoices),
        "by_category":  summary_by_category(invoices),
        # ── Meta ───────────────────────────────────────────────────────
        "platform":     get_platform(),
        "generated_at": datetime.datetime.now().isoformat(),
    }


# ═════════════════════════════════════════════════════════════════════
#  VALIDERING
# ═════════════════════════════════════════════════════════════════════


def validate_invoice(inv: dict) -> list[str]:
    """
    Validerar en faktura-dict. Returnerar lista av varningssträngar.

    Regler
    ──────
    • vat_percent valideras INTE mot KNOWN_VAT_RATES (moms valfri).
    • total_amount == 0 är fel, men negativt är tillåtet (krediter).
    • invoice_type valideras om det finns.
    • "Arkiverad" är giltig status — ger ingen varning.
    """
    warnings: list[str] = []

    # ── Obligatoriska fält ─────────────────────────────────────────────
    for fld in ("supplier", "invoice_number", "due_date"):
        if not str(inv.get(fld, "")).strip():
            warnings.append(f"Obligatoriskt fält saknas: '{fld}'.")

    # ── Belopp ─────────────────────────────────────────────────────────
    amounts = _resolve_invoice_amounts(inv)
    total = amounts["total_amount"]
    if total == 0:
        warnings.append("Belopp kan inte vara 0.")

    # ── Fakturatyp ─────────────────────────────────────────────────────
    itype = str(inv.get("invoice_type", "")).strip()
    if itype and itype not in VALID_INVOICE_TYPES:
        warnings.append(
            f"Okänd fakturatyp: '{itype}' "
            f"(giltiga: {', '.join(sorted(VALID_INVOICE_TYPES))})."
        )
    if itype.lower() in ("kredit", "kreditfaktura") and total > 0:
        warnings.append("Kreditfaktura bör ha negativt belopp.")
    if itype.lower() == "faktura" and total < 0:
        warnings.append(
            "Vanlig faktura bör ha positivt belopp "
            "(använd 'Kredit' för negativa)."
        )

    # ── Datum ─────────────────────────────────────────────────────────
    invoice_date = _parse_date(inv.get("date"))
    due_date = _parse_date(inv.get("due_date"))
    today = _today()

    if inv.get("date") and invoice_date is None:
        warnings.append(
            f"Ogiltigt datumformat: '{inv.get('date')}' "
            f"(kräver YYYY-MM-DD)."
        )
    if inv.get("due_date") and due_date is None:
        warnings.append(
            f"Ogiltigt förfallodatum: '{inv.get('due_date')}' "
            f"(kräver YYYY-MM-DD)."
        )
    if invoice_date and due_date and due_date < invoice_date:
        warnings.append("Förfallodatum är före fakturadatum.")
    if (
        due_date
        and due_date < today
        and inv.get("status") in ("Obetald", "Planerad", "Betalfil skapad")
    ):
        warnings.append(
            f"Förfallodatum {inv.get('due_date')} har passerat "
            f"— fakturan är förfallen."
        )

    # ── Status ─────────────────────────────────────────────────────────
    status = inv.get("status", "")
    if status and status not in VALID_STATUSES:
        warnings.append(f"Okänd status: '{status}'.")

    # ── OCR ────────────────────────────────────────────────────────────
    if not str(inv.get("ocr", "")).strip():
        warnings.append(
            "OCR-nummer saknas — kan orsaka problem vid betalning."
        )

    # ── Bankgiro / Plusgiro-format ─────────────────────────────────────
    bg = str(inv.get("bg", "")).strip()
    if bg and not re.fullmatch(r"\d{3,4}-\d{4}", bg):
        warnings.append(
            f"Bankgiro '{bg}' verkar ha fel format "
            f"(förväntat: XXXX-XXXX)."
        )
    pg = str(inv.get("pg", "")).strip()
    if pg and not re.fullmatch(r"\d{1,7}-\d", pg):
        warnings.append(
            f"Plusgiro '{pg}' verkar ha fel format "
            f"(förväntat: XXXXXXX-X)."
        )

    return warnings


def check_duplicate(
    candidate: dict,
    existing: list[dict],
    exclude_id: str = "",
) -> list[dict]:
    """Dubblettkontroll: samma fakturanummer + leverantör."""
    inv_nr = str(candidate.get("invoice_number", "")).lower().strip()
    supplier = str(candidate.get("supplier", "")).lower().strip()
    if not inv_nr or not supplier:
        return []
    return [
        inv for inv in existing
        if inv.get("id", "") != exclude_id
        and str(inv.get("invoice_number", "")).lower().strip() == inv_nr
        and str(inv.get("supplier", "")).lower().strip() == supplier
    ]


def check_amount_duplicate(
    candidate: dict,
    existing: list[dict],
    exclude_id: str = "",
    tolerance: float = 0.01,
) -> list[dict]:
    """Dubblettkontroll: samma leverantör + (nästan) samma belopp."""
    supplier = str(candidate.get("supplier", "")).lower().strip()
    amount = _amount(candidate, "total_amount")
    return [
        inv for inv in existing
        if inv.get("id", "") != exclude_id
        and str(inv.get("supplier", "")).lower().strip() == supplier
        and abs(_amount(inv, "total_amount") - amount) <= tolerance
    ]


# ═════════════════════════════════════════════════════════════════════
#  BETALBATCH-HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def batch_total(
    invoice_ids: list[str],
    invoices: list[dict],
) -> float:
    """Summa total_amount för fakturorna i batchen (netto inkl krediter)."""
    id_set = set(invoice_ids)
    return round(
        sum(
            _amount(inv, "total_amount")
            for inv in invoices
            if inv.get("id") in id_set
        ),
        2,
    )


def invoices_by_ids(
    invoice_ids: list[str],
    invoices: list[dict],
) -> list[dict]:
    """Hämtar fakturor efter ID-lista. Senast ändrad längst bak."""
    id_set = set(invoice_ids)
    result = [inv for inv in invoices if inv.get("id") in id_set]
    return _sort_newest_last(result)


# ═════════════════════════════════════════════════════════════════════
#  RAPPORTBYGGARE
# ═════════════════════════════════════════════════════════════════════


def monthly_report(
    invoices: list[dict],
    year: int | None = None,
    month: int | None = None,
) -> dict[str, Any]:
    """Månadsrapport med summor, krediter och leverantörsfördelning."""
    today = _today()
    y = year or today.year
    m = month or today.month

    period_start = datetime.date(y, m, 1)
    if m == 12:
        period_end = datetime.date(y + 1, 1, 1)
    else:
        period_end = datetime.date(y, m + 1, 1)

    subset = filter_by_date_range(
        invoices,
        period_start,
        period_end - datetime.timedelta(days=1),
        "date",
    )
    subset = _sort_newest_last(subset)

    return {
        "period":       f"{y:04d}-{m:02d}",
        "invoices":     subset,
        "count":        len(subset),
        "total":        total_invoices(subset),
        "total_vat":    total_vat(subset),
        "total_ex_vat": total_ex_vat(subset),
        "paid":         total_by_status(subset, "Betald"),
        "unpaid":       total_unpaid(subset),
        "overdue":      total_overdue(subset),
        "credits":      total_credits(subset),
        "net":          net_total(subset),
        "by_supplier":  summary_by_supplier(subset),
    }


def supplier_report(
    invoices: list[dict], supplier: str
) -> dict[str, Any]:
    """Leverantörsrapport med månadsfördelning."""
    subset = _sort_newest_last(filter_by_supplier(invoices, supplier))
    return {
        "supplier":  supplier,
        "invoices":  subset,
        "count":     len(subset),
        "total":     total_invoices(subset),
        "total_vat": total_vat(subset),
        "unpaid":    total_unpaid(subset),
        "overdue":   total_overdue(subset),
        "credits":   total_credits(subset),
        "net":       net_total(subset),
        "by_month":  summary_by_month(subset),
    }


def vat_report(invoices: list[dict]) -> dict[str, Any]:
    """
    Momsfördelning per momssats — fungerar även när moms är valfri.
    """
    rates: dict[str, dict] = {}
    for inv in invoices:
        amounts = _resolve_invoice_amounts(inv)
        rate_key = str(int(amounts["vat_percent"]))
        if rate_key not in rates:
            rates[rate_key] = {
                "count":      0,
                "total_ex":   0.0,
                "vat":        0.0,
                "total_incl": 0.0,
            }
        row = rates[rate_key]
        row["count"] += 1
        row["total_ex"] = round(
            row["total_ex"] + amounts["amount_ex_vat"], 2
        )
        row["vat"] = round(row["vat"] + amounts["vat_amount"], 2)
        row["total_incl"] = round(
            row["total_incl"] + amounts["total_amount"], 2
        )
    return {
        "rates":          dict(sorted(rates.items())),
        "total_ex_vat":   total_ex_vat(invoices),
        "total_vat":      total_vat(invoices),
        "total_incl_vat": total_invoices(invoices),
    }


def overdue_report(invoices: list[dict]) -> dict[str, Any]:
    """
    Förfallorapport med åldersintervall (aging buckets).
    Sorterade: senast ändrad längst bak.
    """
    today = _today()
    overdue = overdue_invoices(invoices)   # redan sorterad

    buckets: dict[str, list[dict]] = {
        "1_30":   [],
        "31_60":  [],
        "61_90":  [],
        "over90": [],
    }
    for inv in overdue:
        due = _parse_date(inv.get("due_date"))
        if due is None:
            continue
        days = (today - due).days
        if days <= 30:
            buckets["1_30"].append(inv)
        elif days <= 60:
            buckets["31_60"].append(inv)
        elif days <= 90:
            buckets["61_90"].append(inv)
        else:
            buckets["over90"].append(inv)

    return {
        "count":    len(overdue),
        "total":    total_invoices(overdue),
        "invoices": overdue,
        "buckets": {
            k: {
                "invoices": _sort_newest_last(v),
                "total":    total_invoices(v),
            }
            for k, v in buckets.items()
        },
        "by_supplier": summary_by_supplier(overdue),
    }


# ═════════════════════════════════════════════════════════════════════
#  SÖKMOTOR (light-version — full motor i search.py)
# ═════════════════════════════════════════════════════════════════════

_INVOICE_SEARCH_FIELDS: list[str] = [
    "supplier",
    "invoice_number",
    "invoice_type",
    "ocr",
    "reference",
    "note",
    "category",
    "status",
    "date",
    "due_date",
    "payment_date",
]

_SUPPLIER_SEARCH_FIELDS: list[str] = [
    "name",
    "org_number",
    "email",
    "phone",
    "contact_person",
    "address",
    "note",
]


def search_invoices(
    invoices: list[dict],
    query: str,
    fields: list[str] | None = None,
) -> list[dict]:
    """
    Fritextsökning över fakturor (light-version).
    Resultat sorterade: senast ändrad längst bak.
    """
    if fields is None:
        fields = _INVOICE_SEARCH_FIELDS
    terms = [t.strip().lower() for t in query.split() if t.strip()]
    if not terms:
        return _sort_newest_last(list(invoices))
    result = []
    for inv in invoices:
        haystack = " ".join(
            str(inv.get(f, "")).lower() for f in fields
        )
        if all(term in haystack for term in terms):
            result.append(inv)
    return _sort_newest_last(result)


def search_suppliers(
    suppliers: list[dict],
    query: str,
    fields: list[str] | None = None,
) -> list[dict]:
    """
    Fritextsökning över leverantörer (light-version).
    Resultat sorterade: senast ändrad längst bak.
    """
    if fields is None:
        fields = _SUPPLIER_SEARCH_FIELDS
    terms = [t.strip().lower() for t in query.split() if t.strip()]
    if not terms:
        return _sort_newest_last(list(suppliers))
    result = []
    for sup in suppliers:
        haystack = " ".join(
            str(sup.get(f, "")).lower() for f in fields
        )
        if all(term in haystack for term in terms):
            result.append(sup)
    return _sort_newest_last(result)


# ═════════════════════════════════════════════════════════════════════
#  FORMATERING
# ═════════════════════════════════════════════════════════════════════


def fmt_amount(
    value: float,
    currency: str = "SEK",
    decimals: int = 2,
) -> str:
    """
    Formaterar belopp svenskt: '12 345,67 SEK'.
    Negativa visas med minustecken: '−1 234,50 SEK'.
    """
    prefix = "−" if value < 0 else ""
    s = (
        f"{abs(value):,.{decimals}f}"
        .replace(",", "\u2009")
        .replace(".", ",")
    )
    return f"{prefix}{s} {currency}".strip()


def fmt_date(value: str | datetime.date | None) -> str:
    """Säker datumformaterare (YYYY-MM-DD)."""
    if value is None:
        return ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime(DATE_FMT)
    parsed = _parse_date(value)
    return parsed.strftime(DATE_FMT) if parsed else str(value)


def days_until_due(inv: dict) -> int | None:
    """Dagar till förfallodatum. Negativt = förfallen."""
    due = _parse_date(inv.get("due_date"))
    if due is None:
        return None
    return (due - _today()).days


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python ui/core/calculator.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _sample: list[dict] = [
        {
            "id": "1", "supplier": "Acme AB",
            "invoice_number": "INV-001", "invoice_type": "Faktura",
            "ocr": "123456", "date": "2025-01-10",
            "due_date": "2025-02-10", "payment_date": "2025-02-08",
            "total_amount": 1250.0, "vat_percent": 25,
            "currency": "SEK", "status": "Obetald",
            "category": "IT", "reference": "PO-42", "note": "",
            "created_at": "2025-01-10T08:00:00",
            "updated_at": "2025-01-10T08:00:00",
        },
        {
            "id": "2", "supplier": "Beta Leverans",
            "invoice_number": "2025-042", "invoice_type": "Faktura",
            "ocr": "", "date": "2025-01-15",
            "due_date": "2024-12-31", "payment_date": "",
            "total_amount": 5000.0, "vat_percent": 25,
            "currency": "SEK", "status": "Obetald",
            "category": "Kontorsmaterial", "reference": "",
            "note": "Expressleverans",
            "created_at": "2025-01-15T09:30:00",
            "updated_at": "2025-01-15T09:30:00",
        },
        {
            "id": "3", "supplier": "Acme AB",
            "invoice_number": "KRE-001", "invoice_type": "Kredit",
            "ocr": "654321", "date": "2025-01-20",
            "due_date": "2025-02-20", "payment_date": "",
            "total_amount": -500.0, "vat_percent": 25,
            "currency": "SEK", "status": "Obetald",
            "category": "IT", "reference": "PO-42",
            "note": "Kreditering",
            "created_at": "2025-01-20T10:00:00",
            "updated_at": "2025-01-20T10:00:00",
        },
        {
            "id": "4", "supplier": "Acme AB",
            "invoice_number": "INV-002", "invoice_type": "Faktura",
            "ocr": "654321", "date": "2025-01-20",
            "due_date": "2025-02-20", "payment_date": "",
            "total_amount": 896.0, "vat_percent": 12,
            "currency": "SEK", "status": "Betald",
            "category": "IT", "reference": "PO-43", "note": "",
            "created_at": "2025-01-20T10:00:00",
            "updated_at": "2025-01-22T14:00:00",
        },
        {
            "id": "5", "supplier": "Acme AB",
            "invoice_number": "INV-003", "invoice_type": "Faktura",
            "ocr": "777777", "date": "2025-02-01",
            "due_date": "2025-03-01", "payment_date": "",
            "total_amount": 2000.0, "vat_percent": 25,
            "currency": "SEK", "status": "Arkiverad",
            "category": "IT", "reference": "PO-44",
            "note": "Arkiverad efter export",
            "created_at": "2025-02-01T10:00:00",
            "updated_at": "2025-02-01T10:00:00",
        },
    ]

    print("=" * 65)
    print("  FakturaRäknaren — calculator.py självtest")
    print(f"  © {COPYRIGHT_YEAR} Rickard Längkvist")
    print(f"  Platform: {get_platform()}")
    print("  Fil: FakturaRäknaren_/ui/core/calculator.py")
    print("=" * 65)

    ds = dashboard_summary(_sample)
    print("\n  Dashboard-sammanställning:")
    for key, value in ds.items():
        if not isinstance(value, (list, dict)):
            print(f"    {key:<24} = {value}")

    print(f"\n  count_by_type:   {ds['count_by_type']}")
    print(f"  count_by_status: {ds['count_by_status']}")
    print(f"  total_regular:   {fmt_amount(ds['total_regular'])}")
    print(f"  total_credits:   {fmt_amount(ds['total_credits'])}")
    print(f"  net_total:       {fmt_amount(ds['net_total'])}")

    # Arkiverade ska inte räknas som obetalda
    archived = [s for s in _sample if s.get("status") == "Arkiverad"]
    unpaid = [s for s in _sample if _is_unpaid_status(s)]
    print(f"\n  Arkiverade (ej obetalda): {len(archived)}")
    print(f"  Verkligen obetalda:       {len(unpaid)}")
    assert ds["count_unpaid"] == len(unpaid), "count_unpaid FEL!"
    print("  count_unpaid: ✅ korrekt")

    # Sortering: senast ändrad SIST
    print("\n  ── Sortering: senast ändrad SIST ──")
    recent = ds["recent_invoices"]
    for r in recent:
        print(
            f"    {r['invoice_number']:<12}  updated={r.get('updated_at')}"
        )
    if len(recent) >= 2:
        assert (
            recent[-1].get("updated_at", "")
            >= recent[0].get("updated_at", "")
        ), "SORTERINGSFEL!"
        print("  ✅ Senast ändrad post är SIST")

    print("\n  compute_invoice_amounts(1250, 25):")
    print(f"    {compute_invoice_amounts(1250, 25)}")
    print("  compute_invoice_amounts(-500, 25) [kredit]:")
    print(f"    {compute_invoice_amounts(-500, 25)}")
    print(f"\n  split_vat(1250, 25):  {split_vat(1250, 25)}")
    print(f"  split_vat(-500, 25):  {split_vat(-500, 25)}")
    assert split_vat(-500, 25) == (-400.0, -100.0)

    print(f"\n  Overdue: {len(overdue_invoices(_sample))} "
          f"(Arkiverad räknas inte)")
    ov = overdue_invoices(_sample)
    if len(ov) >= 2:
        assert (
            _timestamp_sort_key(ov[-1]) >= _timestamp_sort_key(ov[0])
        ), "SORTERINGSFEL i overdue!"
        print("  ✅ Overdue: senast ändrad sist")

    print("\n  Validering (faktura 2 — saknar OCR):")
    for w in validate_invoice(_sample[1]):
        print(f"    ⚠  {w}")

    print("\n  Validering (kredit med positivt belopp):")
    bad_credit = {
        "supplier": "X", "invoice_number": "KRE-99",
        "invoice_type": "Kredit", "due_date": "2025-12-31",
        "total_amount": 100.0,
    }
    for w in validate_invoice(bad_credit):
        print(f"    ⚠  {w}")

    print("\n  Validering (Arkiverad — ingen statusvarning):")
    archived_inv = {
        "supplier": "Acme AB", "invoice_number": "INV-ARC",
        "invoice_type": "Faktura", "due_date": "2025-12-31",
        "total_amount": 1000.0, "ocr": "123", "status": "Arkiverad",
    }
    arc_warnings = [
        w for w in validate_invoice(archived_inv)
        if "status" in w.lower()
    ]
    assert not arc_warnings
    print(f"    Statusvarningar: {len(arc_warnings)}  ✅")

    print("\n  Månadsrapport (2025-01):")
    mr = monthly_report(_sample, 2025, 1)
    print(
        f"    count={mr['count']}  total={fmt_amount(mr['total'])}  "
        f"net={fmt_amount(mr['net'])}  credits={fmt_amount(mr['credits'])}"
    )
    if len(mr["invoices"]) >= 2:
        assert (
            mr["invoices"][-1].get("updated_at", "")
            >= mr["invoices"][0].get("updated_at", "")
        ), "Månadsrapport: sorteringsfel!"
        print("    ✅ Månadsrapport: senast ändrad sist")

    print("\n  Förfallorapport:")
    orep = overdue_report(_sample)
    print(
        f"    count={orep['count']}  total={fmt_amount(orep['total'])}"
    )

    print("\n  Momsrapport:")
    vr = vat_report(_sample)
    for rate, data in vr["rates"].items():
        print(f"    {rate}%: {data}")

    print(
        f"\n  search_invoices('acme'): "
        f"{[i['invoice_number'] for i in search_invoices(_sample, 'acme')]}"
    )
    print(
        f"  search_invoices('kredit'): "
        f"{[i['invoice_number'] for i in search_invoices(_sample, 'kredit')]}"
    )
    print(
        f"  search_invoices('2025-02-08'): "
        f"{[i['invoice_number'] for i in search_invoices(_sample, '2025-02-08')]}"
    )
    acme_results = search_invoices(_sample, "acme")
    if len(acme_results) >= 2:
        assert (
            _timestamp_sort_key(acme_results[-1])
            >= _timestamp_sort_key(acme_results[0])
        ), "Sökresultat: sorteringsfel!"
        print("  ✅ Sökresultat: senast ändrad sist")

    print(
        f"\n  filter_by_type('Kredit'): "
        f"{[i['invoice_number'] for i in filter_by_type(_sample, 'Kredit')]}"
    )
    print(
        f"  filter_by_status('Arkiverad'): "
        f"{[i['invoice_number'] for i in filter_by_status(_sample, 'Arkiverad')]}"
    )

    print(f"\n  total_unpaid:  {fmt_amount(total_unpaid(_sample))}")
    print(f"  total_credits: {fmt_amount(total_credits(_sample))}")
    print(f"  net_total:     {fmt_amount(net_total(_sample))}")

    print("\n  ── sort_invoices (sekundär: senast ändrad sist) ──")
    for inv in sort_invoices(_sample, "supplier"):
        print(
            f"    {inv['supplier']:<18} {inv['invoice_number']:<12} "
            f"updated={inv.get('updated_at')}"
        )
    print("  ✅ sort_invoices med sekundärnyckel (typsäker)")

    print("\n✅  Självtest klart.")
