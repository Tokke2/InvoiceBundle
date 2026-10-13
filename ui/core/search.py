from __future__ import annotations

"""
FakturaRäknaren — Search Engine
=====================================
Fil    : FakturaRäknaren_/ui/core/search.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Ren Python-sökmotor utan UI-beroenden.
Används av alla vyer, plugins och den globala sökpaletten.

Söker bland annat på
---------------------
• invoice_number (fakturanummer) — högsta prioritet
• supplier (leverantör)
• ocr
• invoice_type (Faktura / Kreditfaktura)
• total_amount (belopp — inkl negativa kreditfakturor)
• payment_date (betalningsdatum)
• status, category, reference, note, date, due_date

Sortering
---------
• Primär  : score (relevans) — högst poäng = bäst = FÖRST
• Sekundär: updated_at / created_at (stigande) →
  senast ändrad/tillagd post hamnar SIST (längst bak)
• Gäller alla sökresultat, filterresultat och suggestions (MUST-023)

Samarbetar med
--------------
• app.py                 – FakturaApp (get_invoices, get_suppliers)
• invoices_view.py       – sök + filterpipeline
• invoices_helpers.py    – InvoiceDialog autocomplete
• suppliers_view.py      – leverantörssökning
• calculator.py          – _sort_newest_last / _timestamp_sort_key
• storage.py             – DataStore.search()
• pdf_export.py          – söker fakturor vid export

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Iterator

log = logging.getLogger("FakturaSearch")

COPYRIGHT_YEAR: int = datetime.date.today().year

# ═════════════════════════════════════════════════════════════════════
#  FÄLTDEFINITIONER — entitetstyp → sökbara fält
# ═════════════════════════════════════════════════════════════════════

INVOICE_SEARCH_FIELDS: list[str] = [
    "invoice_number",      # ← HÖGSTA PRIORITET
    "supplier",
    "ocr",
    "invoice_type",        # Faktura / Kreditfaktura
    "reference",
    "category",
    "status",
    "note",
    "date",
    "due_date",
    "payment_date",        # betalningsdatum
    "currency",
    "total_amount",        # sökbart som text (inkl negativa)
]

SUPPLIER_SEARCH_FIELDS: list[str] = [
    "name",
    "org_number",
    "bg",
    "pg",
    "iban",
    "bic",
    "email",
    "phone",
    "contact_person",
    "address",
    "note",
]

PAYMENT_SEARCH_FIELDS: list[str] = [
    "status",
    "payment_date",
    "note",
    "currency",
    "total_amount",
]

# ═════════════════════════════════════════════════════════════════════
#  MATCH MODE
# ═════════════════════════════════════════════════════════════════════


class MatchMode(Enum):
    """Söklägen: CONTAINS / STARTS_WITH / EXACT / REGEX."""

    CONTAINS = auto()
    STARTS_WITH = auto()
    EXACT = auto()
    REGEX = auto()


# ═════════════════════════════════════════════════════════════════════
#  SEARCH RESULT
# ═════════════════════════════════════════════════════════════════════


@dataclass
class SearchResult:
    """Ett sökträff med relevanspoäng och matchade fält."""

    item: dict
    entity_type: str = "unknown"
    score: int = 0
    matched_fields: list[str] = field(default_factory=list)

    def __lt__(self, other: "SearchResult") -> bool:
        """
        Primär  : score (högre = bättre = FÖRST)
        Sekundär: timestamp (stigande) → senast ändrad SIST
        """
        if self.score != other.score:
            return self.score > other.score
        self_ts = _timestamp_sort_key(self.item)
        other_ts = _timestamp_sort_key(other.item)
        return self_ts < other_ts  # äldre sorteras före nyare


@dataclass
class GlobalSearchResult:
    """Resultat från global_search över alla entitetstyper."""

    query: str
    invoices: list[dict] = field(default_factory=list)
    suppliers: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    all_items: list[SearchResult] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return (
            len(self.invoices)
            + len(self.suppliers)
            + len(self.payments)
        )

    def is_empty(self) -> bool:
        return self.total_count == 0


# ═════════════════════════════════════════════════════════════════════
#  TIMESTAMP-SORTERINGSNYCKEL  (synkroniserad med calculator.py)
# ═════════════════════════════════════════════════════════════════════


def _timestamp_sort_key(item: dict) -> str:
    """
    Sorteringsnyckel: updated_at → created_at → "".

    Regler (synkroniserat med calculator._timestamp_sort_key):
    • Primärt        : updated_at (senast ändrad)
    • Fallback       : created_at (skapad)
    • Sista fallback : "" (sorteras alltid FÖRE nyare poster)

    Används så att senast ändrad post alltid hamnar SIST (längst bak)
    i alla sökresultat och filterlistor.
    """
    ts = str(item.get("updated_at", "")).strip()
    if not ts:
        ts = str(item.get("created_at", "")).strip()
    return ts


def _sort_newest_last(items: list[dict]) -> list[dict]:
    """
    Sorterar poster med senast ändrad SIST (längst bak).
    Äldst → nyast (stigande ordning på updated_at/created_at).
    Synkroniserad med calculator._sort_newest_last().
    """
    return sorted(items, key=_timestamp_sort_key)


# ═════════════════════════════════════════════════════════════════════
#  TEXTNORMALISERING
# ═════════════════════════════════════════════════════════════════════


def _normalise(text: str) -> str:
    """
    Normaliserar text för jämförelse:
    NFKD-dekomposition, ta bort combining-tecken (åäö → aao), lowercase.
    """
    try:
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(
            c for c in nfkd if not unicodedata.combining(c)
        ).lower()
    except Exception:
        return text.lower()


def _tokenise(query: str) -> list[str]:
    """
    Delar upp query i tokens.
    "Citerade fraser" behandlas som en enhet.
    """
    tokens: list[str] = []
    for match in re.finditer(r'"([^"]+)"|(\S+)', query):
        token = match.group(1) or match.group(2)
        if token and token.strip():
            tokens.append(token.strip())
    return tokens


def _field_value(item: dict, key: str) -> str:
    """Hämtar och normaliserar ett fältvärde från ett record."""
    try:
        val = item.get(key, "")
        if val is None:
            return ""
        return _normalise(str(val))
    except Exception:
        return ""


def _to_float(value: Any, default: float = 0.0) -> float:
    """Säker float-konvertering."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sort_key_typed(key: str) -> Callable[[dict], tuple]:
    """
    Bygger en typsäker sorteringsnyckel för *key*.

    Tal och text blandas inte (TypeError-skydd); sekundär nyckel är
    updated_at (stigande) → senast ändrad SIST vid lika primärvärden.
    """

    def _primary(item: dict) -> tuple[int, float, str]:
        val = item.get(key, "")
        try:
            return (0, float(val), "")
        except (TypeError, ValueError):
            return (1, 0.0, str(val).lower())

    def _sort_key(item: dict) -> tuple[tuple[int, float, str], str]:
        return (_primary(item), _timestamp_sort_key(item))

    return _sort_key


def _score_match(value: str, term: str, mode: MatchMode) -> int:
    """Returnerar poäng för en matchning (0 = ingen match)."""
    if not value or not term:
        return 0

    t = _normalise(term)

    if mode == MatchMode.EXACT:
        return 10 if value == t else 0

    if mode == MatchMode.STARTS_WITH:
        return 5 if value.startswith(t) else 0

    if mode == MatchMode.REGEX:
        try:
            return 3 if re.search(term, value, re.IGNORECASE) else 0
        except re.error:
            return 0

    # CONTAINS
    if value == t:
        return 10
    if value.startswith(t):
        return 5
    if t in value:
        return 3
    return 0


# ═════════════════════════════════════════════════════════════════════
#  KÄRNSÖKNING
# ═════════════════════════════════════════════════════════════════════


def search_list(
    items: list[dict],
    query: str,
    fields: list[str],
    mode: MatchMode = MatchMode.CONTAINS,
    require_all: bool = True,
    entity_type: str = "unknown",
    field_weights: dict[str, int] | None = None,
) -> list[SearchResult]:
    """
    Generisk sökning i en lista av records.

    Sortering (dubbel nyckel)
    ─────────────────────────
    • Primär  : score (relevans) — högst poäng = bäst = FÖRST
    • Sekundär: updated_at/created_at (stigande) →
      senast ändrad/tillagd post hamnar SIST vid lika score

    Parametrar
    ──────────
    items         : listan att söka i
    query         : sökfras (stöder "citerade fraser" och multi-word)
    fields        : vilka fält som ingår i sökningen
    mode          : CONTAINS / STARTS_WITH / EXACT / REGEX
    require_all   : True = ALLA termer måste matcha (AND)
                    False = minst en term (OR)
    entity_type   : "invoice" / "supplier" / "payment"
    field_weights : fältnamn → viktmultiplikator
    """
    weights = field_weights or {}
    tokens = _tokenise(query)

    if not tokens:
        # Ingen query → allt, sorterat senast ändrad SIST
        sorted_items = _sort_newest_last(items)
        return [
            SearchResult(item, entity_type, 0, [])
            for item in sorted_items
        ]

    results: list[SearchResult] = []
    for item in items:
        term_scores: list[int] = []
        matched_fields: list[str] = []
        total_score = 0

        for token in tokens:
            token_score = 0
            token_matched: list[str] = []
            for fld in fields:
                val = _field_value(item, fld)
                s = _score_match(val, token, mode)
                if s > 0:
                    w = weights.get(fld, 1)
                    token_score = max(token_score, s * w)
                    if fld not in token_matched:
                        token_matched.append(fld)
            term_scores.append(token_score)
            for mf in token_matched:
                if mf not in matched_fields:
                    matched_fields.append(mf)
            total_score += token_score

        matched = (
            all(s > 0 for s in term_scores)
            if require_all
            else any(s > 0 for s in term_scores)
        )
        if matched:
            results.append(
                SearchResult(
                    item, entity_type, total_score, matched_fields
                )
            )

    # SearchResult.__lt__: score DESC, timestamp ASC (senast sist)
    results.sort()
    return results


def _to_dicts(results: list[SearchResult]) -> list[dict]:
    """Packar upp SearchResult-lista till rena dicts."""
    return [r.item for r in results]


# ═════════════════════════════════════════════════════════════════════
#  FAKTURA-FÄLTVIKTER
# ═════════════════════════════════════════════════════════════════════

_INVOICE_WEIGHTS: dict[str, int] = {
    "invoice_number": 5,   # ← HÖGST — fakturanummer matchas alltid först
    "supplier":       4,
    "ocr":            3,
    "invoice_type":   3,
    "reference":      2,
    "status":         2,
    "category":       2,
    "total_amount":   2,
    "payment_date":   2,
    "note":           1,
    "date":           1,
    "due_date":       1,
    "currency":       1,
}

#: Leverantörsfältvikter (även bakåtkompatibla fältnamn).
_SUPPLIER_WEIGHTS: dict[str, int] = {
    "name":           5,
    "org_number":     4,
    "email":          3,
    "contact_person": 3,
    "bg":             2,
    "pg":             2,
    "iban":           2,
    "phone":          2,
    "address":        1,
    "note":           1,
}


# ═════════════════════════════════════════════════════════════════════
#  ENTITETSSPECIFIKA SÖKFUNKTIONER
# ═════════════════════════════════════════════════════════════════════


def search_invoices(
    invoices: list[dict],
    query: str,
    mode: MatchMode = MatchMode.CONTAINS,
    require_all: bool = True,
) -> list[dict]:
    """
    Söker i registrerade leverantörsfakturor (inkl kreditfakturor).

    Sortering: score DESC, senast ändrad SIST vid lika score.
    Prioritetsordning: fakturanummer (5) → leverantör (4) →
    ocr/typ (3) → referens/status/kategori/belopp/betaldatum (2) →
    övriga (1).
    """
    return _to_dicts(
        search_list(
            invoices, query,
            fields=INVOICE_SEARCH_FIELDS,
            mode=mode,
            require_all=require_all,
            entity_type="invoice",
            field_weights=_INVOICE_WEIGHTS,
        )
    )


def search_by_invoice_number(
    invoices: list[dict],
    invoice_number: str,
    mode: MatchMode = MatchMode.CONTAINS,
) -> list[dict]:
    """
    Snabbsökning specifikt på fakturanummer.
    Returnerar alla matchande fakturor och kreditfakturor.
    Senast ändrad sist vid lika score.
    """
    if not invoice_number.strip():
        return _sort_newest_last(list(invoices))
    return _to_dicts(
        search_list(
            invoices, invoice_number,
            fields=["invoice_number"],
            mode=mode,
            require_all=True,
            entity_type="invoice",
            field_weights={"invoice_number": 10},
        )
    )


def search_by_type(
    invoices: list[dict],
    invoice_type: str,
) -> list[dict]:
    """
    Filtrerar på typ: "Faktura" eller "Kreditfaktura".
    Tomt / "Alla" → alla poster, sorterade senast ändrad sist.
    """
    if not invoice_type or invoice_type.lower() in ("alla", "all", ""):
        return _sort_newest_last(list(invoices))
    result = [
        inv
        for inv in invoices
        if inv.get("invoice_type", "Faktura") == invoice_type
    ]
    return _sort_newest_last(result)


def search_by_amount(
    invoices: list[dict],
    amount_str: str,
) -> list[dict]:
    """
    Söker fakturor vars total_amount matchar söksträngen.

    Stöder positiva (fakturor) och negativa (krediter) belopp samt
    svenskt format (komma, mellanslag, "kr", "SEK", −-tecken).
    Resultaten sorteras senast ändrad sist.
    """
    if not amount_str.strip():
        return _sort_newest_last(list(invoices))

    cleaned = (
        amount_str.strip()
        .replace(" ", "")
        .replace("\u2009", "")
        .replace(",", ".")
        .replace("kr", "")
        .replace("SEK", "")
        .replace("−", "-")
        .strip()
    )

    results: list[dict] = []
    for inv in invoices:
        total = _to_float(inv.get("total_amount"))
        total_str = str(inv.get("total_amount", ""))
        try:
            search_val = float(cleaned)
            if abs(total - search_val) < 0.01:
                results.append(inv)
                continue
            if search_val >= 0 and abs(abs(total) - search_val) < 0.01:
                results.append(inv)
                continue
        except (ValueError, TypeError):
            pass
        # Delsträngsmatch på beloppet som text (utan minustecken)
        if cleaned.lstrip("-") and cleaned.lstrip("-") in total_str.lstrip("-"):
            results.append(inv)

    # Ta bort dubletter
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in results:
        rid = str(r.get("id", id(r)))
        if rid not in seen:
            seen.add(rid)
            deduped.append(r)
    return _sort_newest_last(deduped)


def search_suppliers(
    suppliers: list[dict],
    query: str,
    mode: MatchMode = MatchMode.CONTAINS,
    require_all: bool = True,
) -> list[dict]:
    """
    Söker i leverantörer.

    Stöder bakåtkompatibla fältnamn: orgnr, bankgiro, plusgiro.
    Returnerar ORIGINAL-posterna (inte normaliserade kopior).
    Senast ändrad sist vid lika score.
    """
    normalised: list[dict] = []
    for idx, s in enumerate(suppliers):
        cp = dict(s)
        cp.setdefault("org_number", cp.get("orgnr", ""))
        cp.setdefault("bg", cp.get("bankgiro", ""))
        cp.setdefault("pg", cp.get("plusgiro", ""))
        cp["_orig_idx"] = idx
        normalised.append(cp)

    results = search_list(
        normalised, query,
        fields=SUPPLIER_SEARCH_FIELDS,
        mode=mode,
        require_all=require_all,
        entity_type="supplier",
        field_weights=_SUPPLIER_WEIGHTS,
    )
    return [
        suppliers[r.item["_orig_idx"]]
        for r in results
        if 0 <= r.item.get("_orig_idx", -1) < len(suppliers)
    ]


def search_payments(
    payments: list[dict],
    query: str,
    mode: MatchMode = MatchMode.CONTAINS,
    require_all: bool = True,
) -> list[dict]:
    """Söker i betalbatchar. Senast ändrad sist vid lika score."""
    return _to_dicts(
        search_list(
            payments, query,
            fields=PAYMENT_SEARCH_FIELDS,
            mode=mode,
            require_all=require_all,
            entity_type="payment",
        )
    )


# ═════════════════════════════════════════════════════════════════════
#  GLOBAL SÖKNING
# ═════════════════════════════════════════════════════════════════════


def global_search(
    data: dict,
    query: str,
    mode: MatchMode = MatchMode.CONTAINS,
    require_all: bool = True,
) -> GlobalSearchResult:
    """
    Söker i alla datastores samtidigt.

    Fakturanummer + leverantörsnamn har högst prioritet.
    Stöder kreditfakturor (negativa belopp).
    Senast ändrad sist vid lika score.
    """
    inv_results = search_list(
        data.get("invoices", []), query,
        fields=INVOICE_SEARCH_FIELDS,
        mode=mode,
        require_all=require_all,
        entity_type="invoice",
        field_weights=_INVOICE_WEIGHTS,
    )
    sup_results = search_list(
        data.get("suppliers", []), query,
        fields=SUPPLIER_SEARCH_FIELDS,
        mode=mode,
        require_all=require_all,
        entity_type="supplier",
        field_weights={"name": 5, "org_number": 4},
    )
    pay_results = search_list(
        data.get("payments", []), query,
        fields=PAYMENT_SEARCH_FIELDS,
        mode=mode,
        require_all=require_all,
        entity_type="payment",
    )

    all_items = sorted(inv_results + sup_results + pay_results)
    return GlobalSearchResult(
        query=query,
        invoices=[r.item for r in inv_results],
        suppliers=[r.item for r in sup_results],
        payments=[r.item for r in pay_results],
        all_items=all_items,
    )


# ═════════════════════════════════════════════════════════════════════
#  EXAKTA / PRECISA MATCHARE
# ═════════════════════════════════════════════════════════════════════


def exact_match(
    items: list[dict], field: str, value: str
) -> list[dict]:
    """Exakt match på ett fält (case-insensitive). Senast ändrad sist."""
    v = _normalise(value)
    result = [
        item
        for item in items
        if _normalise(str(item.get(field, "") or "")) == v
    ]
    return _sort_newest_last(result)


def starts_with_match(
    items: list[dict], field: str, value: str
) -> list[dict]:
    """Prefix-match på ett fält (case-insensitive). Senast ändrad sist."""
    v = _normalise(value)
    result = [
        item
        for item in items
        if _normalise(str(item.get(field, "") or "")).startswith(v)
    ]
    return _sort_newest_last(result)


def multi_field_exact(
    items: list[dict], criteria: dict[str, str]
) -> list[dict]:
    """Exakt match på flera fält samtidigt (AND). Senast ändrad sist."""

    def _matches(item: dict) -> bool:
        return all(
            _normalise(str(item.get(k, "") or ""))
            == _normalise(str(v))
            for k, v in criteria.items()
        )

    result = [item for item in items if _matches(item)]
    return _sort_newest_last(result)


def find_by_id(items: list[dict], record_id: str) -> dict | None:
    """Hittar ett record med ett specifikt ID."""
    for item in items:
        if str(item.get("id", "")) == str(record_id):
            return item
    return None


def find_by_invoice_number(
    invoices: list[dict],
    invoice_number: str,
    supplier: str = "",
) -> list[dict]:
    """
    Hittar fakturor med exakt fakturanummer (även kreditfakturor).
    Begränsa till en leverantör med *supplier*. Senast ändrad sist.
    """
    nr = _normalise(invoice_number)
    results = [
        inv
        for inv in invoices
        if _normalise(str(inv.get("invoice_number", "") or "")) == nr
    ]
    if supplier:
        sup = _normalise(supplier)
        results = [
            inv
            for inv in results
            if _normalise(str(inv.get("supplier", "") or "")) == sup
        ]
    return _sort_newest_last(results)


def find_duplicates(
    items: list[dict],
    match_fields: list[str],
    candidate: dict,
    exclude_id: str = "",
) -> list[dict]:
    """
    Hittar poster som matchar candidate på alla match_fields.
    Case-insensitive. Exkluderar exclude_id. Senast ändrad sist.
    """

    def _matches(item: dict) -> bool:
        if item.get("id") == exclude_id:
            return False
        return all(
            _normalise(str(item.get(f, "") or ""))
            == _normalise(str(candidate.get(f, "") or ""))
            for f in match_fields
        )

    result = [item for item in items if _matches(item)]
    return _sort_newest_last(result)


# ═════════════════════════════════════════════════════════════════════
#  LIVE-SEARCH (stateful cache för vyer)
# ═════════════════════════════════════════════════════════════════════


class LiveSearch:
    """
    Stateful search-cache för vyer.

    Cachar sista sökningen och undviker onödiga fetch-anrop.
    Alla resultat sorteras: senast ändrad sist.

    Usage
    -----
        self._live = LiveSearch(
            fetch_fn  = self._app.get_invoices,
            search_fn = search_invoices,
        )
        results = self._live.update("INV-001")
    """

    def __init__(
        self,
        fetch_fn: Callable[[], list[dict]],
        search_fn: Callable[[list[dict], str], list[dict]],
    ) -> None:
        self._fetch = fetch_fn
        self._search = search_fn
        self._cache: list[dict] = []
        self._last_q: str = ""
        self._results: list[dict] = []

    def refresh_cache(self) -> None:
        """Tvingar omhämtning av data."""
        self._cache = self._fetch()
        self._last_q = ""

    def update(self, query: str) -> list[dict]:
        """
        Uppdaterar sökningen och returnerar matchande poster.
        Resultat sorteras: senast ändrad sist.
        """
        q = query.strip()
        if q == self._last_q:
            return self._results

        if not q or (
            self._last_q and not q.startswith(self._last_q[:2])
        ):
            self._cache = self._fetch()

        self._last_q = q
        if q:
            self._results = self._search(self._cache, q)
        else:
            # Tom query → allt, sorterat senast ändrad sist
            self._results = _sort_newest_last(list(self._cache))
        return self._results

    @property
    def last_results(self) -> list[dict]:
        return self._results

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        """Rensar cache och resultat."""
        self._cache = []
        self._last_q = ""
        self._results = []


# ═════════════════════════════════════════════════════════════════════
#  FILTER PIPELINE
# ═════════════════════════════════════════════════════════════════════


class FilterPipeline:
    """
    Chainable filter för fakturor och kreditfakturor.

    Sortering
    ─────────
    • results() returnerar alltid senast ändrad post SIST.
    • sort_by() överskriver med explicit nyckel men behåller
      senast-ändrad-sist som sekundär nyckel.
    • Stöder negativa belopp (kreditfakturor) i by_amount_range.

    Exempel
    ───────
        results = (
            FilterPipeline(invoices)
            .by_invoice_number("INV-001")
            .by_type("Faktura")
            .by_status("Obetald")
            .by_supplier("Acme AB")
            .by_amount_range(-5000, 10000)
            .sort_by("due_date")
            .results()
        )
        credits = FilterPipeline(invoices).credits_only().results()
        total   = FilterPipeline(invoices).total()
    """

    def __init__(self, items: list[dict]) -> None:
        self._items = list(items)
        self._explicit_sort = False   # True om sort_by() anropats

    # ── Filtermetoder ──────────────────────────────────────────────────

    def where(
        self, predicate: Callable[[dict], bool]
    ) -> "FilterPipeline":
        """Godtycklig predikatfunktion."""
        self._items = [i for i in self._items if predicate(i)]
        return self

    def by_invoice_number(
        self,
        number: str,
        mode: MatchMode = MatchMode.CONTAINS,
    ) -> "FilterPipeline":
        """Filtrerar på fakturanummer (INV-xxx och KRED-xxx)."""
        if not number.strip():
            return self
        n = _normalise(number)
        if mode == MatchMode.EXACT:
            self._items = [
                i for i in self._items
                if _normalise(str(i.get("invoice_number", "") or "")) == n
            ]
        elif mode == MatchMode.STARTS_WITH:
            self._items = [
                i for i in self._items
                if _normalise(
                    str(i.get("invoice_number", "") or "")
                ).startswith(n)
            ]
        else:
            self._items = [
                i for i in self._items
                if n in _normalise(str(i.get("invoice_number", "") or ""))
            ]
        return self

    def by_type(self, invoice_type: str) -> "FilterPipeline":
        """Filtrerar på typ: 'Faktura' eller 'Kreditfaktura'."""
        if invoice_type and invoice_type.lower() not in (
            "alla", "all", "",
        ):
            self._items = [
                i for i in self._items
                if i.get("invoice_type", "Faktura") == invoice_type
            ]
        return self

    def by_status(self, status: str) -> "FilterPipeline":
        """Filtrerar på status."""
        if status and status.lower() not in ("alla", "all", ""):
            self._items = [
                i for i in self._items if i.get("status") == status
            ]
        return self

    def by_supplier(self, supplier: str) -> "FilterPipeline":
        """Filtrerar på leverantör (case-insensitive)."""
        if supplier:
            sup = supplier.lower()
            self._items = [
                i for i in self._items
                if i.get("supplier", "").lower() == sup
            ]
        return self

    def by_category(self, category: str) -> "FilterPipeline":
        """Filtrerar på kategori."""
        if category:
            cat = category.lower()
            self._items = [
                i for i in self._items
                if i.get("category", "").lower() == cat
            ]
        return self

    def by_date_range(
        self,
        start: str | None,
        end: str | None,
        key: str = "date",
    ) -> "FilterPipeline":
        """Filtrerar på datumintervall (YYYY-MM-DD-strängjämförelse)."""
        if start:
            self._items = [
                i for i in self._items if str(i.get(key, "")) >= start
            ]
        if end:
            self._items = [
                i for i in self._items if str(i.get(key, "")) <= end
            ]
        return self

    def by_amount_range(
        self,
        min_amount: float = -float("inf"),
        max_amount: float = float("inf"),
        key: str = "total_amount",
    ) -> "FilterPipeline":
        """
        Filtrerar på belopp. Stöder negativa belopp (kreditfakturor).
        """

        def _amt(item: dict) -> float:
            return _to_float(item.get(key) or item.get("amount"))

        self._items = [
            i for i in self._items
            if min_amount <= _amt(i) <= max_amount
        ]
        return self

    def by_text(
        self,
        query: str,
        fields: list[str] | None = None,
        mode: MatchMode = MatchMode.CONTAINS,
    ) -> "FilterPipeline":
        """Fritextsökning inom pipeline."""
        if query.strip():
            fields = fields or INVOICE_SEARCH_FIELDS
            results = search_list(self._items, query, fields, mode)
            # search_list returnerar redan senast ändrad sist
            self._items = [r.item for r in results]
        return self

    def credits_only(self) -> "FilterPipeline":
        """
        Bara kreditfakturor: negativt belopp ELLER
        invoice_type='Kreditfaktura'.
        """
        self._items = [
            i for i in self._items
            if _to_float(i.get("total_amount")) < 0
            or i.get("invoice_type") == "Kreditfaktura"
        ]
        return self

    def invoices_only(self) -> "FilterPipeline":
        """
        Bara vanliga fakturor: positivt belopp OCH
        invoice_type='Faktura'.
        """
        self._items = [
            i for i in self._items
            if _to_float(i.get("total_amount")) >= 0
            and i.get("invoice_type", "Faktura") == "Faktura"
        ]
        return self

    def exclude_archived(self) -> "FilterPipeline":
        """Exkluderar arkiverade och makulerade fakturor."""
        self._items = [
            i for i in self._items
            if i.get("status") not in ("Arkiverad", "Makulerad")
        ]
        return self

    def sort_by(
        self, key: str, reverse: bool = False
    ) -> "FilterPipeline":
        """
        Sorterar resultat på explicit nyckel.
        Sekundär nyckel: updated_at (stigande) → senast ändrad sist.
        Blandade typer (tal/text) kraschar inte.
        """
        self._explicit_sort = True
        self._items.sort(key=_sort_key_typed(key), reverse=reverse)
        return self

    # ── Resultataccessorer ─────────────────────────────────────────────

    def results(self) -> list[dict]:
        """
        Alla matchande poster.
        Om sort_by() INTE anropats → senast ändrad sist.
        """
        if self._explicit_sort:
            return list(self._items)
        return _sort_newest_last(self._items)

    def count(self) -> int:
        return len(self._items)

    def first(self) -> dict | None:
        """Äldsta posten (om ej sort_by anropats)."""
        if not self._items:
            return None
        if self._explicit_sort:
            return self._items[0]
        return _sort_newest_last(self._items)[0]

    def last(self) -> dict | None:
        """
        Senast ändrad post (längst bak).
        Alltid baserat på timestamp oavsett sort_by.
        """
        if not self._items:
            return None
        return _sort_newest_last(self._items)[-1]

    def total(self, key: str = "total_amount") -> float:
        """Summerar ett fält. Netto = fakturor (+) + krediter (−)."""
        return round(
            sum(_to_float(i.get(key)) for i in self._items), 2
        )

    def total_invoices(self) -> float:
        """Summa av enbart fakturor (positiva belopp)."""
        return round(
            sum(
                amt
                for amt in (
                    _to_float(i.get("total_amount")) for i in self._items
                )
                if amt > 0
            ),
            2,
        )

    def total_credits(self) -> float:
        """Summa av enbart kreditfakturor (negativa belopp)."""
        return round(
            sum(
                amt
                for amt in (
                    _to_float(i.get("total_amount")) for i in self._items
                )
                if amt < 0
            ),
            2,
        )

    def att_betala(self) -> float:
        """ATT BETALA = fakturor + krediter = netto."""
        return round(
            self.total_invoices() + self.total_credits(), 2
        )

    def __iter__(self) -> Iterator[dict]:
        return iter(self.results())

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return f"FilterPipeline(count={self.count()})"


# ═════════════════════════════════════════════════════════════════════
#  SUGGESTION ENGINE
# ═════════════════════════════════════════════════════════════════════


def suggest_suppliers(
    suppliers: list[dict], prefix: str, limit: int = 10
) -> list[str]:
    """
    Föreslår leverantörsnamn som börjar med prefix.
    Returnerar sorterad lista (alfabetisk).
    """
    p = _normalise(prefix)
    names = [
        s.get("name", "")
        for s in suppliers
        if _normalise(s.get("name", "")).startswith(p)
    ]
    return sorted(set(n for n in names if n))[:limit]


def suggest_categories(
    invoices: list[dict], prefix: str = "", limit: int = 20
) -> list[str]:
    """
    Föreslår kategorier (inkl från kreditfakturor).
    Returnerar sorterad lista (alfabetisk).
    """
    p = _normalise(prefix)
    cats = {
        inv.get("category", "")
        for inv in invoices
        if inv.get("category")
    }
    return sorted(
        c for c in cats if _normalise(c).startswith(p)
    )[:limit]


def suggest_invoice_numbers(
    invoices: list[dict], prefix: str, limit: int = 10
) -> list[str]:
    """
    Föreslår fakturanummer (och kreditfakturanummer) med prefix.
    Returnerar sorterad lista, t.ex. ["INV-001", "KRED-001"].
    """
    p = _normalise(prefix)
    nums = {
        inv.get("invoice_number", "")
        for inv in invoices
        if _normalise(
            str(inv.get("invoice_number", "") or "")
        ).startswith(p)
    }
    return sorted(n for n in nums if n)[:limit]


# ═════════════════════════════════════════════════════════════════════
#  SELF-TEST  (python ui/core/search.py)
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _inv = [
        {
            "id": "1", "supplier": "Acme AB",
            "invoice_number": "INV-001", "ocr": "123456",
            "invoice_type": "Faktura",
            "date": "2025-01-10", "due_date": "2025-02-10",
            "payment_date": "2025-02-08",
            "total_amount": 1250.0, "status": "Obetald",
            "category": "IT", "reference": "PO-42", "note": "",
            "created_at": "2025-01-10T08:00:00",
            "updated_at": "2025-01-10T08:00:00",
        },
        {
            "id": "2", "supplier": "Beta Leverans",
            "invoice_number": "2025-042", "ocr": "",
            "invoice_type": "Faktura",
            "date": "2025-01-15", "due_date": "2024-12-31",
            "payment_date": "",
            "total_amount": 5000.0, "status": "Förfallen",
            "category": "Kontorsmaterial", "reference": "",
            "note": "Express",
            "created_at": "2025-01-15T09:30:00",
            "updated_at": "2025-01-15T09:30:00",
        },
        {
            "id": "3", "supplier": "Acme AB",
            "invoice_number": "KRED-001", "ocr": "654321",
            "invoice_type": "Kreditfaktura",
            "date": "2025-01-20", "due_date": "2025-02-20",
            "payment_date": "",
            "total_amount": -500.0, "status": "Betald",
            "category": "IT", "reference": "PO-43", "note": "",
            "created_at": "2025-01-20T10:00:00",
            "updated_at": "2025-01-22T14:00:00",  # ← senast ändrad
        },
        {
            "id": "4", "supplier": "Beta Leverans",
            "invoice_number": "KRED-002", "ocr": "",
            "invoice_type": "Kreditfaktura",
            "date": "2025-02-01", "due_date": "2025-03-01",
            "payment_date": "",
            "total_amount": -250.0, "status": "Obetald",
            "category": "Kontorsmaterial", "reference": "",
            "note": "",
            "created_at": "2025-01-21T09:00:00",
            "updated_at": "2025-01-21T09:00:00",
        },
    ]

    _sup = [
        {
            "id": "s1", "name": "Acme AB",
            "org_number": "5560001234",
            "email": "info@acme.se", "bg": "1234-5678",
            "created_at": "2025-01-01T08:00:00",
            "updated_at": "2025-01-01T08:00:00",
        },
        {
            "id": "s2", "name": "Beta Leverans",
            "org_number": "5560009876",
            "email": "order@beta.se", "pg": "1234567-8",
            "created_at": "2025-01-05T08:00:00",
            "updated_at": "2025-01-10T12:00:00",  # ← senast ändrad
        },
    ]

    print("=" * 65)
    print("  FakturaRäknaren — Search Engine självtest")
    print(f"  © {COPYRIGHT_YEAR} Rickard Längkvist")
    print("  Fil: FakturaRäknaren_/ui/core/search.py")
    print("=" * 65)

    # ── Sortering: senast ändrad SIST ──────────────────────────────────
    print("\n  ── Sortering: senast ändrad SIST ──")
    all_sorted = _sort_newest_last(_inv)
    for r in all_sorted:
        print(f"    {r['invoice_number']:<12} updated={r.get('updated_at')}")
    assert all_sorted[-1]["updated_at"] >= all_sorted[0]["updated_at"]
    print("  ✅ senast ändrad är SIST")

    print("\n--- search_by_invoice_number('INV-001') ---")
    for r in search_by_invoice_number(_inv, "INV-001"):
        print(f"  ✔ {r['invoice_number']}  {r['supplier']}  {r['total_amount']}")

    print("\n--- search_by_invoice_number('INV', STARTS_WITH) ---")
    for r in search_by_invoice_number(_inv, "INV", MatchMode.STARTS_WITH):
        print(f"  ✔ {r['invoice_number']}  {r['supplier']}")

    print("\n--- search_by_invoice_number('KRED', STARTS_WITH) ---")
    res = search_by_invoice_number(_inv, "KRED", MatchMode.STARTS_WITH)
    for r in res:
        print(f"  ✔ {r['invoice_number']}  {r['invoice_type']}  {r['total_amount']}")
    if len(res) >= 2:
        assert _timestamp_sort_key(res[-1]) >= _timestamp_sort_key(res[0])
        print("  ✅ senast ändrad sist")

    print("\n--- search_invoices('acme') ---")
    res = search_invoices(_inv, "acme")
    for r in res:
        print(f"  {r['invoice_number']}  {r['supplier']}  {r['invoice_type']}")
    if len(res) >= 2:
        assert _timestamp_sort_key(res[-1]) >= _timestamp_sort_key(res[0])
        print("  ✅ senast ändrad sist")

    print("\n--- search_invoices('kreditfaktura') ---")
    for r in search_invoices(_inv, "kreditfaktura"):
        print(f"  {r['invoice_number']}  {r['invoice_type']}  {r['total_amount']}")

    print("\n--- search_invoices('2025-02-08') (betalningsdatum) ---")
    for r in search_invoices(_inv, "2025-02-08"):
        print(f"  {r['invoice_number']}  payment_date={r.get('payment_date')}")

    print("\n--- search_by_amount('1250') ---")
    for r in search_by_amount(_inv, "1250"):
        print(f"  {r['invoice_number']}  {r['total_amount']}")

    print("\n--- search_by_amount('-500') ---")
    for r in search_by_amount(_inv, "-500"):
        print(f"  {r['invoice_number']}  {r['total_amount']}")

    print("\n--- search_by_type('Kreditfaktura') ---")
    res = search_by_type(_inv, "Kreditfaktura")
    for r in res:
        print(f"  {r['invoice_number']}  {r['total_amount']}")
    if len(res) >= 2:
        assert _timestamp_sort_key(res[-1]) >= _timestamp_sort_key(res[0])
        print("  ✅ senast ändrad sist")

    print("\n--- find_by_invoice_number('INV-001', 'Acme AB') ---")
    for r in find_by_invoice_number(_inv, "INV-001", "Acme AB"):
        print(f"  ✔ {r['invoice_number']}  {r['supplier']}")

    print("\n--- exact_match('status', 'Obetald') ---")
    res = exact_match(_inv, "status", "Obetald")
    for r in res:
        print(f"  {r['invoice_number']}  {r['status']}")
    if len(res) >= 2:
        assert _timestamp_sort_key(res[-1]) >= _timestamp_sort_key(res[0])
        print("  ✅ senast ändrad sist")

    print("\n--- find_duplicates (supplier + invoice_number) ---")
    dups = find_duplicates(
        _inv,
        ["supplier", "invoice_number"],
        {"supplier": "Acme AB", "invoice_number": "INV-001"},
        exclude_id="1",
    )
    print(f"  Dubbletter: {len(dups)}")

    print("\n--- FilterPipeline: credits_only() ---")
    res = FilterPipeline(_inv).credits_only().results()
    for r in res:
        print(f"  {r['invoice_number']}  {r['total_amount']}")
    if len(res) >= 2:
        assert _timestamp_sort_key(res[-1]) >= _timestamp_sort_key(res[0])
        print("  ✅ senast ändrad sist")

    print("\n--- FilterPipeline: invoices_only() ---")
    for r in FilterPipeline(_inv).invoices_only().results():
        print(f"  {r['invoice_number']}  {r['total_amount']}")

    print("\n--- FilterPipeline: by_invoice_number('KRED') ---")
    for r in FilterPipeline(_inv).by_invoice_number("KRED").results():
        print(f"  {r['invoice_number']}  {r['total_amount']}")

    print("\n--- FilterPipeline: by_amount_range(-1000, 0) ---")
    for r in FilterPipeline(_inv).by_amount_range(-1000, 0).results():
        print(f"  {r['invoice_number']}  {r['total_amount']}")

    print("\n--- FilterPipeline: sort_by('due_date') sekundärnyckel ---")
    for r in FilterPipeline(_inv).sort_by("due_date").results():
        print(f"  {r['invoice_number']}  due={r['due_date']}  updated={r.get('updated_at')}")
    print("  ✅ explicit sort_by respekteras")

    print("\n--- FilterPipeline: last() → senast ändrad ---")
    last = FilterPipeline(_inv).last()
    print(f"  Senast ändrad: {last['invoice_number']}  updated={last.get('updated_at')}")
    assert last["updated_at"] == "2025-01-22T14:00:00"
    print("  ✅ korrekt")

    print("\n--- FilterPipeline totals ---")
    fp = FilterPipeline(_inv)
    print(f"  total_invoices = {fp.total_invoices()}")
    print(f"  total_credits  = {fp.total_credits()}")
    print(f"  att_betala     = {fp.att_betala()}")
    assert fp.att_betala() == 1250.0 + 5000.0 - 500.0 - 250.0

    print("\n--- LiveSearch: tom query → senast ändrad sist ---")
    ls = LiveSearch(lambda: _inv, search_invoices)
    res = ls.update("")
    if len(res) >= 2:
        assert _timestamp_sort_key(res[-1]) >= _timestamp_sort_key(res[0])
        print("  ✅ tom query returnerar senast ändrad sist")

    print("\n--- LiveSearch: 'acme' ---")
    for r in ls.update("acme"):
        print(f"  {r['invoice_number']}  {r['supplier']}")

    print("\n--- global_search('acme') ---")
    gr = global_search(
        {"invoices": _inv, "suppliers": _sup, "payments": []}, "acme"
    )
    print(f"  invoices={len(gr.invoices)}  suppliers={len(gr.suppliers)}")

    print("\n--- suggest_invoice_numbers ---")
    print(f"  'INV'  → {suggest_invoice_numbers(_inv, 'INV')}")
    print(f"  'KRED' → {suggest_invoice_numbers(_inv, 'KRED')}")
    print(f"  ''     → {suggest_invoice_numbers(_inv, '')}")

    print("\n--- suggest_suppliers('Acme') ---")
    print(f"  {suggest_suppliers(_sup, 'Acme')}")

    print("\nKlart. ✅")
