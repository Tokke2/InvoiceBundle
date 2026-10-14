from __future__ import annotations

"""
FakturaRäknaren — PDF Export Helpers
==========================================
Fil    : FakturaRäknaren_/plugins/pdf_export_helpers.py
Författare : Rickard Längkvist
År     : Dynamiskt (auto)

Hjälpmodul för pdf_export.py.

Innehåller
----------
• ASCII-konvertering för PDF-kompatibilitet (åäö → aao)
• Beloppsformatering (ATT BETALA)
• Plattformsidentifiering (Windows / Linux / macOS)
• InvoiceNumberGuard (dubblettskydd, JSON-persisterat)
• Leverantörsuppgifts-lookup
• PDFExporter (reportlab + text-fallback) – stilren, tydlig layout
• Avrundning av ATT BETALA via settings-nyckeln pdf_rounding
  (exact / hel / 50 / 100) – samma regel som GUI:t
• Alla konstanter och färgpaletter
• ExportPaymentDateDialog – frågar betalningsdatum PER export-batch
  - Visas alltid innan export
  - Datumet visas i PDF-rubriken (grön box)
  - Nollställs automatiskt efter exporten
  - Frågar igen vid nästa export

Copyright © dynamiskt år Rickard Längkvist
"""

import datetime
import json
import logging
import math
import platform
import unicodedata
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("FakturaPDF")

COPYRIGHT_YEAR: int = datetime.date.today().year

# ═════════════════════════════════════════════════════════════════════
#  KONSTANTER
# ═════════════════════════════════════════════════════════════════════

DATE_FMT: str = "%Y-%m-%d"
DATETIME_FMT: str = "%Y-%m-%d %H:%M:%S"
DEFAULT_EXPORT_DIR: Path = Path("exports")
APP_ROOT: Path = Path(__file__).resolve().parent.parent
USED_NUMBERS_FILE: str = "used_invoice_numbers.json"

# PDF-geometri
PDF_MARGIN_LEFT: int = 36
PDF_MARGIN_RIGHT: int = 36
PDF_MARGIN_TOP: int = 50
PDF_MARGIN_BOTTOM: int = 45
PDF_LINE_HEIGHT: int = 16
PDF_HEADER_HEIGHT: int = 20

#: PDF-tabellkolumner: (etikett, datanyckel, kolumnbredd)
#: Breddarna summerar till 523 pt = A4 (595) minus marginaler (2×36),
#: så hela tabellen inklusive Status-kolumnen får plats på sidan.
PDF_COLUMNS: list[tuple[str, str, int]] = [
    ("Fakturanr",     "invoice_number",  76),
    ("Typ",           "invoice_type",    58),
    ("Leverantor",    "supplier",       112),
    ("Datum",         "date",            62),
    ("Forfallodatum", "due_date",        72),
    ("Belopp",        "total_amount",    80),
    ("Status",        "status",          63),
]

#: Leverantörsfält som visas i PDF:en
SUPPLIER_DETAIL_FIELDS: list[tuple[str, str]] = [
    ("Org.nr",        "org_number"),
    ("Bankgiro",      "bg"),
    ("Plusgiro",      "pg"),
    ("IBAN",          "iban"),
    ("BIC/SWIFT",     "bic"),
    ("Betalvillkor",  "payment_terms"),
    ("Kontaktperson", "contact_person"),
    ("E-post",        "email"),
    ("Telefon",       "phone"),
    ("Adress",        "address"),
]

# ── Färgpalett ─────────────────────────────────────────────────────────

DARK_PAGE_BG      = "#10151f"   # hel mörk sidyta (mörkt tema)
LIGHT_PAGE_BG     = "#ffffff"   # hel ljus sidyta (ljust tema)
DARK_HEADER_BG    = "#1a365d"
DARK_HEADER_FG    = "#ffffff"
DARK_ROW_ALT      = "#1e2a3a"
DARK_ROW_NORMAL   = "#171f2b"
DARK_TEXT         = "#e2e8f0"
DARK_SUPPLIER_BG  = "#1c2636"

LIGHT_HEADER_BG   = "#2b6cb0"
LIGHT_HEADER_FG   = "#ffffff"
LIGHT_ROW_ALT     = "#ebf4ff"
LIGHT_ROW_NORMAL  = "#ffffff"
LIGHT_TEXT        = "#1a202c"
LIGHT_SUPPLIER_BG = "#f0f7ff"

_ACCENT            = "#3182ce"
ACCENT_DARK        = "#63b3ed"
FOOTER_GREY        = "#718096"
CREDIT_COLOR       = "#e53e3e"
INVOICE_COLOR      = "#38a169"
SUPPLIER_LABEL     = "#718096"
DIVIDER_COLOR      = "#a0aec0"
SUMMARY_BG_DARK    = "#1a365d"
SUMMARY_BG_LIGHT   = "#ebf8ff"
ATT_BETALA_BG_D    = "#2d3748"
ATT_BETALA_BG_L    = "#bee3f8"
DUE_DATE_BG_DARK   = "#1a3a2a"   # grön box – mörkt tema
DUE_DATE_BG_LIGHT  = "#c6f6d5"   # grön box – ljust tema

#: PDF-etiketter per språk. Dokumentet följer appens språk
#: (settings "language"); standard är svenska.
PDF_LABELS: dict[str, dict[str, str]] = {
    "sv": {
        "col_invoice_number": "Fakturanr", "col_type": "Typ",
        "col_supplier": "Leverantor", "col_date": "Datum",
        "col_due_date": "Forfallodatum", "col_amount": "Belopp",
        "col_status": "Status",
        "invoices_plus": "Fakturor  (+):", "credits_minus": "Krediter  (-):",
        "to_pay": "ATT BETALA:", "page": "Sida", "of": "av",
        "invoices": "FAKTUROR", "supplier_details": "LEVERANTORSUPPGIFTER",
        "exported": "Exporterad", "payment_date": "BETALNINGSDATUM:",
        "rounding": "avrundning",
        "terms": "Betalvillkor", "contact": "Kontaktperson",
        "email": "E-post", "phone": "Telefon", "address": "Adress",
        "days": "dagar", "rows": "Rader", "suppliers": "Leverantorer",
    },
    "en": {
        "col_invoice_number": "Invoice no.", "col_type": "Type",
        "col_supplier": "Supplier", "col_date": "Date",
        "col_due_date": "Due date", "col_amount": "Amount",
        "col_status": "Status",
        "invoices_plus": "Invoices  (+):", "credits_minus": "Credits  (-):",
        "to_pay": "TO PAY:", "page": "Page", "of": "of",
        "invoices": "INVOICES", "supplier_details": "SUPPLIER DETAILS",
        "exported": "Exported", "payment_date": "PAYMENT DATE:",
        "rounding": "rounding",
        "terms": "Payment terms", "contact": "Contact person",
        "email": "E-mail", "phone": "Phone", "address": "Address",
        "days": "days", "rows": "Rows", "suppliers": "Suppliers",
    },
}

_PDF_COL_KEYS: dict[str, str] = {
    "invoice_number": "col_invoice_number", "invoice_type": "col_type",
    "supplier": "col_supplier", "date": "col_date",
    "due_date": "col_due_date", "total_amount": "col_amount",
    "status": "col_status",
}


#: Giltiga avrundningslägen för ATT BETALA (samma som GUI).
PDF_ROUNDING_MODES: tuple[str, ...] = ("exact", "hel", "50", "100")


# ═════════════════════════════════════════════════════════════════════
#  HJÄLPARE
# ═════════════════════════════════════════════════════════════════════


def now_iso() -> str:
    return datetime.datetime.now().strftime(DATETIME_FMT)


def today_iso() -> str:
    return datetime.date.today().isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def export_root() -> Path:
    """<appmappen>/exports. Följer inte en symlänk som pekar ut."""
    preferred = APP_ROOT / "exports"
    try:
        if preferred.is_symlink() and not _inside(preferred.resolve(), APP_ROOT):
            log.error(
                "EXPORT_SYMLÄNK_UTANFÖR: %s — använder exports_inne",
                preferred,
            )
            alt = APP_ROOT / "exports_inne"
            alt.mkdir(parents=True, exist_ok=True)
            return alt.resolve()
        preferred.mkdir(parents=True, exist_ok=True)
        resolved = preferred.resolve()
        if _inside(resolved, APP_ROOT):
            return resolved
    except OSError as exc:
        log.warning("export_root: %s", exc)
    preferred.mkdir(parents=True, exist_ok=True)
    return preferred


def confine_export_dir(path: Path) -> Path:
    """Mapp under exports/. Annars exports/ själv."""
    root = export_root()
    raw = Path(path)
    if not raw.is_absolute():
        raw = APP_ROOT / raw
    try:
        resolved = raw.resolve()
    except OSError:
        return root
    if _inside(resolved, root):
        return resolved
    log.warning("EXPORT_UTANFÖR: %s → %s", path, root)
    return root


def confine_export_file(path: Path) -> Path:
    """
    Fil under exports/. Utanför → flyttas in.
    Lös fil direkt i exports/ läggs i dagens undermapp.
    """
    root = export_root()
    raw = Path(path)
    if not raw.is_absolute():
        parts = [p for p in raw.parts if p not in ("", ".", "..")]
        candidate = root.joinpath(*parts) if parts else root / "fakturalista.pdf"
    else:
        candidate = raw
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = root / (raw.name or "fakturalista.pdf")
    if not _inside(resolved, root):
        safe = Path(raw.name or "fakturalista.pdf").name
        safe = "".join(c if c not in '<>:"|?*\\/' else "_" for c in safe)
        if not safe or safe in (".", ".."):
            safe = "fakturalista.pdf"
        if not safe.lower().endswith((".pdf", ".txt", ".json")):
            safe += ".pdf"
        dest = root / datetime.date.today().isoformat() / safe
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.warning("EXPORT_FLYTTAD: %s → %s", path, dest)
        return dest
    if resolved.parent == root:
        day = root / datetime.date.today().isoformat()
        day.mkdir(parents=True, exist_ok=True)
        return day / resolved.name
    return resolved


def get_platform() -> str:
    p = platform.system().lower()
    if p == "darwin":
        return "macos"
    return "windows" if p == "windows" else "linux"


def _to_float(value: Any, default: float = 0.0) -> float:
    """Säker float-konvertering – trasiga belopp kraschar aldrig."""
    try:
        if value is None or value == "" or value is False:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_ascii(text: str) -> str:
    """Konverterar svenska och specialtecken till ren ASCII för PDF."""
    replacements: dict[str, str] = {
        "å": "a", "ä": "a", "ö": "o",
        "Å": "A", "Ä": "A", "Ö": "O",
        "\u2009": " ", "\u2212": "-", "–": "-", "—": "-",
        "“": '"', "”": '"', "‘": "'", "’": "'",
        "…": "...",
        "é": "e", "è": "e", "ê": "e",
        "ü": "u", "Ü": "U",
    }
    result: list[str] = []
    for ch in text:
        if ch in replacements:
            result.append(replacements[ch])
        elif ord(ch) < 128:
            result.append(ch)
        else:
            decomposed = unicodedata.normalize("NFKD", ch)
            ascii_ch = "".join(c for c in decomposed if ord(c) < 128)
            result.append(ascii_ch if ascii_ch else "?")
    return "".join(result)


def fmt_amount(value: float, currency: str = "SEK") -> str:
    """Formaterar belopp: 12 345,67 SEK. Negativt: -12 345,67 SEK."""
    try:
        s = f"{abs(value):,.2f}".replace(",", " ").replace(".", ",")
        prefix = "-" if value < 0 else ""
        return f"{prefix}{s} {currency}".strip()
    except Exception:
        return str(value)


def truncate(text: str, max_chars: int) -> str:
    text = str(text)
    return text if len(text) <= max_chars else text[: max_chars - 1] + "..."


def round_by_mode(value: float, mode: str = "exact") -> float:
    """
    Avrundar ett belopp enligt läge (samma regel som GUI:t):

    • ``exact`` : 2 decimaler (oförändrat)
    • ``hel``   : hel krona (50 öre+ upp)
    • ``50``    : jämnt 50 kr
    • ``100``   : jämnt 100 kr

    Tecken behålls (krediter förblir negativa).
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
#  BETALNINGSDATUM PER EXPORT-BATCH (dialog)
# ═════════════════════════════════════════════════════════════════════


def ask_export_payment_date(
    invoice_count: int,
    supplier_names: list[str],
    total_amount: float,
    currency: str = "SEK",
    session_due_date: str = "",
    parent: Any = None,
) -> tuple[str, bool]:
    """
    Visar en dialog som frågar efter betalningsdatum för DENNA export.

    Regler
    ------
    • Visas ALLTID innan export (inte bara en gång per session).
    • Default = session_due_date om satt, annars idag.
    • Klick på OK     → returnerar (datum_str, True).
    • Klick på Avbryt → returnerar ("", False) → export avbryts.
    • Datumet gäller BARA denna export-batch.
    • Nollställs automatiskt när exporten är klar.
    • Nästa export → frågar igen.
    """
    try:
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QPushButton, QFrame, QDateEdit,
        )
        from PySide6.QtCore import Qt, QDate
        from PySide6.QtGui import QFont

        # Bättre kalender-drop + språk (mjuka importer med fallback —
        # pluginet ska fungera även helt fristående).
        NiceDateEdit = QDateEdit  # type: ignore[assignment,misc]
        quick_pick_row = None
        date_preview_label = None
        try:
            from ui.date_picker import (
                NiceDateEdit, date_preview_label, quick_pick_row,
            )
        except Exception:
            try:
                from date_picker import (  # type: ignore[no-redef]
                    NiceDateEdit, date_preview_label, quick_pick_row,
                )
            except Exception:
                pass
        try:
            from ui.i18n import tr
        except Exception:
            def tr(key: str, **_f: object) -> str:  # type: ignore[no-redef]
                _sv = {
                    "export.date_title": "📄  Ange betalningsdatum för export",
                    "export.payment_date": "Betalningsdatum:",
                    "export.export_with_date": "✔  Exportera med detta datum",
                    "export.cancel_export": "✖  Avbryt export",
                    "export.date_window_title": "Betalningsdatum för export",
                }
                return _sv.get(key, key)

        class _ExportDateDialog(QDialog):
            """Dialog för betalningsdatum per export-batch."""

            def __init__(self) -> None:
                super().__init__(parent)
                self.setWindowTitle(tr("export.date_window_title"))
                self.setWindowFlags(
                    Qt.WindowType.Dialog
                    | Qt.WindowType.WindowStaysOnTopHint
                )
                self.setMinimumWidth(440)
                self.setModal(True)
                self._chosen: str = ""
                self._build_ui()

            def _build_ui(self) -> None:
                root = QVBoxLayout(self)
                root.setSpacing(12)
                root.setContentsMargins(22, 18, 22, 18)

                title = QLabel(tr("export.date_title"))
                title_font = QFont()
                title_font.setPointSize(12)
                title_font.setBold(True)
                title.setFont(title_font)
                title.setAlignment(Qt.AlignmentFlag.AlignCenter)
                root.addWidget(title)

                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setFrameShadow(QFrame.Shadow.Sunken)
                root.addWidget(sep)

                # Export-sammanfattning
                summary_parts: list[str] = [
                    tr("export.date_count", n=invoice_count),
                ]
                if supplier_names:
                    shown = supplier_names[:5]
                    rest = len(supplier_names) - 5
                    sup_str = ",  ".join(shown)
                    if rest > 0:
                        sup_str += tr("export.date_and_more", n=rest)
                    summary_parts.append(
                        tr("export.date_suppliers", names=sup_str)
                    )
                summary_parts.append(
                    f"ATT BETALA:      {fmt_amount(total_amount, currency)}"
                )
                for part in summary_parts:
                    lbl = QLabel(part)
                    lbl.setFont(QFont("Segoe UI", 10))
                    lbl.setWordWrap(True)
                    lbl.setStyleSheet("background:transparent;")
                    root.addWidget(lbl)

                sep2 = QFrame()
                sep2.setFrameShape(QFrame.Shape.HLine)
                sep2.setFrameShadow(QFrame.Shadow.Sunken)
                root.addWidget(sep2)

                info = QLabel(tr("export.date_info"))
                info.setFont(QFont("Segoe UI", 9))
                info.setAlignment(Qt.AlignmentFlag.AlignCenter)
                info.setWordWrap(True)
                info.setStyleSheet("background:transparent;color:#718096;")
                root.addWidget(info)

                # Datumrad
                date_row = QHBoxLayout()
                date_row.setSpacing(10)
                lbl_d = QLabel(tr("export.payment_date"))
                lbl_d.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                lbl_d.setStyleSheet("background:transparent;")
                date_row.addWidget(lbl_d)

                self._date_edit = NiceDateEdit()
                self._date_edit.setMinimumWidth(170)

                # Default: session_due_date → idag
                default_date = datetime.date.today()
                if session_due_date:
                    try:
                        default_date = datetime.date.fromisoformat(
                            session_due_date.strip()
                        )
                    except Exception:
                        pass
                self._date_edit.setDate(
                    QDate(
                        default_date.year,
                        default_date.month,
                        default_date.day,
                    )
                )
                date_row.addWidget(self._date_edit)
                date_row.addStretch()
                root.addLayout(date_row)

                # Snabbval + läsbar förhandsvisning under datumraden
                if quick_pick_row is not None:
                    root.addWidget(quick_pick_row(self._date_edit, self))
                if date_preview_label is not None:
                    root.addWidget(
                        date_preview_label(self._date_edit, self)
                    )

                sep3 = QFrame()
                sep3.setFrameShape(QFrame.Shape.HLine)
                sep3.setFrameShadow(QFrame.Shadow.Sunken)
                root.addWidget(sep3)

                # Knappar
                btn_row = QHBoxLayout()
                btn_row.setSpacing(10)

                btn_ok = QPushButton(tr("export.export_with_date"))
                btn_ok.setDefault(True)
                btn_ok.setMinimumHeight(38)
                btn_ok.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                btn_ok.clicked.connect(self._on_ok)

                btn_cancel = QPushButton(tr("export.cancel_export"))
                btn_cancel.setMinimumHeight(38)
                btn_cancel.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
                btn_cancel.clicked.connect(self.reject)

                btn_row.addWidget(btn_ok)
                btn_row.addWidget(btn_cancel)
                root.addLayout(btn_row)

                self._date_edit.setFocus()

            def _on_ok(self) -> None:
                q = self._date_edit.date()
                self._chosen = (
                    f"{q.year():04d}-{q.month():02d}-{q.day():02d}"
                )
                self.accept()

            def chosen_date(self) -> str:
                return self._chosen

        dlg = _ExportDateDialog()
        result = dlg.exec()

        if result == QDialog.DialogCode.Accepted and dlg.chosen_date():
            chosen = dlg.chosen_date()
            log.info(
                "Export-betalningsdatum valt: %s  (%d fakturor, %s)",
                chosen,
                invoice_count,
                fmt_amount(total_amount, currency),
            )
            return chosen, True

        log.info(
            "Export avbruten av användaren (betalningsdatum-dialog)"
        )
        return "", False

    except Exception as exc:
        log.error("ask_export_payment_date: %s", exc)
        # Fallback: returnera tomt datum utan att krascha
        return "", False


# ═════════════════════════════════════════════════════════════════════
#  LEVERANTÖRS-LOOKUP
# ═════════════════════════════════════════════════════════════════════


def build_supplier_map(
    invoices: list[dict],
    get_suppliers_fn: Callable[[], list[dict]] | None = None,
    suppliers_list: list[dict] | None = None,
) -> dict[str, dict]:
    """Bygger namn(lower) → leverantör-dict, med fallback från fakturor."""
    sup_map: dict[str, dict] = {}
    raw: list[dict] = []
    if get_suppliers_fn is not None:
        try:
            raw = get_suppliers_fn()
        except Exception as exc:
            log.warning("build_supplier_map: %s", exc)
    if not raw and suppliers_list:
        raw = suppliers_list
    for sup in raw:
        name = str(sup.get("name", "")).strip()
        if name:
            sup_map[name.lower()] = sup
    for inv in invoices:
        name = str(inv.get("supplier", "")).strip()
        if name and name.lower() not in sup_map:
            sup_map[name.lower()] = {"name": name}
    return sup_map


_DETAIL_LABEL_KEYS: dict[str, str] = {
    "payment_terms": "terms", "contact_person": "contact",
    "email": "email", "phone": "phone", "address": "address",
}


def supplier_detail_lines(
    sup: dict, language: str = "sv"
) -> list[tuple[str, str]]:
    """Formaterade (etikett, värde)-rader för PDF:ens leverantörsblock."""
    labels = PDF_LABELS["en" if str(language).startswith("en") else "sv"]
    lines: list[tuple[str, str]] = []
    for label, key in SUPPLIER_DETAIL_FIELDS:
        val = str(sup.get(key, "")).strip()
        if val and val != "0":
            if key == "payment_terms":
                val = f"{val} {labels['days']}"
            if key in _DETAIL_LABEL_KEYS:
                label = labels[_DETAIL_LABEL_KEYS[key]]
            lines.append((label, val))
    return lines


# ═════════════════════════════════════════════════════════════════════
#  INVOICE NUMBER GUARD (dubblettskydd)
# ═════════════════════════════════════════════════════════════════════


class InvoiceNumberGuard:
    """Spårar exporterade fakturanummer. Persisteras i JSON."""

    def __init__(self, data_dir: Path) -> None:
        self._path: Path = Path(data_dir) / USED_NUMBERS_FILE
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                    self._data = raw.get("exported_numbers", {})
        except Exception as exc:
            log.error("InvoiceNumberGuard load: %s", exc)
            self._data = {}

    def _save(self) -> None:
        """Atomisk skrivning: .tmp → rename."""
        try:
            ensure_dir(self._path.parent)
            payload = {
                "exported_numbers": self._data,
                "last_updated": now_iso(),
            }
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=4, ensure_ascii=False)
            tmp.replace(self._path)
        except Exception as exc:
            log.error("InvoiceNumberGuard save: %s", exc)

    @staticmethod
    def _key(inv_nr: str, supplier: str) -> str:
        return f"{inv_nr.strip().lower()}|{supplier.strip().lower()}"

    def is_already_exported(self, inv_nr: str, supplier: str) -> bool:
        return self._key(inv_nr, supplier) in self._data

    def get_export_info(self, inv_nr: str, supplier: str) -> dict | None:
        return self._data.get(self._key(inv_nr, supplier))

    def all_exported(self) -> list[dict]:
        return list(self._data.values())

    def count(self) -> int:
        return len(self._data)

    def mark_exported(
        self,
        invoice: dict,
        export_file: str = "",
        batch_id: str = "",
        payment_date: str = "",
    ) -> None:
        nr = str(invoice.get("invoice_number", "")).strip()
        sup = str(invoice.get("supplier", "")).strip()
        if not nr or not sup:
            return
        self._data[self._key(nr, sup)] = {
            "invoice_number": nr,
            "supplier":       sup,
            "total_amount":   _to_float(invoice.get("total_amount")),
            "invoice_type":   invoice.get("invoice_type", "Faktura"),
            "exported_at":    now_iso(),
            "export_file":    export_file,
            "batch_id":       batch_id,
            "invoice_id":     invoice.get("id", ""),
            "payment_date":   payment_date,   # ← betalningsdatum sparas
        }
        self._save()

    def mark_batch_exported(
        self,
        invoices: list[dict],
        export_file: str = "",
        batch_id: str = "",
        payment_date: str = "",
    ) -> tuple[int, list[dict]]:
        """Markerar alla i batchen. Returnerar (antal nya, redan-lista)."""
        already: list[dict] = []
        count = 0
        for inv in invoices:
            nr = str(inv.get("invoice_number", "")).strip()
            sup = str(inv.get("supplier", "")).strip()
            if self.is_already_exported(nr, sup):
                already.append(inv)
            else:
                self.mark_exported(inv, export_file, batch_id, payment_date)
                count += 1
        return count, already

    def check_batch(
        self, invoices: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """Delar batchen i (nya, redan-exporterade)."""
        new_l: list[dict] = []
        done: list[dict] = []
        for inv in invoices:
            nr = str(inv.get("invoice_number", "")).strip()
            sup = str(inv.get("supplier", "")).strip()
            (done if self.is_already_exported(nr, sup) else new_l).append(inv)
        return new_l, done

    def check_duplicates_in_batch(
        self, invoices: list[dict]
    ) -> list[dict]:
        """Hittar dubbletter INOM samma batch (samma nr+leverantör)."""
        seen: dict[str, dict] = {}
        dupes: list[dict] = []
        for inv in invoices:
            nr = str(inv.get("invoice_number", "")).strip()
            sup = str(inv.get("supplier", "")).strip()
            k = self._key(nr, sup)
            if k in seen:
                dupes.append(inv)
            else:
                seen[k] = inv
        return dupes

    def clear(self) -> None:
        self._data = {}
        self._save()

    def remove(self, inv_nr: str, supplier: str) -> bool:
        k = self._key(inv_nr, supplier)
        if k in self._data:
            del self._data[k]
            self._save()
            return True
        return False


# ═════════════════════════════════════════════════════════════════════
#  PDF EXPORTER
# ═════════════════════════════════════════════════════════════════════


class PDFExporter:
    """
    Exporterar fakturalistor till stilren PDF.
    Reportlab när tillgängligt, annars plain-text fallback.

    Betalningsdatum per export
    --------------------------
    • export_invoice_list() tar emot payment_date (str YYYY-MM-DD).
    • Om payment_date är "" och ask_payment_date=True → dialog visas.
    • Om användaren avbryter → exporten avbryts (cancelled=True).
    • Datumet visas i PDF i en grön "Betalningsdatum"-box.
    • Datumet sparas i InvoiceNumberGuard per fakturanummer.
    • Datumet nollställs INTE i exportern – finns bara i result-dict.
    • Nästa export → frågar igen (inget minne av förra datumet).

    Avrundning (pdf_rounding)
    -------------------------
    • rounding_mode: exact / hel / 50 / 100 (samma regel som GUI:t).
    • Påverkar VISAT ATT BETALA i PDF och dialog; exact-värdet sparas
      alltid i result["net_total"].
    """

    def __init__(
        self,
        export_dir: Path,
        data_dir: Path,
        company: str = "",
        org_number: str = "",
        currency: str = "SEK",
        theme: str = "dark",
        get_suppliers_fn: Callable[[], list[dict]] | None = None,
        rounding_mode: str = "exact",
        language: str = "sv",
    ) -> None:
        _lang_in = str(language).lower()
        self._lang = "en" if _lang_in.startswith("en") else "sv"
        self._export_dir = confine_export_dir(Path(export_dir))
        self._data_dir = Path(data_dir)
        self._guard = InvoiceNumberGuard(self._data_dir)
        self._company = company
        self._org_number = org_number
        self._currency = currency
        self._theme = theme
        self._get_suppliers_fn = get_suppliers_fn
        self._rounding = (
            rounding_mode if rounding_mode in PDF_ROUNDING_MODES
            else "exact"
        )
        self._has_rl = False

        ensure_dir(self._export_dir)
        ensure_dir(self._data_dir)

        import importlib.util as _ilu

        self._has_rl = _ilu.find_spec("reportlab") is not None
        if self._has_rl:
            log.info("reportlab available – full PDF support")
        else:
            log.warning("reportlab not installed – text fallback active")

    def _refresh_lang(self) -> None:
        """Hämtar språket live om en språk-källa kopplats (språkbyte)."""
        fn = getattr(self, "_language_fn", None)
        if fn is not None:
            try:
                self._lang = "en" if str(fn()).lower().startswith("en") else "sv"
            except Exception:
                pass

    def _t(self, key: str) -> str:
        """PDF-etikett på dokumentets språk."""
        return PDF_LABELS[self._lang].get(key, key)

    def _columns(self):
        """PDF_COLUMNS med rubriker på dokumentets språk."""
        return [
            (self._t(_PDF_COL_KEYS.get(k, "")), k, w)
            for _lbl, k, w in PDF_COLUMNS
        ]

    @property
    def guard(self) -> InvoiceNumberGuard:
        return self._guard

    def set_theme(self, theme: str) -> None:
        """
        Sätter PDF-tema: dark / light / system / auto.
        auto löses per klockslag (07–20 = ljust), system via darkdetect.
        """
        if theme == "auto":
            theme = (
                "light" if 7 <= datetime.datetime.now().hour < 20
                else "dark"
            )
        self._theme = (
            theme if theme in ("dark", "light", "system") else "dark"
        )

    def set_rounding_mode(self, mode: str) -> None:
        """Sätter avrundningsläge för ATT BETALA (exact/hel/50/100)."""
        self._rounding = (
            mode if mode in PDF_ROUNDING_MODES else "exact"
        )

    def set_suppliers_fn(
        self, fn: Callable[[], list[dict]] | None
    ) -> None:
        self._get_suppliers_fn = fn

    def _is_dark(self) -> bool:
        if self._theme == "dark":
            return True
        if self._theme == "light":
            return False
        try:
            import darkdetect
            return bool(darkdetect.isDark())
        except Exception:
            return True

    def _colours(self) -> dict[str, str]:
        dark = self._is_dark()
        return {
            "header_bg":     DARK_HEADER_BG    if dark else LIGHT_HEADER_BG,
            "header_fg":     DARK_HEADER_FG    if dark else LIGHT_HEADER_FG,
            "row_alt":       DARK_ROW_ALT      if dark else LIGHT_ROW_ALT,
            "row_normal":    DARK_ROW_NORMAL   if dark else LIGHT_ROW_NORMAL,
            "text":          DARK_TEXT         if dark else LIGHT_TEXT,
            "footer":        FOOTER_GREY,
            "accent":        ACCENT_DARK       if dark else _ACCENT,
            "credit":        CREDIT_COLOR,
            "invoice":       INVOICE_COLOR,
            "supplier_bg":   DARK_SUPPLIER_BG  if dark else LIGHT_SUPPLIER_BG,
            "supplier_lbl":  SUPPLIER_LABEL,
            "divider":       DIVIDER_COLOR,
            "summary_bg":    SUMMARY_BG_DARK   if dark else SUMMARY_BG_LIGHT,
            "att_betala_bg": ATT_BETALA_BG_D   if dark else ATT_BETALA_BG_L,
            "due_date_bg":   DUE_DATE_BG_DARK  if dark else DUE_DATE_BG_LIGHT,
            "page_bg":       DARK_PAGE_BG      if dark else LIGHT_PAGE_BG,
        }

    @staticmethod
    def _split_invoices(
        invoices: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """Delar i (vanliga fakturor, kreditfakturor)."""
        regular: list[dict] = []
        credits: list[dict] = []
        for inv in invoices:
            itype = str(inv.get("invoice_type", "Faktura")).strip().lower()
            total = _to_float(inv.get("total_amount"))
            if itype in ("kredit", "kreditfaktura") or total < 0:
                credits.append(inv)
            else:
                regular.append(inv)
        return regular, credits

    @staticmethod
    def _sum_field(items: list[dict], field: str) -> float:
        return round(
            sum(_to_float(i.get(field)) for i in items), 2
        )

    def _auto_filename(self, prefix: str) -> str:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{ts}.pdf"

    def _get_supplier_map(
        self,
        invoices: list[dict],
        suppliers_list: list[dict] | None = None,
    ) -> dict[str, dict]:
        return build_supplier_map(
            invoices,
            get_suppliers_fn=self._get_suppliers_fn,
            suppliers_list=suppliers_list,
        )

    def _unique_suppliers(
        self, invoices: list[dict], sup_map: dict[str, dict]
    ) -> list[dict]:
        seen: set[str] = set()
        result: list[dict] = []
        for inv in invoices:
            name = str(inv.get("supplier", "")).strip()
            key = name.lower()
            if key and key not in seen:
                seen.add(key)
                result.append(sup_map.get(key, {"name": name}))
        return result

    @staticmethod
    def _unique_supplier_names(invoices: list[dict]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for inv in invoices:
            name = str(inv.get("supplier", "")).strip()
            if name and name not in seen:
                seen.add(name)
                result.append(name)
        return result

    # ══════════════════════════════════════════════════════════════════
    #  HUVUDEXPORT
    # ══════════════════════════════════════════════════════════════════

    def export_invoice_list(
        self,
        invoices: list[dict],
        filename: str = "",
        title: str = "Fakturalista",
        check_duplicates: bool = True,
        mark_exported: bool = True,
        force_export: bool = False,
        suppliers_list: list[dict] | None = None,
        payment_date: str = "",
        session_due_date: str = "",
        ask_payment_date: bool = True,
        parent_widget: Any = None,
    ) -> dict[str, Any]:
        self._refresh_lang()
        """
        Exporterar fakturor till PDF.

        Betalningsdatum-flöde
        ---------------------
        1. payment_date angiven (ej tom) → används direkt, ingen dialog.
        2. payment_date tom + ask_payment_date=True → dialog visas.
           - Användaren anger datum → exporten fortsätter.
           - Användaren avbryter → {"success": False, "cancelled": True}.
        3. payment_date tom + ask_payment_date=False → ingen dialog.
        """
        result: dict[str, Any] = {
            "success":            False,
            "cancelled":          False,
            "file_path":          "",
            "exported_count":     0,
            "skipped_count":      0,
            "skipped_invoices":   [],
            "duplicate_in_batch": [],
            "total_invoices":     0.0,
            "total_credits":      0.0,
            "net_total":          0.0,
            "net_total_display":  0.0,
            "rounding_mode":      self._rounding,
            "payment_date":       "",
            "session_due_date":   session_due_date,
            "errors":             [],
        }

        if not invoices:
            result["errors"].append("Inga fakturor att exportera.")
            return result

        # ── Summor INNAN datumdialogen ──────────────────────────────────
        regular_pre, credits_pre = self._split_invoices(invoices)
        sum_inv_pre = self._sum_field(regular_pre, "total_amount")
        sum_crd_pre = self._sum_field(credits_pre, "total_amount")
        net_pre = round(sum_inv_pre + sum_crd_pre, 2)
        net_display_pre = round_by_mode(net_pre, self._rounding)

        # ── Fråga om betalningsdatum ────────────────────────────────────
        effective_payment_date = payment_date.strip()

        if not effective_payment_date and ask_payment_date:
            sup_names = self._unique_supplier_names(invoices)
            chosen_date, confirmed = ask_export_payment_date(
                invoice_count=len(invoices),
                supplier_names=sup_names,
                total_amount=net_display_pre,
                currency=self._currency,
                session_due_date=session_due_date,
                parent=parent_widget,
            )
            if not confirmed:
                result["cancelled"] = True
                result["errors"].append("Export avbruten av användaren.")
                log.info(
                    "Export avbruten – användaren stängde "
                    "betalningsdatum-dialogen"
                )
                return result

            effective_payment_date = chosen_date
            log.info(
                "Betalningsdatum för export: %s  (%d fakturor, %s)",
                effective_payment_date,
                len(invoices),
                fmt_amount(net_display_pre, self._currency),
            )

        result["payment_date"] = effective_payment_date

        # ── Dubblettskydd ───────────────────────────────────────────────
        batch_dupes = self._guard.check_duplicates_in_batch(invoices)
        if batch_dupes:
            result["duplicate_in_batch"] = batch_dupes
            nums = [
                f"{d.get('invoice_number', '?')} "
                f"({d.get('supplier', '?')})"
                for d in batch_dupes
            ]
            result["errors"].append(
                f"Dubletter i batch: {', '.join(nums)}"
            )
            if not force_export:
                return result

        if check_duplicates:
            new_invs, already = self._guard.check_batch(invoices)
            if already and not force_export:
                result["skipped_count"] = len(already)
                result["skipped_invoices"] = already
                invoices = new_invs
                if not invoices:
                    result["errors"].append("Alla redan exporterade.")
                    return result

        if not filename:
            filename = self._auto_filename("fakturalista")
        if not filename.endswith(".pdf"):
            filename += ".pdf"

        file_path = Path(filename)
        if not file_path.is_absolute():
            parts = [p for p in Path(filename).parts if p not in ("", ".", "..")]
            file_path = (
                self._export_dir.joinpath(*parts)
                if parts else self._export_dir / "fakturalista.pdf"
            )
        file_path = confine_export_file(file_path)
        ensure_dir(file_path.parent)

        regular, credits = self._split_invoices(invoices)
        sum_inv = self._sum_field(regular, "total_amount")
        sum_crd = self._sum_field(credits, "total_amount")
        net = round(sum_inv + sum_crd, 2)
        net_display = round_by_mode(net, self._rounding)

        sup_map = self._get_supplier_map(invoices, suppliers_list)
        sup_list = self._unique_suppliers(invoices, sup_map)

        # ── Bygg PDF ────────────────────────────────────────────────────
        try:
            if self._has_rl:
                self._build_reportlab(
                    file_path, invoices, regular, credits,
                    title, sum_inv, sum_crd, net, net_display,
                    sup_list, effective_payment_date,
                )
            else:
                self._build_text(
                    file_path, invoices, regular, credits,
                    title, sum_inv, sum_crd, net, net_display,
                    sup_list, effective_payment_date,
                )
        except Exception as exc:
            result["errors"].append(f"PDF-generering misslyckades: {exc}")
            log.error("PDF build: %s", exc, exc_info=True)
            return result

        # ── Markera exporterade ─────────────────────────────────────────
        if mark_exported:
            batch_id = Path(filename).stem
            self._guard.mark_batch_exported(
                invoices,
                str(file_path),
                batch_id,
                effective_payment_date,   # ← betalningsdatum lagras
            )

        result.update({
            "success":           True,
            "file_path":         str(file_path),
            "exported_count":    len(invoices),
            "total_invoices":    sum_inv,
            "total_credits":     sum_crd,
            "net_total":         net,
            "net_total_display": net_display,
        })

        log.info(
            "PDF: %s (%d rader, att betala %s, betaldatum %s)",
            file_path,
            len(invoices),
            fmt_amount(net_display, self._currency),
            effective_payment_date or "ej angivet",
        )
        return result

    # ══════════════════════════════════════════════════════════════════
    #  REPORTLAB-PDF – stilren layout
    # ══════════════════════════════════════════════════════════════════

    # ══════════════════════════════════════════════════════════════════
    #  REPORTLAB-PDF – PROFFSIG DESIGN (två pass för "Sida x av y")
    # ══════════════════════════════════════════════════════════════════

    def _build_reportlab(
        self,
        file_path: Path,
        invoices: list[dict],
        regular: list[dict],
        credits: list[dict],
        title: str,
        sum_inv: float,
        sum_crd: float,
        net: float,
        net_display: float,
        sup_list: list[dict],
        payment_date: str = "",
    ) -> None:
        """
        Genererar fakturalistan som PDF med reportlab.

        Två pass: pass 1 renderar till minne för att räkna sidor så att
        sidfoten kan visa "Sida X av Y"; pass 2 skriver den riktiga
        filen med korrekt sidantal.
        """
        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas as rl_canvas

        page_w, page_h = A4
        col = self._colours()

        def render(c, total_pages):
            self._draw_report(
                c, page_w, page_h, col,
                invoices, regular, credits, title,
                sum_inv, sum_crd, net, net_display,
                sup_list, payment_date, total_pages,
            )

        buf = io.BytesIO()
        probe = rl_canvas.Canvas(buf, pagesize=A4)
        render(probe, None)
        total = probe.getPageNumber()
        probe.save()

        c = rl_canvas.Canvas(str(file_path), pagesize=A4)
        render(c, total)
        c.save()
        log.debug("PDF klar: %s (%d sidor)", file_path, total)

    def _draw_pdf_icon(self, c, x: float, y: float, size: float) -> float:
        """Ritar appikonen. Returnerar hur långt texten ska skjutas åt höger."""
        icon = APP_ROOT / "app_icon.png"
        if not icon.is_file():
            return 0.0
        try:
            c.drawImage(
                str(icon), x, y, size, size,
                mask="auto", preserveAspectRatio=True, anchor="sw",
            )
            return size + 8
        except Exception as exc:
            log.debug("PDF-ikon: %s", exc)
            return 0.0

    def _draw_report(
        self, c, page_w, page_h, col,
        invoices, regular, credits, title,
        sum_inv, sum_crd, net, net_display,
        sup_list, payment_date, total_pages,
    ) -> None:
        """Ritar hela rapporten på canvas c (proffsig layout)."""
        from reportlab.lib import colors as rl_colors

        hc = rl_colors.HexColor
        content_w = page_w - PDF_MARGIN_LEFT - PDF_MARGIN_RIGHT
        page_num = [1]

        def footer() -> None:
            c.setStrokeColor(hc(col["divider"]))
            c.setLineWidth(0.5)
            c.line(
                PDF_MARGIN_LEFT, PDF_MARGIN_BOTTOM - 6,
                page_w - PDF_MARGIN_RIGHT, PDF_MARGIN_BOTTOM - 6,
            )
            c.setFont("Helvetica", 7)
            c.setFillColor(hc(col["footer"]))
            c.drawString(
                PDF_MARGIN_LEFT, PDF_MARGIN_BOTTOM - 16,
                to_ascii(
                    f"(c) {COPYRIGHT_YEAR} Rickard Langkvist"
                    f"  |  FakturaRäknaren"
                    f"  |  Exporterad {now_iso()}"
                ),
            )
            pages = f"{self._t('page')} {page_num[0]}"
            if total_pages:
                pages += f" {self._t('of')} {total_pages}"
            c.drawRightString(
                page_w - PDF_MARGIN_RIGHT, PDF_MARGIN_BOTTOM - 16, pages,
            )

        def paint_bg() -> None:
            # Hel sidyta i temats färg — annars blir mörkt tema
            # ljus text på vit pappersyta (oläsbart).
            c.setFillColor(hc(col["page_bg"]))
            c.rect(0, 0, page_w, page_h, fill=True, stroke=False)

        def top_band() -> None:
            c.setFillColor(hc(col["header_bg"]))
            c.rect(0, page_h - 12, page_w, 12, fill=True, stroke=False)
            c.setFillColor(hc(col["accent"]))
            c.rect(0, page_h - 14.5, page_w, 2.5, fill=True, stroke=False)

        def new_page() -> float:
            footer()
            c.showPage()
            page_num[0] += 1
            paint_bg()
            top_band()
            y = page_h - PDF_MARGIN_TOP
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(hc(col["accent"]))
            shift = self._draw_pdf_icon(c, PDF_MARGIN_LEFT, y - 2, 14)
            c.drawString(PDF_MARGIN_LEFT + shift, y, to_ascii(title))
            c.setFont("Helvetica", 8)
            c.setFillColor(hc(col["footer"]))
            c.drawRightString(
                page_w - PDF_MARGIN_RIGHT, y, "(fortsatt)",
            )
            y -= 10
            _line(y, 0.5)
            y -= 16
            return y

        def check(y, needed):
            return new_page() if y < PDF_MARGIN_BOTTOM + needed else y

        def _line(y, t=0.5):
            c.setStrokeColor(hc(col["divider"]))
            c.setLineWidth(t)
            c.line(PDF_MARGIN_LEFT, y, page_w - PDF_MARGIN_RIGHT, y)

        def box(y, h, bg, radius=3):
            c.setFillColor(hc(bg))
            c.roundRect(
                PDF_MARGIN_LEFT - 3, y - h + 8,
                content_w + 6, h, radius, fill=True, stroke=False,
            )

        def stripe(y, h, color):
            c.setFillColor(hc(color))
            c.rect(PDF_MARGIN_LEFT - 3, y - h + 8, 3.5, h,
                   fill=True, stroke=False)

        def table_header(y):
            box(y + 8, PDF_HEADER_HEIGHT + 2, col["header_bg"], 4)
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(hc(col["header_fg"]))
            x = PDF_MARGIN_LEFT
            for label, _k, width in self._columns():
                c.drawString(x + 4, y + 4, label)
                x += width
            return y - PDF_HEADER_HEIGHT - 3

        # ── Sida 1: sidyta + toppband + rubrik + företagsinfo ─────────
        paint_bg()
        top_band()
        y = page_h - PDF_MARGIN_TOP

        c.setFont("Helvetica-Bold", 20)
        c.setFillColor(hc(col["text"]))
        shift = self._draw_pdf_icon(c, PDF_MARGIN_LEFT, y - 20, 28)
        c.drawString(PDF_MARGIN_LEFT + shift, y - 8, to_ascii(title))

        if self._company:
            c.setFont("Helvetica-Bold", 10.5)
            c.setFillColor(hc(col["text"]))
            c.drawRightString(
                page_w - PDF_MARGIN_RIGHT, y - 2, to_ascii(self._company),
            )
        if self._org_number:
            c.setFont("Helvetica", 8.5)
            c.setFillColor(hc(col["footer"]))
            c.drawRightString(
                page_w - PDF_MARGIN_RIGHT, y - 14,
                to_ascii(f"Org.nr {self._org_number}"),
            )
        y -= 30

        c.setFont("Helvetica", 8)
        c.setFillColor(hc(col["footer"]))
        c.drawString(
            PDF_MARGIN_LEFT, y,
            to_ascii(
                f"{self._t('exported')}: {now_iso()}   |   {self._t('rows')}: {len(invoices)}"
                f"   |   {self._t('invoices')}: {len(regular)}"
                f"   |   {self._t('credits_minus').split('(')[0].strip()}: {len(credits)}"
                f"   |   {self._t('suppliers')}: {len(sup_list)}"
            ),
        )
        y -= 8
        _line(y, 1.0)
        y -= 20

        # ── Betalningsdatum (grön box med accentstripe) ───────────────
        if payment_date:
            y = check(y, 36)
            box(y + 4, 28, col["due_date_bg"], 5)
            stripe(y + 4, 28, col["invoice"])
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(hc(col["invoice"]))
            c.drawString(
                PDF_MARGIN_LEFT + 10, y - 4,
                to_ascii(self._t("payment_date")),
            )
            c.setFont("Helvetica-Bold", 13)
            c.drawRightString(
                page_w - PDF_MARGIN_RIGHT - 8, y - 4,
                to_ascii(payment_date),
            )
            y -= 34

        # ── Summering – ATT BETALA ────────────────────────────────────
        y = check(y, 84)
        box_h = 70
        box(y + 4, box_h, col["summary_bg"], 5)

        c.setFont("Helvetica", 9.5)
        c.setFillColor(hc(col["invoice"]))
        c.drawString(PDF_MARGIN_LEFT + 8, y - 2, self._t("invoices_plus"))
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(
            page_w - PDF_MARGIN_RIGHT - 8, y - 2,
            fmt_amount(sum_inv, self._currency),
        )
        y -= 17

        c.setFont("Helvetica", 9.5)
        c.setFillColor(hc(col["credit"]))
        c.drawString(PDF_MARGIN_LEFT + 8, y - 2, self._t("credits_minus"))
        c.setFont("Helvetica-Bold", 10)
        c.drawRightString(
            page_w - PDF_MARGIN_RIGHT - 8, y - 2,
            fmt_amount(abs(sum_crd), self._currency),
        )
        y -= 6

        c.setStrokeColor(hc(col["accent"]))
        c.setLineWidth(1.2)
        c.line(
            PDF_MARGIN_LEFT + 6, y, page_w - PDF_MARGIN_RIGHT - 6, y,
        )
        y -= 17

        rounding_note = (
            f"  ({self._t('rounding')}: {self._rounding})"
            if self._rounding != "exact" else ""
        )
        c.setFont("Helvetica-Bold", 13)
        c.setFillColor(hc(col["accent"]))
        c.drawString(PDF_MARGIN_LEFT + 8, y - 4, self._t("to_pay"))
        c.setFont("Helvetica-Bold", 15)
        c.drawRightString(
            page_w - PDF_MARGIN_RIGHT - 8, y - 5,
            fmt_amount(net_display, self._currency)
            + to_ascii(rounding_note),
        )
        y -= 30

        # ── Leverantörsuppgifter ──────────────────────────────────────
        if sup_list:
            y = check(y, 40)
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(hc(col["accent"]))
            c.drawString(PDF_MARGIN_LEFT, y, "LEVERANTORSUPPGIFTER")
            y -= 4
            _line(y, 0.5)
            y -= 12

            for sup in sup_list:
                name = str(sup.get("name", "-")).strip()
                details = supplier_detail_lines(sup, self._lang)
                block_h = 16 + len(details) * 11 + 6
                y = check(y, block_h)

                box(y + 2, block_h, col["supplier_bg"], 3)
                stripe(y + 2, block_h, col["accent"])

                c.setFont("Helvetica-Bold", 9)
                c.setFillColor(hc(col["accent"]))
                c.drawString(
                    PDF_MARGIN_LEFT + 8, y - 2, to_ascii(name),
                )
                y -= 14

                c.setFont("Helvetica", 7.5)
                for label, value in details:
                    c.setFillColor(hc(col["supplier_lbl"]))
                    c.drawString(
                        PDF_MARGIN_LEFT + 12, y, to_ascii(f"{label}:"),
                    )
                    c.setFillColor(hc(col["text"]))
                    c.drawString(
                        PDF_MARGIN_LEFT + 92, y, to_ascii(value),
                    )
                    y -= 11
                y -= 4
            y -= 6

        # ── Tabell ────────────────────────────────────────────────────
        y = check(y, 40)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColor(hc(col["accent"]))
        c.drawString(PDF_MARGIN_LEFT, y, self._t("invoices"))
        y -= 4
        _line(y, 0.5)
        y -= 14
        y = table_header(y)

        row_idx = 0
        for inv in invoices:
            if y < PDF_MARGIN_BOTTOM + 30:
                y = new_page()
                y = table_header(y)

            itype = str(inv.get("invoice_type", "Faktura")).strip()
            total = _to_float(inv.get("total_amount"))
            is_cred = (
                itype.lower() in ("kredit", "kreditfaktura") or total < 0
            )

            row_bg = (
                col["row_alt"] if row_idx % 2 == 0 else col["row_normal"]
            )
            c.setFillColor(hc(row_bg))
            c.rect(
                PDF_MARGIN_LEFT - 3, y - 4,
                content_w + 6, PDF_LINE_HEIGHT, fill=True, stroke=False,
            )

            c.setFont("Helvetica", 8)
            text_col = col["credit"] if is_cred else col["text"]
            c.setFillColor(hc(text_col))

            x = PDF_MARGIN_LEFT
            for _label, key, width in self._columns():
                raw = inv.get(key, "")
                if key == "total_amount":
                    cell = fmt_amount(_to_float(raw), "")
                    c.drawRightString(x + width - 3, y, cell)
                elif key == "invoice_type":
                    cell = truncate(to_ascii(str(raw or "Faktura")), 13)
                    c.drawString(x + 4, y, cell)
                else:
                    cell = truncate(to_ascii(str(raw or "")), 26)
                    c.drawString(x + 4, y, cell)
                x += width

            y -= PDF_LINE_HEIGHT
            row_idx += 1

        footer()

    # ══════════════════════════════════════════════════════════════════
    #  TEXT-FALLBACK (utan reportlab)
    # ══════════════════════════════════════════════════════════════════

    def _build_text(
        self,
        file_path: Path,
        invoices: list[dict],
        regular: list[dict],
        credits: list[dict],
        title: str,
        sum_inv: float,
        sum_crd: float,
        net: float,
        net_display: float,
        sup_list: list[dict],
        payment_date: str = "",
    ) -> None:
        w = 90
        sep = "-" * w
        dbl = "=" * w
        a = to_ascii

        lines: list[str] = [dbl, f"  {a(title)}"]
        if self._company:
            lines.append(
                f"  {a(self._company)}"
                + (
                    f"  |  Org.nr: {self._org_number}"
                    if self._org_number else ""
                )
            )
        lines.append(f"  {self._t('exported')}: {now_iso()}")
        lines.append(dbl)
        lines.append("")

        # Betalningsdatum (om angivet)
        if payment_date:
            lines.append(f"  BETALNINGSDATUM:  {payment_date}")
            lines.append(sep)
            lines.append("")

        rounding_note = (
            f"  (avrundning: {self._rounding})"
            if self._rounding != "exact" else ""
        )
        lines += [
            f"  {self._t('invoices_plus')}  {fmt_amount(sum_inv, self._currency)}",
            f"  {self._t('credits_minus')}  {fmt_amount(abs(sum_crd), self._currency)}",
            sep,
            f"  {self._t('to_pay')}     "
            f"{fmt_amount(net_display, self._currency)}{rounding_note}",
            "",
            sep,
            "",
        ]

        # Leverantörsuppgifter
        if sup_list:
            lines.append(f"  {self._t('supplier_details')}")
            lines.append(sep)
            for sup in sup_list:
                name = a(str(sup.get("name", "-")).strip())
                lines.append(f"  {name}")
                for label, value in supplier_detail_lines(sup, self._lang):
                    lines.append(f"    {a(label):<16} {a(value)}")
                lines.append("")
            lines.append(sep)
            lines.append("")

        # Tabell
        lines.append("  FAKTUROR")
        header = (
            f"  {'Fakturanr':<14}{'Typ':<10}{'Leverantor':<20}"
            f"{'Datum':<12}{'Forfall':<12}{'Belopp':>14}  {'Status':<12}"
        )
        lines += [sep, header, sep]
        for inv in invoices:
            total = _to_float(inv.get("total_amount"))
            itype = a(str(inv.get("invoice_type", "Faktura")))[:9]
            row = (
                f"  {truncate(a(str(inv.get('invoice_number', ''))), 13):<14}"
                f"{itype:<10}"
                f"{truncate(a(str(inv.get('supplier', ''))), 19):<20}"
                f"{str(inv.get('date', '')):<12}"
                f"{str(inv.get('due_date', '')):<12}"
                f"{fmt_amount(total, ''):>14}"
                f"  {a(str(inv.get('status', ''))):<12}"
            )
            lines.append(row)

        lines += [
            sep,
            "",
            f"  (c) {COPYRIGHT_YEAR} Rickard Langkvist"
            f"  |  FakturaRäknaren",
        ]
        file_path.write_text("\n".join(lines), encoding="utf-8")

    # ══════════════════════════════════════════════════════════════════
    #  SAMMANSTÄLLNINGSEXPORT
    # ══════════════════════════════════════════════════════════════════

    def export_summary(
        self,
        invoices: list[dict],
        title: str = "Sammanstallning",
        filename: str = "",
        suppliers_list: list[dict] | None = None,
        payment_date: str = "",
        session_due_date: str = "",
    ) -> dict[str, Any]:
        """Per leverantör + per månad, med Fakturor/Krediter/ATT BETALA."""
        try:
            from ui.core.calculator import (
                summary_by_supplier, summary_by_month,
            )
        except ImportError:
            try:
                from calculator import (  # type: ignore
                    summary_by_supplier, summary_by_month,
                )
            except ImportError:
                summary_by_supplier = self._fb_supplier  # type: ignore
                summary_by_month = self._fb_month  # type: ignore

        if not filename:
            filename = self._auto_filename("sammanstallning")
        fp = confine_export_file(self._export_dir / Path(filename).name)

        by_sup = summary_by_supplier(invoices)
        by_mon = summary_by_month(invoices)
        sup_map = self._get_supplier_map(invoices, suppliers_list)

        regular, creds = self._split_invoices(invoices)
        si = self._sum_field(regular, "total_amount")
        sc = self._sum_field(creds, "total_amount")
        n = round(si + sc, 2)
        n_display = round_by_mode(n, self._rounding)

        w = 92
        sep = "-" * w
        dbl = "=" * w
        a = to_ascii

        lines: list[str] = [dbl, f"  {a(title)}"]
        if self._company:
            lines.append(f"  {a(self._company)}  {self._org_number}")
        lines.append(f"  Exporterad: {now_iso()}")
        lines.append(dbl)
        lines.append("")

        # Betalningsdatum
        if payment_date:
            lines.append(f"  BETALNINGSDATUM:  {payment_date}")
            lines.append(sep)
            lines.append("")

        lines += [
            f"  Fakturor  (+):  {fmt_amount(si, self._currency)}",
            f"  Krediter  (-):  {fmt_amount(abs(sc), self._currency)}",
            sep,
            f"  ATT BETALA:     {fmt_amount(n_display, self._currency)}",
            "",
            sep,
            "",
            "  PER LEVERANTOR:",
            sep,
        ]

        for name, data in by_sup.items():
            sup = sup_map.get(name.lower(), {"name": name})
            lines.append(f"  {a(name)}")
            for lb, val in supplier_detail_lines(sup):
                lines.append(f"    {a(lb):<16} {a(val)}")
            lines.append(
                f"    {'Antal:':<16} {data.get('count', 0)}"
            )
            lines.append(
                f"    {'Total:':<16} "
                f"{fmt_amount(_to_float(data.get('total_amount')), self._currency)}"
            )
            lines.append("")

        lines += [
            "  PER MANAD:",
            sep,
            f"  {'Manad':<12}{'Antal':>6}{'Total':>18}",
            f"  {'-' * 38}",
        ]
        for month, data in by_mon.items():
            lines.append(
                f"  {month:<12}"
                f"{data.get('count', 0):>6}"
                f"{fmt_amount(_to_float(data.get('total_amount')), self._currency):>18}"
            )

        lines += [
            "",
            sep,
            f"  (c) {COPYRIGHT_YEAR} Rickard Langkvist"
            f"  |  FakturaRäknaren",
        ]
        fp.write_text("\n".join(lines), encoding="utf-8")
        return {
            "success":        True,
            "file_path":      str(fp),
            "payment_date":   payment_date,
            "net_total":      n,
            "net_total_display": n_display,
        }

    # ══════════════════════════════════════════════════════════════════
    #  ENSKILD / BATCH / STATISTIK
    # ══════════════════════════════════════════════════════════════════

    def export_single(
        self,
        invoice: dict,
        filename: str = "",
        suppliers_list: list[dict] | None = None,
        payment_date: str = "",
        ask_payment_date: bool = True,
        parent_widget: Any = None,
    ) -> dict[str, Any]:
        return self.export_invoice_list(
            [invoice],
            filename=filename or self._auto_filename(
                f"faktura_{invoice.get('invoice_number', 'unk')}"
            ),
            title=to_ascii(
                f"Faktura {invoice.get('invoice_number', '')} "
                f"- {invoice.get('supplier', '')}"
            ),
            check_duplicates=False,
            mark_exported=True,
            force_export=True,
            suppliers_list=suppliers_list,
            payment_date=payment_date,
            ask_payment_date=ask_payment_date,
            parent_widget=parent_widget,
        )

    def export_payment_batch(
        self,
        invoices: list[dict],
        batch_date: str = "",
        batch_note: str = "",
        filename: str = "",
        suppliers_list: list[dict] | None = None,
        payment_date: str = "",
        ask_payment_date: bool = True,
        parent_widget: Any = None,
    ) -> dict[str, Any]:
        if not batch_date:
            batch_date = today_iso()
        t = f"Betalbatch - {batch_date}"
        if batch_note:
            t += f"  |  {to_ascii(batch_note)}"
        return self.export_invoice_list(
            invoices,
            filename=filename or self._auto_filename("betalbatch"),
            title=t,
            check_duplicates=False,
            mark_exported=False,
            force_export=True,
            suppliers_list=suppliers_list,
            payment_date=payment_date,
            ask_payment_date=ask_payment_date,
            parent_widget=parent_widget,
        )

    def get_export_stats(self) -> dict[str, Any]:
        pdfs: list[str] = []
        try:
            pdfs = [f.name for f in self._export_dir.rglob("*.pdf")]
        except Exception:
            pass
        return {
            "total_exported": self._guard.count(),
            "export_dir":     str(self._export_dir),
            "pdf_files":      pdfs,
            "has_reportlab":  self._has_rl,
            "platform":       get_platform(),
            "theme":          self._theme,
            "rounding_mode":  self._rounding,
        }

    @staticmethod
    def _fb_supplier(invoices: list[dict]) -> dict[str, dict]:
        """Fallback per leverantör (när calculator saknas)."""
        r: dict[str, dict] = {}
        for inv in invoices:
            n = str(inv.get("supplier", "-")).strip() or "-"
            if n not in r:
                r[n] = {"count": 0, "total_amount": 0.0}
            r[n]["count"] += 1
            r[n]["total_amount"] = round(
                r[n]["total_amount"] + _to_float(inv.get("total_amount")), 2,
            )
        return r

    @staticmethod
    def _fb_month(invoices: list[dict]) -> dict[str, dict]:
        """Fallback per månad (när calculator saknas)."""
        r: dict[str, dict] = {}
        for inv in invoices:
            ds = str(inv.get("date", ""))
            m = ds[:7] if len(ds) >= 7 else "Okand"
            if m not in r:
                r[m] = {"count": 0, "total_amount": 0.0}
            r[m]["count"] += 1
            r[m]["total_amount"] = round(
                r[m]["total_amount"] + _to_float(inv.get("total_amount")), 2,
            )
        return r
